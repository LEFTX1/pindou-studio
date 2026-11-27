# -*- coding: utf-8 -*-
"""Convert uploaded cat2 reference (3ccc1d59) or AI pixel redraw into reduced-grid pixel-art MARD patterns."""

from collections import Counter
from pathlib import Path
import sys
import numpy as np
from PIL import Image
from skimage import color as skcolor

PROJECT_ROOT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from convert_uploaded_cat2_ref import (
    UPLOADED_REF,
    _allowed_palette_indices,
    clean_and_calibrate_grid,
    extract_dp_grid,
)
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

OUT_DIR = PROJECT_ROOT / "猫咪拼豆图纸汇总" / "05_参考图直转_圆脸猫高清像素版"
AUX_DIR = OUT_DIR / "辅助_采购清单与可编辑工程"
AI_PIXEL_SRC = PROJECT_ROOT / "inputs" / "ai_sources" / "cat2_pixel_48x45_ai.png"


def _restrict_rose_to_nose(
    idx_grid: np.ndarray,
    src_rgb: np.ndarray,
    pal: list[dict],
    pal_lab: np.ndarray,
    rose_codes: tuple[str, ...] = ("F20", "M8"),
) -> np.ndarray:
    """Keep dusty-rose codes inside central cat nose triangle so pink dots do not bleed onto cheeks."""
    gh, gw = idx_grid.shape
    out = idx_grid.copy()
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}
    rose_set = {code_to_idx[c] for c in rose_codes if c in code_to_idx}
    used = sorted(set(int(x) for x in out.ravel()))
    alt_pool = [i for i in used if i not in rose_set]
    if not (rose_set and alt_pool):
        return out

    alt_arr = np.array(alt_pool, dtype=np.int32)
    alt_lab = pal_lab[alt_arr]
    src_lab = skcolor.rgb2lab(src_rgb.astype(np.float64) / 255.0)
    nr0, nr1 = int(round(gh * 0.49)), int(round(gh * 0.77))
    nc0, nc1 = int(round(gw * 0.28)), int(round(gw * 0.61))

    for r in range(gh):
        for c in range(gw):
            if int(out[r, c]) not in rose_set:
                continue
            R, G, _ = map(int, src_rgb[r, c])
            in_nose = (nr0 <= r <= nr1) and (nc0 <= c <= nc1) and ((R - G) >= 10)
            if not in_nose:
                de = delta_e2000_matrix(src_lab[r, c].reshape(1, 3), alt_lab)[0]
                out[r, c] = int(alt_arr[int(np.argmin(de))])
    return out


def _feature_preserving_block_downsample(
    idx_grid: np.ndarray,
    src_rgb: np.ndarray,
    pal: list[dict],
    target_w: int,
    target_h: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Downsample a crisp palette-indexed sprite to (target_h, target_w) with mode voting
    that protects single-bead catchlights, dark pupils, nostrils/mouth, and dusty-rose nose.
    """
    sh, sw = idx_grid.shape
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}
    h1_idx = code_to_idx["H1"]
    dark_eye_codes = {"H7", "H16", "F11"}

    out_idx = np.zeros((target_h, target_w), dtype=np.int32)
    out_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)

    for tr in range(target_h):
        r0 = int(np.floor(tr * sh / target_h))
        r1 = max(r0 + 1, int(np.ceil((tr + 1) * sh / target_h)))
        r1 = min(sh, r1)
        for tc in range(target_w):
            c0 = int(np.floor(tc * sw / target_w))
            c1 = max(c0 + 1, int(np.ceil((tc + 1) * sw / target_w)))
            c1 = min(sw, c1)

            block_idx = idx_grid[r0:r1, c0:c1].ravel()
            block_rgb = src_rgb[r0:r1, c0:c1].reshape(-1, 3)

            # Weight center sample slightly higher to favor clean grid alignment
            weights: dict[int, float] = {}
            cr = (r0 + r1 - 1) / 2.0
            cc = (c0 + c1 - 1) / 2.0
            k = 0
            for sr in range(r0, r1):
                for sc in range(c0, c1):
                    lbl = int(idx_grid[sr, sc])
                    dist = abs(sr - cr) + abs(sc - cc)
                    w = 1.35 if dist <= 0.6 else 1.0
                    code = pal[lbl]["code"]
                    # Boost crucial dark contour/mouth/nostril features slightly inside mixed blocks
                    if code in dark_eye_codes and (0.20 <= tr / target_h <= 0.85):
                        w *= 1.15
                    weights[lbl] = weights.get(lbl, 0.0) + w
                    k += 1

            # Protect pure white eye catchlight (H1 inside left eye upper zone)
            if h1_idx in weights and (0.22 <= tr / target_h <= 0.42) and (0.05 <= tc / target_w <= 0.25):
                # Keep crisp 1-bead glint if block has >=1 H1 pixel and sits near catchlight center
                out_idx[tr, tc] = h1_idx
                out_rgb[tr, tc] = pal[h1_idx]["rgb"]
                continue

            best_lbl = max(weights.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            out_idx[tr, tc] = best_lbl
            # Representative RGB from pixels in block matching best_lbl, fallback palette rgb
            matching = block_rgb[block_idx == best_lbl]
            if len(matching) > 0:
                out_rgb[tr, tc] = np.round(np.median(matching, axis=0)).astype(np.uint8)
            else:
                out_rgb[tr, tc] = pal[best_lbl]["rgb"]

    return out_idx, out_rgb


def _polish_pixel_art_grid(
    idx_grid: np.ndarray,
    pal: list[dict],
    pal_de_mat: np.ndarray,
) -> np.ndarray:
    """
    Apply true pixel-art cleanup: remove stray 1-bead orphans outside protected facial anchors
    (eye catchlights, mouth stem, nostrils) and keep 1-bead glint crisp.
    """
    gh, gw = idx_grid.shape
    out = idx_grid.copy()
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}
    h1_idx = code_to_idx["H1"]

    # Collapse wide catchlights in left eye to crisp 1-bead glint (pixel art sweet spot at <=52 width)
    left_glint_coords = [
        (r, c)
        for r in range(int(gh * 0.22), int(gh * 0.42))
        for c in range(int(gw * 0.05), int(gw * 0.25))
        if int(out[r, c]) == h1_idx
    ]
    if len(left_glint_coords) > 1:
        # Keep the top-left-most crisp glint pixel, revert extras to surrounding pupil H16
        left_glint_coords.sort()
        keep_r, keep_c = left_glint_coords[0]
        pupil_fill = code_to_idx.get("H16", code_to_idx.get("H7", 0))
        for r, c in left_glint_coords[1:]:
            out[r, c] = pupil_fill
        out[keep_r, keep_c] = h1_idx

    # Clean non-anchor 1-pixel isolated noise surrounded by >=3 identical cardinal neighbors
    anchor_codes = {"H1", "H7", "H16", "F11", "G8"}
    for _pass in range(2):
        prev = out.copy()
        for r in range(gh):
            for c in range(gw):
                cur = int(prev[r, c])
                if pal[cur]["code"] in anchor_codes:
                    # Still clean dark H16 if completely isolated outside eye/nose/mouth bottom-right
                    if pal[cur]["code"] in {"H16", "G8"} and (0.35 <= r / gh <= 0.85) and (c / gw < 0.30 or c / gw > 0.65):
                        pass
                    else:
                        continue
                nbrs = []
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < gh and 0 <= nc < gw:
                        nbrs.append(int(prev[nr, nc]))
                if not nbrs:
                    continue
                dom, dom_cnt = Counter(nbrs).most_common(1)[0]
                if all(n != cur for n in nbrs) and dom_cnt >= 2:
                    if float(pal_de_mat[cur, dom]) < 22.0 or dom_cnt >= 3:
                        out[r, c] = dom
    return out


def build_algorithmic_pixel_style(
    target_w: int,
    target_h: int,
    max_colors: int = 14,
    out_prefix: str | None = None,
) -> dict:
    """Build a crisp reduced-grid flat-block pixel-art MARD pattern directly from calibrated 3ccc1d59."""
    pal, pal_lab = load_palette()
    pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)

    raw_grid, _ = extract_dp_grid(UPLOADED_REF)
    cal_grid = clean_and_calibrate_grid(raw_grid)
    sh, sw, _ = cal_grid.shape
    full_mask_hi = np.ones((sh, sw), dtype=bool)

    allowed_idx = _allowed_palette_indices(pal)
    pal_sub = [pal[i] for i in allowed_idx]
    pal_lab_sub = pal_lab[allowed_idx]
    pal_de_sub = pal_de_mat[np.ix_(allowed_idx, allowed_idx)]

    # Flatten shading into clean ~15 flat pixel-art color planes on the 92x86 sprite first
    sub_idx_hi, _ = pindou_studio_photo_quantize(
        cal_grid,
        full_mask_hi,
        pal_sub,
        pal_lab_sub,
        pal_de_sub,
        max_colors=max_colors + 2,
        has_outer_alpha=False,
        seed=20261116,
    )
    full_map = np.array(allowed_idx, dtype=np.int32)
    idx_hi = full_map[sub_idx_hi]
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}

    # Ensure crisp eye catchlight in hi grid before downsampling
    lum_hi = cal_grid.astype(np.float32).mean(axis=2)
    el_r0, el_r1 = int(round(sh * 0.22)), int(round(sh * 0.44))
    el_c0, el_c1 = int(round(sw * 0.04)), int(round(sw * 0.28))
    for r in range(el_r0, el_r1):
        for c in range(el_c0, el_c1):
            if lum_hi[r, c] >= 165:
                nbr = lum_hi[max(0, r - 2) : min(sh, r + 3), max(0, c - 2) : min(sw, c + 3)]
                if (nbr < 85).sum() >= 10:
                    idx_hi[r, c] = code_to_idx["H1"]

    # Ensure dusty-rose nose gradient holds cleanly before downsampling
    nr0, nr1 = int(round(sh * 0.52)), int(round(sh * 0.74))
    nc0, nc1 = int(round(sw * 0.28)), int(round(sw * 0.60))
    rose_pool = [code_to_idx[c] for c in ("F20", "M8") if c in code_to_idx]
    rose_lab = pal_lab[rose_pool]
    for r in range(nr0, nr1):
        for c in range(nc0, nc1):
            R, G, B = map(int, cal_grid[r, c])
            if (R - G >= 16) and (R >= 136) and (B >= 80) and ((G - B) <= 15):
                px_lab = skcolor.rgb2lab(cal_grid[r : r + 1, c : c + 1].astype(np.float64) / 255.0).reshape(1, 3)
                de = delta_e2000_matrix(px_lab, rose_lab)[0]
                if de.min() < 13.5:
                    idx_hi[r, c] = int(rose_pool[int(np.argmin(de))])

    idx_hi = _restrict_rose_to_nose(idx_hi, cal_grid, pal, pal_lab)

    # Feature-preserving downsample -> (target_h, target_w)
    idx_lo, _ = _feature_preserving_block_downsample(idx_hi, cal_grid, pal, target_w=target_w, target_h=target_h)
    lo_mask = np.ones((target_h, target_w), dtype=bool)
    protected = {"H1", "H16", "M8", "F20", "G1", "A23"}
    idx_lo = keep_exact_color_count_reduce(
        idx_lo,
        lo_mask,
        pal,
        pal_lab,
        target_colors=max_colors,
        protected_codes=protected,
        pal_de_mat=pal_de_mat,
    )
    idx_lo = _polish_pixel_art_grid(idx_lo, pal, pal_de_mat)

    n_colors = len(set(int(x) for x in idx_lo.ravel()))
    base_name = out_prefix or f"图二_像素减格版_{target_w}x{target_h}_MARD{n_colors}色"
    return _save_outputs(idx_lo, pal, base_name, f"算法减格重构 · 原图92×86→{target_w}×{target_h}")


def build_from_image_source(
    img_path: Path,
    target_w: int,
    target_h: int,
    max_colors: int = 14,
    out_prefix: str | None = None,
) -> dict:
    """Crop outer white frame, extract native ~89x91 pixel-art blocks, flatten to ~max_colors, and crisp-downsample."""
    pal, pal_lab = load_palette()
    pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)

    arr = np.array(Image.open(img_path).convert("RGB"), dtype=np.float32)
    lum = arr.mean(axis=2)
    h, w = lum.shape
    # Auto-crop pure-white outer border (~20px margin in AI canvas) without cropping dark/colored fur edges
    nonwhite_rows = np.where((lum[:, int(w * 0.1) : int(w * 0.9)] < 245).mean(axis=1) > 0.20)[0]
    nonwhite_cols = np.where((lum[int(h * 0.1) : int(h * 0.9), :] < 245).mean(axis=0) > 0.20)[0]
    y0, y1 = int(nonwhite_rows[0]) + 1, int(nonwhite_rows[-1])
    x0, x1 = int(nonwhite_cols[0]) + 1, int(nonwhite_cols[-1])
    cropped = arr[y0 : y1 + 1, x0 : x1 + 1]
    ch, cw, _ = cropped.shape

    # Sample native crisp block centers (~11px block grid -> ~89x91 clean unblended sprite)
    dx = np.abs(cropped[:, 1:] - cropped[:, :-1]).mean(axis=(0, 2))
    dy = np.abs(cropped[1:, :] - cropped[:-1, :]).mean(axis=(1, 2))
    px = np.where((dx[1:-1] > dx[:-2]) & (dx[1:-1] > dx[2:]) & (dx[1:-1] > 4.0))[0] + 1
    py = np.where((dy[1:-1] > dy[:-2]) & (dy[1:-1] > dy[2:]) & (dy[1:-1] > 4.0))[0] + 1
    step_x = float(np.median(np.diff(px))) if len(px) >= 10 else 11.0
    step_y = float(np.median(np.diff(py))) if len(py) >= 10 else 11.0
    nw = max(target_w, int(round(cw / max(8.0, step_x))))
    nh = max(target_h, int(round(ch / max(8.0, step_y))))

    native_rgb = np.zeros((nh, nw, 3), dtype=np.uint8)
    for r in range(nh):
        ry0 = int((r + 0.25) * ch / nh)
        ry1 = max(ry0 + 1, int((r + 0.75) * ch / nh))
        for c in range(nw):
            cx0 = int((c + 0.25) * cw / nw)
            cx1 = max(cx0 + 1, int((c + 0.75) * cw / nw))
            patch = cropped[ry0:ry1, cx0:cx1].reshape(-1, 3)
            native_rgb[r, c] = np.round(np.median(patch, axis=0)).astype(np.uint8)

    # Neutralize green cast on pale neutrals without washing out bright white fur
    r_c, g_c, b_c = native_rgb[:, :, 0], native_rgb[:, :, 1], native_rgb[:, :, 2]
    pale = (r_c > 195) & (g_c > 190) & (b_c > 170) & ((g_c - b_c) < 38)
    native_rgb[:, :, 1] = np.where(pale & (g_c > r_c - 2), np.minimum(g_c, r_c - 2), g_c)

    hi_mask = np.ones((nh, nw), dtype=bool)
    ban_pixel_art = {"M14", "F17", "F18", "F19", "G20"}
    allowed_idx = [i for i in _allowed_palette_indices(pal) if pal[i]["code"] not in ban_pixel_art]
    pal_sub = [pal[i] for i in allowed_idx]
    pal_lab_sub = pal_lab[allowed_idx]
    pal_de_sub = pal_de_mat[np.ix_(allowed_idx, allowed_idx)]

    sub_idx_hi, _ = pindou_studio_photo_quantize(
        native_rgb,
        hi_mask,
        pal_sub,
        pal_lab_sub,
        pal_de_sub,
        max_colors=max_colors + 2,
        has_outer_alpha=False,
        seed=20261116,
    )
    full_map = np.array(allowed_idx, dtype=np.int32)
    idx_hi = full_map[sub_idx_hi]
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}

    # Protect pure H1 left-eye catchlight inside dark pupil before downsampling
    lum_hi = native_rgb.astype(np.float32).mean(axis=2)
    el_r0, el_r1 = int(round(nh * 0.22)), int(round(nh * 0.44))
    el_c0, el_c1 = int(round(nw * 0.04)), int(round(nw * 0.28))
    for r in range(el_r0, el_r1):
        for c in range(el_c0, el_c1):
            if lum_hi[r, c] >= 175:
                nbr = lum_hi[max(0, r - 2) : min(nh, r + 3), max(0, c - 2) : min(nw, c + 3)]
                if (nbr < 85).sum() >= 10:
                    idx_hi[r, c] = code_to_idx["H1"]

    # Lock dusty-rose pink tones cleanly onto nose pad only
    nr0, nr1 = int(round(nh * 0.50)), int(round(nh * 0.74))
    nc0, nc1 = int(round(nw * 0.28)), int(round(nw * 0.62))
    rose_pool = [code_to_idx[c] for c in ("F20", "M8") if c in code_to_idx]
    rose_lab = pal_lab[rose_pool]
    for r in range(nr0, nr1):
        for c in range(nc0, nc1):
            R, G, B = map(int, native_rgb[r, c])
            if (R - G >= 18) and (R >= 140) and (B >= 90) and ((G - B) <= 14):
                px_lab = skcolor.rgb2lab(native_rgb[r : r + 1, c : c + 1].astype(np.float64) / 255.0).reshape(1, 3)
                de = delta_e2000_matrix(px_lab, rose_lab)[0]
                if de.min() < 13.5:
                    idx_hi[r, c] = int(rose_pool[int(np.argmin(de))])
    idx_hi = _restrict_rose_to_nose(idx_hi, native_rgb, pal, pal_lab)

    # Feature-preserving downsample -> target_w x target_h
    idx_lo, _ = _feature_preserving_block_downsample(idx_hi, native_rgb, pal, target_w=target_w, target_h=target_h)
    lo_mask = np.ones((target_h, target_w), dtype=bool)
    idx_lo = keep_exact_color_count_reduce(
        idx_lo,
        lo_mask,
        pal,
        pal_lab,
        target_colors=max_colors,
        protected_codes={"H1", "H16", "M8", "F20", "G1", "E16"},
        pal_de_mat=pal_de_mat,
    )
    idx_lo = _polish_pixel_art_grid(idx_lo, pal, pal_de_mat)

    n_colors = len(set(int(x) for x in idx_lo.ravel()))
    base_name = out_prefix or f"图二_减格像素风_{target_w}x{target_h}_MARD{n_colors}色"
    return _save_outputs(idx_lo, pal, base_name, f"16-bit 像素风重构 · {target_w}×{target_h}")


def _save_outputs(idx_grid: np.ndarray, pal: list[dict], base_name: str, mode_note: str) -> dict:
    gh, gw = idx_grid.shape
    mask = np.ones((gh, gw), dtype=bool)
    n_colors = len(set(int(x) for x in idx_grid.ravel()))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUX_DIR.mkdir(parents=True, exist_ok=True)

    out_sheet = OUT_DIR / f"{base_name}_图纸.png"
    out_baked = OUT_DIR / f"{base_name}_烘烤成品预览图.jpg"
    out_csv = AUX_DIR / f"{base_name}_采购清单.csv"
    out_json = AUX_DIR / f"{base_name}.pindou.json"

    title = f"完整猫脸 · 减格像素风版（{gw}×{gh}）"
    subtitle = f"MARD {n_colors}色 · {mode_note} · 大色块平涂风 · 共 {gw * gh} 颗"
    bom, total_beads = render_sheet_png(
        idx_grid,
        mask,
        pal,
        title=title,
        subtitle=subtitle,
        out_png=out_sheet,
        cell_px=38 if gw <= 52 else 34,
        palette_name="MARD",
    )
    write_bom_csv(bom, total_beads, pal, out_csv, palette_name="MARD")
    export_pindou_json(idx_grid, mask, pal, UPLOADED_REF, base_name, out_json)
    render_baked_flat_melt_preview(idx_grid, mask, pal, out_baked, cell_px=24 if gw <= 52 else 18, seed=20261116)

    return {
        "base_name": base_name,
        "w": gw,
        "h": gh,
        "colors": n_colors,
        "total_beads": total_beads,
        "sheet": out_sheet,
        "baked": out_baked,
        "csv": out_csv,
        "json": out_json,
        "bom": [(pal[i]["code"], pal[i]["name_zh"], cnt) for i, cnt in bom],
    }


def main():
    if not AI_PIXEL_SRC.exists():
        raise FileNotFoundError(f"Missing AI pixel source: {AI_PIXEL_SRC}")

    for w, h, k, tag in [
        (48, 48, 14, "图二_减格像素风_精致48x48_MARD14色"),
        (36, 36, 12, "图二_减格像素风_迷你36x36_MARD12色"),
    ]:
        info_ai = build_from_image_source(
            AI_PIXEL_SRC, target_w=w, target_h=h, max_colors=k, out_prefix=tag
        )
        print(
            f"[AI-PIXEL] {info_ai['base_name']}: {info_ai['w']}x{info_ai['h']} ({info_ai['total_beads']} beads), "
            f"{info_ai['colors']} colors -> {info_ai['baked'].name}"
        )
        print("  BOM:", ", ".join(f"{c}({n} x{cnt})" for c, n, cnt in info_ai["bom"]))


if __name__ == "__main__":
    main()
