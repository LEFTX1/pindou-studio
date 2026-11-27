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


def super_resolve_lowres_4x(rgb_u8: np.ndarray, has_white_caption: bool = False) -> np.ndarray:
    h, w = rgb_u8.shape[:2]
    bgr = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
    den = cv2.fastNlMeansDenoisingColored(bgr, None, h=4.5, hColor=9.0, templateWindowSize=5, searchWindowSize=15)
    den_rgb = cv2.cvtColor(den, cv2.COLOR_BGR2RGB).astype(np.float32)

    txt_mask = None
    if has_white_caption:
        mx = rgb_u8.max(axis=2)
        mn = rgb_u8.min(axis=2)
        txt_mask = ((mn >= 190) & ((mx - mn) <= 32)).astype(np.float32)
        txt_mask[int(round(h * 0.30)):, :] = 0.0

    cur = cv2.resize(den_rgb, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
    for step in range(10):
        blurred = cv2.GaussianBlur(cur, (0, 0), sigmaX=0.85)
        sim_lr = cv2.resize(blurred, (w, h), interpolation=cv2.INTER_AREA)
        err_lr = den_rgb - sim_lr
        err_hr = cv2.resize(err_lr, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        cur = np.clip(cur + 0.55 * err_hr, 0.0, 255.0)
        if step in (3, 6, 9):
            cur = cv2.bilateralFilter(cur.astype(np.float32), d=5, sigmaColor=16.0, sigmaSpace=2.2)

    lab = cv2.cvtColor(np.clip(cur, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab[:, :, 0]
    L_blur = cv2.GaussianBlur(L, (0, 0), sigmaX=1.3)
    delta = np.clip(L - L_blur, -10.0, 20.0)
    lab[:, :, 0] = np.clip(L + 0.55 * delta, 0.0, 255.0)
    sr_rgb = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

    if txt_mask is not None and txt_mask.max() > 0:
        cap_hr = cv2.resize(rgb_u8.astype(np.float32), (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        cap_blur = cv2.GaussianBlur(cap_hr, (0, 0), sigmaX=1.2)
        cap_sharp = np.clip(cap_hr + 0.9 * (cap_hr - cap_blur), 0.0, 255.0)
        m_hr = cv2.resize(txt_mask, (w * 4, h * 4), interpolation=cv2.INTER_LINEAR)
        m_dil = cv2.dilate((m_hr > 0.25).astype(np.uint8), np.ones((5, 5), np.uint8))
        m_blend = cv2.GaussianBlur(m_dil.astype(np.float32), (0, 0), 1.0)[..., None]
        sr_rgb = np.clip(sr_rgb.astype(np.float32) * (1.0 - m_blend) + cap_sharp * m_blend, 0, 255).astype(np.uint8)
    return sr_rgb


def calibrate_cat4_calico_rgb(sr_rgb: np.ndarray) -> np.ndarray:
    H, W = sr_rgb.shape[:2]
    arr = sr_rgb.astype(np.float32)
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    caption_mask = ((mn >= 198) & ((mx - mn) <= 34)).astype(np.float32)
    caption_mask[int(round(H * 0.28)):, :] = 0.0
    caption_mask = cv2.GaussianBlur(caption_mask, (0, 0), 1.2)[..., None]

    cal = np.clip(arr * 1.24 + 4.0, 0, 255)
    cal = 255.0 * np.power(cal / 255.0, 0.88)

    lum = 0.299 * cal[:, :, 0] + 0.587 * cal[:, :, 1] + 0.114 * cal[:, :, 2]
    sat = (cal.max(axis=2) - cal.min(axis=2))
    yy, xx = np.mgrid[0:H, 0:W]
    lower_face = (yy >= 0.36 * H) & (xx <= 0.72 * W)
    white_fur_w = np.clip((lum - 135.0) / 50.0, 0.0, 1.0) * np.clip(1.0 - (sat - 18.0) / 36.0, 0.0, 1.0) * lower_face.astype(np.float32)
    target_white = np.array([249.0, 247.0, 243.0], dtype=np.float32)
    cal = cal * (1.0 - 0.72 * white_fur_w[..., None]) + target_white * (0.72 * white_fur_w[..., None])

    reye = ((yy >= 0.42 * H) & (yy <= 0.60 * H) & (xx >= 0.58 * W) & (xx <= 0.76 * W))
    leye = ((yy >= 0.39 * H) & (yy <= 0.56 * H) & (xx >= 0.21 * W) & (xx <= 0.37 * W))
    eye_roi = reye | leye
    iris_mask = eye_roi & (lum >= 20.0) & (lum <= 95.0)
    cal_iris = np.clip(cal * np.array([1.22, 1.32, 1.18], dtype=np.float32) + 8.0, 0, 255)
    cal[iris_mask] = cal_iris[iris_mask]

    cap_clean = np.clip((arr - 15.0) * 1.15, 0, 255)
    out = cal * (1.0 - caption_mask) + cap_clean * caption_mask
    return np.clip(out, 0, 255).astype(np.uint8)


def _pick_used_or_close(grid, pal, preferred_codes, fallback_rgb):
    """Strictly pick ONLY from colors already in grid so refine never busts max_colors budget!"""
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


def draw_elliptical_cat_eye(
    grid: np.ndarray,
    idx_pupil: int,
    idx_iris: int,
    idx_iris_lt: int,
    idx_glint: int,
    idx_lid: int | None,
    cy: float,
    cx: float,
    rx_iris: float,
    ry_iris: float,
    rx_pupil: float,
    ry_pupil: float,
    tilt_rad: float,
    glint_pts: list[tuple[int, int]],
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
            if v < -0.78 * ry_iris:
                if idx_lid is not None and d_iris <= 1.10 and v >= -1.04 * ry_iris:
                    grid[r, c] = idx_lid
                continue
            if d_iris <= 1.0:
                d_pup = (u / rx_pupil) ** 2 + (v / ry_pupil) ** 2
                if d_pup <= 1.0:
                    grid[r, c] = idx_pupil
                else:
                    if v > 0.35 * ry_iris or u > 0.25 * rx_iris:
                        grid[r, c] = idx_iris_lt
                    else:
                        grid[r, c] = idx_iris
    for gr, gc in glint_pts:
        if 0 <= gr < H and 0 <= gc < W:
            grid[gr, gc] = idx_glint


def build_ganma_bitmap() -> np.ndarray:
    GAN = [
        "11111111111",
        "00000100000",
        "00000100000",
        "00000100000",
        "00000100000",
        "11111111111",
        "00000100000",
        "00000100000",
        "00000100000",
        "00000100000",
        "00000100000",
        "00000100000",
    ]
    MA = [
        "000000001000000",
        "000011111111111",
        "111010000000000",
        "101010010001000",
        "101011111011111",
        "101010010001000",
        "101010111011101",
        "111011101111011",
        "000010010001000",
        "000100010001000",
        "000100010001000",
        "001000010001000",
    ]
    h = 12
    w = len(GAN[0]) + 2 + len(MA[0]) + 1 + 17
    bmp = np.zeros((h, w), dtype=bool)
    for r, row in enumerate(GAN):
        for c, ch in enumerate(row):
            if ch == "1":
                bmp[r, c] = True
    ox = len(GAN[0]) + 2
    for r, row in enumerate(MA):
        for c, ch in enumerate(row):
            if ch == "1":
                bmp[r, ox + c] = True
    dots_x = ox + len(MA[0]) + 1
    for k in range(6):
        cx = dots_x + k * 3
        bmp[h - 2, cx] = True
        bmp[h - 1, cx] = True
    return bmp


def refine_cat4_details(idx_grid: np.ndarray, pal: list) -> np.ndarray:
    grid = idx_grid.copy()
    H, W = grid.shape
    w_i = _pick_used_or_close(grid, pal, ["H1", "H2", "E14"], (252, 252, 250))
    blk_i = _pick_used_or_close(grid, pal, ["H7", "H16", "H6"], (18, 18, 20))
    char_i = _pick_used_or_close(grid, pal, ["H6", "H5", "M6", "H7"], (48, 48, 46))
    iris_i = _pick_used_or_close(grid, pal, ["M3", "G17", "H17", "M6", "H5"], (82, 92, 82))
    iris_lt_i = _pick_used_or_close(grid, pal, ["H17", "M2", "G16", "H4", "M3"], (122, 134, 122))
    glint_i = _pick_used_or_close(grid, pal, ["H2", "H1", "H3", "H17"], (218, 222, 218))
    pink_i = _pick_used_or_close(grid, pal, ["F20", "E15", "E3", "G13", "A7"], (190, 122, 96))

    # Crisp "干嘛......" without creating a grey rectangular sticker
    bmp = build_ganma_bitmap()
    bh, bw = bmp.shape
    r0 = max(3, int(round(H * 0.06)))
    c0 = max(6, int(round(W * 0.16)))
    # Clear old fuzzy white text fragments in caption zone slightly toward local neighbor if isolated
    cap_r1 = min(H, r0 + bh + 2)
    cap_c0, cap_c1 = max(0, c0 - 2), min(W, c0 + bw + 2)
    for r in range(r0 - 1, cap_r1):
        for c in range(cap_c0, cap_c1):
            rr, gg, bb = [int(v) for v in pal[grid[r, c]]["rgb"]]
            if (0.299 * rr + 0.587 * gg + 0.114 * bb) > 195:
                # Replace blurry residual white pixel with dark brown/charcoal neighbor behind caption
                # Pick median non-white pixel from vertical band below caption (same column)
                sample_rows = [min(H - 1, r0 + bh + 2 + k) for k in range(3)]
                best_bg = min(sample_rows, key=lambda sr: sum(int(v) for v in pal[grid[sr, c]]["rgb"]))
                grid[r, c] = grid[best_bg, c]

    for r in range(bh):
        for c in range(bw):
            gr, gc = r0 + r, c0 + c
            if 0 <= gr < H and 0 <= gc < W:
                if bmp[r, c]:
                    grid[gr, gc] = w_i
                elif r > 0 and c > 0 and bmp[r - 1, c - 1]:
                    rr, gg, bb = [int(v) for v in pal[grid[gr, gc]]["rgb"]]
                    if (0.299 * rr + 0.587 * gg + 0.114 * bb) > 140:
                        grid[gr, gc] = char_i

    # Left eye: almond charcoal-olive iris + vertical elliptical pupil
    le_cy, le_cx = 0.478 * H, 0.286 * W
    draw_elliptical_cat_eye(
        grid, blk_i, char_i, iris_i, glint_i, blk_i,
        cy=le_cy, cx=le_cx,
        rx_iris=0.068 * W, ry_iris=0.072 * H,
        rx_pupil=0.025 * W, ry_pupil=0.056 * H,
        tilt_rad=0.14,
        glint_pts=[
            (int(round(le_cy - 0.024 * H)), int(round(le_cx - 0.032 * W))),
            (int(round(le_cy - 0.008 * H)), int(round(le_cx - 0.037 * W))),
        ],
    )

    # Right eye: larger open almond olive-slate iris + vertical elliptical black pupil!
    re_cy, re_cx = 0.520 * H, 0.672 * W
    draw_elliptical_cat_eye(
        grid, blk_i, iris_i, iris_lt_i, glint_i, blk_i,
        cy=re_cy, cx=re_cx,
        rx_iris=0.078 * W, ry_iris=0.078 * H,
        rx_pupil=0.027 * W, ry_pupil=0.058 * H,
        tilt_rad=-0.10,
        glint_pts=[
            (int(round(re_cy - 0.028 * H)), int(round(re_cx - 0.028 * W))),
            (int(round(re_cy - 0.013 * H)), int(round(re_cx - 0.035 * W))),
        ],
    )

    # Warm pink triangular nose + cute tiny black nose-bridge freckle
    nr0, nr1 = int(round(0.68 * H)), int(round(0.76 * H))
    nc0, nc1 = int(round(0.412 * W)), int(round(0.495 * W))
    ny_c, nx_c = 0.72 * H, 0.452 * W
    for r in range(nr0, nr1 + 1):
        for c in range(nc0, nc1 + 1):
            dy = (r - ny_c) / max(1.0, 0.036 * H)
            dx = (c - nx_c) / max(1.0, 0.036 * W)
            w_row = max(0.28, 1.0 - max(0.0, (r - (ny_c - 0.02 * H)) / max(1.0, 0.06 * H)))
            if abs(c - nx_c) <= 0.038 * W * w_row and dy * dy + 0.4 * dx * dx <= 1.0:
                grid[r, c] = pink_i
    fr_r, fr_c = int(round(0.662 * H)), int(round(0.402 * W))
    for dr in (0, 1):
        for dc in (0, 1):
            if dr + dc <= 1 and 0 <= fr_r + dr < H and 0 <= fr_c + dc < W:
                grid[fr_r + dr, fr_c + dc] = blk_i
    n_y = int(round(0.755 * H))
    for dc in (-2, 2):
        if 0 <= n_y < H and 0 <= int(round(nx_c)) + dc < W:
            grid[n_y, int(round(nx_c)) + dc] = char_i
    return grid


def make_clean_cat4_ai_illustration(sr_rgb: np.ndarray, out_path: Path, grid_w: int = 96, grid_h: int = 81):
    cal = calibrate_cat4_calico_rgb(sr_rgb)
    sm = cal.copy()
    for _ in range(4):
        sm = cv2.bilateralFilter(sm, d=9, sigmaColor=28, sigmaSpace=7)
    H, W = cal.shape[:2]
    mx = sr_rgb.max(axis=2)
    mn = sr_rgb.min(axis=2)
    cap = ((mn >= 198) & ((mx - mn) <= 34)).copy()
    cap[int(round(H * 0.28)):, :] = False
    sm[cap] = [255, 255, 255]

    small = cv2.resize(sm, (grid_w, grid_h), interpolation=cv2.INTER_AREA)
    pts = small.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 25, 0.5)
    _, labels, centers = cv2.kmeans(pts, 14, None, criteria, 6, cv2.KMEANS_PP_CENTERS)
    flat = np.clip(centers[labels.flatten()].reshape(grid_h, grid_w, 3), 0, 255).astype(np.uint8)
    Image.fromarray(flat).resize((grid_w * 8, grid_h * 8), Image.Resampling.NEAREST).save(out_path)


pal, pal_lab = fpc.load_palette()
pal_de_mat = fpc.delta_e2000_matrix(pal_lab, pal_lab)

sr_raw = np.array(Image.open(OUT / "cat4_sr4x.png").convert("RGB"))
cal_rgb = calibrate_cat4_calico_rgb(sr_raw)
cal_rgba = np.dstack([cal_rgb, np.full(cal_rgb.shape[:2], 255, dtype=np.uint8)])

# Track 1: Same fusion formula as cat1-cat3!
g_edge, mask_t1 = fpc.sample_photo_tiles(cal_rgba, longest_edge=92, force_square=None, mode="edge_aware")
g_bead, _ = fpc.sample_photo_tiles(cal_rgba, longest_edge=92, force_square=None, mode="bead")
diff = np.max(np.abs(g_edge.astype(np.int16) - g_bead.astype(np.int16)), axis=2)
blend = np.round(0.65 * g_edge.astype(np.float32) + 0.35 * g_bead.astype(np.float32)).astype(np.uint8)
g_fused = np.where(diff[:, :, None] < 40, blend, g_edge)
idx_t1, _ = fpc.pindou_studio_photo_quantize(
    g_fused, mask_t1, pal, pal_lab, pal_de_mat, max_colors=20, has_outer_alpha=False
)
idx_t1 = refine_cat4_details(idx_t1, pal)

# Track 2: 96x81 Clean 16-bit Illustration -> <=16 colors
ai_illu = OUT / "cat4_ai_pixel_v4.png"
make_clean_cat4_ai_illustration(sr_raw, ai_illu, 96, 81)
idx_t2, mask_t2, _ = fpc.ai_redraw_photo_quantize(
    ai_illu, pal, pal_lab, pal_de_mat, longest_edge=96, force_square=None, strip_outer_white=False, target_colors=16
)
idx_t2 = refine_cat4_details(idx_t2, pal)

print("T1 shape:", idx_t1.shape, "colors:", len(set(idx_t1.flatten().tolist())), "codes:", [pal[i]["code"] for i in sorted(set(idx_t1.flatten().tolist()))])
print("T2 shape:", idx_t2.shape, "colors:", len(set(idx_t2.flatten().tolist())), "codes:", [pal[i]["code"] for i in sorted(set(idx_t2.flatten().tolist()))])

rth.render_baked_flat_melt_preview(idx_t1, mask_t1, pal, OUT / "v4_t1_baked.jpg", cell_px=16, seed=41)
rth.render_baked_flat_melt_preview(idx_t2, mask_t2, pal, OUT / "v4_t2_baked.jpg", cell_px=16, seed=42)
fpc.render_sheet_png(idx_t1, mask_t1, pal, "图四 · 方案1 测试", "4x超分 + 椭圆瞳孔 + 干嘛文字精修", OUT / "v4_t1_sheet.png", cell_px=24, palette_name="MARD")
fpc.render_sheet_png(idx_t2, mask_t2, pal, "图四 · 方案2 测试", "4x超分 + 16-bit重绘 + 椭圆瞳孔", OUT / "v4_t2_sheet.png", cell_px=24, palette_name="MARD")
