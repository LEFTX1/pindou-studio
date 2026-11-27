import csv
import json
from collections import Counter, deque
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import label
from skimage import color as skcolor

BASE = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
PALETTE_CSV = BASE / "repos" / "pindou-skill" / "palettes" / "mard_221.csv"
INPUTS_DIR = BASE / "inputs"
OUT_A = BASE / "outputs" / "pathway_A_precision"
OUT_D = BASE / "outputs" / "pathway_D_bfs_simplified"
OUT_A.mkdir(parents=True, exist_ok=True)
OUT_D.mkdir(parents=True, exist_ok=True)


def load_palette():
    rows = []
    with PALETTE_CSV.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "code": row["code"],
                "hex": row["hex"],
                "rgb": np.array([int(row["r"]), int(row["g"]), int(row["b"])], dtype=np.uint8),
                "name_zh": row.get("name_zh", ""),
            })
    pal_rgb = np.stack([r["rgb"] for r in rows], axis=0)
    pal_lab = skcolor.rgb2lab(pal_rgb.astype(np.float64) / 255.0)
    return rows, pal_lab


def ciede2000_snap(rgb_arr: np.ndarray, pal_lab: np.ndarray) -> np.ndarray:
    """rgb_arr: (H, W, 3) uint8 -> (H, W) int index into palette."""
    h, w, _ = rgb_arr.shape
    lab = skcolor.rgb2lab(rgb_arr.reshape(-1, 3).astype(np.float64) / 255.0)
    q = np.broadcast_to(lab[:, None, :], (lab.shape[0], pal_lab.shape[0], 3))
    p = np.broadcast_to(pal_lab[None, :, :], (lab.shape[0], pal_lab.shape[0], 3))
    de = skcolor.deltaE_ciede2000(q, p)
    return np.argmin(de, axis=1).reshape(h, w)


def denoise_jpeg_sprite(rgba: np.ndarray, is_medallion: bool = True, de_thresh: float = 3.6) -> np.ndarray:
    """
    Clean subtle JPEG block compression noise on pixel art before palette snapping:
    1) Unify near-white low-chroma cells -> (255, 255, 255)
    2) If medallion, unify the outer lace border ring to its median RGB
    3) Greedy Lab clustering within de_thresh so flat areas map consistently
    """
    rgb = rgba[:, :, :3].copy()
    mask = rgba[:, :, 3] > 0

    # 1) Unify near-white low-chroma cells to pure white
    r_c, g_c, b_c = rgb[:, :, 0].astype(int), rgb[:, :, 1].astype(int), rgb[:, :, 2].astype(int)
    chroma = np.maximum(np.maximum(r_c, g_c), b_c) - np.minimum(np.minimum(r_c, g_c), b_c)
    near_white = mask & (r_c >= 238) & (g_c >= 238) & (b_c >= 238) & (chroma <= 14)
    rgb[near_white] = [255, 255, 255]

    # 2) Unify outer 1-2 cell lace border ring (cells adjacent to background)
    if is_medallion:
        from scipy.ndimage import binary_dilation
        bg = ~mask
        # Any foreground non-white cell within 2 steps (4-connected or 8-connected) of outer background
        touch1 = binary_dilation(bg, structure=np.ones((3, 3))) & mask & (~near_white)
        if touch1.any():
            b_med = np.median(rgb[touch1], axis=0)
            touch2 = binary_dilation(bg, iterations=2, structure=np.ones((3, 3))) & mask & (~near_white)
            is_border = touch2 & (np.linalg.norm(rgb.astype(float) - b_med, axis=2) < 42)
            if is_border.any():
                rgb[is_border] = np.round(np.median(rgb[is_border], axis=0)).astype(np.uint8)

    # 3) Greedy Lab clustering (mean/median per cluster within de_thresh) for remaining FG pixels
    fg_coords = np.argwhere(mask)
    fg_rgb = rgb[mask]
    fg_lab = skcolor.rgb2lab(fg_rgb.astype(np.float64) / 255.0)
    # Sort by frequency / deterministic order: cluster in Lab space
    # Use sequential leader clustering with medoid refinement
    centers_lab = []
    clusters = []
    for i in range(len(fg_lab)):
        lab_i = fg_lab[i]
        if not centers_lab:
            centers_lab.append(lab_i)
            clusters.append([i])
            continue
        dists = np.linalg.norm(np.array(centers_lab) - lab_i, axis=1)
        j = int(np.argmin(dists))
        if dists[j] <= de_thresh:
            clusters[j].append(i)
            # update center gently
            centers_lab[j] = fg_lab[clusters[j]].mean(axis=0)
        else:
            centers_lab.append(lab_i)
            clusters.append([i])

    clean_rgb = rgb.copy()
    for cl in clusters:
        med = np.round(np.median(fg_rgb[cl], axis=0)).astype(np.uint8)
        for idx_pt in cl:
            y, x = fg_coords[idx_pt]
            clean_rgb[y, x] = med

    # Keep pure white crisp
    clean_rgb[near_white] = [255, 255, 255]
    return clean_rgb


def bfs_simplify_and_reduce(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
    target_colors: int = 14,
    protected_codes: set = None,
) -> np.ndarray:
    """
    Zippland/perler-beads style:
    1) Merge rare colors while protecting essential accent colors (e.g. eye/gem/yellow rings)
       using perceptual Lab distance weighted so salient accent colors stay distinct.
    2) BFS connected-component cleanup: absorb tiny 1-2 bead noise islands into adjacent
       larger regions if Lab distance < 24 (preserves high-contrast sparkles on white ring!).
    """
    if protected_codes is None:
        protected_codes = set()
    out = idx_grid.copy()
    h, w = out.shape

    # Step 1: BFS tiny-island cleanup first (area <= 2 and adjacent color within de < 20)
    def bfs_merge(grid, max_island=2, max_de=20.0):
        g = grid.copy()
        visited = np.zeros((h, w), dtype=bool)
        for r in range(h):
            for c in range(w):
                if not mask[r, c] or visited[r, c]:
                    continue
                col = int(g[r, c])
                comp = []
                nbr_colors = Counter()
                q = deque([(r, c)])
                visited[r, c] = True
                while q:
                    cr, cc = q.popleft()
                    comp.append((cr, cc))
                    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < h and 0 <= nc < w and mask[nr, nc]:
                            ncol = int(g[nr, nc])
                            if ncol == col:
                                if not visited[nr, nc]:
                                    visited[nr, nc] = True
                                    q.append((nr, nc))
                            else:
                                nbr_colors[ncol] += 1
                if len(comp) <= max_island and nbr_colors:
                    # Protect vivid small features (e.g. tongue, forehead gem, eye highlight) from dark/neutral absorption
                    if pal[col]["code"] in protected_codes:
                        continue
                    c_rgb = pal[col]["rgb"].astype(int)
                    if (int(c_rgb.max()) - int(c_rgb.min())) > 55:
                        continue
                    # Pick most frequent neighbor that is close in Lab
                    best_nbr = None
                    best_score = -1e9
                    for ncol, cnt in nbr_colors.items():
                        de = float(skcolor.deltaE_ciede2000(pal_lab[col][None, :], pal_lab[ncol][None, :])[0])
                        if de <= max_de:
                            score = cnt * 10 - de
                            if score > best_score:
                                best_score = score
                                best_nbr = ncol
                    if best_nbr is not None:
                        for cr, cc in comp:
                            g[cr, cc] = best_nbr
        return g

    out = bfs_merge(out, max_island=2, max_de=18.0)

    # Step 2: Iterative color reduction down to target_colors
    # At each step, pick the non-protected color with smallest (count * min_dist_to_other_present_color)
    # so rare colors that are VERY close to another existing color merge first, while distinct accent colors survive!
    while True:
        fg_vals = out[mask]
        counts = Counter(int(x) for x in fg_vals)
        if len(counts) <= target_colors:
            break
        present = list(counts.keys())
        best_merge = None
        best_cost = 1e18
        for src in present:
            if pal[src]["code"] in protected_codes:
                continue
            for dst in present:
                if dst == src:
                    continue
                de = float(skcolor.deltaE_ciede2000(pal_lab[src][None, :], pal_lab[dst][None, :])[0])
                # Cost = number of beads moved * perceptual error^1.5
                cost = counts[src] * (de ** 1.4)
                if cost < best_cost:
                    best_cost = cost
                    best_merge = (src, dst)
        if best_merge is None:
            break
        src, dst = best_merge
        out[(out == src) & mask] = dst

    # Final light BFS pass to clean any 1-cell strays created by merging
    out = bfs_merge(out, max_island=1, max_de=22.0)
    return out


def get_font(size: int, bold: bool = False):
    candidates = (
        ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold
        else ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/arial.ttf"]
    )
    for fp in candidates:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_sheet_png(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    title: str,
    subtitle: str,
    out_png: Path,
    cell_px: int = 34,
    palette_name: str = "MARD",
):
    h, w = idx_grid.shape
    counts = Counter(int(x) for x in idx_grid[mask])
    bom = sorted(counts.items(), key=lambda kv: -kv[1])
    total_beads = sum(counts.values())

    header_h = 84
    margin_l = 48
    margin_t = 40
    margin_r = 34
    margin_b = 34
    bom_w = 340

    grid_w_px = w * cell_px
    grid_h_px = h * cell_px

    bom_line_h = 30
    needed_bom_h = 64 + len(bom) * bom_line_h + 40
    canvas_w = margin_l + grid_w_px + margin_r + bom_w
    canvas_h = header_h + max(margin_t + grid_h_px + margin_b, needed_bom_h)

    img = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Top header banner
    draw.rectangle([0, 0, canvas_w, header_h], fill=(38, 34, 62))
    f_title = get_font(28, bold=True)
    f_sub = get_font(16, bold=False)
    f_coord = get_font(13, bold=True)
    f_code = get_font(max(10, int(cell_px * 0.34)), bold=True)
    f_bom_title = get_font(20, bold=True)
    f_bom = get_font(15, bold=False)
    f_bom_b = get_font(15, bold=True)

    draw.text((28, 14), title, fill=(255, 255, 255), font=f_title)
    draw.text(
        (28, 52),
        f"{subtitle}  |  尺寸: {w}×{h} 格  |  用色: {len(bom)} 种  |  总豆数: {total_beads} 颗",
        fill=(210, 205, 235),
        font=f_sub,
    )

    gx0 = margin_l
    gy0 = header_h + margin_t

    # Draw empty-cell subtle backdrop & filled beads
    for r in range(h):
        for c in range(w):
            x0 = gx0 + c * cell_px
            y0 = gy0 + r * cell_px
            x1 = x0 + cell_px
            y1 = y0 + cell_px
            if not mask[r, c]:
                # Subtle dot in empty cell so user clearly distinguishes empty vs white bead H1
                draw.rectangle([x0, y0, x1, y1], fill=(247, 248, 250))
                continue
            entry = pal[int(idx_grid[r, c])]
            R, G, B = map(int, entry["rgb"])
            draw.rectangle([x0, y0, x1, y1], fill=(R, G, B))
            lum = (0.299 * R + 0.587 * G + 0.114 * B) / 255.0
            t_col = (20, 20, 20) if lum > 0.56 else (255, 255, 255)
            code = entry["code"]
            bbox = draw.textbbox((0, 0), code, font=f_code)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(
                (x0 + (cell_px - tw) / 2, y0 + (cell_px - th) / 2 - 1),
                code,
                fill=t_col,
                font=f_code,
            )

    # Grid lines: thin gray everywhere, medium every 5, bold dark every 10
    for c in range(w + 1):
        x = gx0 + c * cell_px
        if c % 10 == 0 or c == w:
            col, width = (45, 45, 55), 2
        elif c % 5 == 0:
            col, width = (130, 130, 145), 1
        else:
            col, width = (205, 208, 214), 1
        draw.line([(x, gy0), (x, gy0 + grid_h_px)], fill=col, width=width)

    for r in range(h + 1):
        y = gy0 + r * cell_px
        if r % 10 == 0 or r == h:
            col, width = (45, 45, 55), 2
        elif r % 5 == 0:
            col, width = (130, 130, 145), 1
        else:
            col, width = (205, 208, 214), 1
        draw.line([(gx0, y), (gx0 + grid_w_px, y)], fill=col, width=width)

    # Coordinates (top, bottom, left, right)
    for c in range(w):
        label_s = str(c + 1)
        bbox = draw.textbbox((0, 0), label_s, font=f_coord)
        tw = bbox[2] - bbox[0]
        cx = gx0 + c * cell_px + (cell_px - tw) / 2
        tcol = (40, 40, 60) if (c + 1) % 5 == 0 else (110, 110, 125)
        draw.text((cx, gy0 - 20), label_s, fill=tcol, font=f_coord)
        draw.text((cx, gy0 + grid_h_px + 6), label_s, fill=tcol, font=f_coord)

    for r in range(h):
        label_s = str(r + 1)
        bbox = draw.textbbox((0, 0), label_s, font=f_coord)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        cy = gy0 + r * cell_px + (cell_px - th) / 2 - 1
        tcol = (40, 40, 60) if (r + 1) % 5 == 0 else (110, 110, 125)
        draw.text((gx0 - tw - 8, cy), label_s, fill=tcol, font=f_coord)
        draw.text((gx0 + grid_w_px + 8, cy), label_s, fill=tcol, font=f_coord)

    # Right-side BOM panel
    bx = gx0 + grid_w_px + margin_r
    by = gy0
    draw.rounded_rectangle(
        [bx - 12, by - 10, canvas_w - 18, by + 56 + len(bom) * bom_line_h + 16],
        radius=10,
        fill=(249, 249, 252),
        outline=(215, 215, 228),
        width=1,
    )
    draw.text((bx, by), f"{palette_name} 采购清单 ({len(bom)}色)", fill=(35, 32, 58), font=f_bom_title)
    draw.text((bx, by + 28), f"总计 {total_beads} 颗 · 空格为透明不拼", fill=(110, 108, 128), font=f_sub)

    y_cur = by + 60
    for idx_pal, cnt in bom:
        entry = pal[idx_pal]
        R, G, B = map(int, entry["rgb"])
        draw.rectangle([bx, y_cur + 2, bx + 22, y_cur + 24], fill=(R, G, B), outline=(100, 100, 110))
        draw.text((bx + 32, y_cur + 3), f"{entry['code']:<4}", fill=(30, 30, 40), font=f_bom_b)
        draw.text((bx + 84, y_cur + 3), f"{entry['name_zh']}", fill=(90, 90, 105), font=f_bom)
        cnt_s = f"×{cnt}"
        cb = draw.textbbox((0, 0), cnt_s, font=f_bom_b)
        draw.text((canvas_w - 32 - (cb[2] - cb[0]), y_cur + 3), cnt_s, fill=(38, 34, 62), font=f_bom_b)
        y_cur += bom_line_h

    img.save(out_png)
    return bom, total_beads


def render_bead_preview(idx_grid: np.ndarray, mask: np.ndarray, pal: list, out_png: Path, cell_px: int = 16):
    """Render realistic fuse-bead preview (cylindrical beads with center holes on a soft pegboard)."""
    h, w = idx_grid.shape
    pad = 20
    cw, ch = w * cell_px + 2 * pad, h * cell_px + 2 * pad
    img = Image.new("RGB", (cw, ch), (242, 243, 247))
    draw = ImageDraw.Draw(img)
    for r in range(h):
        for c in range(w):
            cx = pad + c * cell_px + cell_px / 2
            cy = pad + r * cell_px + cell_px / 2
            if not mask[r, c]:
                # subtle pegboard peg dot
                draw.ellipse([cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5], fill=(218, 220, 228))
                continue
            R, G, B = map(int, pal[int(idx_grid[r, c])]["rgb"])
            rad = cell_px * 0.47
            # outer slight shadow
            shadow = (max(0, int(R * 0.78)), max(0, int(G * 0.78)), max(0, int(B * 0.78)))
            draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(R, G, B), outline=shadow, width=1)
            # center hole
            hr = cell_px * 0.16
            hole_col = (232, 234, 240) if (R + G + B) > 650 else (max(0, int(R * 0.45)), max(0, int(G * 0.45)), max(0, int(B * 0.45)))
            draw.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=hole_col)
    img.save(out_png)


def write_bom_csv(bom, total_beads, pal, out_csv: Path, palette_name: str = "MARD"):
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"{palette_name}色号", "HEX", "中文名称", "数量(颗)"])
        for idx_pal, cnt in bom:
            e = pal[idx_pal]
            w.writerow([e["code"], e["hex"], e["name_zh"], cnt])
        w.writerow(["总计", f"{len(bom)}种", "", total_beads])


def main():
    pal, pal_lab = load_palette()

    configs = [
        ("espeon", "太阳伊布", {"H1", "E7", "C24", "A2", "A1", "E24"}),
        ("umbreon", "月亮伊布", {"H2", "H1", "D10", "A3", "A16", "E13", "F7", "F9"}),
    ]

    for name, cn_name, protect in configs:
        # --- Pathway A1: Full 64x64 Medallion (denoised 1:1 CIEDE2000) ---
        med_rgba = np.array(Image.open(INPUTS_DIR / f"{name}_medallion_64x64.png").convert("RGBA"))
        med_mask = med_rgba[:, :, 3] > 0
        med_clean = denoise_jpeg_sprite(med_rgba, is_medallion=True, de_thresh=3.5)
        med_idx = ciede2000_snap(med_clean, pal_lab)

        bom_a1, tot_a1 = render_sheet_png(
            med_idx, med_mask, pal,
            title=f"{cn_name} · 原生1:1去噪精准版（完整蕾丝圆章）",
            subtitle="途径 A1：锁相还原 + JPEG降噪 + MARD CIEDE2000",
            out_png=OUT_A / f"{name}_A1_medallion_pattern.png",
            cell_px=34,
        )
        write_bom_csv(bom_a1, tot_a1, pal, OUT_A / f"{name}_A1_medallion_bom.csv")
        render_bead_preview(med_idx, med_mask, pal, OUT_A / f"{name}_A1_bead_preview.png", cell_px=16)
        print(f"[A1] {name}: {len(bom_a1)} colors, {tot_a1} beads -> {[pal[i]['code'] for i, _ in bom_a1[:8]]}")

        # --- Pathway A2: Inner Sprite Only (no white lace ring, saves 1400+ beads) ---
        in_rgba = np.array(Image.open(INPUTS_DIR / f"{name}_inner_only.png").convert("RGBA"))
        in_mask = in_rgba[:, :, 3] > 0
        in_clean = denoise_jpeg_sprite(in_rgba, is_medallion=False, de_thresh=3.5)
        in_idx = ciede2000_snap(in_clean, pal_lab)

        bom_a2, tot_a2 = render_sheet_png(
            in_idx, in_mask, pal,
            title=f"{cn_name} · 纯主体无白圈版（省豆推荐）",
            subtitle="途径 A2：剥离白底与紫边，仅保留伊布与花簇",
            out_png=OUT_A / f"{name}_A2_inner_pattern.png",
            cell_px=38,
        )
        write_bom_csv(bom_a2, tot_a2, pal, OUT_A / f"{name}_A2_inner_bom.csv")
        render_bead_preview(in_idx, in_mask, pal, OUT_A / f"{name}_A2_bead_preview.png", cell_px=18)
        print(f"[A2] {name}: {len(bom_a2)} colors, {tot_a2} beads -> {[pal[i]['code'] for i, _ in bom_a2[:8]]}")

        # --- Pathway D: Zippland BFS Noise Merge + 14-Color Beginner Edition ---
        d_idx = bfs_simplify_and_reduce(
            med_idx, med_mask, pal, pal_lab,
            target_colors=14,
            protected_codes=protect,
        )
        bom_d, tot_d = render_sheet_png(
            d_idx, med_mask, pal,
            title=f"{cn_name} · 七卡瓦风格 BFS 精简版（14色新手友好）",
            subtitle="途径 D：连通域杂色自动合并 + 14色精简色卡",
            out_png=OUT_D / f"{name}_D_bfs_14colors.png",
            cell_px=34,
        )
        write_bom_csv(bom_d, tot_d, pal, OUT_D / f"{name}_D_bfs_14colors_bom.csv")
        render_bead_preview(d_idx, med_mask, pal, OUT_D / f"{name}_D_bead_preview.png", cell_px=16)
        print(f"[D]  {name}: {len(bom_d)} colors, {tot_d} beads -> {[pal[i]['code'] for i, _ in bom_d]}")


if __name__ == "__main__":
    main()
