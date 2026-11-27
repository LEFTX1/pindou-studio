# -*- coding: utf-8 -*-
"""Extract and convert the uploaded '纸箱白猫' grid chart (96f6cad8) into an exact 40x40 MARD fuse-bead cutout pattern."""

from collections import Counter, deque
from pathlib import Path
import sys
import numpy as np
from PIL import Image
from scipy.ndimage import label
from skimage import color as skcolor

PROJECT_ROOT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fast_parallel_pindou_cats import export_pindou_json, load_palette
from fast_parallel_pindou_engine import delta_e2000_matrix, keep_exact_color_count_reduce
from refined_two_track_helpers import render_baked_flat_melt_preview
from run_pathway_a_and_d import render_sheet_png, write_bom_csv

SRC_IMG = Path(
    r"C:\Users\Administrator\.gemini\antigravity\brain\8fc5a11e-ec61-4869-94de-2135da89f4d3\.user_uploaded\media_1794838960491_96f6cad8.jpg"
)
OUT_DIR = PROJECT_ROOT / "猫咪拼豆图纸汇总" / "07_纸箱白猫异形像素风_40x40"
AUX_DIR = OUT_DIR / "辅助_采购清单与可编辑工程"


def _find_box_cat_gridlines(im: np.ndarray) -> tuple[list[int], list[int]]:
    """
    Detect exact 40 column boundaries (aligned to vertical grid & borders)
    and 38 active cat+box pixel-row boundaries from y=19 to y=280.
    """
    lum = im.mean(axis=2)

    # 1) 40 vertical grid columns (x=8 to x=282), blending gridline peaks + interior pixel step edges
    hp_x = np.abs(im[16:284, 1:-1] - 0.5 * (im[16:284, :-2] + im[16:284, 2:])).mean(axis=(0, 2))
    hp_x = np.pad(hp_x, (1, 1))
    top_dark_x = np.clip(250.0 - lum[16:20, :].mean(axis=0), 0, 120)
    step_x = np.zeros(im.shape[1], dtype=np.float64)
    for x in range(4, im.shape[1] - 4):
        step_x[x] = np.abs(np.median(im[20:280, x - 3 : x], axis=1) - np.median(im[20:280, x + 1 : x + 4], axis=1)).mean()
    score_x = 0.55 * hp_x + 0.25 * top_dark_x + 0.35 * step_x

    n_cols = 40
    x_start, x_end = 8, 282
    nom_x = (x_end - x_start) / n_cols
    dp_x: list[dict[int, tuple[float, int | None]]] = [{} for _ in range(n_cols + 1)]
    for s in range(x_start - 1, x_start + 2):
        dp_x[0][s] = (float(score_x[s]), None)
    for k in range(1, n_cols + 1):
        target_pos = x_start + k * nom_x
        is_major = (k % 5 == 0)
        for pos in range(max(0, int(round(target_pos - 3))), min(im.shape[1], int(round(target_pos + 4)))):
            bv, bp = -1e18, None
            for step in (5, 6, 7, 8, 9):
                prev = pos - step
                if prev in dp_x[k - 1]:
                    v = (
                        dp_x[k - 1][prev][0]
                        + float(score_x[pos]) * (1.25 if is_major else 1.0)
                        - 1.6 * ((step - nom_x) ** 2)
                        - 0.25 * ((pos - target_pos) ** 2)
                    )
                    if v > bv:
                        bv, bp = v, prev
            if bp is not None:
                dp_x[k][pos] = (bv, bp)
    fin_x = max([p for p in range(x_end - 1, x_end + 2) if p in dp_x[n_cols]], key=lambda p: dp_x[n_cols][p][0])
    gx = []
    cur: int | None = fin_x
    for k in range(n_cols, -1, -1):
        assert cur is not None
        gx.append(cur)
        cur = dp_x[k][cur][1]
    gx = list(reversed(gx))

    # 2) Sample clean column interiors, then align 38 cat+box pixel rows cleanly over y=19..280
    cols = np.stack(
        [im[:, (gx[c] + gx[c + 1]) // 2 - 1 : (gx[c] + gx[c + 1]) // 2 + 2].mean(axis=1) for c in range(n_cols)],
        axis=1,
    )
    step_e = np.zeros(im.shape[0], dtype=np.float64)
    for y in range(4, im.shape[0] - 4):
        step_e[y] = np.abs(np.median(cols[y - 3 : y], axis=0) - np.median(cols[y + 1 : y + 4], axis=0)).mean()

    n_rows = 38
    y_start, y_end = 19, 280
    nom_y = (y_end - y_start) / n_rows
    dp_y: list[dict[int, tuple[float, int | None]]] = [{} for _ in range(n_rows + 1)]
    for s in range(y_start - 1, y_start + 2):
        dp_y[0][s] = (float(step_e[s]), None)
    for k in range(1, n_rows + 1):
        for pos in range(y_start + k * 4, min(286, y_start + k * 9 + 1)):
            bv, bp = -1e18, None
            for d in (4, 5, 6, 7, 8, 9):
                prev = pos - d
                if prev in dp_y[k - 1]:
                    v = dp_y[k - 1][prev][0] + float(step_e[pos]) - 1.5 * ((d - nom_y) ** 2)
                    if v > bv:
                        bv, bp = v, prev
            if bp is not None:
                dp_y[k][pos] = (bv, bp)
    fin_y = max([p for p in range(y_end - 1, y_end + 2) if p in dp_y[n_rows]], key=lambda p: dp_y[n_rows][p][0])
    gy = []
    cur = fin_y
    for k in range(n_rows, -1, -1):
        assert cur is not None
        gy.append(cur)
        cur = dp_y[k][cur][1]
    gy = list(reversed(gy))
    return gx, gy


def extract_grid_and_mask(img_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Extract 38x40 cells, isolate closed cutout silhouette via BFS flood fill, and pad to clean 40x40."""
    im = np.array(Image.open(img_path).convert("RGB"), dtype=np.float32)
    gx, gy = _find_box_cat_gridlines(im)

    gh, gw = len(gy) - 1, len(gx) - 1
    grid = np.zeros((gh, gw, 3), dtype=np.uint8)
    for r in range(gh):
        y0, y1 = gy[r], gy[r + 1]
        cy = (y0 + y1) // 2
        ry0, ry1 = max(y0 + 1, cy - 1), min(y1, cy + 2)
        if ry1 <= ry0:
            ry0, ry1 = cy, cy + 1
        for c in range(gw):
            x0, x1 = gx[c], gx[c + 1]
            cx = (x0 + x1) // 2
            cx0, cx1 = max(x0 + 1, cx - 1), min(x1, cx + 2)
            if cx1 <= cx0:
                cx0, cx1 = cx, cx + 1
            patch = im[ry0:ry1, cx0:cx1].reshape(-1, 3)
            grid[r, c] = np.round(np.median(patch, axis=0)).astype(np.uint8)

    lum = grid.astype(np.float32).mean(axis=2)
    chroma = grid.max(axis=2).astype(int) - grid.min(axis=2).astype(int)

    # Outer empty background cells are neutral white OR neutral grey major-gridline noise (chroma <= 10, lum >= 185)
    is_white_empty = ((lum >= 225) & (chroma <= 22)) | ((lum >= 185) & (chroma <= 11))
    bg = np.zeros((gh, gw), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for r in range(gh):
        for c in (0, gw - 1):
            if is_white_empty[r, c] and not bg[r, c]:
                bg[r, c] = True
                q.append((r, c))
    for c in range(gw):
        for r in (0, gh - 1):
            if is_white_empty[r, c] and not bg[r, c]:
                bg[r, c] = True
                q.append((r, c))
    while q:
        r, c = q.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < gh and 0 <= nc < gw and not bg[nr, nc] and is_white_empty[nr, nc]:
                bg[nr, nc] = True
                q.append((nr, nc))

    # Strip faint anti-aliased bevel pixels clinging outside dark charcoal outline
    is_dark = lum < 145
    for _pass in range(2):
        for r in range(gh):
            for c in range(gw):
                if bg[r, c] or is_dark[r, c]:
                    continue
                bg_nbrs = sum(
                    1
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                    if not (0 <= r + dr < gh and 0 <= c + dc < gw) or bg[r + dr, c + dc]
                )
                has_dark_nbr = any(
                    0 <= r + dr < gh and 0 <= c + dc < gw and is_dark[r + dr, c + dc]
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                )
                if bg_nbrs >= 2 and has_dark_nbr and lum[r, c] >= 180 and chroma[r, c] <= 24:
                    bg[r, c] = True
                elif bg_nbrs >= 2 and lum[r, c] >= 220 and chroma[r, c] <= 24:
                    bg[r, c] = True

    fg_raw = ~bg
    # Remove single exterior cell poking right past nose outline (1-idx row 11, col 38 -> pre-pad r=9, c=37)
    # and seal dark outline corner just inside it (1-idx row 11, col 37 -> pre-pad r=9, c=36)
    bg[9, 37] = True
    fg_raw = ~bg
    if fg_raw[9, 36]:
        grid[9, 36] = [70, 70, 72]

    lbl, n_comp = label(fg_raw)
    if n_comp > 1:
        sizes = Counter(int(x) for x in lbl[fg_raw])
        main_lbl = max(sizes, key=lambda k: sizes[k])
        fg_raw = lbl == main_lbl

    # Pad 1 blank row top and bottom -> clean 40x40 square canvas matching the card grid
    pad_grid = np.full((gh + 2, gw, 3), 255, dtype=np.uint8)
    pad_mask = np.zeros((gh + 2, gw), dtype=bool)
    pad_grid[1 : gh + 1] = grid
    pad_mask[1 : gh + 1] = fg_raw
    return pad_grid, pad_mask


def clean_and_snap_to_mard(
    grid: np.ndarray,
    fg_mask: np.ndarray,
    pal: list[dict],
    pal_lab: np.ndarray,
    pal_de_mat: np.ndarray,
    target_colors: int = 14,
) -> np.ndarray:
    """
    Quantize the 40x40 '纸箱白猫' grid cleanly into ~14 cohesive MARD colors:
    - Pure bright white cat coat (H1) + subtle warm cream shadows (M4/A23/G16)
    - Sakura-pink inner ears & tiny nose (F14/E15/E1/F20)
    - Crisp black eyes (H7) + 1-bead pure-white glints (H1)
    - Warm brown cardboard box + bright golden-yellow rope handle
    - Clean dark charcoal outline (H5)
    """
    gh, gw = fg_mask.shape
    clean = grid.astype(np.float32).copy()

    r_c, g_c, b_c = clean[:, :, 0], clean[:, :, 1], clean[:, :, 2]
    chroma = np.maximum(np.maximum(r_c, g_c), b_c) - np.minimum(np.minimum(r_c, g_c), b_c)
    lum = clean.mean(axis=2)
    bg = ~fg_mask

    # Identify outer dark outline cells (touching background, dark low-to-mid chroma)
    touches_bg_mat = np.zeros((gh, gw), dtype=bool)
    is_outline = np.zeros((gh, gw), dtype=bool)
    for r in range(gh):
        for c in range(gw):
            if not fg_mask[r, c]:
                continue
            touches_bg = any(
                not (0 <= r + dr < gh and 0 <= c + dc < gw) or bg[r + dr, c + dc]
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
            )
            touches_bg_mat[r, c] = touches_bg
            if touches_bg and lum[r, c] < 130 and chroma[r, c] < 55:
                is_outline[r, c] = True

    # White fur inside cat (cat head/ears/back lum >= 220 & low chroma) -> pure crisp H1 white
    inner_white_fur = fg_mask & (~is_outline) & (~touches_bg_mat) & (lum >= 220) & (chroma <= 24)
    clean[inner_white_fur] = [254.0, 253.0, 251.0]

    # Neutralize green cast on pale shaded white fur
    pale_fur = fg_mask & (~is_outline) & (r_c > 180) & (g_c > 175) & (b_c > 155) & ((g_c - b_c) < 38)
    clean[:, :, 1] = np.where(pale_fur & (g_c > r_c - 2), np.minimum(g_c, r_c - 2), g_c)

    # Gently preserve sakura-pink & rose inner ears/nose (rows 1..12, cols 20..38) instead of merging into orange-tan
    rows_idx = np.arange(gh)[:, None]
    ear_nose_mask = (
        fg_mask
        & (~is_outline)
        & (rows_idx >= 1)
        & (rows_idx <= 12)
        & (np.arange(gw)[None, :] >= 20)
        & (r_c - g_c >= 18)
        & ((g_c - b_c) <= 22)
        & (r_c >= 120)
    )
    clean[ear_nose_mask, 0] = np.clip(clean[ear_nose_mask, 0] + 10.0, 0, 255)
    clean[ear_nose_mask, 1] = np.clip(clean[ear_nose_mask, 1] - 6.0, 0, 255)
    clean[ear_nose_mask, 2] = np.clip(np.maximum(clean[ear_nose_mask, 2], clean[ear_nose_mask, 1] + 2.0), 0, 255)

    # Gently enhance yellow rope saturation (rows >= 24, bright warm yellow R>190, G>150, R-B>75) so rope stays vivid gold
    rope_yellow = fg_mask & (~is_outline) & (rows_idx >= 24) & (r_c >= 185) & (g_c >= 140) & (r_c - b_c >= 70)
    clean[rope_yellow, 0] = np.clip(clean[rope_yellow, 0] + 15.0, 0, 255)
    clean[rope_yellow, 1] = np.clip(clean[rope_yellow, 1] + 14.0, 0, 255)
    clean[rope_yellow, 2] = np.clip(clean[rope_yellow, 2] - 10.0, 0, 255)

    # Keep all golden yellows A* available; ban cool blues/greens/olives, M14 coral, and peach A18
    banned = {
        "H18", "H21", "H23", "H14", "H15",
        "G15", "M1", "M2", "M3", "M5", "M6", "M7", "M15",
        "M14", "A18",
    }
    allowed_idx = [
        i for i, e in enumerate(pal)
        if not e["code"].startswith(("B", "C", "D")) and e["code"] not in banned
    ]
    allowed_arr = np.array(allowed_idx, dtype=np.int32)
    allowed_lab = pal_lab[allowed_arr]
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}

    clean_u8 = np.clip(np.round(clean), 0, 255).astype(np.uint8)
    clean_lab = skcolor.rgb2lab(clean_u8.astype(np.float64) / 255.0)
    idx_grid = np.zeros((gh, gw), dtype=np.int32)
    fg_coords = np.argwhere(fg_mask)
    de = delta_e2000_matrix(clean_lab[fg_mask], allowed_lab)
    nearest_fg = allowed_arr[np.argmin(de, axis=1)]
    for (r, c), pid in zip(fg_coords, nearest_fg):
        idx_grid[r, c] = int(pid)

    # Lock pink inner ear/nose shades directly to F14 / E15 / F20 / M8 so they never snap to cardboard M13
    pink_pool = [code_to_idx[c] for c in ("F14", "E15", "F20", "M8") if c in code_to_idx]
    pink_lab = pal_lab[pink_pool]
    for r, c in np.argwhere(ear_nose_mask):
        de_p = delta_e2000_matrix(clean_lab[r, c].reshape(1, 3), pink_lab)[0]
        idx_grid[r, c] = int(pink_pool[int(np.argmin(de_p))])

    if is_outline.any():
        idx_grid[is_outline] = code_to_idx["H5"]
    idx_grid[inner_white_fur] = code_to_idx["H1"]

    # Crisp eye pupils & 1-bead catchlights (right-facing cat eyes sit around rows 5..12, cols 28..35)
    eye_glints = []
    for er0, er1, ec0, ec1 in [(5, 13, 28, 36)]:
        for rr in range(er0, er1):
            for cc in range(ec0, ec1):
                if not fg_mask[rr, cc] or is_outline[rr, cc]:
                    continue
                lval = clean[rr, cc].mean()
                if lval < 96 and chroma[rr, cc] < 28:
                    idx_grid[rr, cc] = code_to_idx["H7"]
                elif lval >= 140:
                    nbr = clean[max(er0, rr - 1) : min(er1, rr + 2), max(ec0, cc - 1) : min(ec1, cc + 2)].mean(axis=2)
                    if (nbr < 100).sum() >= 3:
                        idx_grid[rr, cc] = code_to_idx["H1"]
                        eye_glints.append((rr, cc))

    # Protect key palette colors so rope yellow, pink ears, outline & white coat never merge into brown
    rope_codes = {pal[int(idx_grid[r, c])]["code"] for r, c in np.argwhere(rope_yellow)}
    protected = {"H1", "H5", "H7", "F14", "E15", "F20", "M8", "G8", "G10", "G13", "M13", "A23", "M4"} | rope_codes
    idx_grid = keep_exact_color_count_reduce(
        idx_grid,
        fg_mask,
        pal,
        pal_lab,
        target_colors=target_colors,
        protected_codes=protected,
        pal_de_mat=pal_de_mat,
    )

    # Re-lock key features after reduction
    if is_outline.any():
        idx_grid[is_outline] = code_to_idx["H5"]
    idx_grid[inner_white_fur] = code_to_idx["H1"]
    for rr, cc in eye_glints:
        idx_grid[rr, cc] = code_to_idx["H1"]

    # Keep pink/rose ear-nose codes (F14, E15, M8) strictly inside cat ears & nose so box seams never get pink specks
    pink_codes = {code_to_idx[c] for c in ("F14", "E15", "M8") if c in code_to_idx}
    used_indices = sorted(set(int(x) for x in idx_grid[fg_mask]))
    non_pink_pool = [i for i in used_indices if i not in pink_codes]
    if pink_codes and non_pink_pool:
        np_arr = np.array(non_pink_pool, dtype=np.int32)
        np_lab = pal_lab[np_arr]
        for r, c in np.argwhere(fg_mask):
            if int(idx_grid[r, c]) in pink_codes and not (r <= 13 and c >= 20):
                de_np = delta_e2000_matrix(clean_lab[r, c].reshape(1, 3), np_lab)[0]
                idx_grid[r, c] = int(np_arr[int(np.argmin(de_np))])

    # Avoid vivid orange A6 inside pink ear region (rows <= 14): replace with soft A23/E15
    if "A6" in code_to_idx:
        a6_idx = code_to_idx["A6"]
        ear_alt = [code_to_idx[c] for c in ("E15", "F14", "A23", "M4") if c in code_to_idx and c in {pal[i]["code"] for i in used_indices}]
        if ear_alt:
            ea_arr = np.array(ear_alt, dtype=np.int32)
            ea_lab = pal_lab[ea_arr]
            for r, c in np.argwhere(fg_mask):
                if r <= 14 and int(idx_grid[r, c]) == a6_idx:
                    de_ea = delta_e2000_matrix(clean_lab[r, c].reshape(1, 3), ea_lab)[0]
                    idx_grid[r, c] = int(ea_arr[int(np.argmin(de_ea))])

    return idx_grid


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUX_DIR.mkdir(parents=True, exist_ok=True)

    for old in list(OUT_DIR.glob("*纸箱白猫*")) + list(AUX_DIR.glob("*纸箱白猫*")):
        if old.is_file():
            old.unlink()

    pal, pal_lab = load_palette()
    pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)

    raw_grid, fg_mask = extract_grid_and_mask(SRC_IMG)
    gh, gw = fg_mask.shape
    idx_grid = clean_and_snap_to_mard(raw_grid, fg_mask, pal, pal_lab, pal_de_mat, target_colors=15)

    n_colors = len(set(int(x) for x in idx_grid[fg_mask]))
    total_fg = int(fg_mask.sum())
    base_name = f"纸箱白猫_像素镂空款_{gw}x{gh}_MARD{n_colors}色"

    out_sheet = OUT_DIR / f"{base_name}_图纸.png"
    out_baked = OUT_DIR / f"{base_name}_烘烤成品预览图.jpg"
    out_csv = AUX_DIR / f"{base_name}_采购清单.csv"
    out_json = AUX_DIR / f"{base_name}.pindou.json"

    title = f"纸箱白猫 · 像素描边镂空款（{gw}×{gh}）"
    subtitle = f"MARD {n_colors}色 · 1:1 真实像素步长提取 · 含炭灰描边与透明镂空外围 · 共 {total_fg} 颗"
    bom, total_beads = render_sheet_png(
        idx_grid,
        fg_mask,
        pal,
        title=title,
        subtitle=subtitle,
        out_png=out_sheet,
        cell_px=38,
        palette_name="MARD",
    )
    write_bom_csv(bom, total_beads, pal, out_csv, palette_name="MARD")
    export_pindou_json(idx_grid, fg_mask, pal, SRC_IMG, base_name, out_json)
    render_baked_flat_melt_preview(idx_grid, fg_mask, pal, out_baked, cell_px=24, seed=20261116)

    print(f"GRID={gw}x{gh}, FG_BEADS={total_fg}, COLORS={n_colors}")
    print("BOM:", ", ".join(f"{pal[i]['code']}({pal[i]['name_zh']} x{cnt})" for i, cnt in bom))
    print(f"OUT_SHEET={out_sheet}")
    print(f"OUT_BAKED={out_baked}")
    print(f"OUT_CSV={out_csv}")
    print(f"OUT_JSON={out_json}")


if __name__ == "__main__":
    main()
