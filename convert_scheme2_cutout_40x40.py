# -*- coding: utf-8 -*-
"""Convert chubby AI Scheme-2 ginger tabby sprite into an ultra-clean 40x38 MARD cutout fuse-bead pattern."""

from collections import Counter, deque
from pathlib import Path
import sys
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, label
from skimage import color as skcolor

PROJECT_ROOT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fast_parallel_pindou_cats import (
    export_pindou_json,
    load_palette,
    pindou_studio_photo_quantize,
)
from fast_parallel_pindou_engine import delta_e2000_matrix, keep_exact_color_count_reduce
from refined_two_track_helpers import render_baked_flat_melt_preview
from run_pathway_a_and_d import render_sheet_png, write_bom_csv

AI_SRC = PROJECT_ROOT / "inputs" / "ai_sources" / "cat2_scheme2_chubby_40x40_ai.png"
OUT_DIR = PROJECT_ROOT / "猫咪拼豆图纸汇总" / "08_图二异形像素风_40x40"
AUX_DIR = OUT_DIR / "辅助_采购清单与可编辑工程"


def _allowed_cutout_indices(pal: list[dict]) -> list[int]:
    """Keep harmonious ginger-cat & pastel MARD shades; ban green casts, H16 (use H7), and neon yellow/oranges."""
    banned = {
        "G15", "H18", "H21", "H23", "H14", "H15", "H16",
        "M1", "M2", "M3", "M5", "M6", "M7", "M14", "M15",
        "A7", "G19",
    }
    return [
        i for i, e in enumerate(pal)
        if not e["code"].startswith(("B", "C", "D"))
        and e["code"] not in banned
        and not (e["code"].startswith("A") and int(e["rgb"][1]) > 215 and int(e["rgb"][2]) < 130)
    ]


def _extract_native_or_fit(img_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Extract wide-chubby silhouette scaled cleanly into width=40 (38 inner + 1 border margin),
    keeping border silhouette crisp and recording high-res white eye-glint intensity map.
    """
    im = np.array(Image.open(img_path).convert("RGB"), dtype=np.float32)
    h, w, _ = im.shape
    lum = im.mean(axis=2)
    chroma = im.max(axis=2) - im.min(axis=2)

    is_bg_px = (lum >= 242) & (chroma <= 16)
    ext = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for r in range(h):
        for c in (0, w - 1):
            if is_bg_px[r, c] and not ext[r, c]:
                ext[r, c] = True
                q.append((r, c))
    for c in range(w):
        for r in (0, h - 1):
            if is_bg_px[r, c] and not ext[r, c]:
                ext[r, c] = True
                q.append((r, c))
    while q:
        r, c = q.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and not ext[nr, nc] and is_bg_px[nr, nc]:
                ext[nr, nc] = True
                q.append((nr, nc))

    fg_px = ~ext
    ys, xs = np.where(fg_px)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1

    sub = im[y0:y1, x0:x1]
    sub_fg = fg_px[y0:y1, x0:x1]
    sh, sw, _ = sub.shape

    tw = 38
    th = max(28, min(40, int(round(tw * sh / sw))))
    gw = 40
    gh = th + 2
    ox = (gw - tw) // 2
    oy = (gh - th) // 2

    grid_rgb = np.full((gh, gw, 3), 255, dtype=np.uint8)
    fg_mask = np.zeros((gh, gw), dtype=bool)
    bright_frac = np.zeros((gh, gw), dtype=np.float32)

    for tr in range(th):
        sy0 = int((tr + 0.16) * sh / th)
        sy1 = max(sy0 + 1, int((tr + 0.84) * sh / th))
        for tc in range(tw):
            sx0 = int((tc + 0.16) * sw / tw)
            sx1 = max(sx0 + 1, int((tc + 0.84) * sw / tw))
            patch_fg = sub_fg[sy0:sy1, sx0:sx1]
            fg_frac = float(patch_fg.mean())
            patch_all = sub[sy0:sy1, sx0:sx1].reshape(-1, 3)
            dark_all_frac = float((patch_all.mean(axis=1) < 120).mean())

            # Preserve outer dark charcoal ear/chin corners cleanly so inner fur is never left naked
            if fg_frac < 0.36 and dark_all_frac < 0.25:
                continue

            patch_rgb = sub[sy0:sy1, sx0:sx1][patch_fg] if fg_frac > 0.05 else patch_all[patch_all.mean(axis=1) < 130]
            if len(patch_rgb) == 0:
                continue
            lums = patch_rgb.mean(axis=1)
            bright_frac[oy + tr, ox + tc] = float((lums >= 210).mean())

            # Preserve crisp dark border on outer silhouette edge; prevent thin mouth strokes from over-fattening
            is_lower_mouth = (tr / th) >= 0.72 and 0.36 <= (tc / tw) <= 0.64
            if not is_lower_mouth and (lums < 115).mean() >= 0.30:
                col = np.round(np.median(patch_rgb[lums < 115], axis=0)).astype(np.uint8)
            elif is_lower_mouth and (lums < 95).mean() >= 0.45:
                col = np.round(np.median(patch_rgb[lums < 95], axis=0)).astype(np.uint8)
            else:
                col = np.round(np.median(patch_rgb, axis=0)).astype(np.uint8)

            fg_mask[oy + tr, ox + tc] = True
            grid_rgb[oy + tr, ox + tc] = col

    lbl, n_comp = label(fg_mask)
    if n_comp > 1:
        sizes = Counter(int(x) for x in lbl[fg_mask])
        main_lbl = max(sizes, key=lambda k: sizes[k])
        fg_mask = lbl == main_lbl
        grid_rgb[~fg_mask] = [255, 255, 255]

    return grid_rgb, fg_mask, bright_frac


def quantize_chubby_cat(
    grid_rgb: np.ndarray,
    fg_mask: np.ndarray,
    bright_frac: np.ndarray,
    pal: list[dict],
    pal_lab: np.ndarray,
    pal_de_mat: np.ndarray,
    target_colors: int = 13,
) -> np.ndarray:
    """
    Quantize chubby cat head cleanly into ~13 MARD shades:
    - Single crisp 1-bead H5 charcoal outline strictly along silhouette perimeter (touches_bg)
    - Pure bright white blaze/cheeks (strict low-chroma pure white), pale cream eyelids untouched
    - Restored 1x1 white catchlights in BOTH black H7 eyes
    - Thin crisp 1-bead symmetrical cat mouth + coral/pink nose & pastel pink F14 inner ears
    """
    gh, gw = fg_mask.shape
    clean = grid_rgb.astype(np.float32).copy()
    r_c, g_c, b_c = clean[:, :, 0], clean[:, :, 1], clean[:, :, 2]
    chroma = np.maximum(np.maximum(r_c, g_c), b_c) - np.minimum(np.minimum(r_c, g_c), b_c)
    lum = clean.mean(axis=2)
    bg = ~fg_mask

    # Strict 1-bead outer border outline (4-connected touches_bg)
    is_outline = binary_dilation(bg, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])) & fg_mask

    # Neutralize green cast cleanly on light fur
    pale_fur = fg_mask & (~is_outline) & (r_c > 180) & (g_c > 175) & (b_c > 155) & ((g_c - b_c) < 38)
    clean[:, :, 1] = np.where(pale_fur & (g_c > r_c - 2), np.minimum(g_c, r_c - 2), g_c)

    # Strict pure white for blaze & cheeks so warm pale cream eyelids stay warm cream instead of turning stark white
    inner_white = fg_mask & (~is_outline) & (lum >= 236) & (chroma <= 18)
    clean[inner_white] = [254.0, 253.0, 251.0]

    # Slightly purify pastel inner ear pink F14 (strictly inside ears only)
    rows_idx = np.arange(gh)[:, None]
    cols_idx = np.arange(gw)[None, :]
    in_ears = (rows_idx <= int(round(gh * 0.34))) & ((cols_idx <= int(round(gw * 0.25))) | (cols_idx >= int(round(gw * 0.72))))
    ear_pink = fg_mask & (~is_outline) & in_ears & (r_c - g_c >= 22) & ((g_c - b_c) <= 22) & (r_c >= 180)
    clean[ear_pink, 1] = np.clip(clean[ear_pink, 1] - 8.0, 0, 255)
    clean[ear_pink, 2] = np.clip(np.maximum(clean[ear_pink, 2], clean[ear_pink, 1] + 8.0), 0, 255)

    # Ensure interior cells aren't quantized to H5 accidentally (reserve H5 strictly for outer perimeter)
    allowed_all = _allowed_cutout_indices(pal)
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}
    allowed_no_h5 = [i for i in allowed_all if pal[i]["code"] != "H5"]
    pal_sub = [pal[i] for i in allowed_no_h5]
    pal_lab_sub = pal_lab[allowed_no_h5]
    pal_de_sub = pal_de_mat[np.ix_(allowed_no_h5, allowed_no_h5)]

    interior_mask = fg_mask & (~is_outline)
    sub_idx, _ = pindou_studio_photo_quantize(
        np.clip(np.round(clean), 0, 255).astype(np.uint8),
        interior_mask,
        pal_sub,
        pal_lab_sub,
        pal_de_sub,
        max_colors=target_colors - 1,  # reserve 1 slot for H5 outline
        has_outer_alpha=True,
        seed=20261117,
    )
    full_map = np.array(allowed_no_h5, dtype=np.int32)
    idx_grid = full_map[sub_idx]

    if is_outline.any():
        idx_grid[is_outline] = code_to_idx["H5"]
    idx_grid[inner_white] = code_to_idx["H1"]

    # Lock crisp round black H7 pupils + restore exact 1x1 white H1 catchlights inside BOTH dark pupils
    eye_glints: list[tuple[int, int]] = []
    er0, er1 = int(round(gh * 0.30)), int(round(gh * 0.60))
    for ec0, ec1 in [
        (int(round(gw * 0.14)), int(round(gw * 0.40))),
        (int(round(gw * 0.60)), int(round(gw * 0.86))),
    ]:
        pupil_cells = []
        for rr in range(er0, er1):
            for cc in range(ec0, ec1):
                if not interior_mask[rr, cc]:
                    continue
                if lum[rr, cc] < 72 and chroma[rr, cc] < 35:
                    idx_grid[rr, cc] = code_to_idx["H7"]
                    pupil_cells.append((rr, cc))

        if pupil_cells:
            # Find candidate catchlight inside upper/mid pupil with highest high-res bright fraction
            min_r = min(r for r, _ in pupil_cells)
            max_r = max(r for r, _ in pupil_cells)
            min_c = min(c for _, c in pupil_cells)
            max_c = max(c for _, c in pupil_cells)
            cands = []
            for r, c in pupil_cells:
                # Avoid extreme bottom/right rim; prefer upper-left inside dark pupil
                if min_r <= r <= (min_r + max_r) // 2 and min_c <= c <= (min_c + max_c) // 2 + 1:
                    score = float(bright_frac[r, c]) * 100.0 - 0.5 * (r - min_r) - 0.3 * (c - min_c)
                    cands.append((score, r, c))
            if cands:
                # Pick highest bright_frac (or clean top-left interior pupil bead if bright_frac tie)
                best = max(cands, key=lambda x: x[0])
                gl_r, gl_c = best[1], best[2]
                # Ensure it's inside pupil (nudge 1 step inward if on very top-left border)
                if gl_r == min_r and (gl_r + 1, gl_c) in pupil_cells:
                    gl_r += 1
                if gl_c == min_c and (gl_r, gl_c + 1) in pupil_cells:
                    gl_c += 1
                idx_grid[gl_r, gl_c] = code_to_idx["H1"]
                eye_glints.append((gl_r, gl_c))

    # Clean nose tip / thin symmetrical cat mouth (invert-Y / inverted-T shape centered below nose)
    nose_region = (rows_idx >= int(round(gh * 0.58))) & (rows_idx <= int(round(gh * 0.80))) & (cols_idx >= 14) & (cols_idx <= 25)
    # Remove any stray pastel ear pink F14 outside ears cleanly -> soft nose/fur tone
    if "F14" in code_to_idx:
        f14_idx = code_to_idx["F14"]
        alt_nose = code_to_idx.get("F23", code_to_idx.get("F17", code_to_idx["G3"]))
        for rr, cc in np.argwhere(idx_grid == f14_idx):
            if not in_ears[rr, cc]:
                idx_grid[rr, cc] = alt_nose if nose_region[rr, cc] else code_to_idx["G3"]

    protected = {"H1", "H5", "H7", "F14", "F23", "F17", "G10", "G9", "G3", "A9", "F10", "G13"}
    idx_grid = keep_exact_color_count_reduce(
        idx_grid,
        fg_mask,
        pal,
        pal_lab,
        target_colors=target_colors,
        protected_codes=protected,
        pal_de_mat=pal_de_mat,
    )

    if is_outline.any():
        idx_grid[is_outline] = code_to_idx["H5"]
    idx_grid[inner_white] = code_to_idx["H1"]
    for rr, cc in eye_glints:
        idx_grid[rr, cc] = code_to_idx["H1"]

    # Clean thick mouth block cleanly into thin crisp 1-bead cat mouth (inverted-Y centered under nose)
    mr0, mr1 = int(round(gh * 0.74)), gh - 3
    mc0, mc1 = 16, 24
    # Replace dark H7 blobs in mouth area with surrounding warm peach/tan first, then draw exact crisp 1-bead mouth
    h7_idx = code_to_idx["H7"]
    mouth_dark = [(r, c) for r in range(mr0, mr1) for c in range(mc0, mc1) if int(idx_grid[r, c]) == h7_idx]
    if mouth_dark:
        # Find nose bottom center column from pink/coral nose cells just above mouth
        pink_nose = [
            (r, c)
            for r in range(int(round(gh * 0.60)), mr0 + 2)
            for c in range(15, 25)
            if pal[int(idx_grid[r, c])]["code"] in {"F23", "F17", "F14", "F10", "G8", "M8"}
        ]
        c_mid = int(round(np.mean([c for _, c in pink_nose]))) if pink_nose else 20
        r_top = min(r for r, _ in mouth_dark)
        fill_col = code_to_idx.get("G3", code_to_idx.get("M13", 0))
        for r, c in mouth_dark:
            # Find nearest non-dark neighbor color cleanly
            nbrs = [
                int(idx_grid[r + dr, c + dc])
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                if 0 <= r + dr < gh and 0 <= c + dc < gw and int(idx_grid[r + dr, c + dc]) != h7_idx
            ]
            idx_grid[r, c] = Counter(nbrs).most_common(1)[0][0] if nbrs else fill_col

        # Draw crisp 1-bead cat mouth: 2-bead stem at c_mid, 1-bead flare left/right below it
        for rr, cc in [
            (r_top, c_mid),
            (r_top + 1, c_mid),
            (r_top + 2, c_mid - 1),
            (r_top + 2, c_mid + 1),
            (r_top + 2, c_mid - 2),
            (r_top + 2, c_mid + 2),
        ]:
            if 0 <= rr < gh - 2 and 0 <= cc < gw and not is_outline[rr, cc]:
                idx_grid[rr, cc] = h7_idx

    # Remove any stray H7 (pure black) outside eyes and mouth (e.g. double-outline bleed along H5 border)
    used_non_dark = [
        i for i in sorted(set(int(x) for x in idx_grid[fg_mask]))
        if pal[i]["code"] not in {"H7", "H5", "H1"}
    ]
    nd_arr = np.array(used_non_dark, dtype=np.int32)
    nd_lab = pal_lab[nd_arr]
    for rr, cc in np.argwhere(idx_grid == h7_idx):
        in_eyes = (er0 <= rr < er1) and ((14 <= cc * 100 // gw <= 40) or (60 <= cc * 100 // gw <= 86))
        in_mouth = (mr0 <= rr < mr1) and (mc0 <= cc < mc1)
        if in_eyes or in_mouth:
            continue
        # At forehead top stripe (r <= 12), snap dark outline bleed to F10; on cheek/chin border, use clean interior fur neighbor
        if rr <= 12 and "F10" in code_to_idx:
            idx_grid[rr, cc] = code_to_idx["F10"]
        else:
            nbr_fur = [
                int(idx_grid[rr + dr, cc + dc])
                for dr in (-1, 0, 1)
                for dc in (-1, 0, 1)
                if 0 <= rr + dr < gh and 0 <= cc + dc < gw
                and fg_mask[rr + dr, cc + dc]
                and not is_outline[rr + dr, cc + dc]
                and int(idx_grid[rr + dr, cc + dc]) != h7_idx
            ]
            if nbr_fur:
                idx_grid[rr, cc] = Counter(nbr_fur).most_common(1)[0][0]
            elif len(nd_arr) > 0:
                de_nd = delta_e2000_matrix(clean_lab[rr, cc].reshape(1, 3), nd_lab)[0]
                idx_grid[rr, cc] = int(nd_arr[int(np.argmin(de_nd))])

    return idx_grid


def main():
    if not AI_SRC.exists():
        raise FileNotFoundError(f"Waiting for AI cutout sprite at: {AI_SRC}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUX_DIR.mkdir(parents=True, exist_ok=True)

    for old in list(OUT_DIR.glob("*图二_异形描边*")) + list(AUX_DIR.glob("*图二_异形描边*")):
        if old.is_file():
            old.unlink()

    pal, pal_lab = load_palette()
    pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)

    grid_rgb, fg_mask, bright_frac = _extract_native_or_fit(AI_SRC)
    gh, gw = fg_mask.shape
    idx_grid = quantize_chubby_cat(grid_rgb, fg_mask, bright_frac, pal, pal_lab, pal_de_mat, target_colors=13)

    n_colors = len(set(int(x) for x in idx_grid[fg_mask]))
    total_fg = int(fg_mask.sum())
    base_name = f"图二_异形描边像素款_{gw}x{gh}_MARD{n_colors}色"

    out_sheet = OUT_DIR / f"{base_name}_图纸.png"
    out_baked = OUT_DIR / f"{base_name}_烘烤成品预览图.jpg"
    out_csv = AUX_DIR / f"{base_name}_采购清单.csv"
    out_json = AUX_DIR / f"{base_name}.pindou.json"

    title = f"完整猫脸（图二·大脸发腮版）· 像素描边镂空款（{gw}×{gh}）"
    subtitle = f"MARD {n_colors}色 · 肥嘟嘟宽圆大脸 + 1圈炭灰描边 + 双眼高光 · 共 {total_fg} 颗"
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
    export_pindou_json(idx_grid, fg_mask, pal, AI_SRC, base_name, out_json)
    render_baked_flat_melt_preview(idx_grid, fg_mask, pal, out_baked, cell_px=24, seed=20261117)

    print(f"GRID={gw}x{gh}, FG_BEADS={total_fg}, COLORS={n_colors}")
    print("BOM:", ", ".join(f"{pal[i]['code']}({pal[i]['name_zh']} x{cnt})" for i, cnt in bom))
    print(f"OUT_SHEET={out_sheet}")
    print(f"OUT_BAKED={out_baked}")


if __name__ == "__main__":
    main()
