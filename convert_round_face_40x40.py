# -*- coding: utf-8 -*-
"""Extract and convert the uploaded '圆脸猫' grid chart (8fd14af5) into an exact 40x41 MARD fuse-bead cutout pattern."""

from collections import Counter, deque
from pathlib import Path
import sys
import numpy as np
from PIL import Image
from skimage import color as skcolor

PROJECT_ROOT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fast_parallel_pindou_cats import export_pindou_json, load_palette
from fast_parallel_pindou_engine import delta_e2000_matrix, keep_exact_color_count_reduce
from refined_two_track_helpers import render_baked_flat_melt_preview
from run_pathway_a_and_d import render_sheet_png, write_bom_csv

SRC_IMG = Path(
    r"C:\Users\Administrator\.gemini\antigravity\brain\8fc5a11e-ec61-4869-94de-2135da89f4d3\.user_uploaded\media_1794838953773_8fd14af5.jpg"
)
OUT_DIR = PROJECT_ROOT / "猫咪拼豆图纸汇总" / "06_圆脸猫异形像素风_40x40"
AUX_DIR = OUT_DIR / "辅助_采购清单与可编辑工程"


def _find_exact_cat_gridlines(im: np.ndarray) -> tuple[list[int], list[int]]:
    """
    Detect exact 40 column boundaries (aligned to decorative grid & vertical borders)
    and 41 cat pixel-row boundaries (aligned directly to true pixel color-step transitions
    from y=18 to y=263 so non-uniformly scaled bottom chin stairs never split).
    """
    lum = im.mean(axis=2)

    # 1) Exact 40 columns from high-pass + top white margin dark gridline dips
    hp_x = np.abs(im[4:264, 1:-1] - 0.5 * (im[4:264, :-2] + im[4:264, 2:])).mean(axis=(0, 2))
    hp_x = np.pad(hp_x, (1, 1))
    top_dark_x = np.clip(252.0 - lum[5:10, :].mean(axis=0), 0, 120)
    score_x = 0.7 * hp_x + 0.35 * top_dark_x

    n_cols = 40
    x_start, x_end = 6, 280
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

    # 2) Sample clean column interiors, then detect true 41 pixel rows across [18..263]
    cols = np.stack(
        [im[:, (gx[c] + gx[c + 1]) // 2 - 1 : (gx[c] + gx[c + 1]) // 2 + 2].mean(axis=1) for c in range(n_cols)],
        axis=1,
    )
    step_e = np.zeros(im.shape[0], dtype=np.float64)
    for y in range(4, im.shape[0] - 4):
        step_e[y] = np.abs(np.median(cols[y - 3 : y], axis=0) - np.median(cols[y + 1 : y + 4], axis=0)).mean()

    n_rows = 41
    y_start, y_end = 18, 263
    nom_y = (y_end - y_start) / n_rows
    dp_y: list[dict[int, tuple[float, int | None]]] = [{} for _ in range(n_rows + 1)]
    for s in range(y_start - 1, y_start + 2):
        dp_y[0][s] = (float(step_e[s]), None)
    for k in range(1, n_rows + 1):
        for pos in range(y_start + k * 4, min(267, y_start + k * 8 + 1)):
            bv, bp = -1e18, None
            for d in (4, 5, 6, 7, 8):
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


def extract_grid_and_mask(img_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Extract exact 41x40 cell colors and build a solid foreground mask:
    - Pad 1 clean empty row on top -> 42x40 canvas with clear outer border breathing space
    - Prevent flood fill from eating into the borderless bottom white chin (rows 39..40)
    - Exclude faint JPEG fringe halo outside the closed charcoal outline
    """
    im = np.array(Image.open(img_path).convert("RGB"), dtype=np.float32)
    gx, gy = _find_exact_cat_gridlines(im)

    gh, gw = len(gy) - 1, len(gx) - 1
    grid = np.zeros((gh, gw, 3), dtype=np.uint8)
    raw_min_lum = np.zeros((gh, gw), dtype=np.float32)
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
            raw_min_lum[r, c] = float(im[y0 + 1 : max(y0 + 2, y1), x0 + 1 : max(x0 + 2, x1)].mean(axis=2).min())

    # Repair subtle half-cell diagonal transition at left cheek step (r=34, c=3..4): dark border sits across edge
    lum = grid.astype(np.float32).mean(axis=2)
    if lum[33, 3] < 120 and lum[35, 4] < 120 and lum[34, 4] > 160 and lum[34, 3] > 160:
        if raw_min_lum[34, 3] < 150:
            grid[34, 3] = [80, 78, 76]
        else:
            grid[34, 4] = [80, 78, 76]

    lum = grid.astype(np.float32).mean(axis=2)
    chroma = grid.max(axis=2).astype(int) - grid.min(axis=2).astype(int)

    # Identify exterior background pixels without letting flood-fill cross the un-outlined bottom chin edge:
    # Build temporary chin barrier across bottom row r=39 between left outline c=10 and right outline c=28,
    # and seal bottom-left chin curve r=40 c=12..17.
    barrier = lum < 230
    barrier[39, 10:29] = True
    # Only keep r=40 chin tip c=11..17 where actual chin pixels exist (chroma>=12 or dark outline)
    for c in range(11, 18):
        if lum[40, c] < 245 or chroma[40, c] >= 12:
            barrier[40, c] = True

    # Also treat ear-edge valley dark pixels or top corners cleanly as barrier where outline sits
    bg = np.zeros((gh, gw), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for r in range(gh):
        for c in (0, gw - 1):
            if not barrier[r, c] and not bg[r, c]:
                bg[r, c] = True
                q.append((r, c))
    for c in range(gw):
        for r in (0, gh - 1):
            if not barrier[r, c] and not bg[r, c]:
                bg[r, c] = True
                q.append((r, c))

    # Do not let flood fill enter interior bright white cheeks/blaze above r=38 even if lum>=230
    while q:
        r, c = q.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < gh and 0 <= nc < gw and not bg[nr, nc] and not barrier[nr, nc]:
                # Extra safety: inside outer outline, white cells at r>=39 and 11<=c<=17 belong to chin tip
                if nr == 40 and 11 <= nc <= 17 and chroma[nr, nc] >= 10:
                    continue
                bg[nr, nc] = True
                q.append((nr, nc))

    # Strip faint anti-aliased bevel pixels right outside the dark ear/cheek outline:
    is_dark_outline = lum < 130
    for _pass in range(2):
        for r in range(gh):
            for c in range(gw):
                if bg[r, c] or is_dark_outline[r, c]:
                    continue
                if r >= 38:
                    continue  # Never strip bottom white chin!
                bg_nbrs = sum(
                    1
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                    if not (0 <= r + dr < gh and 0 <= c + dc < gw) or bg[r + dr, c + dc]
                )
                has_dark_nbr = any(
                    0 <= r + dr < gh and 0 <= c + dc < gw and is_dark_outline[r + dr, c + dc]
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                )
                if bg_nbrs >= 2 and has_dark_nbr and lum[r, c] >= 180 and r <= 12:
                    bg[r, c] = True
                elif bg_nbrs >= 2 and lum[r, c] >= 225:
                    bg[r, c] = True

    # Seal 1-pixel broken gap in left ear-to-forehead border & right valley edge, remove exterior stray cheek bevel
    # Coordinates here are pre-padding (gh=41, gw=40; +1 row after padding):
    # Pre-pad r=5, c=13 (1-idx row 7, col 14) & r=5, c=27 (1-idx row 7, col 28) bridge charcoal border cleanly
    for vr, vc in ((5, 13), (5, 27)):
        if bg[vr, vc] or lum[vr, vc] > 140:
            bg[vr, vc] = False
            grid[vr, vc] = [70, 70, 72]
    # Remove single stray exterior white pixel hanging outside right cheek outline (pre-pad r=29, c=38 -> 1-idx 31, 39)
    if lum[29, 37] < 130 and lum[29, 38] >= 210:
        bg[29, 38] = True

    # Ensure strictly 1 connected foreground silhouette (drop any tiny stray speck outside outline)
    from scipy.ndimage import label
    fg_raw = ~bg
    lbl, n_comp = label(fg_raw)
    if n_comp > 1:
        sizes = Counter(int(x) for x in lbl[fg_raw])
        main_lbl = max(sizes, key=lambda k: sizes[k])
        fg_raw = lbl == main_lbl

    # Pad 1 empty row on top and 1 on bottom -> clean 40x43 frame so top ear sits cleanly at row 2 (zero edge clipping)
    pad_grid = np.full((gh + 2, gw, 3), 255, dtype=np.uint8)
    pad_mask = np.zeros((gh + 2, gw), dtype=bool)
    pad_grid[1 : gh + 1] = grid
    pad_mask[1 : gh + 1] = fg_raw
    pad_raw_min = np.full((gh + 2, gw), 255.0, dtype=np.float32)
    pad_raw_min[1 : gh + 1] = raw_min_lum

    return pad_grid, pad_mask, pad_raw_min


def clean_and_snap_to_mard(
    grid: np.ndarray,
    fg_mask: np.ndarray,
    pal: list[dict],
    pal_lab: np.ndarray,
    pal_de_mat: np.ndarray,
    target_colors: int = 14,
) -> np.ndarray:
    """Snap clean 40x43 '圆脸猫' grid onto cohesive MARD palette preserving outline, pink ears/nose, eyes & white fur."""
    gh, gw = fg_mask.shape
    clean = grid.astype(np.float32).copy()

    r_c, g_c, b_c = clean[:, :, 0], clean[:, :, 1], clean[:, :, 2]
    chroma = np.maximum(np.maximum(r_c, g_c), b_c) - np.minimum(np.minimum(r_c, g_c), b_c)
    lum = clean.mean(axis=2)
    bg = ~fg_mask

    # Identify outer charcoal border cells (touching empty background, dark low-chroma)
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
            if touches_bg and lum[r, c] < 128 and chroma[r, c] < 36:
                is_outline[r, c] = True

    # White fur inside cat (face cheeks, blaze, bottom white chin) -> pure crisp white H1
    rows_idx = np.arange(gh)[:, None]
    inner_white_fur = (
        fg_mask
        & (~is_outline)
        & ((~touches_bg_mat) | (rows_idx >= 39))
        & (
            ((lum >= 224) & (chroma <= 24))
            | ((rows_idx >= 36) & (lum >= 218) & (chroma <= 26))
        )
    )
    clean[inner_white_fur] = [254.0, 253.0, 251.0]

    # Neutralize green cast on light cream/beige fur
    pale_fur = fg_mask & (~is_outline) & (r_c > 175) & (g_c > 170) & (b_c > 150) & ((g_c - b_c) < 38)
    clean[:, :, 1] = np.where(pale_fur & (g_c > r_c - 2), np.minimum(g_c, r_c - 2), g_c)

    # Gently enhance soft pink inner ears (top rows 2..11 inside left c=3..7 & right c=33..37) so right ear keeps soft blush too
    for er_r0, er_r1, er_c0, er_c1 in [(2, 11, 3, 8), (2, 11, 32, 38)]:
        sub = clean[er_r0:er_r1, er_c0:er_c1]
        sr, sg, sb = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
        ear_pink = (sr - sg >= 14) & (sr >= 195) & ((sg - sb) <= 18) & (lum[er_r0:er_r1, er_c0:er_c1] >= 165)
        sub[:, :, 0] = np.where(ear_pink, np.clip(sr + 8.0, 0, 255), sr)
        sub[:, :, 2] = np.where(ear_pink, np.clip(np.maximum(sb, sg + 2.0), 0, 255), sb)

    banned = {
        "H18", "H21", "H23", "H14", "H15",
        "G15", "M1", "M2", "M3", "M5", "M6", "M7", "M15",
        "M14",
    }
    allowed_idx = [
        i for i, e in enumerate(pal)
        if not e["code"].startswith(("B", "C", "D")) and e["code"] not in banned
        and not (e["code"].startswith("A") and int(e["rgb"][1]) > 215 and int(e["rgb"][2]) < 130)
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

    if is_outline.any():
        idx_grid[is_outline] = code_to_idx["H5"]
    idx_grid[inner_white_fur] = code_to_idx["H1"]

    # Eye pupils + crisp 1-bead catchlights (rows shifted +1 by top pad!)
    for er0, er1, ec0, ec1 in [
        (14, 24, 5, 13),   # left eye
        (14, 24, 26, 34),  # right eye
    ]:
        for rr in range(er0, er1):
            for cc in range(ec0, ec1):
                if not fg_mask[rr, cc] or is_outline[rr, cc]:
                    continue
                lval = clean[rr, cc].mean()
                if lval < 64:
                    idx_grid[rr, cc] = code_to_idx["H7"]
                elif lval >= 145:
                    nbr = clean[max(er0, rr - 1) : min(er1, rr + 2), max(ec0, cc - 1) : min(ec1, cc + 2)].mean(axis=2)
                    if (nbr < 85).sum() >= 4:
                        idx_grid[rr, cc] = code_to_idx["H1"]

    protected = {"H1", "H5", "H7", "F14", "E15", "E1", "F20", "G8", "G10", "G9", "G3", "G16", "A23"}
    idx_grid = keep_exact_color_count_reduce(
        idx_grid,
        fg_mask,
        pal,
        pal_lab,
        target_colors=target_colors,
        protected_codes=protected,
        pal_de_mat=pal_de_mat,
    )

    # Re-lock key features cleanly
    if is_outline.any():
        idx_grid[is_outline] = code_to_idx["H5"]
    idx_grid[inner_white_fur] = code_to_idx["H1"]

    # Clean isolated non-pink bead accidentally speckling inside F14 nose pad (rows 25..30, cols 16..24)
    f14_idx = code_to_idx["F14"]
    for rr in range(25, 31):
        for cc in range(16, 25):
            if idx_grid[rr, cc] == f14_idx or not fg_mask[rr, cc]:
                continue
            pink_nbrs = sum(
                1 for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                if pal[int(idx_grid[rr + dr, cc + dc])]["code"] in {"F14", "E1", "E15"}
            )
            if pink_nbrs >= 3:
                idx_grid[rr, cc] = f14_idx

    return idx_grid


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUX_DIR.mkdir(parents=True, exist_ok=True)

    pal, pal_lab = load_palette()
    pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)

    # Remove previous 40x40 wrong-aspect files before writing exact 40x43
    for old in list(OUT_DIR.glob("*40x40*")) + list(AUX_DIR.glob("*40x40*")):
        if old.is_file():
            old.unlink()

    raw_grid, fg_mask, _ = extract_grid_and_mask(SRC_IMG)
    gh, gw = fg_mask.shape
    idx_grid = clean_and_snap_to_mard(raw_grid, fg_mask, pal, pal_lab, pal_de_mat, target_colors=13)

    n_colors = len(set(int(x) for x in idx_grid[fg_mask]))
    total_fg = int(fg_mask.sum())
    base_name = f"圆脸猫_像素镂空款_{gw}x{gh}_MARD{n_colors}色"

    out_sheet = OUT_DIR / f"{base_name}_图纸.png"
    out_baked = OUT_DIR / f"{base_name}_烘烤成品预览图.jpg"
    out_csv = AUX_DIR / f"{base_name}_采购清单.csv"
    out_json = AUX_DIR / f"{base_name}.pindou.json"

    title = f"圆脸猫 · 像素描边镂空款（{gw}×{gh}）"
    subtitle = f"MARD {n_colors}色 · 真实像素步长对齐 · 完整下巴与闭合描边 · 共 {total_fg} 颗"
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
