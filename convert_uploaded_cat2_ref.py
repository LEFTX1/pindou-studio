# -*- coding: utf-8 -*-
"""Convert the uploaded HD pixel reference image (3ccc1d59 / cat2 face) to a clean MARD fuse-bead pattern."""

from pathlib import Path
import sys
import numpy as np
from PIL import Image
from skimage import color as skcolor

PROJECT_ROOT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fast_parallel_pindou_cats import (
    export_pindou_json,
    load_palette,
    pindou_studio_photo_quantize,
)
from fast_parallel_pindou_engine import (
    delta_e2000_matrix,
    keep_exact_color_count_reduce,
)
from refined_two_track_helpers import render_baked_flat_melt_preview
from run_pathway_a_and_d import render_sheet_png, write_bom_csv

UPLOADED_REF = Path(
    r"C:\Users\Administrator\.gemini\antigravity\brain\8fc5a11e-ec61-4869-94de-2135da89f4d3\.user_uploaded\media_1794828153787_3ccc1d59.jpg"
)
OUT_DIR = PROJECT_ROOT / "猫咪拼豆图纸汇总" / "05_参考图直转_圆脸猫高清像素版"
AUX_DIR = OUT_DIR / "辅助_采购清单与可编辑工程"


def _detect_outer_grid_bounds(im: np.ndarray) -> tuple[int, int, int, int]:
    """Detect outer non-white canvas bounds containing the pixel grid (excluding margin/caption)."""
    lum = im.mean(axis=2)
    h, w = lum.shape
    # Active band has lower mean luminance than the outer ~250 white border/caption area
    row_active = np.where((lum[:, int(w * 0.1) : int(w * 0.9)] < 235).mean(axis=1) > 0.35)[0]
    col_active = np.where((lum[int(h * 0.1) : int(h * 0.85), :] < 235).mean(axis=0) > 0.35)[0]
    y0, y1 = int(row_active[0]), int(row_active[-1])
    x0, x1 = int(col_active[0]), int(col_active[-1])
    return x0, x1, y0, y1


def _dp_align_gridlines(
    hp_score: np.ndarray,
    start: int,
    end: int,
    step_min: int = 9,
    step_max: int = 13,
    nominal_step: float = 10.88,
) -> list[int]:
    """Find optimal monotonic gridline pixel positions using DP on 1D high-pass energy."""
    smoothed = 0.25 * np.roll(hp_score, -1) + 0.5 * hp_score + 0.25 * np.roll(hp_score, 1)
    dp: dict[int, tuple[float, int | None]] = {start: (float(smoothed[start]), None)}
    for pos in range(start + step_min, end + 3):
        if pos >= len(smoothed):
            break
        best_val = -1e18
        best_prev = None
        for step in range(step_min, step_max + 1):
            prev = pos - step
            if prev in dp:
                score = dp[prev][0] + float(smoothed[pos]) - 0.5 * ((step - nominal_step) ** 2)
                if score > best_val:
                    best_val = score
                    best_prev = prev
        if best_prev is not None:
            dp[pos] = (best_val, best_prev)
    cands = [p for p in range(end - 2, end + 3) if p in dp]
    fin = max(cands, key=lambda p: dp[p][0])
    path = []
    cur: int | None = fin
    while cur is not None:
        path.append(cur)
        cur = dp[cur][1]
    return list(reversed(path))


def extract_dp_grid(img_path: Path) -> tuple[np.ndarray, dict]:
    """Extract clean cell-by-cell RGB grid from a JPEG grid-overlaid pixel reference image."""
    im = np.array(Image.open(img_path).convert("RGB"), dtype=np.float32)
    x0, x1, y0, y1 = _detect_outer_grid_bounds(im)

    hp_x = np.abs(im[y0 + 4 : y1 - 4, 1:-1] - 0.5 * (im[y0 + 4 : y1 - 4, :-2] + im[y0 + 4 : y1 - 4, 2:])).mean(
        axis=(0, 2)
    )
    hp_x = np.pad(hp_x, (1, 1))
    hp_y = np.abs(im[1:-1, x0 + 4 : x1 - 4] - 0.5 * (im[:-2, x0 + 4 : x1 - 4] + im[2:, x0 + 4 : x1 - 4])).mean(
        axis=(1, 2)
    )
    hp_y = np.pad(hp_y, (1, 1))

    gx = _dp_align_gridlines(hp_x, x0, x1, step_min=9, step_max=13, nominal_step=10.90)
    gy = _dp_align_gridlines(hp_y, y0, y1, step_min=9, step_max=13, nominal_step=10.86)

    gh, gw = len(gy) - 1, len(gx) - 1
    grid = np.zeros((gh, gw, 3), dtype=np.uint8)
    interior_stds = []
    for r in range(gh):
        ry0, ry1 = gy[r] + 3, gy[r + 1] - 2
        if ry1 <= ry0:
            mid_y = (gy[r] + gy[r + 1]) // 2
            ry0, ry1 = mid_y - 1, mid_y + 2
        for c in range(gw):
            cx0, cx1 = gx[c] + 3, gx[c + 1] - 2
            if cx1 <= cx0:
                mid_x = (gx[c] + gx[c + 1]) // 2
                cx0, cx1 = mid_x - 1, mid_x + 2
            patch = im[ry0:ry1, cx0:cx1]
            interior_stds.append(float(patch.std()))
            grid[r, c] = np.round(np.median(patch.reshape(-1, 3), axis=0)).astype(np.uint8)

    stats = {
        "bounds": (x0, x1, y0, y1),
        "shape": (gh, gw),
        "max_patch_std": float(max(interior_stds)),
        "mean_patch_std": float(np.mean(interior_stds)),
    }
    return grid, stats


def clean_and_calibrate_grid(grid: np.ndarray) -> np.ndarray:
    """
    Remove bottom-left collar smudge artifact seamlessly, neutralize greenish casts on white fur,
    preserve bright white/ivory muzzle contrast against orange tabby cheeks, and enhance dusty-rose nose tone.
    """
    out = grid.astype(np.float32).copy()
    gh, gw, _ = out.shape

    # 1) Clean tiny blurry collar/tag smudge at bottom-left white chest (rows ~0.81H..H, cols ~0.08W..0.21W)
    r_lo, r_hi = int(round(gh * 0.81)), gh
    c_lo, c_hi = int(round(gw * 0.08)), int(round(gw * 0.21))
    chest_patch = out[r_lo:r_hi, c_lo:c_hi]
    lum_patch = chest_patch.mean(axis=2)
    clean_mask = lum_patch >= np.percentile(lum_patch, 60)
    if clean_mask.any():
        chest_ref = np.median(chest_patch[clean_mask], axis=0)
        # Replace dark smudge cells using median of non-smudge neighbors clamped near local chest cream
        smudge = lum_patch < (chest_ref.mean() - 16.0)
        ys, xs = np.where(smudge)
        for ry, cx in zip(ys, xs):
            rr, cc = r_lo + int(ry), c_lo + int(cx)
            w_sub = out[max(r_lo - 2, rr - 2) : min(gh, rr + 3), max(c_lo - 1, cc - 2) : min(c_hi + 2, cc + 3)]
            w_lum = w_sub.mean(axis=2)
            bright = w_sub[w_lum >= (chest_ref.mean() - 14.0)]
            fill = np.median(bright, axis=0) if len(bright) >= 3 else chest_ref
            # Clamp slightly below max white so smudge repair blends smoothly into adjacent G1 cream
            out[rr, cc] = np.minimum(fill, chest_ref + 4.0)

    # 2) Neutralize faint green/yellow-green cast on pale cream/white fur (ensure R >= G + 3 in pale neutral pixels)
    r_c, g_c, b_c = out[:, :, 0], out[:, :, 1], out[:, :, 2]
    pale_fur = (r_c > 190) & (g_c > 185) & (b_c > 165) & ((g_c - b_c) < 38)
    out[:, :, 1] = np.where(pale_fur & (g_c > r_c - 3), np.minimum(g_c, r_c - 3), g_c)

    # 3) Gently lift shaded white muzzle & whisker pads (low-chroma cream shadow R-B<=54) so muzzle stays ivory vs orange cheeks
    ys_all, xs_all = np.mgrid[0:gh, 0:gw]
    r_c, g_c, b_c = out[:, :, 0], out[:, :, 1], out[:, :, 2]
    chroma_rb = r_c - b_c
    # Exclude nose region itself and deep bottom chin edge shadow
    nose_box = (ys_all >= int(gh * 0.50)) & (ys_all <= int(gh * 0.78)) & (xs_all >= int(gw * 0.28)) & (xs_all <= int(gw * 0.60))
    muzzle_shadow = (
        (ys_all >= int(gh * 0.52))
        & (ys_all <= int(gh * 0.90))
        & (xs_all >= int(gw * 0.10))
        & (xs_all <= int(gw * 0.86))
        & (~nose_box)
        & (r_c >= 172)
        & (r_c <= 222)
        & (chroma_rb <= 54)
        & ((r_c - g_c) <= 34)
    )
    out[muzzle_shadow] = np.clip(out[muzzle_shadow] + np.array([20.0, 20.0, 21.0], dtype=np.float32), 0, 245)

    # 4) Smoothly preserve dusty-rose tone across full upper & mid nose pad without purple/orange cliff
    nr0, nr1 = int(round(gh * 0.50)), int(round(gh * 0.77))
    nc0, nc1 = int(round(gw * 0.27)), int(round(gw * 0.61))
    nose_view = out[nr0:nr1, nc0:nc1]
    nr, ng, nb = nose_view[:, :, 0], nose_view[:, :, 1], nose_view[:, :, 2]
    pinkish = (nr - ng >= 14) & (nr >= 128) & ((ng - nb) <= 16)
    if pinkish.any():
        gray_mid = 0.5 * (ng + nb)
        nr_new = np.clip(gray_mid + 1.18 * (nr - gray_mid) + 8.0, 0, 255)
        ng_new = np.clip(ng + 5.0, 0, 255)
        nb_new = np.clip(nb + 10.0, 0, 255)
        nose_view[:, :, 0] = np.where(pinkish, nr_new, nr)
        nose_view[:, :, 1] = np.where(pinkish, ng_new, ng)
        nose_view[:, :, 2] = np.where(pinkish, nb_new, nb)

    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def _allowed_palette_indices(pal: list[dict]) -> list[int]:
    """Exclude green/blue/cyan/olive/purple MARD families and M7 grey-olive irrelevant to orange-white tabby cat."""
    banned_exact = {
        "H18", "H21", "H23", "H14", "H15",
        "G15", "M1", "M2", "M3", "M5", "M6", "M7", "M15",
    }
    allowed = []
    for idx, entry in enumerate(pal):
        code = entry["code"]
        if code.startswith(("B", "C", "D")):
            continue
        if code in banned_exact:
            continue
        if code.startswith("A"):
            r, g, b = map(int, entry["rgb"])
            if g > 215 and b < 130:
                continue
        allowed.append(idx)
    return allowed


def quantize_uploaded_ref(
    grid: np.ndarray,
    pal: list[dict],
    pal_lab: np.ndarray,
    pal_de_mat: np.ndarray,
    target_colors: int = 20,
) -> tuple[np.ndarray, list[str]]:
    """Quantize clean RGB grid into MARD palette while locking dusty-rose nose & eye catchlights."""
    gh, gw, _ = grid.shape
    full_mask = np.ones((gh, gw), dtype=bool)

    allowed_idx = _allowed_palette_indices(pal)
    pal_sub = [pal[i] for i in allowed_idx]
    pal_lab_sub = pal_lab[allowed_idx]
    pal_de_sub = pal_de_mat[np.ix_(allowed_idx, allowed_idx)]

    sub_idx_grid, selected_codes = pindou_studio_photo_quantize(
        grid,
        full_mask,
        pal_sub,
        pal_lab_sub,
        pal_de_sub,
        max_colors=target_colors + 2,
        has_outer_alpha=False,
        seed=20261116,
    )

    code_to_full = {e["code"]: i for i, e in enumerate(pal)}
    full_map = np.array(allowed_idx, dtype=np.int32)
    idx_grid = full_map[sub_idx_grid]

    # Ensure key features exist cleanly before final reduction:
    # Snap pure bright pixels inside left & right eyes (catchlights) back to H1 / crisp highlight if present in grid
    lum = grid.astype(np.float32).mean(axis=2)
    # Left eye region (viewer's left): rows ~0.22H..0.44H, cols ~0.04W..0.28W
    el_r0, el_r1 = int(round(gh * 0.22)), int(round(gh * 0.44))
    el_c0, el_c1 = int(round(gw * 0.04)), int(round(gw * 0.28))
    eye_left_glint = np.zeros((gh, gw), dtype=bool)
    eye_left_glint[el_r0:el_r1, el_c0:el_c1] = lum[el_r0:el_r1, el_c0:el_c1] >= 165
    # Verify glint pixels sit inside dark surround (cat eye pupil/iris, not outer cheek white fur)
    for r, c in np.argwhere(eye_left_glint):
        nbr = lum[max(0, r - 2) : min(gh, r + 3), max(0, c - 2) : min(gw, c + 3)]
        if (nbr < 85).sum() >= 10:
            idx_grid[r, c] = code_to_full["H1"]
        else:
            eye_left_glint[r, c] = False

    # Right eye subtle catchlight inside dark pupil (rows ~0.24H..0.44H, cols ~0.68W..0.90W)
    er_r0, er_r1 = int(round(gh * 0.24)), int(round(gh * 0.44))
    er_c0, er_c1 = int(round(gw * 0.68)), int(round(gw * 0.90))
    eye_right_glint = np.zeros((gh, gw), dtype=bool)
    for r in range(er_r0, er_r1):
        for c in range(er_c0, er_c1):
            nbr = lum[max(0, r - 2) : min(gh, r + 3), max(0, c - 2) : min(gw, c + 3)]
            if (nbr < 65).sum() >= 14 and lum[r, c] >= 80:
                eye_right_glint[r, c] = True
                # Keep crisp 1-bead subtle highlight (H3/H4/H19 depending on original brightness)
                if lum[r, c] >= 135:
                    idx_grid[r, c] = code_to_full["H2"]
                else:
                    idx_grid[r, c] = code_to_full["H4"]

    # Force dusty-rose nose pixels cleanly across coherent gradient (F20 -> M8 -> G17), avoiding rusty G7/G8 cliff
    nr0, nr1 = int(round(gh * 0.52)), int(round(gh * 0.76))
    nc0, nc1 = int(round(gw * 0.27)), int(round(gw * 0.61))
    rose_pool_codes = [c for c in ("F20", "M8", "G17") if c in code_to_full]
    rose_pool_idx = np.array([code_to_full[c] for c in rose_pool_codes], dtype=np.int32)
    rose_pool_lab = pal_lab[rose_pool_idx]
    for r in range(nr0, nr1):
        for c in range(nc0, nc1):
            R, G, B = map(int, grid[r, c])
            # Exclude dark nostrils/mouth cleft (R < 126) and orange fur (G - B > 18)
            if (R - G >= 16) and (R >= 128) and (B >= 78) and ((G - B) <= 16):
                px_lab = skcolor.rgb2lab(grid[r : r + 1, c : c + 1].astype(np.float64) / 255.0).reshape(1, 3)
                de = delta_e2000_matrix(px_lab, rose_pool_lab)[0]
                best_j = int(np.argmin(de))
                # Bias mid-rose rows (R >= 140) away from dark G17 so soft pink nose pad holds smoothly
                if R >= 140 and pal[int(rose_pool_idx[best_j])]["code"] == "G17" and de[rose_pool_codes.index("M8")] < 12.8:
                    idx_grid[r, c] = int(code_to_full["M8"])
                elif de[best_j] < 13.5:
                    idx_grid[r, c] = int(rose_pool_idx[best_j])

    protected = {"H1", "H7", "H16", "F20", "M8", "G17", "A23", "G1"}
    idx_grid = keep_exact_color_count_reduce(
        idx_grid,
        full_mask,
        pal,
        pal_lab,
        target_colors=target_colors,
        protected_codes=protected,
        pal_de_mat=pal_de_mat,
    )

    # Restrict dusty-rose beads (F20, M8) strictly to the cat nose pad so no pink flecks spill onto cheeks/chin
    used_indices = sorted(set(int(x) for x in idx_grid[full_mask]))
    non_rose_used = [i for i in used_indices if pal[i]["code"] not in {"F20", "M8"}]
    rose_only = {code_to_full[c] for c in ("F20", "M8") if c in code_to_full}
    nose_r0, nose_r1 = int(round(gh * 0.50)), int(round(gh * 0.77))
    nose_c0, nose_c1 = int(round(gw * 0.29)), int(round(gw * 0.61))
    if non_rose_used and rose_only:
        non_rose_arr = np.array(non_rose_used, dtype=np.int32)
        non_rose_lab = pal_lab[non_rose_arr]
        grid_lab = skcolor.rgb2lab(grid.astype(np.float64) / 255.0)
        for r in range(gh):
            for c in range(gw):
                if int(idx_grid[r, c]) not in rose_only:
                    continue
                R, G, _ = map(int, grid[r, c])
                in_nose_pad = (nose_r0 <= r <= nose_r1) and (nose_c0 <= c <= nose_c1) and ((R - G) >= 12)
                if not in_nose_pad:
                    de_alt = delta_e2000_matrix(grid_lab[r, c].reshape(1, 3), non_rose_lab)[0]
                    idx_grid[r, c] = int(non_rose_arr[int(np.argmin(de_alt))])

    # Re-assert catchlight anchor pixels so reduction/isolation never erases 1-bead glint
    if eye_left_glint.any():
        idx_grid[eye_left_glint] = code_to_full["H1"]
    if eye_right_glint.any() and code_to_full.get("H4") is not None:
        # Use brightest dark-grey/silver already in grid or H4 if present
        used_idx = sorted(set(int(x) for x in idx_grid[full_mask]))
        # Pick lightest neutral in used_idx with lum between 95 and 190 for right-eye subtle catchlight
        mid_neutrals = [
            i for i in used_idx
            if 95 <= float(pal[i]["rgb"].mean()) <= 200
            and int(pal[i]["rgb"].max() - pal[i]["rgb"].min()) <= 35
        ]
        if mid_neutrals:
            sub_idx = max(mid_neutrals, key=lambda i: float(pal[i]["rgb"].mean()))
            idx_grid[eye_right_glint] = sub_idx

    used_codes = [pal[i]["code"] for i in sorted(set(int(x) for x in idx_grid[full_mask]))]
    return idx_grid, used_codes


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUX_DIR.mkdir(parents=True, exist_ok=True)

    pal, pal_lab = load_palette()
    pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)

    raw_grid, stats = extract_dp_grid(UPLOADED_REF)
    cal_grid = clean_and_calibrate_grid(raw_grid)
    gh, gw, _ = cal_grid.shape

    target_colors = 20
    idx_grid, used_codes = quantize_uploaded_ref(
        cal_grid,
        pal,
        pal_lab,
        pal_de_mat,
        target_colors=target_colors,
    )
    full_mask = np.ones((gh, gw), dtype=bool)
    n_colors = len(used_codes)

    base_name = f"图二_参考图直转版_{gw}x{gh}_MARD{n_colors}色"
    out_sheet = OUT_DIR / f"{base_name}_图纸.png"
    out_baked = OUT_DIR / f"{base_name}_烘烤成品预览图.jpg"
    out_csv = AUX_DIR / f"{base_name}_采购清单.csv"
    out_json = AUX_DIR / f"{base_name}.pindou.json"

    title = f"完整猫脸 · 参考图直转精修版（{gw}×{gh}）"
    subtitle = f"MARD {n_colors}色 · DP逐格对齐提取 · 圆润眼神光 + 柔粉猫鼻 + 零边框零绿斑 · 共 {gh * gw} 颗"
    bom, total_beads = render_sheet_png(
        idx_grid,
        full_mask,
        pal,
        title=title,
        subtitle=subtitle,
        out_png=out_sheet,
        cell_px=34,
        palette_name="MARD",
    )
    write_bom_csv(bom, total_beads, pal, out_csv, palette_name="MARD")
    export_pindou_json(idx_grid, full_mask, pal, UPLOADED_REF, base_name, out_json)
    render_baked_flat_melt_preview(idx_grid, full_mask, pal, out_baked, cell_px=18, seed=20261116)

    print(f"EXTRACTION_STATS={stats}")
    print(f"GRID={gw}x{gh} (W x H), COLORS={n_colors}, TOTAL_BEADS={total_beads}")
    print("USED_CODES=" + ", ".join(f"{pal[i]['code']}({pal[i]['name_zh']} x{cnt})" for i, cnt in bom))
    print(f"OUT_SHEET={out_sheet}")
    print(f"OUT_BAKED={out_baked}")
    print(f"OUT_CSV={out_csv}")
    print(f"OUT_JSON={out_json}")


if __name__ == "__main__":
    main()
