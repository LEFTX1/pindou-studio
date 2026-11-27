# -*- coding: utf-8 -*-
"""
三只猫咪拼豆精修核心辅助模块：
1. 白猫室内暖黄偏色中和（确保纯白猫身映射至 H1 纯白与柔和灰米过渡，而非发黄或发棕）。
2. 外圈抗锯齿灰边清洗（AI 重绘主体边沿去噪）。
3. 数据驱动的五官圆润度与眼神高光精修（彻底消除低分辨率菱角/方块/紫眼像素）。
4. 基于真实世界满焊/近满焊实物物理特征的烘烤成品像素渲染器（圆角小方砖融接、微缩针眼闭合、压纸微缎面高光）。
5. 供 ChatGPT 浏览器并发生图使用的精准像素参考图导出器。
"""

from collections import Counter, deque
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter


def neutralize_white_cat_fur_rgba(rgba: np.ndarray, cat_id: str) -> np.ndarray:
    """
    温和校正图一与图三白色猫咪身上的室内钨丝灯暖黄偏色：
    仅作用于低饱和浅亮毛发像素，严格避开纸箱、黄绳、粉耳与蓝格床单。
    """
    out = rgba.copy()
    rgb = out[:, :, :3].astype(np.float32)
    alpha = out[:, :, 3] > 0
    max_c = rgb.max(axis=2)
    min_c = rgb.min(axis=2)
    chroma = max_c - min_c
    lum = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114

    if cat_id == "cat1":
        # 白猫亮部高光到浅灰阴影（chroma <= 30 且 min >= 198，避开高饱和黄色麻绳与暖褐纸箱/地板）
        fur = alpha & (min_c >= 198.0) & (chroma <= 30.0) & (rgb[:, :, 2] >= 188.0)
        strength = np.clip((lum - 196.0) / 54.0, 0.0, 1.0) * 0.78
        target = np.clip(lum * 1.035, 0.0, 255.0)
        for ch_i in range(3):
            rgb[:, :, ch_i] = np.where(fur, rgb[:, :, ch_i] * (1.0 - strength) + target * strength, rgb[:, :, ch_i])
    elif cat_id == "cat3":
        # 蓝床单上的白猫：避开蓝色床单 (B > R + 2) 与高饱和粉红耳鼻 ((R - G) > 24)，
        # 中和室内暖光造成的中暗部奶白/冷灰阴影偏色（覆盖背光胸腹与面部轮廓），防止出现泥棕色块
        not_blue = (rgb[:, :, 2] <= rgb[:, :, 0] + 2.0)
        not_pink_ear = ((rgb[:, :, 0] - rgb[:, :, 1]) <= 22.0)
        white_gray_fur = alpha & not_blue & not_pink_ear & (chroma <= 54.0) & (lum >= 115.0)
        strength = np.where(
            lum >= 175.0,
            np.clip((lum - 170.0) / 70.0, 0.25, 1.0) * 0.85,
            np.clip((lum - 115.0) / 65.0, 0.0, 1.0) * 0.62,
        )
        # 微调向纯净中性白/银灰靠拢
        target = np.clip(lum * 1.045 + np.where(lum >= 195.0, 8.0, 2.0), 0.0, 255.0)
        for ch_i in range(3):
            rgb[:, :, ch_i] = np.where(
                white_gray_fur,
                rgb[:, :, ch_i] * (1.0 - strength) + target * strength,
                rgb[:, :, ch_i],
            )

    out[:, :, :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    return out


def clean_exterior_grey_halo(idx_grid: np.ndarray, mask: np.ndarray, pal: list) -> tuple[np.ndarray, np.ndarray]:
    """
    多层剥除 AI 白底边缘图（尤其是图三蓝格床单外缘）的抗锯齿灰绿/灰褐边（M3/M7/H3/H4/H10/H11/C20/C21）：
    反复检查接触透明背景的低饱和灰杂点，若 8 邻域存在高饱和蓝色床单，则替换为最近邻蓝豆，确保外圈纯蓝无灰边。
    """
    out = idx_grid.copy()
    m = mask.copy()
    h, w = out.shape
    halo_codes = {"M3", "M7", "H3", "H4", "H10", "H11", "C20", "C21", "M4"}

    for _ in range(5):
        nxt = out.copy()
        changed = 0
        for r in range(h):
            for c in range(w):
                if not m[r, c]:
                    continue
                cur_code = pal[int(out[r, c])]["code"]
                if cur_code not in halo_codes:
                    continue
                # 检查 4 邻域是否接触外部透明背景
                touches_bg = False
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if not (0 <= nr < h and 0 <= nc < w) or not m[nr, nc]:
                        touches_bg = True
                        break
                if not touches_bg:
                    continue
                # 在 5×5 半径内寻找主色蓝色床单豆
                blue_nbrs = Counter()
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < h and 0 <= nc < w and m[nr, nc]:
                            ni = int(out[nr, nc])
                            ncode = pal[ni]["code"]
                            nr_v, _, nb_v = map(int, pal[ni]["rgb"])
                            if nb_v > nr_v + 18 and ncode not in halo_codes:
                                wt = 2 if (abs(dr) <= 1 and abs(dc) <= 1) else 1
                                blue_nbrs[ni] += wt
                if blue_nbrs:
                    nxt[r, c] = blue_nbrs.most_common(1)[0][0]
                    changed += 1
        out = nxt
        if changed == 0:
            break
    return out, m


def _code_map(pal: list) -> dict[str, int]:
    return {e["code"]: i for i, e in enumerate(pal)}


def _pick_existing_or_code(grid: np.ndarray, mask: np.ndarray, pal: list, c2i: dict[str, int], preferred: list[str], fallback: str | None = None) -> int:
    used = {pal[int(x)]["code"] for x in grid[mask]}
    for code in preferred:
        if code in used and code in c2i:
            return c2i[code]
    for code in preferred:
        if code in c2i:
            return c2i[code]
    if fallback and fallback in c2i:
        return c2i[fallback]
    return 0


def _find_dark_center(
    grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    r0: int,
    r1: int,
    c0: int,
    c1: int,
    lum_thresh: float = 88.0,
) -> tuple[float, float] | None:
    """在指定眼部窗口内定位最深瞳孔质心，确保细修圆眼稳定居中。"""
    h, w = grid.shape
    pts_r, pts_c, wts = [], [], []
    for r in range(max(0, r0), min(h, r1)):
        for c in range(max(0, c0), min(w, c1)):
            if not mask[r, c]:
                continue
            R, G, B = map(float, pal[int(grid[r, c])]["rgb"])
            lum = 0.299 * R + 0.587 * G + 0.114 * B
            if lum <= lum_thresh:
                pts_r.append(r)
                pts_c.append(c)
                wts.append(max(1.0, (lum_thresh + 10.0) - lum))
    if not pts_r:
        return None
    wt_arr = np.asarray(wts, dtype=np.float64)
    cy = float(np.sum(np.asarray(pts_r) * wt_arr) / wt_arr.sum())
    cx = float(np.sum(np.asarray(pts_c) * wt_arr) / wt_arr.sum())
    return cy, cx


def _stamp_patch(grid: np.ndarray, mask: np.ndarray, top_r: int, top_c: int, patch: list[list[int | None]]) -> None:
    h, w = grid.shape
    for dr, row in enumerate(patch):
        r = top_r + dr
        if not (0 <= r < h):
            continue
        for dc, val in enumerate(row):
            c = top_c + dc
            if val is not None and 0 <= c < w and mask[r, c]:
                grid[r, c] = int(val)


def _sample_mode_clean(img_rgb: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """对像素风格重绘底图按中心区块中位数下采样，保留 1px 眼神光与锐利眼线，避免双线性涂抹。"""
    H, W, _ = img_rgb.shape
    out = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    for r in range(out_h):
        y0 = int(round(r * H / out_h))
        y1 = max(y0 + 1, int(round((r + 1) * H / out_h)))
        ym = (y0 + y1) // 2
        yc0 = max(y0, ym - max(1, (y1 - y0) // 4))
        yc1 = min(y1, ym + max(1, (y1 - y0) // 4) + 1)
        for c in range(out_w):
            x0 = int(round(c * W / out_w))
            x1 = max(x0 + 1, int(round((c + 1) * W / out_w)))
            xm = (x0 + x1) // 2
            xc0 = max(x0, xm - max(1, (x1 - x0) // 4))
            xc1 = min(x1, xm + max(1, (x1 - x0) // 4) + 1)
            out[r, c] = np.median(img_rgb[yc0:yc1, xc0:xc1].reshape(-1, 3), axis=0).astype(np.uint8)
    return out


def refine_cat_face_and_details(
    cat_id: str,
    kind: str,
    idx_grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    source_pixel_path: Path | None = None,
) -> np.ndarray:
    """
    对四只猫咪的五官、眼神光、轮廓杂点进行工艺级精修（保证猫眼贴合原图神态与瞳孔形态）：
    - 图一/图二：圆润有神的深咖啡/纯黑玻璃感大眼 + 精准单格/对称纯白眼神高光；
    - 图三：温和柔美的浅橄榄绿杏仁眼（M15/M2）+ 纤细上睫线 + 洁白鼻梁与粉耳；
    - 图四：清晰竖向椭圆黑瞳孔 + 烟熏橄榄灰虹膜 + 锐利纯白「干嘛......」。
    """
    g = idx_grid.copy()
    h, w = g.shape
    c2i = _code_map(pal)

    idx_white = _pick_existing_or_code(g, mask, pal, c2i, ["H1", "H2", "E16", "H19"])
    idx_dark = _pick_existing_or_code(g, mask, pal, c2i, ["H16", "H7", "H6"])
    idx_charcoal = _pick_existing_or_code(g, mask, pal, c2i, ["H6", "H5", "M7", "H16"])
    idx_pink = _pick_existing_or_code(g, mask, pal, c2i, ["F14", "E15", "E1", "F20", "A23"])

    if cat_id == "cat1":
        # 1) 清除眼眶与面部区域中误映出的深紫色(D10等)
        head_r0, head_r1 = 0, int(h * 0.44)
        head_c0, head_c1 = int(w * 0.54), w
        for r in range(head_r0, head_r1):
            for c in range(head_c0, head_c1):
                if not mask[r, c]:
                    continue
                R, G, B = map(int, pal[int(g[r, c])]["rgb"])
                if B > R + 10 and R < 90 and G < 90:
                    g[r, c] = idx_dark

        if kind == "ai_refined":
            # 保留升级版灵魂圆眼（92×89），精准点亮近眼与额边远眼高光
            w12 = _pick_existing_or_code(g, mask, pal, c2i, ["H1", "H2", "H19"])
            pup12 = _pick_existing_or_code(g, mask, pal, c2i, ["H7", "H16", "H6"])
            br12 = _pick_existing_or_code(g, mask, pal, c2i, ["G8", "F10", "G7", "H5"])
            nc = _find_dark_center(g, mask, pal, 13, 21, 69, 78, lum_thresh=90.0)
            if nc is not None:
                gr, gc = int(round(nc[0] - 0.7)), int(round(nc[1] - 0.8))
                if 0 <= gr < h and 0 <= gc < w and mask[gr, gc]:
                    g[gr, gc] = w12
            _stamp_patch(g, mask, 8, 77, [
                [br12,  pup12, pup12, None],
                [pup12, w12,   pup12, br12],
                [br12,  pup12, pup12, br12],
            ])
        else:
            # cat1 fusion_refined (87×88)：清理白毛孤立暗点 + 圆润饱满近眼 + 贴合额缘远眼
            fur11 = _pick_existing_or_code(g, mask, pal, c2i, ["H2", "H1", "H19"])
            rim11 = _pick_existing_or_code(g, mask, pal, c2i, ["M7", "M8", "G17", "H4", "M4"])
            ir11 = _pick_existing_or_code(g, mask, pal, c2i, ["G8", "H5", "H6", "F10"])
            pup11 = _pick_existing_or_code(g, mask, pal, c2i, ["H16", "H7", "H6"])
            for r in range(22, min(h, 54)):
                for c in range(18, min(w, 64)):
                    R, G, B = map(int, pal[int(g[r, c])]["rgb"])
                    if R * 0.299 + G * 0.587 + B * 0.114 < 155:
                        nbr_lums = [
                            pal[int(g[r + dr, c + dc])]["rgb"][0] * 0.299
                            + pal[int(g[r + dr, c + dc])]["rgb"][1] * 0.587
                            + pal[int(g[r + dr, c + dc])]["rgb"][2] * 0.114
                            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                        ]
                        if sum(1 for nl in nbr_lums if nl > 215) >= 3:
                            g[r, c] = fur11

            mc = _find_dark_center(g, mask, pal, 16, 23, 66, 74, lum_thresh=95.0)
            if mc is not None:
                mr0 = max(16, min(19, int(round(mc[0])) - 2))
                mc0 = max(67, min(70, int(round(mc[1])) - 2))
                for rr in range(mr0 - 1, mr0 + 5):
                    for cc in range(mc0 - 1, mc0 + 5):
                        if 0 <= rr < h and 0 <= cc < w and mask[rr, cc] and pal[int(g[rr, cc])]["rgb"][0] < 130:
                            g[rr, cc] = fur11
                _stamp_patch(g, mask, mr0, mc0, [
                    [rim11, pup11, pup11, rim11],
                    [pup11, idx_white, pup11, pup11],
                    [pup11, pup11, pup11, pup11],
                    [rim11, pup11, ir11,  rim11],
                ])

            fc = _find_dark_center(g, mask, pal, 11, 17, 70, 77, lum_thresh=95.0)
            if fc is not None:
                fr0 = max(11, min(13, int(round(fc[0])) - 1))
                fc0 = 72
                for rr in range(fr0 - 1, fr0 + 4):
                    for cc in range(fc0 - 1, fc0 + 4):
                        if 0 <= rr < h and 0 <= cc < w and mask[rr, cc] and pal[int(g[rr, cc])]["rgb"][0] < 130:
                            g[rr, cc] = fur11
                _stamp_patch(g, mask, fr0, fc0, [
                    [fur11, ir11,  pup11],
                    [rim11, idx_white, pup11],
                    [fur11, pup11, ir11],
                ])

    elif cat_id == "cat2":
        # 图二（72×72）：高光点对齐为左右对称干净 2×2 纯白 H1；雕刻细腻倒 Y 弧形猫嘴
        l_white_coords = []
        r_white_coords = []
        for r in range(21, 30):
            for c in range(4, 17):
                if mask[r, c] and pal[int(g[r, c])]["code"] in {"H1", "H2"}:
                    l_white_coords.append((r, c))
            for c in range(52, 66):
                if mask[r, c] and pal[int(g[r, c])]["code"] in {"H1", "H2"}:
                    r_white_coords.append((r, c))
        if l_white_coords:
            for r, c in l_white_coords:
                g[r, c] = idx_dark
            lr = min(r for r, _ in l_white_coords)
            lc = min(c for _, c in l_white_coords)
            _stamp_patch(g, mask, lr, lc, [
                [idx_white, idx_white],
                [idx_white, idx_white],
            ])
        if r_white_coords:
            for r, c in r_white_coords:
                g[r, c] = idx_dark
            rr_min = min(r for r, _ in r_white_coords)
            rc_min = min(c for _, c in r_white_coords)
            _stamp_patch(g, mask, rr_min, rc_min, [
                [idx_white, idx_white],
                [idx_white, idx_white],
            ])

        if kind == "ai_refined":
            mouth_dark = _pick_existing_or_code(g, mask, pal, c2i, ["H16", "H7", "H6"])
            chin_light = _pick_existing_or_code(g, mask, pal, c2i, ["G3", "G16", "M4"])
            chin_shade = _pick_existing_or_code(g, mask, pal, c2i, ["M13", "G13", "G3"])
            if 68 < h and 42 < w:
                _stamp_patch(g, mask, 64, 29, [
                    [chin_light, chin_light, chin_light, chin_light, chin_light, mouth_dark, mouth_dark, mouth_dark, chin_light, chin_light, chin_light, chin_light, chin_light],
                    [chin_light, chin_light, chin_light, mouth_dark, mouth_dark, chin_light, mouth_dark, chin_light, mouth_dark, mouth_dark, chin_light, chin_light, chin_light],
                    [chin_light, mouth_dark, mouth_dark, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, mouth_dark, mouth_dark, chin_light],
                    [chin_light, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_shade, chin_light],
                ])

    elif cat_id == "cat3":
        # 图三（趴趴白猫）：温和浅橄榄绿杏仁眼（M15/M2）+ 细腻上睫线 + 洁白鼻梁与粉耳
        w3 = c2i["H1"]
        ivory_i = _pick_existing_or_code(g, mask, pal, c2i, ["H10", "H17", "H2", "H11"])
        silver_i = _pick_existing_or_code(g, mask, pal, c2i, ["H11", "H3", "H10"])
        blk_i = _pick_existing_or_code(g, mask, pal, c2i, ["H7", "H16", "H6"])
        olive_mid_i = c2i["M15"]
        olive_lt_i = c2i["M2"]
        pink_ear_i = c2i["F14"]

        if kind == "ai_refined":
            sm_rgb = None
            if source_pixel_path is not None and Path(source_pixel_path).exists():
                src_im = np.array(Image.open(source_pixel_path).convert("RGB"))
                sm_rgb = _sample_mode_clean(src_im, w, h)
            # 清除白毛身上误映射的淡紫/粉灰/淡黄杂色（D19/D11/E22/D26/D2/H8/G1）
            bad_coat = {"E22", "D19", "D11", "D26", "D2", "H8", "G1"}
            for r in range(h):
                for c in range(w):
                    if not mask[r, c]:
                        continue
                    if pal[int(g[r, c])]["code"] in bad_coat:
                        if sm_rgb is not None:
                            R0, G0, B0 = [int(v) for v in sm_rgb[r, c]]
                            if B0 - R0 < 24 and min(R0, G0, B0) >= 130:
                                g[r, c] = w3 if min(R0, G0, B0) >= 230 else (ivory_i if min(R0, G0, B0) >= 195 else silver_i)
                        else:
                            g[r, c] = ivory_i
            if sm_rgb is not None:
                r_diff = sm_rgb[:, :, 0].astype(int) - sm_rgb[:, :, 1].astype(int)
                for r in range(int(0.14 * h), int(0.36 * h)):
                    for c in range(int(0.62 * w), int(0.90 * w)):
                        if r_diff[r, c] >= 20 and sm_rgb[r, c, 0] >= 175:
                            g[r, c] = pink_ear_i
            for r in range(28, min(h, 36)):
                for c in range(70, min(w, 82)):
                    if pal[int(g[r, c])]["code"] in {"F14", "E22", "D19", "D11", "H8"}:
                        g[r, c] = w3 if r <= 31 else ivory_i
            _stamp_patch(g, mask, 29, 75, [
                [pink_ear_i, pink_ear_i, pink_ear_i],
                [w3,         pink_ear_i, w3],
                [ivory_i,    silver_i,   ivory_i],
            ])
            w_l = (int(0.24 * h), int(0.36 * h), int(0.68 * w), int(0.76 * w))
            w_r = (int(0.24 * h), int(0.36 * h), int(0.77 * w), int(0.85 * w))
            clear_rad_y0, clear_rad_y1, clear_rad_x0, clear_rad_x1 = -2, 4, -3, 4
        else:
            # cat3 fusion_refined (75×94)：柔和提亮双目间鼻梁，仅清理核心眼窝不破坏面颊毛色过渡
            for r in range(21, 26):
                for c in range(72, 76):
                    if mask[r, c] and pal[int(g[r, c])]["rgb"][0] < 235:
                        g[r, c] = w3
            w_l = (20, 27, 65, 73)
            w_r = (20, 27, 74, 82)
            clear_rad_y0, clear_rad_y1, clear_rad_x0, clear_rad_x1 = -1, 3, -2, 2

        for (r0, r1, c0, c1) in (w_l, w_r):
            cen = _find_dark_center(g, mask, pal, r0, r1, c0, c1, lum_thresh=115.0)
            cy, cx = ((r0 + r1) // 2, (c0 + c1) // 2) if cen is None else (int(round(cen[0])), int(round(cen[1])))
            for rr in range(max(0, cy + clear_rad_y0), min(h, cy + clear_rad_y1)):
                for cc in range(max(0, cx + clear_rad_x0), min(w, cx + clear_rad_x1)):
                    R, G, B = map(int, pal[int(g[rr, cc])]["rgb"])
                    if not (B > R + 22 and R < 150) and (kind == "ai_refined" or R < 150):
                        g[rr, cc] = w3
            _stamp_patch(g, mask, cy - 1, cx - 2, [
                [None,        blk_i,       blk_i,       blk_i],
                [olive_mid_i, w3,          blk_i,       olive_lt_i],
                [olive_lt_i,  blk_i,       blk_i,       olive_mid_i],
                [None,        olive_mid_i, olive_lt_i,  None],
            ])

    elif cat_id == "cat4":
        return _refine_cat4_details(g, pal, is_ai=(kind == "ai_refined"))

    return g


def super_resolve_lowres_4x(rgb_u8: np.ndarray, has_white_caption: bool = False) -> np.ndarray:
    """
    对低分辨率原图执行 4x 超分重建（色度去噪 + 10轮迭代反投影 IBP + 双边保边先验 + Lab 防光晕微反差锐化）。
    若有顶部白字表情包（如'干嘛......'），会单独分流重建文字轮廓以防止字符涂抹。
    """
    h, w = rgb_u8.shape[:2]
    bgr = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
    den = cv2.fastNlMeansDenoisingColored(
        bgr, None, h=4.5, hColor=9.0, templateWindowSize=5, searchWindowSize=15
    )
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
        sr_rgb = np.clip(
            sr_rgb.astype(np.float32) * (1.0 - m_blend) + cap_sharp * m_blend, 0, 255
        ).astype(np.uint8)
    return sr_rgb


def super_resolve_lowres_rgba_if_needed(
    rgba: np.ndarray,
    min_dim_threshold: int = 220,
    has_white_caption: bool = False,
) -> np.ndarray:
    """当输入图像最短边低于阈值时自动执行 4x 超分；高分辨率原图则直接原样返回。"""
    h, w = rgba.shape[:2]
    if min(h, w) >= min_dim_threshold:
        return rgba
    sr_rgb = super_resolve_lowres_4x(rgba[:, :, :3], has_white_caption=has_white_caption)
    sr_alpha = cv2.resize(rgba[:, :, 3], (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
    return np.dstack([sr_rgb, sr_alpha])


def _inpaint_cat4_caption_area(sr_rgb: np.ndarray) -> np.ndarray:
    """Sampling前清除顶部低分辨率模糊文字残影，避免双点重影并方便后续重绘锐利'干嘛......'像素字。"""
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
    """图四三花猫暗光影调校准：提亮暗部、提纯鼻梁/胸口白毛、分离深橄榄虹膜与椭圆瞳孔、温和化鼻尖粉。"""
    H, W = sr_rgb.shape[:2]
    clean = _inpaint_cat4_caption_area(sr_rgb).astype(np.float32)
    cal = np.clip(clean * 1.18 + 6.0, 0, 255)
    cal = 255.0 * np.power(cal / 255.0, 0.91)

    lum = 0.299 * cal[:, :, 0] + 0.587 * cal[:, :, 1] + 0.114 * cal[:, :, 2]
    sat = cal.max(axis=2) - cal.min(axis=2)
    yy, xx = np.mgrid[0:H, 0:W]

    lower_face = (yy >= 0.42 * H) & (xx <= 0.66 * W)
    white_fur_w = (
        np.clip((lum - 138.0) / 48.0, 0.0, 1.0)
        * np.clip(1.0 - (sat - 16.0) / 34.0, 0.0, 1.0)
        * lower_face.astype(np.float32)
    )
    target_white = np.array([248.0, 246.0, 243.0], dtype=np.float32)
    cal = cal * (1.0 - 0.72 * white_fur_w[..., None]) + target_white * (0.72 * white_fur_w[..., None])

    reye = (yy >= 0.43 * H) & (yy <= 0.61 * H) & (xx >= 0.58 * W) & (xx <= 0.76 * W)
    leye = (yy >= 0.40 * H) & (yy <= 0.56 * H) & (xx >= 0.22 * W) & (xx <= 0.37 * W)
    iris_mask = (reye | leye) & (lum >= 24.0) & (lum <= 92.0)
    cal_iris = np.clip(cal * np.array([1.08, 1.16, 1.16], dtype=np.float32) + 6.0, 0, 255)
    cal[iris_mask] = cal_iris[iris_mask]

    muzzle_roi = (yy >= 0.68 * H) & (yy <= 0.99 * H) & (xx >= 0.30 * W) & (xx <= 0.60 * W)
    mouth_slit = (yy >= 0.87 * H) & (yy <= 0.92 * H) & (xx >= 0.43 * W) & (xx <= 0.52 * W)
    lift_mask = muzzle_roi & (~mouth_slit) & (lum < 142.0)
    cal_m = np.clip(cal * 1.24 + np.array([16.0, 18.0, 14.0], dtype=np.float32), 0, 255)
    r_exc = np.maximum(0.0, cal_m[:, :, 0] - cal_m[:, :, 1] - 32.0)
    cal_m[:, :, 0] = np.clip(cal_m[:, :, 0] - 0.45 * r_exc, 0, 255)
    cal[lift_mask] = cal_m[lift_mask]

    nose_roi = (yy >= 0.705 * H) & (yy <= 0.79 * H) & (xx >= 0.415 * W) & (xx <= 0.495 * W)
    cal[nose_roi] = np.clip(
        cal[nose_roi] * np.array([1.06, 0.96, 0.96], dtype=np.float32) + np.array([10.0, 4.0, 5.0], dtype=np.float32),
        0,
        255,
    )
    return np.clip(cal, 0, 255).astype(np.uint8)


def calibrate_cat4_calico_rgba(rgba: np.ndarray) -> np.ndarray:
    """对低分辨率 RGBA 图四先做 4x 超分再执行暗光影调校准。"""
    sr_rgba = super_resolve_lowres_rgba_if_needed(rgba, min_dim_threshold=220, has_white_caption=True)
    cal_rgb = calibrate_cat4_calico_rgb(sr_rgba[:, :, :3])
    return np.dstack([cal_rgb, sr_rgba[:, :, 3]])


def generate_cat1_16bit_illustration(src_ai_path: Path, out_path: Path) -> Path:
    """将 Gemini 灵魂重绘版图一对齐至原生 8px 逻辑像素格，裁紧白边并导出高清底图供方案2使用。"""
    im = np.array(Image.open(src_ai_path).convert("RGB"))
    dx = np.abs(np.diff(im.astype(np.float32), axis=1)).mean(axis=(0, 2))
    dy = np.abs(np.diff(im.astype(np.float32), axis=0)).mean(axis=(1, 2))
    ox = max(range(8), key=lambda o: dx[o::8].mean())
    oy = max(range(8), key=lambda o: dy[o::8].mean())
    sx, sy = (ox + 1) % 8, (oy + 1) % 8
    hn, wn = (im.shape[0] - sy) // 8, (im.shape[1] - sx) // 8
    grid_raw = np.zeros((hn, wn, 3), dtype=np.uint8)
    for r in range(hn):
        for c in range(wn):
            patch = im[sy + r * 8 + 2 : sy + r * 8 + 6, sx + c * 8 + 2 : sx + c * 8 + 6]
            grid_raw[r, c] = np.median(patch.reshape(-1, 3), axis=0).astype(np.uint8)
    nw = grid_raw.min(axis=2) < 236
    ys, xs = np.where(nw)
    crop = grid_raw[max(0, int(ys.min()) - 1) : min(hn, int(ys.max()) + 2), max(0, int(xs.min()) - 1) : min(wn, int(xs.max()) + 2)].copy()
    ow = (crop.min(axis=2) >= 238) & ((crop.max(axis=2) - crop.min(axis=2)) <= 16)
    crop[ow] = [255, 255, 255]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(crop).resize((crop.shape[1] * 8, crop.shape[0] * 8), Image.Resampling.NEAREST).save(out_path)
    return out_path


def generate_cat3_16bit_illustration(src_ai_path: Path, out_path: Path, grid_w: int = 96) -> Path:
    """
    裁剪 Gemini 版图三外圈白边，彻底中和猫毛上的冷紫/藕荷偏色（还原纯白+中性银灰光影），
    并保留粉红耳廓与柔和浅橄榄眼底色，供方案2（96格横版）高清量化使用。
    """
    im = np.array(Image.open(src_ai_path).convert("RGB"))
    ys, xs = np.where(im.min(axis=2) < 230)
    crop = im[int(ys.min()) + 5 : int(ys.max()) - 4, int(xs.min()) + 9 : int(xs.max()) - 8].astype(np.float32)

    is_blue_sheet = (crop[:, :, 2] - crop[:, :, 0] >= 26) & (crop[:, :, 0] < 178)
    is_pink_area = (crop[:, :, 0] - crop[:, :, 1] >= 18) & (crop[:, :, 0] > 165) & (crop[:, :, 0] >= crop[:, :, 2] - 2)
    is_green_iris = (crop[:, :, 1] - crop[:, :, 2] >= 8) & (crop[:, :, 1] >= crop[:, :, 0])
    lum = crop[:, :, 0] * 0.299 + crop[:, :, 1] * 0.587 + crop[:, :, 2] * 0.114
    is_fur = (~is_blue_sheet) & (~is_pink_area) & (~is_green_iris) & (lum >= 105.0)

    ivory = np.where(lum >= 218.0, 255.0, np.clip(lum * 1.04 + 4.0, 120.0, 250.0))
    crop[is_fur, 0] = ivory[is_fur]
    crop[is_fur, 1] = ivory[is_fur]
    crop[is_fur, 2] = np.clip(ivory[is_fur] - np.where(lum[is_fur] >= 218.0, 0.0, 1.5), 0, 255)

    hc, wc, _ = crop.shape
    ear_roi = np.zeros((hc, wc), dtype=bool)
    ear_roi[int(0.14 * hc) : int(0.32 * hc), int(0.64 * wc) : int(0.89 * wc)] = True
    pink_ears = ear_roi & is_pink_area
    crop[pink_ears, 0] = np.clip(crop[pink_ears, 0] * 1.02 + 4, 0, 255)
    crop[pink_ears, 1] = np.clip(crop[pink_ears, 1] * 0.94, 0, 255)
    crop[pink_ears, 2] = np.clip(crop[pink_ears, 2] * 0.95, 0, 255)

    out_h = max(1, int(round(grid_w * hc / wc)))
    sm = _sample_mode_clean(np.clip(crop, 0, 255).astype(np.uint8), grid_w, out_h)
    for col_i in (0, grid_w - 1):
        nbr_c = 1 if col_i == 0 else grid_w - 2
        for row_i in range(out_h):
            if sm[row_i, col_i].min() > 210:
                sm[row_i, col_i] = sm[row_i, nbr_c]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(sm).resize((grid_w * 8, out_h * 8), Image.Resampling.NEAREST).save(out_path)
    return out_path


def generate_cat4_16bit_illustration(
    src_path: Path, out_path: Path, grid_w: int = 96, grid_h: int = 88, ai_src_path: Path | None = None
) -> Path:
    """为图四（干嘛三花猫）生成满幅精绘高清像素底图（优先采用 Gemini 灵魂重绘版并校准烟熏橄榄虹膜与柔粉鼻尖）。"""
    if ai_src_path is not None and Path(ai_src_path).exists():
        gv3 = np.array(Image.open(ai_src_path).convert("RGB")).astype(np.float32)
        lum_g = 0.299 * gv3[:, :, 0] + 0.587 * gv3[:, :, 1] + 0.114 * gv3[:, :, 2]
        sat_g = gv3.max(axis=2) - gv3.min(axis=2)
        neutral_lt = (lum_g >= 150) & (lum_g < 235) & (sat_g <= 25)
        gv3[neutral_lt] = np.clip(gv3[neutral_lt] * np.array([1.09, 1.08, 1.04]) + np.array([16, 14, 10]), 0, 255)
        pink_g = (gv3[:, :, 0] > 180) & (gv3[:, :, 1] < 135) & (gv3[:, :, 2] < 135)
        gv3[pink_g] = np.clip(gv3[pink_g] * np.array([0.88, 0.96, 1.08]) + np.array([12, 12, 14]), 0, 255)
        hg, wg, _ = gv3.shape
        eye_mask_g = np.zeros((hg, wg), dtype=bool)
        eye_mask_g[int(0.38 * hg) : int(0.58 * hg), int(0.18 * wg) : int(0.76 * wg)] = True
        olive_g = eye_mask_g & (gv3[:, :, 1] > gv3[:, :, 2] + 12) & (lum_g > 60) & (lum_g < 185)
        gv3[olive_g, 0] = np.clip(gv3[olive_g, 0] * 0.95 + 10, 0, 255)
        gv3[olive_g, 1] = np.clip(gv3[olive_g, 1] * 0.95 + 10, 0, 255)
        gv3[olive_g, 2] = np.clip(gv3[olive_g, 2] * 1.15 + 22, 0, 255)

        sm_g = _sample_mode_clean(np.clip(gv3, 0, 255).astype(np.uint8), grid_w, grid_h)
        cl_g = sm_g.copy()
        # 擦除原图顶部手绘字迹，交由标准点阵 _build_ganma_bitmap() 统一生成锐利纯白'干嘛......'
        for r in range(0, min(grid_h, 23)):
            for c in range(14, min(grid_w, 82)):
                R, G, B = [int(v) for v in cl_g[r, c]]
                if min(R, G, B) >= 182 and (max(R, G, B) - min(R, G, B)) <= 32:
                    for d in range(1, 16):
                        found = False
                        for rr in (r - d, r + d):
                            if 0 <= rr < grid_h:
                                rv, gv, bv = [int(x) for x in sm_g[rr, c]]
                                if min(rv, gv, bv) < 172:
                                    cl_g[r, c] = sm_g[rr, c]
                                    found = True
                                    break
                        if found:
                            break
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(cl_g).resize((grid_w * 8, grid_h * 8), Image.Resampling.NEAREST).save(out_path)
        return out_path

    raw = np.array(Image.open(src_path).convert("RGB"))
    sr_rgb = super_resolve_lowres_4x(raw, has_white_caption=True)
    cal = calibrate_cat4_calico_rgb(sr_rgb)
    sm = cal.copy()
    for _ in range(3):
        sm = cv2.bilateralFilter(sm, d=9, sigmaColor=24, sigmaSpace=6)
    small = cv2.resize(sm, (grid_w, grid_h), interpolation=cv2.INTER_AREA)
    pts = small.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 35, 0.35)
    _, labels, centers = cv2.kmeans(pts, 16, None, criteria, 8, cv2.KMEANS_PP_CENTERS)
    flat = np.clip(centers[labels.flatten()].reshape(grid_h, grid_w, 3), 0, 255).astype(np.uint8)
    lum_c = 0.299 * centers[:, 0] + 0.587 * centers[:, 1] + 0.114 * centers[:, 2]
    darkest = int(np.argmin(lum_c))
    brightest = int(np.argmax(lum_c))
    lbl = labels.reshape(grid_h, grid_w)
    flat[lbl == darkest] = [6, 6, 6]
    flat[lbl == brightest] = [252, 252, 250]
    flat[
        int(round(0.73 * grid_h)):int(round(0.77 * grid_h)),
        int(round(0.44 * grid_w)):int(round(0.47 * grid_w)),
    ] = [194, 120, 102]
    flat[
        int(round(0.51 * grid_h)):int(round(0.56 * grid_h)),
        int(round(0.68 * grid_w)):int(round(0.73 * grid_w)),
    ] = [114, 125, 122]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(flat).resize((grid_w * 8, grid_h * 8), Image.Resampling.NEAREST).save(out_path)
    return out_path


def _pick_used_or_close(grid: np.ndarray, pal: list, preferred_codes: list[str], fallback_rgb: tuple[int, int, int]) -> int:
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


def _build_ganma_bitmap() -> np.ndarray:
    gan = [
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
    ma = [
        "00000000001000000",
        "00000111111111111",
        "11110100000000000",
        "10010100010000100",
        "10010101111101111",
        "10010100010000100",
        "11110100111001110",
        "00000101010110101",
        "00000110010000100",
        "00000100010000100",
        "00001000010000100",
        "00001000010000100",
        "00010000010000100",
        "00010000010000100",
    ]
    h = 14
    w = 12 + 2 + 17 + 2 + 25
    bmp = np.zeros((h, w), dtype=bool)
    for r, row in enumerate(gan):
        for c, ch in enumerate(row):
            if ch == "1":
                bmp[r, c] = True
    ox = 14
    for r, row in enumerate(ma):
        for c, ch in enumerate(row):
            if ch == "1":
                bmp[r, ox + c] = True
    dots_x = ox + 19
    for k in range(6):
        cx = dots_x + k * 4
        bmp[h - 2, cx:cx + 2] = True
        bmp[h - 1, cx:cx + 2] = True
    return bmp


def _refine_cat4_details(grid: np.ndarray, pal: list, is_ai: bool = False) -> np.ndarray:
    """精修图四三花猫：烟熏橄榄灰杏仁眼眶（M15/M2/H5）+ 竖向椭圆黑瞳孔 + 纯白高光 + 锐利'干嘛......'。"""
    H, W = grid.shape
    c2i = _code_map(pal)
    w_i = _pick_used_or_close(grid, pal, ["H1", "H2", "E14"], (255, 255, 255))
    pup_i = _pick_used_or_close(grid, pal, ["H7", "H16", "H6"], (6, 6, 6))
    sh_i = _pick_used_or_close(grid, pal, ["H6", "H5"], (44, 44, 44))
    ir_dk = c2i["H5"]
    ir_md = c2i["M15"]
    ir_lt = c2i["M2"]
    glint_i = _pick_used_or_close(grid, pal, ["H1", "H2", "H19", "H3"], (250, 248, 246))
    pink_i = _pick_used_or_close(grid, pal, ["M14", "F20", "M8", "M13", "G13", "F17"], (188, 126, 104))

    bmp = _build_ganma_bitmap()
    bh, bw = bmp.shape
    r0_t = 4 if is_ai else max(2, int(round(H * 0.045)))
    c0_t = 16 if is_ai else max(6, int(round(W * 0.16)))
    for r in range(bh):
        for c in range(bw):
            gr, gc = r0_t + r, c0_t + c
            if 0 <= gr < H and 0 <= gc < W and bmp[r, c]:
                grid[gr, gc] = w_i

    # 清除眼部区域的亮荧光绿杂豆（B11/B23/B32 -> 烟熏橄榄灰）
    for r in range(int(0.36 * H), min(H, int(0.64 * H))):
        for c in range(int(0.18 * W), min(W, int(0.78 * W))):
            if pal[int(grid[r, c])]["code"] in {"B11", "B23", "B32"}:
                grid[r, c] = ir_md if is_ai else ir_dk

    if is_ai:
        # 保留 Gemini 原生自然拱形浅棕眉（位于 r=40..42），仅轻微理顺左眼上眶折线与右眼下外缘单颗杂点
        for c in range(23, min(W, 36)):
            grid[39, c] = sh_i
        if 52 < H and 69 < W and pal[int(grid[52, 69])]["code"] != "H7":
            grid[52, 69] = pup_i
        specs = [
            (29.3, 45.6, 7.6, 5.8, 2.00, 4.5, +0.08, False),
            (63.4, 47.2, 8.3, 6.2, 2.20, 4.9, -0.08, True),
        ]
    else:
        specs = [
            (0.296 * W, 0.482 * H, 0.072 * W, 0.072 * H, 0.021 * W, 0.054 * H, +0.08, False),
            (0.672 * W, 0.512 * H, 0.078 * W, 0.074 * H, 0.022 * W, 0.056 * H, -0.08, True),
        ]

    for cx, cy, rx, ry, px_r, py_r, tilt, is_right in specs:
        r0, r1 = max(0, int(np.floor(cy - ry - 2))), min(H, int(np.ceil(cy + ry + 2)))
        c0, c1 = max(0, int(np.floor(cx - rx - 2))), min(W, int(np.ceil(cx + rx + 2)))
        for r in range(r0, r1):
            for c in range(c0, c1):
                nx = (c - cx) / rx
                ny = (r - cy) / ry
                y_top = -0.90 + 0.46 * (nx ** 2) + (tilt * nx)
                y_bot = +0.94 - 0.48 * (nx ** 2) - (0.05 * nx if is_right else 0.0)
                if -1.02 <= nx <= 1.02 and y_top <= ny <= y_bot:
                    if ny <= y_top + 0.16:
                        grid[r, c] = pup_i
                        continue
                    if ny >= y_bot - 0.14 or abs(nx) >= 0.91:
                        grid[r, c] = sh_i if (ny > 0.20) else pup_i
                        continue
                    dx_p = (c - (cx + (-0.15 if is_right else +0.10))) / px_r
                    dy_p = (r - (cy + 0.06 * ry)) / (py_r * 0.88)
                    taper = 1.0 + 0.25 * (dy_p ** 2)
                    if (dx_p * taper) ** 2 + dy_p ** 2 <= 1.0:
                        grid[r, c] = pup_i
                    else:
                        ls = (0.52 * ny + 0.34 * nx) if is_right else (-0.38 * nx + 0.52 * ny)
                        thr_lt = 0.28 if is_right else 0.42
                        thr_md = -0.14 if is_right else -0.05
                        grid[r, c] = ir_lt if ls > thr_lt else (ir_md if ls > thr_md else ir_dk)
        gr, gc = int(round(cy - 0.25 * ry)), int(round(cx - px_r * 0.85))
        if 0 <= gr < H and 0 <= gc < W:
            grid[gr, gc] = glint_i

    if not is_ai:
        # 方案1 融合版：还原三文鱼粉鼻头 + 鼻梁左侧自然小雀斑（贴近鼻上缘单颗炭黑）
        nr0, nr1 = int(round(0.712 * H)), int(round(0.785 * H))
        nc0, nc1 = int(round(0.415 * W)), int(round(0.498 * W))
        nx_c = 0.456 * W
        for r in range(nr0, nr1 + 1):
            for c in range(nc0, nc1 + 1):
                t = max(0.0, (r - nr0) / max(1.0, (nr1 - nr0)))
                half_w = 0.038 * W * (1.0 - 0.65 * t)
                if abs(c - nx_c) <= half_w:
                    grid[r, c] = pink_i
        n_y = int(round(0.780 * H))
        for dc in (-2, 2):
            if 0 <= n_y < H and 0 <= int(round(nx_c)) + dc < W:
                grid[n_y, int(round(nx_c)) + dc] = sh_i
        w_nose = _pick_used_or_close(grid, pal, ["H1", "H2", "H19"], (250, 250, 248))
        for r in range(int(round(0.62 * H)), int(round(0.70 * H))):
            for c in range(int(round(0.37 * W)), int(round(0.45 * W))):
                if pal[int(grid[r, c])]["code"] in {"H7", "H16"}:
                    grid[r, c] = w_nose
        fr_r, fr_c = int(round(0.692 * H)), int(round(0.398 * W))
        if 0 <= fr_r < H and 0 <= fr_c < W:
            grid[fr_r, fr_c] = sh_i
    return grid


def render_baked_flat_melt_preview(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    out_path: Path,
    cell_px: int = 18,
    seed: int = 42,
) -> None:
    """
    真实世界拼豆『烘烤/热熨定型（满焊~近满焊）』物理实拍效果渲染：
    - 受热塑料豆压扁并横向膨胀为彼此紧密咬合的「圆角小方砖（squircle）」像素格，彻底告别未熨烫的空心圆管感；
    - 约 75% 中心孔受热完全熔合封闭，约 25% 仅保留随机微弱针眼小凹点（无机械整齐大黑洞）；
    - 相邻像素之间呈柔和热熔沟槽与烘焙油纸半哑光塑料微反光，外沿保持柔和半圆豆角边缘。
    """
    rng = np.random.default_rng(seed)
    h, w = idx_grid.shape
    pad = max(44, int(round(min(h, w) * cell_px * 0.14)))
    cw = w * cell_px + 2 * pad
    ch = h * cell_px + 2 * pad

    # 温暖哑光手工作品桌面底图 + 轻微纸纹暗角
    bg_base = np.zeros((ch, cw, 3), dtype=np.float32)
    yy, xx = np.mgrid[0:ch, 0:cw]
    vign = 1.0 - 0.085 * (((xx - cw / 2) / (cw / 2)) ** 2 + ((yy - ch / 2) / (ch / 2)) ** 2)
    grain = gaussian_filter(rng.normal(0.0, 2.0, (ch, cw)).astype(np.float32), sigma=0.75)
    bg_base[:, :, 0] = 232.0 * vign + grain
    bg_base[:, :, 1] = 225.0 * vign + grain * 0.96
    bg_base[:, :, 2] = 216.0 * vign + grain * 0.92

    piece_mask = np.zeros((ch, cw), dtype=bool)
    color_img = np.zeros((ch, cw, 3), dtype=np.float32)
    height_map = np.zeros((ch, cw), dtype=np.float32)
    seam_shadow = np.zeros((ch, cw), dtype=np.float32)
    pinhole_map = np.zeros((ch, cw), dtype=np.float32)

    # 约84%中心孔随热区平滑熔融闭合，仅少数保留轻微凹陷（避免机械网格点阵）
    hole_choices = np.array([0.0] * 10 + [0.13, 0.17], dtype=np.float32)

    for r in range(h):
        for c in range(w):
            if not mask[r, c]:
                continue
            y0 = pad + r * cell_px
            x0 = pad + c * cell_px
            cur_idx = int(idx_grid[r, c])
            R, G, B = map(float, pal[cur_idx]["rgb"])

            has_top = (r > 0) and mask[r - 1, c]
            has_bot = (r + 1 < h) and mask[r + 1, c]
            has_left = (c > 0) and mask[r, c - 1]
            has_right = (c + 1 < w) and mask[r, c + 1]
            adj_count = int(has_top) + int(has_bot) + int(has_left) + int(has_right)

            # 同色相邻塑料几乎无缝融成一片，仅异色接壤或外边界留微弱熔痕
            diff_top = 1.0 if (has_top and int(idx_grid[r - 1, c]) != cur_idx) else 0.14
            diff_bot = 1.0 if (has_bot and int(idx_grid[r + 1, c]) != cur_idx) else 0.14
            diff_left = 1.0 if (has_left and int(idx_grid[r, c - 1]) != cur_idx) else 0.14
            diff_right = 1.0 if (has_right and int(idx_grid[r, c + 1]) != cur_idx) else 0.14

            dx_j = rng.uniform(-0.36, 0.36)
            dy_j = rng.uniform(-0.36, 0.36)

            oy0 = max(0, y0 - 1)
            oy1 = min(ch, y0 + cell_px + 1)
            ox0 = max(0, x0 - 1)
            ox1 = min(cw, x0 + cell_px + 1)
            ly, lx = np.mgrid[oy0:oy1, ox0:ox1]
            ny = (ly - (y0 + cell_px * 0.5 + dy_j)) / (cell_px * 0.5)
            nx = (lx - (x0 + cell_px * 0.5 + dx_j)) / (cell_px * 0.5)
            # 轻微热融液态波纹偏移，打破机械直边
            nx = nx + 0.045 * np.sin(ny * 3.2 + c * 1.3)
            ny = ny + 0.045 * np.cos(nx * 3.2 + r * 1.7)

            # 内部热融时塑料向四周及四角满溢闭合，外轮廓保持圆润豆角弧
            box_d = np.maximum(np.abs(nx), np.abs(ny))
            squircle_d = (np.abs(nx) ** 3.1 + np.abs(ny) ** 3.1) ** (1.0 / 3.1)
            if adj_count == 4:
                dist_sq = 0.85 * box_d + 0.15 * squircle_d
                inside = box_d <= 1.08
            elif adj_count >= 2:
                dist_sq = 0.45 * box_d + 0.55 * squircle_d
                inside = dist_sq <= 1.03
            else:
                dist_sq = squircle_d
                inside = dist_sq <= 0.99

            # 按方位异色权重衰减同色接缝，同一块白毛/棕壳不会出现棋盘格线
            seam_dir = np.where(
                np.abs(ny) >= np.abs(nx),
                np.where(ny < 0, diff_top, diff_bot),
                np.where(nx < 0, diff_left, diff_right),
            )
            dome = np.clip(1.0 - 0.095 * (dist_sq ** 3.6) * (0.4 + 0.6 * seam_dir), 0.50, 1.0)
            groove = np.clip((dist_sq - 0.87) / 0.19, 0.0, 1.0) * seam_dir

            hole_r = float(rng.choice(hole_choices))
            pin = np.zeros_like(dist_sq)
            if hole_r > 0.0:
                radial = np.sqrt(nx * nx + ny * ny)
                pin = np.clip(1.0 - radial / hole_r, 0.0, 1.0) ** 1.6

            jitter = rng.uniform(-1.5, 1.5, 3).astype(np.float32)
            bead_col = np.clip(np.array([R, G, B], dtype=np.float32) + jitter, 0.0, 255.0)

            write_mask = inside & (~piece_mask[oy0:oy1, ox0:ox1] | (dist_sq < 0.96))
            piece_mask[oy0:oy1, ox0:ox1] |= inside
            for ch_i in range(3):
                color_img[oy0:oy1, ox0:ox1, ch_i] = np.where(write_mask, bead_col[ch_i], color_img[oy0:oy1, ox0:ox1, ch_i])
            height_map[oy0:oy1, ox0:ox1] = np.where(write_mask, dome, height_map[oy0:oy1, ox0:ox1])
            seam_shadow[oy0:oy1, ox0:ox1] = np.where(write_mask, np.maximum(seam_shadow[oy0:oy1, ox0:ox1], groove), seam_shadow[oy0:oy1, ox0:ox1])
            if hole_r > 0.0:
                pinhole_map[oy0:oy1, ox0:ox1] = np.where(write_mask, np.maximum(pinhole_map[oy0:oy1, ox0:ox1], pin), pinhole_map[oy0:oy1, ox0:ox1])

    piece_f = piece_mask.astype(np.float32)
    alpha = np.clip((gaussian_filter(piece_f, sigma=0.65) - 0.15) / 0.68, 0.0, 1.0)

    # 塑料熔融边沿柔和漫混（sigma=0.60 让相邻塑料色边沿略呈蜡质融合）
    melted_color = np.zeros_like(color_img)
    w_denom = gaussian_filter(piece_f, sigma=0.60) + 1e-6
    for ch_i in range(3):
        melted_color[:, :, ch_i] = gaussian_filter(color_img[:, :, ch_i] * piece_f, sigma=0.60) / w_denom
    color_img = np.where(piece_mask[:, :, None], 0.56 * color_img + 0.44 * melted_color, color_img)

    # 烘焙油纸质感漫反射 + 微缎面高光 + 斜向塑料反光带
    gy, gx = np.gradient(gaussian_filter(height_map, sigma=0.95))
    nz = 0.28
    norm = np.sqrt(gx * gx + gy * gy + nz * nz) + 1e-6
    diffuse = (-(gx * -0.45 + gy * -0.58) + nz * 0.68) / norm
    diffuse = 0.95 + 0.11 * np.clip(diffuse, -0.5, 1.0)
    iron_tex = gaussian_filter(rng.normal(0.0, 1.2, (ch, cw)).astype(np.float32), sigma=1.2)
    sheen_band = np.clip(1.0 - np.abs(((xx - cw * 0.35) / cw) + ((yy - ch * 0.32) / ch)) * 2.4, 0.0, 1.0) * 6.5
    spec = np.clip((diffuse - 1.005) * 4.5, 0.0, 1.0) * 10.0 + sheen_band

    shaded = color_img * diffuse[:, :, None] + spec[:, :, None] + iron_tex[:, :, None]
    shaded = np.clip(shaded * (1.0 - 0.045 * seam_shadow[:, :, None]) * (1.0 - 0.12 * pinhole_map[:, :, None]), 0.0, 255.0)

    # 自然实物投影
    shadow_alpha = gaussian_filter(piece_f, sigma=cell_px * 0.30)
    off_y, off_x = max(3, cell_px // 4), max(2, cell_px // 5)
    shifted = np.zeros_like(shadow_alpha)
    shifted[off_y:, off_x:] = shadow_alpha[:-off_y, :-off_x]
    ao_shadow = np.clip(shifted * 0.34 + shadow_alpha * 0.18, 0.0, 0.52) * (1.0 - alpha)
    bg_lit = bg_base * (1.0 - ao_shadow[:, :, None])

    comp = shaded * alpha[:, :, None] + bg_lit * (1.0 - alpha[:, :, None])
    out_u8 = np.clip(np.round(comp), 0, 255).astype(np.uint8)
    Image.fromarray(out_u8, "RGB").save(out_path, quality=95)


def export_crisp_grid_ref_for_chatgpt(idx_grid: np.ndarray, mask: np.ndarray, pal: list, out_png: Path, cell_px: int = 12) -> None:
    """导出纯正无噪点高清像素色块参考图（供 ChatGPT 识别严格位置与圆润五官后渲染真实热熨实物照片）。"""
    h, w = idx_grid.shape
    pad = cell_px * 2
    img = Image.new("RGB", (w * cell_px + 2 * pad, h * cell_px + 2 * pad), (246, 244, 240))
    draw = ImageDraw.Draw(img)
    for r in range(h):
        for c in range(w):
            if not mask[r, c]:
                continue
            R, G, B = map(int, pal[int(idx_grid[r, c])]["rgb"])
            x0, y0 = pad + c * cell_px, pad + r * cell_px
            draw.rectangle([x0, y0, x0 + cell_px - 1, y0 + cell_px - 1], fill=(R, G, B))
    img.save(out_png)
