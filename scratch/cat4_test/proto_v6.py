import sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

PROJECT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
sys.path.insert(0, str(PROJECT))

import fast_parallel_pindou_cats as fpc
import refined_two_track_helpers as rth

OUT = PROJECT / "scratch" / "cat4_test"
OUT.mkdir(parents=True, exist_ok=True)


def inpaint_cat4_caption_area(sr_rgb: np.ndarray) -> np.ndarray:
    H, W = sr_rgb.shape[:2]
    arr = sr_rgb.copy()
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    is_txt = (mn >= 140) & ((mx - mn) <= 46)
    mask = np.zeros((H, W), dtype=np.uint8)
    y0, y1 = int(round(0.02 * H)), int(round(0.26 * H))
    x0, x1 = int(round(0.14 * W)), int(round(0.84 * W))
    mask[y0:y1, x0:x1] = is_txt[y0:y1, x0:x1].astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8))
    return cv2.inpaint(arr, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)


def calibrate_cat4_calico_rgb(sr_rgb: np.ndarray) -> np.ndarray:
    H, W = sr_rgb.shape[:2]
    clean = inpaint_cat4_caption_area(sr_rgb).astype(np.float32)

    cal = np.clip(clean * 1.18 + 6.0, 0, 255)
    cal = 255.0 * np.power(cal / 255.0, 0.91)

    lum = 0.299 * cal[:, :, 0] + 0.587 * cal[:, :, 1] + 0.114 * cal[:, :, 2]
    sat = cal.max(axis=2) - cal.min(axis=2)
    yy, xx = np.mgrid[0:H, 0:W]

    # Clean white blaze & chest below brow
    lower_face = (yy >= 0.42 * H) & (xx <= 0.66 * W)
    white_fur_w = np.clip((lum - 138.0) / 48.0, 0.0, 1.0) * np.clip(1.0 - (sat - 16.0) / 34.0, 0.0, 1.0) * lower_face.astype(np.float32)
    target_white = np.array([248.0, 246.0, 243.0], dtype=np.float32)
    cal = cal * (1.0 - 0.72 * white_fur_w[..., None]) + target_white * (0.72 * white_fur_w[..., None])

    # Gentle neutral slate-olive iris lift (balanced RGB so zero bright chartreuse B11 fringe!)
    reye = (yy >= 0.43 * H) & (yy <= 0.61 * H) & (xx >= 0.58 * W) & (xx <= 0.76 * W)
    leye = (yy >= 0.40 * H) & (yy <= 0.56 * H) & (xx >= 0.22 * W) & (xx <= 0.37 * W)
    iris_mask = (reye | leye) & (lum >= 24.0) & (lum <= 92.0)
    cal_iris = np.clip(cal * np.array([1.08, 1.16, 1.16], dtype=np.float32) + 6.0, 0, 255)
    cal[iris_mask] = cal_iris[iris_mask]

    # Lift & warm lower muzzle / chin shadow (0.70..0.98*H, x=0.33..0.58) so it doesn't become a dark beard blob!
    muzzle_roi = (yy >= 0.68 * H) & (yy <= 0.99 * H) & (xx >= 0.30 * W) & (xx <= 0.60 * W)
    # Keep tiny thin horizontal mouth slit at 0.85..0.89 slightly darker, lift wider brown beard shadows
    mouth_slit = (yy >= 0.85 * H) & (yy <= 0.90 * H) & (xx >= 0.42 * W) & (xx <= 0.53 * W)
    lift_mask = muzzle_roi & (~mouth_slit) & (lum < 135.0)
    # Gently boost brightness and neutralize maroon excess toward warm ginger-tan
    cal_m = np.clip(cal * 1.18 + np.array([12.0, 16.0, 12.0], dtype=np.float32), 0, 255)
    r_exc = np.maximum(0.0, cal_m[:, :, 0] - cal_m[:, :, 1] - 32.0)
    cal_m[:, :, 0] = np.clip(cal_m[:, :, 0] - 0.5 * r_exc, 0, 255)
    cal[lift_mask] = cal_m[lift_mask]

    # Subtle warmth on nose area (0.70..0.79*H, x=0.41..0.50)
    nose_roi = (yy >= 0.70 * H) & (yy <= 0.79 * H) & (xx >= 0.41 * W) & (xx <= 0.50 * W)
    cal[nose_roi] = np.clip(cal[nose_roi] * np.array([1.14, 0.98, 0.95], dtype=np.float32) + np.array([14, 4, 4], dtype=np.float32), 0, 255)

    return np.clip(cal, 0, 255).astype(np.uint8)


def _pick_used_or_close(grid, pal, preferred_codes, fallback_rgb):
    used = sorted(set(int(x) for x in grid.flatten().tolist()))
    c2i = {c["code"]: i for i, c in enumerate(pal)}
    for code in preferred_codes:
        idx = c2i.get(code)
        if idx is not None and idx in used:
            return idx
    fr, fg, fb = map(int, fallback_rgb)
    best_i, best_d = used[0], 10**12
    for i in used:
        r, g, b = map(int, pal[i]["rgb"])
        d = (r - fr) ** 2 + (g - fg) ** 2 + (b - fb) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def draw_cat4_almond_elliptical_eye(
    grid: np.ndarray,
    idx_pupil: int,
    idx_iris_dark: int,
    idx_iris_olive: int,
    idx_glint: int,
    idx_lid: int,
    cy: float,
    cx: float,
    rx_iris: float,
    ry_iris: float,
    rx_pupil: float,
    ry_pupil: float,
    tilt_rad: float,
    glint_pts: list[tuple[int, int]],
    soft_crescent_left: bool = False,
):
    H, W = grid.shape
    cos_t, sin_t = np.cos(tilt_rad), np.sin(tilt_rad)
    r0, r1 = max(0, int(np.floor(cy - ry_iris - 2))), min(H, int(np.ceil(cy + ry_iris + 3)))
    c0, c1 = max(0, int(np.floor(cx - rx_iris - 2))), min(W, int(np.ceil(cx + rx_iris + 3)))
    for r in range(r0, r1):
        for c in range(c0, c1):
            dy = r - cy
            dx = c - cx
            u = dx * cos_t + dy * sin_t
            v = -dx * sin_t + dy * cos_t
            d_iris = (u / rx_iris) ** 2 + (v / ry_iris) ** 2
            if v < -0.74 * ry_iris:
                if d_iris <= 1.15 and v >= -1.04 * ry_iris:
                    grid[r, c] = idx_lid
                continue
            if d_iris <= 1.0:
                taper = 1.0 + 0.16 * (v / ry_pupil) ** 2
                d_pup = ((u * taper) / rx_pupil) ** 2 + (v / ry_pupil) ** 2
                if d_pup <= 1.0:
                    grid[r, c] = idx_pupil
                else:
                    if soft_crescent_left:
                        if u < -0.32 * rx_iris and abs(v) < 0.65 * ry_iris:
                            grid[r, c] = idx_iris_olive
                        else:
                            grid[r, c] = idx_iris_dark
                    else:
                        if u > 0.18 * rx_iris or v > 0.34 * ry_iris:
                            grid[r, c] = idx_iris_olive
                        else:
                            grid[r, c] = idx_iris_dark
    for gr, gc in glint_pts:
        if 0 <= gr < H and 0 <= gc < W:
            grid[gr, gc] = idx_glint


def build_ganma_bitmap() -> np.ndarray:
    GAN = [
        "111111111111",
        "000001100000",
        "000001000000",
        "000001000000",
        "000001000000",
        "000001000000",
        "111111111111",
        "000001000000",
        "000001000000",
        "000001000000",
        "000001000000",
        "000001000000",
        "000001000000",
        "000001000000",
    ]
    MA = [
        "00000000001000000",  # centered dot over 广
        "00000111111111111",  # roof of 广
        "11110100000000000",  # 口 top + 广 spine
        "10010100010000100",  # 口 + 木 trunks
        "10010101111101111",  # 口 + 木 bars
        "10010100010000100",  # 口 + 木 trunks
        "11110100111001110",  # 口 bot + branches
        "00000101010110101",  # branches
        "00000110010000100",  # 广 sweep + stems
        "00000100010000100",
        "00001000010000100",
        "00001000010000100",
        "00010000010000100",
        "00010000010000100",
    ]
    h = 14
    w = 12 + 2 + 17 + 2 + 25
    bmp = np.zeros((h, w), dtype=bool)
    for r, row in enumerate(GAN):
        for c, ch in enumerate(row):
            if ch == "1":
                bmp[r, c] = True
    ox = 14
    for r, row in enumerate(MA):
        for c, ch in enumerate(row):
            if ch == "1":
                bmp[r, ox + c] = True
    dots_x = ox + 19
    for k in range(6):
        cx = dots_x + k * 4
        bmp[h - 2, cx:cx + 2] = True
        bmp[h - 1, cx:cx + 2] = True
    return bmp


def refine_cat4_details(idx_grid: np.ndarray, pal: list) -> np.ndarray:
    grid = idx_grid.copy()
    H, W = grid.shape
    w_i = _pick_used_or_close(grid, pal, ["H1", "H2", "E14"], (255, 255, 255))
    blk_i = _pick_used_or_close(grid, pal, ["H7", "H16", "H6"], (10, 10, 10))
    char_i = _pick_used_or_close(grid, pal, ["H6", "H5"], (48, 48, 48))
    iris_dark_i = _pick_used_or_close(grid, pal, ["H5", "H6", "M3"], (68, 72, 68))
    iris_olive_i = _pick_used_or_close(grid, pal, ["M3", "M15", "M2", "H4", "M7"], (112, 124, 118))
    glint_i = _pick_used_or_close(grid, pal, ["H1", "H2", "H19", "H3"], (242, 240, 236))
    pink_i = _pick_used_or_close(grid, pal, ["F20", "M8", "M14", "E15", "G13", "M13"], (196, 136, 116))

    # 1. Clean crisp "干嘛......"
    bmp = build_ganma_bitmap()
    bh, bw = bmp.shape
    r0 = max(2, int(round(H * 0.045)))
    c0 = max(6, int(round(W * 0.16)))
    for r in range(bh):
        for c in range(bw):
            gr, gc = r0 + r, c0 + c
            if 0 <= gr < H and 0 <= gc < W and bmp[r, c]:
                grid[gr, gc] = w_i

    # 2. Left Eye: darker olive-charcoal almond + vertical elliptical pupil + soft glint
    le_cy, le_cx = 0.478 * H, 0.298 * W
    draw_cat4_almond_elliptical_eye(
        grid,
        idx_pupil=blk_i,
        idx_iris_dark=iris_dark_i,
        idx_iris_olive=iris_olive_i,
        idx_glint=glint_i,
        idx_lid=blk_i,
        cy=le_cy,
        cx=le_cx,
        rx_iris=0.068 * W,
        ry_iris=0.074 * H,
        rx_pupil=0.022 * W,
        ry_pupil=0.058 * H,
        tilt_rad=0.14,
        glint_pts=[
            (int(round(le_cy - 0.020 * H)), int(round(le_cx - 0.032 * W))),
            (int(round(le_cy - 0.008 * H)), int(round(le_cx - 0.036 * W))),
        ],
        soft_crescent_left=True,
    )

    # 3. Right Eye: crisp almond olive-slate iris + narrow vertical elliptical black pupil!
    re_cy, re_cx = 0.514 * H, 0.672 * W
    draw_cat4_almond_elliptical_eye(
        grid,
        idx_pupil=blk_i,
        idx_iris_dark=iris_dark_i,
        idx_iris_olive=iris_olive_i,
        idx_glint=glint_i,
        idx_lid=blk_i,
        cy=re_cy,
        cx=re_cx,
        rx_iris=0.078 * W,
        ry_iris=0.079 * H,
        rx_pupil=0.020 * W,
        ry_pupil=0.060 * H,
        tilt_rad=-0.08,
        glint_pts=[
            (int(round(re_cy - 0.024 * H)), int(round(re_cx - 0.026 * W))),
            (int(round(re_cy - 0.011 * H)), int(round(re_cx - 0.030 * W))),
        ],
        soft_crescent_left=False,
    )

    # 4. Warm pink/terracotta triangle nose accurately positioned over photo nose (0.715..0.785*H)
    nr0, nr1 = int(round(0.710 * H)), int(round(0.782 * H))
    nc0, nc1 = int(round(0.415 * W)), int(round(0.500 * W))
    ny_c, nx_c = 0.742 * H, 0.456 * W
    for r in range(nr0, nr1 + 1):
        for c in range(nc0, nc1 + 1):
            dy = (r - ny_c) / max(1.0, 0.036 * H)
            dx = (c - nx_c) / max(1.0, 0.038 * W)
            w_row = max(0.28, 1.0 - max(0.0, (r - (ny_c - 0.022 * H)) / max(1.0, 0.06 * H)))
            if abs(c - nx_c) <= 0.038 * W * w_row and dy * dy + 0.42 * dx * dx <= 1.0:
                grid[r, c] = pink_i
    # Small nostril shadows at bottom corners
    n_y = int(round(0.778 * H))
    for dc in (-2, 2):
        if 0 <= n_y < H and 0 <= int(round(nx_c)) + dc < W:
            grid[n_y, int(round(nx_c)) + dc] = char_i
    # Nose-bridge black freckle above left side of nose
    fr_r, fr_c = int(round(0.660 * H)), int(round(0.402 * W))
    for dr in (0, 1):
        for dc in (0, 1):
            if dr + dc <= 1 and 0 <= fr_r + dr < H and 0 <= fr_c + dc < W:
                grid[fr_r + dr, fr_c + dc] = blk_i

    return grid


def make_clean_cat4_ai_illustration(sr_rgb: np.ndarray, out_path: Path, grid_w: int = 96, grid_h: int = 81):
    cal = calibrate_cat4_calico_rgb(sr_rgb)
    sm = cal.copy()
    for _ in range(3):
        sm = cv2.bilateralFilter(sm, d=9, sigmaColor=24, sigmaSpace=6)
    small = cv2.resize(sm, (grid_w, grid_h), interpolation=cv2.INTER_AREA)
    pts = small.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 35, 0.35)
    _, labels, centers = cv2.kmeans(pts, 15, None, criteria, 8, cv2.KMEANS_PP_CENTERS)
    flat = np.clip(centers[labels.flatten()].reshape(grid_h, grid_w, 3), 0, 255).astype(np.uint8)
    lum_c = 0.299 * centers[:, 0] + 0.587 * centers[:, 1] + 0.114 * centers[:, 2]
    darkest = int(np.argmin(lum_c))
    brightest = int(np.argmax(lum_c))
    lbl = labels.reshape(grid_h, grid_w)
    flat[lbl == darkest] = [6, 6, 6]
    flat[lbl == brightest] = [252, 252, 250]
    # Preserve pink nose seed in clean AI illustration so M14/F20 salmon cluster stays alive
    flat[int(round(0.73*grid_h)):int(round(0.77*grid_h)), int(round(0.44*grid_w)):int(round(0.47*grid_w))] = [194, 128, 110]
    Image.fromarray(flat).resize((grid_w * 8, grid_h * 8), Image.Resampling.NEAREST).save(out_path)


pal, pal_lab = fpc.load_palette()
pal_de_mat = fpc.delta_e2000_matrix(pal_lab, pal_lab)

sr_raw = np.array(Image.open(OUT / "cat4_sr4x.png").convert("RGB"))
cal_rgb = calibrate_cat4_calico_rgb(sr_raw)
cal_rgba = np.dstack([cal_rgb, np.full(cal_rgb.shape[:2], 255, dtype=np.uint8)])

g_edge, mask_t1 = fpc.sample_photo_tiles(cal_rgba, longest_edge=92, force_square=None, mode="edge_aware")
g_bead, _ = fpc.sample_photo_tiles(cal_rgba, longest_edge=92, force_square=None, mode="bead")
diff = np.max(np.abs(g_edge.astype(np.int16) - g_bead.astype(np.int16)), axis=2)
blend = np.round(0.65 * g_edge.astype(np.float32) + 0.35 * g_bead.astype(np.float32)).astype(np.uint8)
g_fused = np.where(diff[:, :, None] < 40, blend, g_edge)
idx_t1, _ = fpc.pindou_studio_photo_quantize(
    g_fused, mask_t1, pal, pal_lab, pal_de_mat, max_colors=20, has_outer_alpha=False
)
idx_t1 = refine_cat4_details(idx_t1, pal)

ai_illu = OUT / "cat4_ai_pixel_v6.png"
make_clean_cat4_ai_illustration(sr_raw, ai_illu, 96, 81)
idx_t2, mask_t2, _ = fpc.ai_redraw_photo_quantize(
    ai_illu, pal, pal_lab, pal_de_mat, longest_edge=96, force_square=None, strip_outer_white=False, target_colors=16
)
idx_t2 = refine_cat4_details(idx_t2, pal)

print("T1 shape:", idx_t1.shape, "colors:", len(set(idx_t1.flatten().tolist())), "codes:", [pal[i]["code"] for i in sorted(set(idx_t1.flatten().tolist()))])
print("T2 shape:", idx_t2.shape, "colors:", len(set(idx_t2.flatten().tolist())), "codes:", [pal[i]["code"] for i in sorted(set(idx_t2.flatten().tolist()))])

rth.render_baked_flat_melt_preview(idx_t1, mask_t1, pal, OUT / "v6_t1_baked.jpg", cell_px=16, seed=41)
rth.render_baked_flat_melt_preview(idx_t2, mask_t2, pal, OUT / "v6_t2_baked.jpg", cell_px=16, seed=42)
