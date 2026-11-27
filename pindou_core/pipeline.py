# -*- coding: utf-8 -*-
"""
统一拼豆转图流水线：
1. photo_fusion   : 照片融合精修（显著性/边缘加权 Lab K-means++ + CIEDE2000 + ICM 平滑）
2. cutout_outline : 异形描边镂空（自动抠底去背景 + 1 格 H5 炭灰描边 + 白毛防偏绿）
3. grid_extract   : 网格参考图直提（去白边/字幕 + 格内中心采样 + MARD 量化）
"""

from __future__ import annotations

from collections import deque
import sys
from typing import Any

import numpy as np
from PIL import Image, ImageOps
from skimage import color as skcolor

from .palette import (
    delta_e2000_matrix,
    filter_palette_subset,
    get_palette_maps,
    normalize_mard_code,
)
from .standards import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fast_parallel_pindou_cats import pindou_studio_photo_quantize, sample_photo_tiles  # noqa: E402
from fast_parallel_pindou_engine import keep_exact_color_count_reduce  # noqa: E402


def _neutralize_pale_green_cast(rgba: np.ndarray) -> np.ndarray:
    """消除高光白毛或浅灰背景中偏绿（G > max(R, B)）的相机色偏，防止误映射为 B/C/D/G15。"""
    out = rgba.copy()
    rgb = out[:, :, :3].astype(np.int16)
    alpha = out[:, :, 3]
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    pale_neutral = (alpha >= 128) & (lum >= 195.0) & ((max_c - min_c) <= 30) & (g >= r) & (g >= b)
    if np.any(pale_neutral):
        target_g = np.clip(np.minimum(r, b) + 1, 0, 255)
        # 温和消除纯绿偏移并略提亮中性白
        rgb[:, :, 1] = np.where(pale_neutral, np.minimum(g, target_g + 2), g)
        out[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return out


def _auto_remove_backdrop_rgba(rgba: np.ndarray, dist_thresh: float = 28.0) -> np.ndarray:
    """
    若原图无有效透明通道，从四角泛洪填充去除统一浅色/纯色背景。
    """
    h, w, _ = rgba.shape
    alpha = rgba[:, :, 3]
    if float((alpha < 128).mean()) >= 0.04:
        # 已有透明区域，保留透明通道并做二值硬化边缘
        out = rgba.copy()
        out[:, :, 3] = np.where(alpha >= 128, 255, 0).astype(np.uint8)
        return out

    rgb = rgba[:, :, :3].astype(np.float32)
    # 采样四角 4x4 邻域中位数作为背景参考色
    corners = [
        rgb[0:min(4, h), 0:min(4, w)].reshape(-1, 3),
        rgb[0:min(4, h), max(0, w - 4):w].reshape(-1, 3),
        rgb[max(0, h - 4):h, 0:min(4, w)].reshape(-1, 3),
        rgb[max(0, h - 4):h, max(0, w - 4):w].reshape(-1, 3),
    ]
    bg_rgb = np.median(np.vstack(corners), axis=0)

    visited = np.zeros((h, w), dtype=bool)
    is_bg = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()
    for sr, sc in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)):
        visited[sr, sc] = True
        q.append((sr, sc))

    thresh_sq = dist_thresh * dist_thresh * 3.0
    while q:
        r, c = q.popleft()
        diff = rgb[r, c] - bg_rgb
        if float(np.dot(diff, diff)) <= thresh_sq:
            is_bg[r, c] = True
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w and not visited[nr, nc]:
                    visited[nr, nc] = True
                    q.append((nr, nc))

    # 若误抠超过 92% 画面，回退不抠底以免主体丢失
    if float(is_bg.mean()) > 0.92 or float(is_bg.mean()) < 0.01:
        return rgba

    out = rgba.copy()
    out[is_bg, 3] = 0
    return out


def _crop_to_foreground(rgba: np.ndarray, pad_ratio: float = 0.04) -> np.ndarray:
    """裁剪掉外围全透明留白，仅保留主体外接框加少量边距。"""
    fg = rgba[:, :, 3] >= 128
    if not fg.any():
        return rgba
    ys, xs = np.where(fg)
    h, w, _ = rgba.shape
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    pad = max(1, int(round(max(y1 - y0, x1 - x0) * pad_ratio)))
    y0 = max(0, y0 - pad)
    y1 = min(h, y1 + pad)
    x0 = max(0, x0 - pad)
    x1 = min(w, x1 + pad)
    return rgba[y0:y1, x0:x1]


def _fit_rgba_to_canvas(rgba: np.ndarray, target_w: int, target_h: int, margin: int = 0) -> np.ndarray:
    """等比缩放 RGBA 主体并居中放入透明背景画布（用于采样前的对齐准备）。"""
    scale_px = 8  # 先在 8× 超采样画布上做透明隔离采样，减少网格混色
    cw, ch = target_w * scale_px, target_h * scale_px
    inner_w = max(scale_px, (target_w - 2 * margin) * scale_px)
    inner_h = max(scale_px, (target_h - 2 * margin) * scale_px)

    pil_fg = Image.fromarray(rgba, "RGBA")
    src_w, src_h = pil_fg.size
    ratio = min(inner_w / max(1, src_w), inner_h / max(1, src_h))
    new_w = max(1, int(round(src_w * ratio)))
    new_h = max(1, int(round(src_h * ratio)))
    resized = pil_fg.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (cw, ch), (255, 255, 255, 0))
    off_x = (cw - new_w) // 2
    off_y = (ch - new_h) // 2
    canvas.paste(resized, (off_x, off_y), resized)
    return np.array(canvas)


def _sample_tiles_exact(rgba: np.ndarray, out_w: int, out_h: int) -> tuple[np.ndarray, np.ndarray]:
    """按目标 (out_h, out_w) 进行前景隔离的块采样（支持任意非正方形尺寸）。"""
    src_h, src_w, _ = rgba.shape
    # 若恰好正方形，直接复用 sample_photo_tiles 获得特征锚点保持
    if out_w == out_h:
        return sample_photo_tiles(rgba, longest_edge=out_w, force_square=out_w, mode="edge_aware")

    # 否则先把长边放入 sample_photo_tiles 同等网格尺度采样，再精确映射每格
    grid_rgb = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    mask = np.zeros((out_h, out_w), dtype=bool)
    rgb_all = rgba[:, :, :3]
    a_all = rgba[:, :, 3]

    for oy in range(out_h):
        y0 = int(round(oy * src_h / out_h))
        y1 = max(y0 + 1, int(round((oy + 1) * src_h / out_h)))
        for ox in range(out_w):
            x0 = int(round(ox * src_w / out_w))
            x1 = max(x0 + 1, int(round((ox + 1) * src_w / out_w)))
            fg = a_all[y0:y1, x0:x1] >= 128
            if float(fg.mean()) < 0.45:
                continue
            fg_px = rgb_all[y0:y1, x0:x1][fg].astype(np.float64)
            lin = np.where(fg_px / 255.0 <= 0.04045, (fg_px / 255.0) / 12.92, ((fg_px / 255.0 + 0.055) / 1.055) ** 2.4).mean(axis=0)
            srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * (np.maximum(lin, 0.0) ** (1.0 / 2.4)) - 0.055)
            grid_rgb[oy, ox] = np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)
            mask[oy, ox] = True
    return grid_rgb, mask


def _cleanup_isolated_fg(mask: np.ndarray, min_component: int = 8) -> np.ndarray:
    """清除异形抠底后的微小孤立噪点连通域。"""
    h, w = mask.shape
    visited = np.zeros((h, w), dtype=bool)
    out = np.zeros((h, w), dtype=bool)
    for r in range(h):
        for c in range(w):
            if not mask[r, c] or visited[r, c]:
                continue
            comp: list[tuple[int, int]] = []
            q = deque([(r, c)])
            visited[r, c] = True
            while q:
                cr, cc = q.popleft()
                comp.append((cr, cc))
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = cr + dr, cc + dc
                    if 0 <= nr < h and 0 <= nc < w and mask[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        q.append((nr, nc))
            if len(comp) >= min_component:
                for cr, cc in comp:
                    out[cr, cc] = True
    return out if out.any() else mask


def _apply_one_bead_outline(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    outline_idx: int,
) -> tuple[np.ndarray, np.ndarray]:
    """围绕有效豆子主体外侧生成 1 格 4-邻域深色描边。"""
    h, w = mask.shape
    new_mask = mask.copy()
    new_grid = idx_grid.copy()
    outline_coords: list[tuple[int, int]] = []
    for r in range(h):
        for c in range(w):
            if mask[r, c]:
                continue
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w and mask[nr, nc]:
                    outline_coords.append((r, c))
                    break
    for r, c in outline_coords:
        new_mask[r, c] = True
        new_grid[r, c] = outline_idx
    return new_grid, new_mask


def _extract_grid_reference_cells(rgba: np.ndarray, target_w: int, target_h: int) -> tuple[np.ndarray, np.ndarray]:
    """从网格参考图提取中心稳定色彩：先裁去底部字幕与白边，再取每格中心 50% 中位数。"""
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]
    # 若右下/底部存在明显全白字幕栏，从底部上扫裁剪白条
    h, w, _ = rgb.shape
    non_white = (np.min(rgb, axis=2) < 245) | (alpha < 250)
    if non_white.any():
        ys, xs = np.where(non_white)
        y0, y1 = max(0, int(ys.min()) - 2), min(h, int(ys.max()) + 3)
        x0, x1 = max(0, int(xs.min()) - 2), min(w, int(xs.max()) + 3)
        rgb = rgb[y0:y1, x0:x1]
        alpha = alpha[y0:y1, x0:x1]

    ch, cw, _ = rgb.shape
    grid_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    mask = np.zeros((target_h, target_w), dtype=bool)
    for oy in range(target_h):
        cy0 = oy * ch / target_h
        cy1 = (oy + 1) * ch / target_h
        sy0 = max(0, int(round(cy0 + 0.25 * (cy1 - cy0))))
        sy1 = min(ch, max(sy0 + 1, int(round(cy1 - 0.25 * (cy1 - cy0)))))
        for ox in range(target_w):
            cx0 = ox * cw / target_w
            cx1 = (ox + 1) * cw / target_w
            sx0 = max(0, int(round(cx0 + 0.25 * (cx1 - cx0))))
            sx1 = min(cw, max(sx0 + 1, int(round(cx1 - 0.25 * (cx1 - cx0)))))
            fg = alpha[sy0:sy1, sx0:sx1] >= 128
            if float(fg.mean()) < 0.4:
                continue
            med = np.median(rgb[sy0:sy1, sx0:sx1][fg], axis=0)
            grid_rgb[oy, ox] = np.clip(np.round(med), 0, 255).astype(np.uint8)
            mask[oy, ox] = True
    return grid_rgb, mask


def _pick_nearest_palette_idx(
    rgb: np.ndarray,
    full_pal_lab: np.ndarray,
    allowed_indices: list[int],
    used_set: set[int],
) -> int:
    """将目标混合色映射至最接近的允许色卡索引，并轻微偏好图纸已用颜色避免过度增色。"""
    lab = skcolor.rgb2lab((rgb.astype(np.float64) / 255.0).reshape(1, 1, 3)).reshape(1, 3)
    cand_labs = full_pal_lab[allowed_indices]
    dists = delta_e2000_matrix(lab, cand_labs).reshape(-1)
    # 若图纸已有极近色，略微减权优先复用已有色号
    adjusted = np.array(
        [d - (2.4 if allowed_indices[i] in used_set else 0.0) for i, d in enumerate(dists)],
        dtype=np.float64,
    )
    return allowed_indices[int(np.argmin(adjusted))]


def _smooth_round_eyes_and_aa(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    full_pal: list[dict[str, Any]],
    full_pal_lab: np.ndarray,
    code_to_idx: dict[str, int],
    allowed_indices: list[int],
) -> np.ndarray:
    """
    圆润大眼与圆形特征抗锯齿优化：
    1) 自动识别紧凑深色圆形/椭圆区域（眼睛、瞳孔、鼻头），过滤细长外描边与大块阴影；
    2) 削去生硬直角并收束核心圆弧，在外斜角 L 型凹槽自动填补约 44% 过渡抗锯齿珠；
    3) 对成对眼睛保留/点亮干净的 H1 纯白高光眼神光，消除像素锯齿与棱角感。
    """
    out = idx_grid.copy()
    h, w = out.shape
    if h < 12 or w < 12:
        return out

    pal_rgb = np.array([e["rgb"] for e in full_pal], dtype=np.float64)
    pal_lum = pal_rgb[:, 0] * 0.299 + pal_rgb[:, 1] * 0.587 + pal_rgb[:, 2] * 0.114
    lum_grid = np.where(mask, pal_lum[out], 255.0)
    used_set = {int(x) for x in out[mask]}

    dark_mask = mask & (lum_grid < 88.0)
    visited = np.zeros((h, w), dtype=bool)
    candidates: list[dict[str, Any]] = []

    for r in range(h):
        for c in range(w):
            if not dark_mask[r, c] or visited[r, c]:
                continue
            comp: list[tuple[int, int]] = []
            q: deque[tuple[int, int]] = deque([(r, c)])
            visited[r, c] = True
            while q:
                cr, cc = q.popleft()
                comp.append((cr, cc))
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < h and 0 <= nc < w and dark_mask[nr, nc] and not visited[nr, nc]:
                            visited[nr, nc] = True
                            q.append((nr, nc))

            if len(comp) < 1 or len(comp) > max(64, int(w * h * 0.055)):
                continue
            rs = [p[0] for p in comp]
            cs = [p[1] for p in comp]
            r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
            if r0 == 0 or r1 == h - 1 or c0 == 0 or c1 == w - 1:
                continue
            bh, bw = r1 - r0 + 1, c1 - c0 + 1
            if bh > max(11, int(h * 0.24)) or bw > max(11, int(w * 0.24)):
                continue
            if max(bh, bw) / max(1, min(bh, bw)) > 2.2:
                continue

            comp_set = set(comp)
            interior_bright: list[tuple[int, int]] = []
            touch_unmasked = 0
            for pr in range(r0, r1 + 1):
                for pc in range(c0, c1 + 1):
                    if (pr, pc) in comp_set:
                        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            nr, nc = pr + dr, pc + dc
                            if not (0 <= nr < h and 0 <= nc < w and mask[nr, nc]):
                                touch_unmasked += 1
                                break
                    elif mask[pr, pc] and lum_grid[pr, pc] >= 160.0:
                        dark_nbrs = sum(
                            1
                            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                            if (pr + dr, pc + dc) in comp_set
                        )
                        if dark_nbrs >= 3:
                            interior_bright.append((pr, pc))

            raw_fill = len(comp) / max(1, bh * bw)
            fill_ratio = (len(comp) + len(interior_bright)) / max(1, bh * bw)
            if raw_fill < 0.50 or fill_ratio < 0.54 or touch_unmasked > 1:
                continue

            comp_indices = [int(out[pr, pc]) for pr, pc in comp_set]
            dark_idx = max(set(comp_indices), key=lambda ix: (comp_indices.count(ix), -pal_lum[ix]))

            bg_rgbs: list[np.ndarray] = []
            bg_indices: list[int] = []
            ring_total = 0
            ring_bright = 0
            ring_lum_sum = 0.0
            for rr in range(max(0, r0 - 2), min(h, r1 + 3)):
                for cc in range(max(0, c0 - 2), min(w, c1 + 3)):
                    if not mask[rr, cc] or (rr, cc) in comp_set or (rr, cc) in interior_bright:
                        continue
                    lum = float(lum_grid[rr, cc])
                    ring_total += 1
                    ring_lum_sum += lum
                    if lum >= 115.0:
                        ring_bright += 1
                    if lum >= 95.0:
                        bg_rgbs.append(pal_rgb[int(out[rr, cc])])
                        bg_indices.append(int(out[rr, cc]))
            if not bg_rgbs or ring_total == 0:
                continue
            ring_bright_ratio = ring_bright / ring_total
            ring_avg_lum = ring_lum_sum / ring_total
            if len(comp) <= 2 and (ring_bright_ratio < 0.62 or ring_avg_lum < 125.0):
                continue

            candidates.append(
                {
                    "comp": comp_set,
                    "r0": r0,
                    "r1": r1,
                    "c0": c0,
                    "c1": c1,
                    "bh": bh,
                    "bw": bw,
                    "cy": (r0 + r1) / 2.0,
                    "cx": (c0 + c1) / 2.0,
                    "area": len(comp) + len(interior_bright),
                    "bright": interior_bright,
                    "ring_bright_ratio": ring_bright_ratio,
                    "ring_avg_lum": ring_avg_lum,
                    "dark_idx": dark_idx,
                    "dom_bg_idx": max(set(bg_indices), key=bg_indices.count),
                    "local_bg_rgb": np.median(np.array(bg_rgbs), axis=0),
                }
            )

    if not candidates:
        return out

    # 配对验证对称双眼，优先选择亮度对比最清晰、高度对齐最紧密的对组
    pair_scores: list[tuple[int, int, float]] = []
    for i, ci in enumerate(candidates):
        if ci["ring_bright_ratio"] < 0.50 or ci["cy"] > h * 0.74:
            continue
        for j in range(i + 1, len(candidates)):
            cj = candidates[j]
            if cj["ring_bright_ratio"] < 0.50 or cj["cy"] > h * 0.74:
                continue
            dy = abs(ci["cy"] - cj["cy"])
            dx = abs(ci["cx"] - cj["cx"])
            ratio = min(ci["area"], cj["area"]) / max(1, max(ci["area"], cj["area"]))
            if dy <= max(2.2, h * 0.055) and 3.0 <= dx <= w * 0.45 and ratio >= 0.25 and abs(ci["ring_avg_lum"] - cj["ring_avg_lum"]) <= 58.0:
                score = (ci["ring_bright_ratio"] + cj["ring_bright_ratio"]) * 10.0 - dy * 2.0 + min(ci["area"], cj["area"]) * 0.4
                pair_scores.append((i, j, score))
    pair_scores.sort(key=lambda x: -x[2])

    paired_used: set[int] = set()
    eye_pairs: list[tuple[int, int]] = []
    for i, j, _ in pair_scores:
        if i not in paired_used and j not in paired_used:
            paired_used.add(i)
            paired_used.add(j)
            eye_pairs.append((i, j))

    confirmed_eye_ids: set[int] = set()
    for i, j in eye_pairs:
        confirmed_eye_ids.add(i)
        confirmed_eye_ids.add(j)
    for i, ci in enumerate(candidates):
        if ci["bright"] and ci["area"] >= 6:
            confirmed_eye_ids.add(i)

    white_idx = code_to_idx.get("H1", allowed_indices[0])

    # 1) 成对眼睛执行尺寸、高度对齐与瞳孔色深等大对称校准
    for i, j in eye_pairs:
        ci, cj = candidates[i], candidates[j]
        left, right = (ci, cj) if ci["cx"] <= cj["cx"] else (cj, ci)
        shared_dark = left["dark_idx"] if pal_lum[left["dark_idx"]] <= pal_lum[right["dark_idx"]] else right["dark_idx"]
        dx = abs(left["cx"] - right["cx"])
        max_area = max(left["area"], right["area"])

        if max_area <= 4:
            th, tw = (1, 1) if (dx <= 5.2 or max_area <= 2) else (2, 2)
            same_row = abs(left["cy"] - right["cy"]) <= 1.15
            l_r = int(round((left["cy"] + right["cy"]) / 2.0)) if same_row else left["r0"]
            r_r = l_r if same_row else right["r0"]
            for feat_item, tc_r in ((left, l_r), (right, r_r)):
                for pr, pc in feat_item["comp"]:
                    if mask[pr, pc]:
                        out[pr, pc] = feat_item["dom_bg_idx"]
                rs0 = tc_r if th == 1 else int(round(tc_r - (th - 1) / 2.0))
                cs0 = int(round(feat_item["cx"])) if tw == 1 else int(round(feat_item["cx"] - (tw - 1) / 2.0))
                for dr in range(th):
                    for dc in range(tw):
                        rr, cc = rs0 + dr, cs0 + dc
                        if 0 <= rr < h and 0 <= cc < w and mask[rr, cc]:
                            out[rr, cc] = shared_dark
        else:
            target_h = max(3, int(round((left["bh"] + right["bh"]) / 2.0)))
            target_w = max(3, int(round((left["bw"] + right["bw"]) / 2.0)))
            same_row = abs(left["cy"] - right["cy"]) <= 1.15
            shared_cy = (left["cy"] + right["cy"]) / 2.0 if same_row else left["cy"]
            for feat_item, t_cy in ((left, shared_cy), (right, shared_cy if same_row else right["cy"])):
                for pr, pc in feat_item["comp"]:
                    if mask[pr, pc]:
                        out[pr, pc] = feat_item["dom_bg_idx"]
                r0 = max(1, min(h - target_h - 1, int(round(t_cy - (target_h - 1) / 2.0))))
                c0 = max(1, min(w - target_w - 1, int(round(feat_item["cx"] - (target_w - 1) / 2.0))))
                r1, c1 = r0 + target_h - 1, c0 + target_w - 1
                cy, cx = (r0 + r1) / 2.0, (c0 + c1) / 2.0
                ry, rx = max(1.0, target_h / 2.0), max(1.0, target_w / 2.0)
                core_set: set[tuple[int, int]] = set()
                for rr in range(r0, r1 + 1):
                    for cc in range(c0, c1 + 1):
                        if not mask[rr, cc]:
                            continue
                        if target_h == 3 and target_w == 3:
                            if rr in (r0, r1) and cc in (c0, c1):
                                continue
                            core_set.add((rr, cc))
                        elif ((rr - cy) / ry) ** 2 + ((cc - cx) / rx) ** 2 <= 0.90:
                            core_set.add((rr, cc))
                for rr, cc in core_set:
                    out[rr, cc] = shared_dark
                if target_h >= 5 and target_w >= 5:
                    for rr in range(max(0, r0 - 1), min(h, r1 + 2)):
                        for cc in range(max(0, c0 - 1), min(w, c1 + 2)):
                            if not mask[rr, cc] or (rr, cc) in core_set:
                                continue
                            ortho = sum(1 for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)) if (rr + dr, cc + dc) in core_set)
                            if ortho >= 2 and lum_grid[rr, cc] >= 95.0:
                                blend = 0.26 * pal_rgb[shared_dark] + 0.74 * feat_item["local_bg_rgb"]
                                aa_idx = _pick_nearest_palette_idx(blend, full_pal_lab, allowed_indices, used_set)
                                out[rr, cc] = aa_idx
                                used_set.add(aa_idx)
                if target_h >= 4 and target_w >= 4 and len(core_set) >= 10:
                    hr = max(r0, min(r1, int(round(cy - max(0.5, target_h * 0.22)))))
                    hc = max(c0, min(c1, int(round(cx - max(0.5, target_w * 0.22)))))
                    if (hr, hc) in core_set:
                        out[hr, hc] = white_idx

    # 2) 未成对的孤立大圆特征（如鼻头、侧颜单眼）走单独圆润化
    for cid, feat in enumerate(candidates):
        if cid in paired_used:
            continue
        bh, bw = feat["bh"], feat["bw"]
        if bh < 3 or bw < 3:
            continue
        r0, r1, c0, c1 = feat["r0"], feat["r1"], feat["c0"], feat["c1"]
        cy, cx = feat["cy"], feat["cx"]
        comp_set = feat["comp"]
        dark_idx = feat["dark_idx"]
        dark_rgb = pal_rgb[dark_idx]
        local_bg_rgb = feat["local_bg_rgb"]
        dom_bg_idx = feat["dom_bg_idx"]

        ry = max(1.0, bh / 2.0)
        rx = max(1.0, bw / 2.0)
        core_set = set()
        for rr in range(r0, r1 + 1):
            for cc in range(c0, c1 + 1):
                if not mask[rr, cc]:
                    continue
                if bh == 3 and bw == 3:
                    if (rr in (r0, r1)) and (cc in (c0, c1)):
                        continue
                    core_set.add((rr, cc))
                elif ((rr - cy) / ry) ** 2 + ((cc - cx) / rx) ** 2 <= 0.90:
                    core_set.add((rr, cc))
        if not core_set:
            continue

        preserved_bright = {pt for pt in feat["bright"] if pt in core_set}
        for rr, cc in core_set:
            if (rr, cc) not in preserved_bright:
                out[rr, cc] = dark_idx

        apply_soft_aa = (bh >= 5 and bw >= 5)
        for rr in range(max(0, r0 - 1), min(h, r1 + 2)):
            for cc in range(max(0, c0 - 1), min(w, c1 + 2)):
                if not mask[rr, cc] or (rr, cc) in core_set:
                    continue
                core_ortho = sum(1 for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)) if (rr + dr, cc + dc) in core_set)
                is_corner = (rr in (r0, r1)) and (cc in (c0, c1))
                if apply_soft_aa and (core_ortho >= 2 or (is_corner and (rr, cc) in comp_set and core_ortho >= 1)):
                    blend = 0.26 * dark_rgb + 0.74 * local_bg_rgb
                    aa_idx = _pick_nearest_palette_idx(blend, full_pal_lab, allowed_indices, used_set)
                    out[rr, cc] = aa_idx
                    used_set.add(aa_idx)
                elif (rr, cc) in comp_set:
                    out[rr, cc] = dom_bg_idx

        if cid in confirmed_eye_ids and (preserved_bright or (bh >= 4 and bw >= 4 and len(core_set) >= 10)):
            if preserved_bright:
                for br, bc in preserved_bright:
                    out[br, bc] = white_idx
            else:
                hr = max(r0, min(r1, int(round(cy - max(0.5, bh * 0.22)))))
                hc = max(c0, min(c1, int(round(cx - max(0.5, bw * 0.22)))))
                if (hr, hc) in core_set:
                    out[hr, hc] = white_idx

    return out


def convert_image(
    img: Image.Image,
    mode: str = "photo_fusion",
    target_w: int = 52,
    target_h: int = 52,
    max_colors: int = 18,
    suppress_green_cast: bool = True,
    smooth_eyes: bool = True,
    remove_bg: bool = False,
    add_outline: bool = False,
    outline_code: str = "H5",
    seed: int = 42,
) -> dict[str, Any]:
    """
    统一图像转拼豆网格入口：返回标准化的 MARD 221 网格 (`grid[r][c]`) 及统计信息。
    """
    tw = max(12, min(128, int(target_w)))
    th = max(12, min(128, int(target_h)))
    cap = max(4, min(48, int(max_colors)))
    clean_mode = mode if mode in ("photo_fusion", "cutout_outline", "grid_extract") else "photo_fusion"

    full_pal, code_to_entry, full_code_to_idx, full_pal_lab, _ = get_palette_maps()
    sub_pal_raw, sub_pal_lab, sub_de_mat = filter_palette_subset(suppress_green_cast=suppress_green_cast)
    # 兼容 legacy 量化函数（其内部会调用 entry["rgb"].astype(int)）
    sub_pal = [{**e, "rgb": np.array(e["rgb"], dtype=np.int16)} for e in sub_pal_raw]

    rgba_src = img.convert("RGBA")
    rgba_arr = np.array(rgba_src)
    if suppress_green_cast:
        rgba_arr = _neutralize_pale_green_cast(rgba_arr)

    if clean_mode == "grid_extract":
        grid_rgb, mask = _extract_grid_reference_cells(rgba_arr, tw, th)
        if remove_bg:
            # 去除最外圈近似纯白背景格（泛洪）
            visited = np.zeros((th, tw), dtype=bool)
            q: deque[tuple[int, int]] = deque()
            for r in range(th):
                for c in (0, tw - 1):
                    if mask[r, c] and not visited[r, c]:
                        visited[r, c] = True
                        q.append((r, c))
            for c in range(tw):
                for r in (0, th - 1):
                    if mask[r, c] and not visited[r, c]:
                        visited[r, c] = True
                        q.append((r, c))
            while q:
                r, c = q.popleft()
                if np.min(grid_rgb[r, c]) >= 238:
                    mask[r, c] = False
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < th and 0 <= nc < tw and mask[nr, nc] and not visited[nr, nc]:
                            visited[nr, nc] = True
                            q.append((nr, nc))
        # 直接 CIEDE2000 映射并限色
        fg_rgb = grid_rgb[mask].astype(np.float64) / 255.0
        idx_sub = np.zeros((th, tw), dtype=np.int32)
        if len(fg_rgb) > 0:
            fg_lab = skcolor.rgb2lab(fg_rgb.reshape(1, -1, 3)).reshape(-1, 3)
            dists = delta_e2000_matrix(fg_lab, sub_pal_lab)
            idx_sub[mask] = np.argmin(dists, axis=1).astype(np.int32)
        idx_sub = keep_exact_color_count_reduce(
            idx_sub,
            mask,
            sub_pal,
            sub_pal_lab,
            target_colors=cap,
            protected_codes={"H1", "H16", "H5"},
            pal_de_mat=sub_de_mat,
        )
    elif clean_mode == "cutout_outline":
        rgba_cut = _auto_remove_backdrop_rgba(rgba_arr)
        rgba_crop = _crop_to_foreground(rgba_cut, pad_ratio=0.02)
        margin = 1 if add_outline else 0
        rgba_canvas = _fit_rgba_to_canvas(rgba_crop, tw, th, margin=margin)
        grid_rgb, mask = _sample_tiles_exact(rgba_canvas, tw, th)
        mask = _cleanup_isolated_fg(mask, min_component=6)
        idx_sub, protected = pindou_studio_photo_quantize(
            grid_rgb,
            mask,
            sub_pal,
            sub_pal_lab,
            sub_de_mat,
            max_colors=cap,
            has_outer_alpha=True,
            seed=seed,
        )
        idx_sub = keep_exact_color_count_reduce(
            idx_sub,
            mask,
            sub_pal,
            sub_pal_lab,
            target_colors=cap,
            protected_codes=protected | {"H1", "H5"},
            pal_de_mat=sub_de_mat,
        )
    else:
        # photo_fusion
        if remove_bg:
            rgba_cut = _auto_remove_backdrop_rgba(rgba_arr)
            rgba_crop = _crop_to_foreground(rgba_cut, pad_ratio=0.02)
            margin = 1 if add_outline else 0
            rgba_canvas = _fit_rgba_to_canvas(rgba_crop, tw, th, margin=margin)
            has_alpha = True
        else:
            # 满格贴合，保留主体完整构图（按目标画布比例居中裁切到高分辨率，再做边缘感知采样）
            fit_pil = ImageOps.fit(
                Image.fromarray(rgba_arr, "RGBA"),
                (tw * 8, th * 8),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            rgba_canvas = np.array(fit_pil)
            has_alpha = False
        grid_rgb, mask = _sample_tiles_exact(rgba_canvas, tw, th)
        if not mask.any():
            mask[:, :] = True
        idx_sub, protected = pindou_studio_photo_quantize(
            grid_rgb,
            mask,
            sub_pal,
            sub_pal_lab,
            sub_de_mat,
            max_colors=cap,
            has_outer_alpha=has_alpha,
            seed=seed,
        )
        idx_sub = keep_exact_color_count_reduce(
            idx_sub,
            mask,
            sub_pal,
            sub_pal_lab,
            target_colors=cap,
            protected_codes=protected | {"H1"},
            pal_de_mat=sub_de_mat,
        )

    # 将 sub_pal 索引映射回全量 221 基准索引，方便统一描边与导出
    sub_to_full = np.array([full_code_to_idx[e["code"]] for e in sub_pal], dtype=np.int32)
    full_idx_grid = sub_to_full[idx_sub]

    if smooth_eyes and clean_mode != "grid_extract":
        full_idx_grid = _smooth_round_eyes_and_aa(
            full_idx_grid,
            mask,
            full_pal,
            full_pal_lab,
            full_code_to_idx,
            sub_to_full.tolist(),
        )

    if add_outline and bool((~mask).any()):
        out_code_norm = normalize_mard_code(outline_code) or "H5"
        outline_full_idx = full_code_to_idx.get(out_code_norm, full_code_to_idx["H5"])
        full_idx_grid, mask = _apply_one_bead_outline(full_idx_grid, mask, outline_full_idx)

    grid: list[list[str | None]] = []
    used_codes: set[str] = set()
    bead_count = 0
    for r in range(th):
        row_list: list[str | None] = []
        for c in range(tw):
            if mask[r, c]:
                code = full_pal[int(full_idx_grid[r, c])]["code"]
                row_list.append(code)
                used_codes.add(code)
                bead_count += 1
            else:
                row_list.append(None)
        grid.append(row_list)

    return {
        "width": tw,
        "height": th,
        "grid": grid,
        "mode": clean_mode,
        "bead_count": bead_count,
        "color_count": len(used_codes),
    }
