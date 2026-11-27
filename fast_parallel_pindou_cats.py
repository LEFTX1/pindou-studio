# -*- coding: utf-8 -*-
"""
三只猫咪照片双路精修并行拼豆生成引擎：
每张主图严格输出【2 套精修图纸 + 2 张真实烘烤成品预览图 = 4 张主输出图片】：
- 方案1 · 融合精修版（PindouStudio + PixelBeads 协同采样/量化 + 白毛色偏校正 + 五官圆润精修）
- 方案2 · AI 重绘精修版（AI 16-bit 像素底图升级高分辨率 + 外缘灰边清洗 + 五官圆润精修）
并发运行 3 张主图 × 2 套权威精修方案 = 6 项核心任务，全中文命名。
"""

import base64
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
import datetime
import io
import json
import os
from pathlib import Path
import re
import shutil
import time
import urllib.parse
import uuid

import numpy as np
from PIL import Image
from skimage import color as skcolor

from fast_parallel_pindou_engine import delta_e2000_matrix, keep_exact_color_count_reduce
from refined_two_track_helpers import (
    calibrate_cat4_calico_rgba,
    clean_exterior_grey_halo,
    export_crisp_grid_ref_for_chatgpt,
    generate_cat1_16bit_illustration,
    generate_cat3_16bit_illustration,
    generate_cat4_16bit_illustration,
    neutralize_white_cat_fur_rgba,
    refine_cat_face_and_details,
    render_baked_flat_melt_preview,
    super_resolve_lowres_rgba_if_needed,
)
from run_pathway_a_and_d import (
    load_palette,
    render_sheet_png,
    write_bom_csv,
)

PROJECT_ROOT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
INPUTS_DIR = PROJECT_ROOT / "inputs"
AI_SOURCES_DIR = INPUTS_DIR / "ai_sources"
AI_DIR = PROJECT_ROOT / "outputs" / "ai_redraw_cats"
SUMMARY_DIR = PROJECT_ROOT / "猫咪拼豆图纸汇总"
CHATGPT_REF_DIR = PROJECT_ROOT / "scratch" / "chatgpt_refs"
ARTIFACT_DIR = Path(r"C:\Users\Administrator\.gemini\antigravity\brain\8fc5a11e-ec61-4869-94de-2135da89f4d3")


def find_ai_image(prefix: str) -> Path:
    """查找 AI 像素重绘输出图片（支持 png / jpg / webp）。"""
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        cand = AI_DIR / f"{prefix}{ext}"
        if cand.exists():
            return cand
    matches = sorted(AI_DIR.glob(f"{prefix}*"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"未找到 AI 重绘图片: {AI_DIR / prefix}.*")


AI_FINISHED_PREFIXES: dict[tuple[str, str], str] = {
    ("cat1", "fusion_refined"): "cat1_fusion_baked_chatgpt",
    ("cat1", "ai_refined"): "cat1_ai_baked_chatgpt",
    ("cat2", "fusion_refined"): "cat2_fusion_baked_chatgpt",
    ("cat2", "ai_refined"): "cat2_ai_baked_chatgpt",
    ("cat3", "fusion_refined"): "cat3_fusion_baked_chatgpt",
    ("cat3", "ai_refined"): "cat3_ai_baked_chatgpt",
    ("cat4", "fusion_refined"): "cat4_fusion_baked_chatgpt",
    ("cat4", "ai_refined"): "cat4_ai_baked_chatgpt",
}


def find_ai_finished_preview(cat_id: str, kind: str) -> Path | None:
    """在产物目录中查找已生成并通过核验的 ChatGPT 真实烘烤成品实拍图（按时间戳取最新一张）。"""
    prefix = AI_FINISHED_PREFIXES.get((cat_id, kind))
    if not prefix:
        return None
    matches: list[Path] = []
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        matches.extend(ARTIFACT_DIR.glob(f"{prefix}_*{ext}"))
    if not matches:
        return None
    matches.sort(key=lambda p: p.name)
    return matches[-1]


def _weighted_median_channel(samples_rgb: np.ndarray, channel: int) -> int:
    vals = samples_rgb[:, channel]
    return int(np.round(np.median(vals)))


def _dominant_cluster_rgb(samples_rgb: np.ndarray) -> np.ndarray:
    """在 4-bit 量化桶中找占比最大的主色簇并返回各通道中位数。"""
    if samples_rgb.shape[0] == 1:
        return samples_rgb[0].astype(np.uint8)
    s_i32 = samples_rgb.astype(np.int32)
    keys = (s_i32[:, 0] >> 4) * 256 + (s_i32[:, 1] >> 4) * 16 + (s_i32[:, 2] >> 4)
    uniq, counts = np.unique(keys, return_counts=True)
    dom_key = uniq[int(np.argmax(counts))]
    cluster = samples_rgb[keys == dom_key]
    return np.array([
        _weighted_median_channel(cluster, 0),
        _weighted_median_channel(cluster, 1),
        _weighted_median_channel(cluster, 2),
    ], dtype=np.uint8)


def _representative_rgb(samples_rgb: np.ndarray, mode_kind: str = "bead") -> np.ndarray:
    """
    特征保留色簇代表提取（参考 image-to-pindou representative 逻辑）：
    保住黑色瞳孔与轮廓、白色高光眼珠点以及粉色/黄色等高饱和特征。
    """
    mode = _dominant_cluster_rgb(samples_rgb)
    lum = samples_rgb[:, 0] * 0.299 + samples_rgb[:, 1] * 0.587 + samples_rgb[:, 2] * 0.114
    mode_lum = float(mode[0] * 0.299 + mode[1] * 0.587 + mode[2] * 0.114)

    max_c = samples_rgb.max(axis=1).astype(np.float64)
    min_c = samples_rgb.min(axis=1).astype(np.float64)
    sat = np.where(max_c > 0, (max_c - min_c) / np.maximum(1.0, max_c), 0.0)
    mode_max = float(mode.max())
    mode_sat = (mode_max - float(mode.min())) / max(1.0, mode_max)

    n = samples_rgb.shape[0]
    dark_mask = lum <= min(72.0, mode_lum - 28.0)
    if mode_lum > 75.0 and float(dark_mask.sum()) / n >= 0.15:
        return _dominant_cluster_rgb(samples_rgb[dark_mask])

    # 保护黑眼中微小白色高光眼神点
    bright_mask = (lum >= 225.0) & (sat <= 0.18)
    if mode_lum < 155.0 and float(bright_mask.sum()) / n >= 0.12:
        return _dominant_cluster_rgb(samples_rgb[bright_mask])

    accent_mask = sat >= max(0.32, mode_sat + 0.15)
    if float(accent_mask.sum()) / n >= (0.18 if mode_kind == "cartoon" else 0.22):
        return _dominant_cluster_rgb(samples_rgb[accent_mask])

    return mode


def sample_photo_tiles(
    rgba: np.ndarray,
    longest_edge: int,
    force_square: int | None = None,
    mode: str = "edge_aware",
) -> tuple[np.ndarray, np.ndarray]:
    """
    对真实高分辨率照片进行 alpha 隔离的前景网格超采样，避免透明边缘混合发灰，
    并按 edge_aware / bead 模式在特征边缘保留高对比轮廓与高光。
    """
    src_h, src_w, _ = rgba.shape
    if force_square is not None:
        out_w, out_h = force_square, force_square
    else:
        if src_w >= src_h:
            out_w = longest_edge
            out_h = max(1, int(round(longest_edge * src_h / src_w)))
        else:
            out_h = longest_edge
            out_w = max(1, int(round(longest_edge * src_w / src_h)))

    avg_grid = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    rep_grid = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    mask = np.zeros((out_h, out_w), dtype=bool)

    rgb_all = rgba[:, :, :3]
    a_all = rgba[:, :, 3]

    rope_mask_grid = np.zeros((out_h, out_w), dtype=bool)
    rope_rgb_grid = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    catch_cand_grid = np.zeros((out_h, out_w), dtype=bool)
    catch_rgb_grid = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    dark_pupil_grid = np.zeros((out_h, out_w), dtype=bool)

    for oy in range(out_h):
        y0 = int(round(oy * src_h / out_h))
        y1 = max(y0 + 1, int(round((oy + 1) * src_h / out_h)))
        for ox in range(out_w):
            x0 = int(round(ox * src_w / out_w))
            x1 = max(x0 + 1, int(round((ox + 1) * src_w / out_w)))
            p_a = a_all[y0:y1, x0:x1]
            fg = p_a >= 128
            cov = float(fg.mean())
            if cov < 0.45:
                continue
            fg_px = rgb_all[y0:y1, x0:x1][fg]
            fg_f = fg_px.astype(np.float64)

            # 特征优先采样 1：黄绳（R>200, G>175, B<85 且格内占比 >= 0.16）
            rope_px = (fg_px[:, 0] > 200) & (fg_px[:, 1] > 175) & (fg_px[:, 2] < 85)
            if float(rope_px.mean()) >= 0.16:
                rope_mask_grid[oy, ox] = True
                rope_rgb_grid[oy, ox] = np.clip(np.round(np.median(fg_px[rope_px], axis=0)), 0, 255).astype(np.uint8)

            # 特征优先采样 2：深瞳孔 (min_lum < 60) 与 眼神高光纯白 (min(R,G,B) >= 245)
            lum_px = fg_f[:, 0] * 0.299 + fg_f[:, 1] * 0.587 + fg_f[:, 2] * 0.114
            if float(lum_px.min()) < 60.0:
                dark_pupil_grid[oy, ox] = True
            catch_px = np.min(fg_px, axis=1) >= 245
            if int(catch_px.sum()) >= 1:
                catch_cand_grid[oy, ox] = True
                catch_rgb_grid[oy, ox] = np.clip(np.round(fg_px[catch_px].mean(axis=0)), 0, 255).astype(np.uint8)

            # 线性光空间均值（避免暗部+亮部 sRGB 直接平均发灰）
            lin = np.where(
                fg_f / 255.0 <= 0.04045,
                (fg_f / 255.0) / 12.92,
                ((fg_f / 255.0 + 0.055) / 1.055) ** 2.4,
            ).mean(axis=0)
            srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * (np.maximum(lin, 0.0) ** (1.0 / 2.4)) - 0.055)
            avg_grid[oy, ox] = np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)
            rep_grid[oy, ox] = _representative_rgb(fg_px, mode_kind="bead" if mode != "edge_aware" else "cartoon")
            mask[oy, ox] = True

    feature_override = np.zeros((out_h, out_w), dtype=bool)
    for oy in range(out_h):
        for ox in range(out_w):
            if not mask[oy, ox]:
                continue
            if rope_mask_grid[oy, ox]:
                rep_grid[oy, ox] = rope_rgb_grid[oy, ox]
                avg_grid[oy, ox] = rope_rgb_grid[oy, ox]
                feature_override[oy, ox] = True
            elif catch_cand_grid[oy, ox]:
                y_a, y_b = max(0, oy - 1), min(out_h, oy + 2)
                x_a, x_b = max(0, ox - 1), min(out_w, ox + 2)
                if bool(dark_pupil_grid[y_a:y_b, x_a:x_b].any()):
                    rep_grid[oy, ox] = catch_rgb_grid[oy, ox]
                    avg_grid[oy, ox] = catch_rgb_grid[oy, ox]
                    feature_override[oy, ox] = True

    if mode == "bead":
        return rep_grid, mask

    # edge_aware: Lab 强突变邻域切换为特征代表色 rep_grid，渐变区域保持线性平均 avg_grid（特征优先格不覆盖）
    avg_lab = skcolor.rgb2lab(avg_grid.astype(np.float64) / 255.0)
    out_rgb = avg_grid.copy()
    for y in range(out_h):
        for x in range(out_w):
            if not mask[y, x] or feature_override[y, x]:
                continue
            strong_edge = False
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < out_h and 0 <= nx < out_w and mask[ny, nx]:
                    if np.linalg.norm(avg_lab[y, x] - avg_lab[ny, nx]) >= 9.0:
                        strong_edge = True
                        break
            if strong_edge:
                out_rgb[y, x] = rep_grid[y, x]
    return out_rgb, mask


def _refill_palette_to_exact_count(
    idx_grid: np.ndarray,
    grid_rgb: np.ndarray,
    mask: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
    target_colors: int,
    protect_map: np.ndarray | None = None,
) -> np.ndarray:
    """若量化与清理后色数低于目标色数，从高误差残留区按感知收益精确补足至 target_colors。"""
    fg_pos = np.argwhere(mask)
    if len(fg_pos) < target_colors:
        return idx_grid

    out = idx_grid.copy()
    cur_indices = np.array([int(out[r, c]) for r, c in fg_pos], dtype=np.int32)
    counts = Counter(cur_indices.tolist())
    if len(counts) >= target_colors:
        return out

    lab_fg = skcolor.rgb2lab(grid_rgb[mask].astype(np.float64) / 255.0)
    de_all = delta_e2000_matrix(lab_fg, pal_lab)
    n_fg = len(fg_pos)
    de_cur = de_all[np.arange(n_fg), cur_indices].copy()
    weight = (1.0 + 0.8 * protect_map[mask]) if protect_map is not None else np.ones(n_fg, dtype=np.float64)

    used = set(counts.keys())
    while len(used) < target_colors:
        gain_mat = np.maximum(0.0, de_cur[:, None] - de_all) * weight[:, None]
        gain_per_cand = np.sum(gain_mat, axis=0)
        for u in used:
            gain_per_cand[u] = -1.0

        best_cand = int(np.argmax(gain_per_cand))
        if gain_per_cand[best_cand] > 1e-6:
            improved = []
            for j in np.argsort(-gain_mat[:, best_cand]):
                if gain_mat[j, best_cand] <= 1e-6:
                    break
                old_c = int(cur_indices[j])
                if counts[old_c] > 1:
                    counts[old_c] -= 1
                    cur_indices[j] = best_cand
                    de_cur[j] = de_all[j, best_cand]
                    improved.append(j)
            if improved:
                counts[best_cand] = len(improved)
                used.add(best_cand)
                continue

        # 兜底：若现有颜色已经极贴近目标色板，从多格区域挑误差最小的未使用色号精准补 1 格
        eligible = np.array([counts[int(c)] > 1 for c in cur_indices], dtype=bool)
        if not eligible.any():
            break
        err_order = np.argsort(-(de_cur * weight))
        picked = False
        for si in err_order:
            if not eligible[si]:
                continue
            for cand_p in np.argsort(de_all[si]):
                cand_i = int(cand_p)
                if cand_i not in used:
                    old_c = int(cur_indices[si])
                    counts[old_c] -= 1
                    cur_indices[si] = cand_i
                    de_cur[si] = de_all[si, cand_i]
                    counts[cand_i] = 1
                    used.add(cand_i)
                    picked = True
                    break
            if picked:
                break
        if not picked:
            break

    for j, (r, c) in enumerate(fg_pos):
        out[r, c] = int(cur_indices[j])
    return out


def _auto_detect_feature_anchors(grid_rgb: np.ndarray, mask: np.ndarray, pal: list, pal_lab: np.ndarray) -> set[str]:
    """
    从实际照片网格中自动提取必须锁定的关键特征锚点色号：
    最黑瞳孔/深轮廓、最纯亮白/眼神光、高饱和红粉（鼻头/耳内）与高饱和金黄（麻绳）。
    """
    fg_rgb = grid_rgb[mask].astype(np.float64)
    fg_lab = skcolor.rgb2lab(fg_rgb / 255.0)
    lum = fg_rgb[:, 0] * 0.299 + fg_rgb[:, 1] * 0.587 + fg_rgb[:, 2] * 0.114
    chroma = fg_rgb.max(axis=1) - fg_rgb.min(axis=1)

    protected = set()
    # 1) 最暗瞳孔像素对应的 MARD 色号
    dark_idx = int(np.argmin(lum))
    if lum[dark_idx] < 65.0:
        de_dark = delta_e2000_matrix(fg_lab[dark_idx : dark_idx + 1], pal_lab)[0]
        protected.add(pal[int(np.argmin(de_dark))]["code"])

    # 2) 最亮纯白高光/白毛
    white_cands = np.where((lum >= 225.0) & (chroma <= 26.0))[0]
    if len(white_cands) > 0:
        w_best = white_cands[int(np.argmax(lum[white_cands]))]
        de_w = delta_e2000_matrix(fg_lab[w_best : w_best + 1], pal_lab)[0]
        protected.add(pal[int(np.argmin(de_w))]["code"])

    # 3) 显著高饱和粉/黄特征（取最饱和像素若占比较有意义）
    hi_sat = np.where(chroma >= 82.0)[0]
    if len(hi_sat) >= 2:
        top_s = hi_sat[np.argsort(-chroma[hi_sat])[:min(8, len(hi_sat))]]
        labs_s = fg_lab[top_s]
        de_s = delta_e2000_matrix(labs_s, pal_lab)
        best_p = [int(np.argmin(row)) for row in de_s]
        for p_idx, _ in Counter(best_p).most_common(2):
            protected.add(pal[p_idx]["code"])

    return protected


def pindou_studio_photo_quantize(
    grid_rgb: np.ndarray,
    mask: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
    pal_de_mat: np.ndarray,
    max_colors: int = 20,
    has_outer_alpha: bool = True,
    seed: int = 20261116,
) -> tuple[np.ndarray, set[str]]:
    """
    Aswellle/Pindou-Studio 针对实拍照片网格适配的 5 步科学量化算法：
    1) edgeStrength + saliency -> protection 保护图
    2) 中性锚点（黑眼/纯白）与高饱和（黄绳/粉鼻）锁定 + 加权 Lab K-means++
    3) CIEDE2000 映射至 MARD 221
    4) ICM 迭代条件模式空间平滑精炼
    5) 棋盘伪影抑制 + 保护型孤立豆清理 + 微岛清理 + 精准补齐目标色数
    """
    h, w, _ = grid_rgb.shape
    lab_img = skcolor.rgb2lab(grid_rgb.astype(np.float64) / 255.0)
    fg_labs = lab_img[mask]
    n_fg = fg_labs.shape[0]
    protected_codes = _auto_detect_feature_anchors(grid_rgb, mask, pal, pal_lab)

    # 1) 边缘强度 edgeStrength (95 分位归一化)
    edge_map = np.zeros((h, w), dtype=np.float64)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr = np.clip(np.arange(h) + dr, 0, h - 1)[:, None]
        cc = np.clip(np.arange(w) + dc, 0, w - 1)[None, :]
        nbr_mask = mask[rr, cc] & mask
        diff = np.where(nbr_mask, np.linalg.norm(lab_img - lab_img[rr, cc], axis=2), 0.0)
        edge_map = np.maximum(edge_map, diff)
    pos_vals = edge_map[mask & (edge_map > 0)]
    pivot = max(1e-6, float(np.percentile(pos_vals, 95)) if pos_vals.size > 0 else 1.0)
    edge_strength = np.where(mask, np.clip(edge_map / pivot, 0.0, 1.0), 0.0)

    # 2) 主体显著性 saliency
    bg_lab = np.array([100.0, 0.0, 0.0]) if has_outer_alpha else np.median(fg_labs, axis=0)
    ys, xs = np.mgrid[0:h, 0:w]
    center_prior = np.clip(
        1.0 - 0.65 * (np.abs(xs / max(1, w - 1) - 0.5) + np.abs(ys / max(1, h - 1) - 0.5)),
        0.0,
        1.0,
    )
    bg_dist_fg = np.minimum(1.0, delta_e2000_matrix(fg_labs, bg_lab[None, :])[:, 0] / 38.0)
    bg_dist = np.zeros((h, w), dtype=np.float64)
    bg_dist[mask] = bg_dist_fg
    raw_sal = np.where(mask, (0.52 * bg_dist + 0.48 * edge_strength) * center_prior, 0.0)
    saliency = raw_sal / max(1e-6, float(raw_sal.max()))
    protection = np.clip(0.5 * edge_strength + 0.5 * saliency, 0.0, 1.0)

    # 强化五官高反差极端点（最黑瞳孔 & 眼神亮斑）的 protection，防止 ICM/清理误伤
    lum_fg = grid_rgb[:, :, 0] * 0.299 + grid_rgb[:, :, 1] * 0.587 + grid_rgb[:, :, 2] * 0.114
    extreme_face = mask & ((lum_fg <= 48.0) | (lum_fg >= 242.0))
    protection[extreme_face] = np.maximum(protection[extreme_face], 0.72)

    # 3) 加权 Lab K-means++
    weights = 1.0 + 1.8 * edge_strength[mask] + 0.9 * saliency[mask]
    pal_euc = np.linalg.norm(fg_labs[:, None, :] - pal_lab[None, :, :], axis=2)
    pal_counts = np.bincount(np.argmin(pal_euc, axis=1), minlength=len(pal))

    lock_cands = []
    for p_idx, entry in enumerate(pal):
        ratio = pal_counts[p_idx] / max(1, n_fg)
        rp, gp, bp = map(int, entry["rgb"])
        is_neutral = (max(rp, gp, bp) <= 28 or min(rp, gp, bp) >= 235) and ratio >= 0.001
        is_accent = (max(rp, gp, bp) - min(rp, gp, bp) >= 135) and ratio >= 0.004
        is_prot = entry["code"] in protected_codes
        if is_prot or is_neutral or is_accent:
            lock_cands.append(((100000 if is_prot else 0) + pal_counts[p_idx], p_idx))
    lock_cands.sort(reverse=True)
    locked_indices = [idx for _, idx in lock_cands[:max_colors]]

    rng = np.random.default_rng(seed)
    centers = [fg_labs[int(rng.integers(0, n_fg))].copy()]
    while len(centers) < max_colors:
        c_arr = np.asarray(centers)
        d2 = np.min(np.sum((fg_labs[:, None, :] - c_arr[None, :, :]) ** 2, axis=2), axis=1)
        wd2 = d2 * weights
        tot = float(wd2.sum())
        picked = int(rng.integers(0, n_fg)) if tot <= 0 else int(rng.choice(n_fg, p=wd2 / tot))
        centers.append(fg_labs[picked].copy())
    centers = np.asarray(centers, dtype=np.float64)
    for _ in range(18):
        assign = np.argmin(np.sum((fg_labs[:, None, :] - centers[None, :, :]) ** 2, axis=2), axis=1)
        for ci in range(max_colors):
            sel = assign == ci
            if sel.any():
                w_sel = weights[sel][:, None]
                centers[ci] = np.sum(fg_labs[sel] * w_sel, axis=0) / float(w_sel.sum())

    de_c2p = delta_e2000_matrix(centers, pal_lab)
    mapped_pairs = sorted(
        [(float(de_c2p[ci, np.argmin(de_c2p[ci])]), int(np.argmin(de_c2p[ci]))) for ci in range(max_colors)],
        key=lambda x: x[0],
    )
    active_pal_indices = list(locked_indices)
    used_set = set(active_pal_indices)
    for _, p_idx in mapped_pairs:
        if p_idx not in used_set:
            active_pal_indices.append(p_idx)
            used_set.add(p_idx)
        if len(active_pal_indices) >= max_colors:
            break
    while len(active_pal_indices) < max_colors:
        sub_labs = pal_lab[active_pal_indices]
        cur_err = np.min(np.linalg.norm(fg_labs[:, None, :] - sub_labs[None, :, :], axis=2), axis=1) * weights
        added = False
        for s_i in np.argsort(-cur_err):
            cand_p = int(np.argmin(delta_e2000_matrix(fg_labs[s_i : s_i + 1], pal_lab)[0]))
            if cand_p not in used_set:
                active_pal_indices.append(cand_p)
                used_set.add(cand_p)
                added = True
                break
        if not added:
            break

    active_pal_indices = active_pal_indices[:max_colors]
    active_labs = pal_lab[active_pal_indices]
    de_grid_fg = delta_e2000_matrix(fg_labs, active_labs)
    de_act_pair = pal_de_mat[np.ix_(active_pal_indices, active_pal_indices)]

    fg_pos = np.argwhere(mask)
    local_idx = np.full((h, w), -1, dtype=np.int32)
    fg_lookup = np.full((h, w), -1, dtype=np.int32)
    init_best = np.argmin(de_grid_fg, axis=1)
    for fi, (r, c) in enumerate(fg_pos):
        local_idx[r, c] = int(init_best[fi])
        fg_lookup[r, c] = fi

    # 4) ICM 空间精炼
    spatial_weight = 0.12
    for _ in range(4):
        changed = 0
        next_idx = local_idx.copy()
        for r, c in fg_pos:
            fi = fg_lookup[r, c]
            nbrs = [
                int(local_idx[r + dr, c + dc])
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                if 0 <= r + dr < h and 0 <= c + dc < w and local_idx[r + dr, c + dc] >= 0
            ]
            if not nbrs:
                continue
            cands = set(nbrs) | {int(local_idx[r, c]), int(init_best[fi])}
            f_scale = 1.0 + 0.4 * float(protection[r, c])
            best_c, best_cost = int(local_idx[r, c]), 1e18
            for ci in cands:
                fid = float(de_grid_fg[fi, ci]) * f_scale
                smo = sum(float(de_act_pair[ci, n]) for n in nbrs if n != ci) / len(nbrs)
                tot_c = fid + spatial_weight * smo
                if tot_c < best_cost:
                    best_cost, best_c = tot_c, ci
            if best_c != local_idx[r, c]:
                next_idx[r, c] = best_c
                changed += 1
        local_idx = next_idx
        if changed == 0:
            break

    # 5) 保护型孤立豆清理 & 微岛清理 (跳过 protection > 0.55)
    counts_local = Counter(int(local_idx[r, c]) for r, c in fg_pos)
    cleaned = local_idx.copy()
    for r, c in fg_pos:
        cur = int(local_idx[r, c])
        if counts_local[cur] <= 1 or protection[r, c] > 0.55:
            continue
        nbrs = [
            int(local_idx[r + dr, c + dc])
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
            if 0 <= r + dr < h and 0 <= c + dc < w and local_idx[r + dr, c + dc] >= 0
        ]
        if len(nbrs) >= 2 and all(n != cur for n in nbrs):
            dom_c, dom_n = Counter(nbrs).most_common(1)[0]
            if dom_n >= (len(nbrs) + 1) // 2 and float(de_grid_fg[fg_lookup[r, c], dom_c]) < 8.0:
                cleaned[r, c] = dom_c
                counts_local[cur] -= 1
                counts_local[dom_c] += 1
    local_idx = cleaned

    visited = np.zeros((h, w), dtype=bool)
    cleaned2 = local_idx.copy()
    for r, c in fg_pos:
        if visited[r, c]:
            continue
        col = int(local_idx[r, c])
        comp = []
        q = deque([(r, c)])
        visited[r, c] = True
        while q:
            cr, cc = q.popleft()
            comp.append((cr, cc))
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = cr + dr, cc + dc
                if 0 <= nr < h and 0 <= nc < w and not visited[nr, nc] and local_idx[nr, nc] == col:
                    visited[nr, nc] = True
                    q.append((nr, nc))
        if len(comp) > 4 or counts_local[col] <= len(comp):
            continue
        if any(protection[cr, cc] > 0.55 for cr, cc in comp):
            continue
        bnd = Counter()
        bnd_tot = 0
        for cr, cc in comp:
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = cr + dr, cc + dc
                if 0 <= nr < h and 0 <= nc < w and local_idx[nr, nc] >= 0 and local_idx[nr, nc] != col:
                    bnd[int(local_idx[nr, nc])] += 1
                    bnd_tot += 1
        if bnd_tot > 0:
            dom_c, dom_n = bnd.most_common(1)[0]
            if dom_n >= (bnd_tot + 1) // 2 and all(float(de_grid_fg[fg_lookup[cr, cc], dom_c]) < 6.0 for cr, cc in comp):
                for cr, cc in comp:
                    cleaned2[cr, cc] = dom_c
                counts_local[col] -= len(comp)
                counts_local[dom_c] += len(comp)
    local_idx = cleaned2

    global_grid = np.zeros((h, w), dtype=np.int32)
    for r, c in fg_pos:
        global_grid[r, c] = active_pal_indices[int(local_idx[r, c])]
    global_grid = _refill_palette_to_exact_count(
        global_grid, grid_rgb, mask, pal, pal_lab, max_colors, protect_map=protection
    )
    return global_grid, protected_codes


def pixel_beads_quantize(
    grid_rgb: np.ndarray,
    mask: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
    pal_de_mat: np.ndarray,
    target_colors: int = 18,
) -> tuple[np.ndarray, set[str]]:
    """
    Pixel-Beads / image-to-pindou 均衡实拼量化：
    CIEDE2000 初配 -> 加权感知增益挑色（保黑眼/高光/黄绳等关键锚点）-> 微小杂区合并。
    """
    protected_codes = _auto_detect_feature_anchors(grid_rgb, mask, pal, pal_lab)
    fg_lab = skcolor.rgb2lab(grid_rgb[mask].astype(np.float64) / 255.0)
    de_fg = delta_e2000_matrix(fg_lab, pal_lab)
    best_fg = np.argmin(de_fg, axis=1)

    h, w, _ = grid_rgb.shape
    raw_grid = np.zeros((h, w), dtype=np.int32)
    raw_grid[mask] = best_fg

    counts = Counter(int(x) for x in best_fg)
    present = sorted(counts.keys())
    if len(present) > target_colors:
        code_to_idx = {e["code"]: i for i, e in enumerate(pal)}
        kept = []
        for pc in protected_codes:
            pi = code_to_idx[pc]
            if pi in counts and pi not in kept:
                kept.append(pi)
        most_common = [p for p, _ in counts.most_common() if p not in kept]
        if not kept and most_common:
            kept.append(most_common.pop(0))

        # 基于 weighted perceptual error reduction 贪心挑选其余保留色号
        while len(kept) < min(target_colors, len(present)):
            cur_min = np.min(pal_de_mat[np.ix_(present, kept)], axis=1)
            best_cand, best_gain = None, -1.0
            for cand in present:
                if cand in kept:
                    continue
                after = np.minimum(cur_min, pal_de_mat[present, cand])
                gain = sum(counts[p] * (float(cur_min[i]) ** 2 - float(after[i]) ** 2) for i, p in enumerate(present))
                if gain > best_gain:
                    best_gain, best_cand = gain, cand
            if best_cand is None:
                break
            kept.append(best_cand)

        remap = {p: kept[int(np.argmin(pal_de_mat[p, kept]))] for p in present}
        for r in range(h):
            for c in range(w):
                if mask[r, c]:
                    raw_grid[r, c] = remap[int(raw_grid[r, c])]

    # 轻度清理 <= 2 格碎片（保护小高光/瞳孔锚点）
    final_grid = keep_exact_color_count_reduce(
        raw_grid, mask, pal, pal_lab, target_colors, protected_codes, pal_de_mat=pal_de_mat
    )
    final_grid = _refill_palette_to_exact_count(
        final_grid, grid_rgb, mask, pal, pal_lab, target_colors
    )
    return final_grid, protected_codes


def export_pindou_json(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    src_img_path: Path,
    name: str,
    out_json: Path,
) -> None:
    """导出兼容 Pin Dou / image-to-pindou 的可编辑 .pindou.json (schemaVersion 4)。"""
    h, w = idx_grid.shape
    used_codes = sorted({pal[int(idx_grid[r, c])]["code"] for r in range(h) for c in range(w) if mask[r, c]})
    code_to_one_based = {code: i + 1 for i, code in enumerate(used_codes)}
    size = 1 if len(used_codes) < 255 else 2
    buf = bytearray(h * w * size)
    for r in range(h):
        for c in range(w):
            idx = r * w + c
            val = code_to_one_based[pal[int(idx_grid[r, c])]["code"]] if mask[r, c] else 0
            if size == 1:
                buf[idx] = val
            else:
                buf[2 * idx] = val & 255
                buf[2 * idx + 1] = val >> 8

    png_bytes = io.BytesIO()
    Image.open(src_img_path).convert("RGBA").save(png_bytes, format="PNG")
    src_b64 = base64.b64encode(png_bytes.getvalue()).decode("ascii")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    payload = {
        "schemaVersion": 4,
        "exportedAt": now,
        "sources": [f"data:image/png;base64,{src_b64}"],
        "projects": [
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "createdAt": now,
                "updatedAt": now,
                "sourceName": src_img_path.name,
                "source": 0,
                "transform": {"rotation": 0, "flipX": False, "flipY": False, "zoom": 1, "offsetX": 0, "offsetY": 0},
                "settings": {
                    "longestEdge": max(w, h),
                    "maxColors": len(used_codes),
                    "paletteSize": 221,
                    "excludedColorIds": [],
                    "processingMode": "dominant",
                    "colorMerge": 5,
                    "background": "plain",
                    "mirror": False,
                    "mode": "local",
                },
                "pattern": {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "createdAt": now,
                    "snapshot": {
                        "w": w,
                        "h": h,
                        "c": {"p": used_codes, "d": base64.b64encode(bytes(buf)).decode("ascii"), "s": size},
                        "o": {"x": 0, "y": 0, "width": w, "height": h},
                    },
                },
            }
        ],
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def ai_redraw_photo_quantize(
    ai_path: Path,
    pal: list,
    pal_lab: np.ndarray,
    pal_de_mat: np.ndarray,
    longest_edge: int,
    force_square: int | None,
    strip_outer_white: bool,
    target_colors: int = 16,
) -> tuple[np.ndarray, np.ndarray, set[str]]:
    """
    AI 16-bit 像素重绘 -> 精确拼豆网格：
    对白底主体（图一/图三）在全分辨率做边界连通纯白洪水清洗并裁紧主体边界框，
    再仅对前景做 2 聚类主色重采样；对满幅猫脸（图二）保留完整画面直接重采样。
    """
    hi_rgb = np.array(Image.open(ai_path).convert("RGB"), dtype=np.int16)
    h_hi, w_hi, _ = hi_rgb.shape

    if strip_outer_white:
        max_c = hi_rgb.max(axis=2)
        min_c = hi_rgb.min(axis=2)
        is_white = (min_c >= 230) & ((max_c - min_c) <= 24)
        bg_hi = np.zeros((h_hi, w_hi), dtype=bool)
        q = deque()
        for x in range(w_hi):
            for y in (0, h_hi - 1):
                if is_white[y, x] and not bg_hi[y, x]:
                    bg_hi[y, x] = True
                    q.append((y, x))
        for y in range(1, h_hi - 1):
            for x in (0, w_hi - 1):
                if is_white[y, x] and not bg_hi[y, x]:
                    bg_hi[y, x] = True
                    q.append((y, x))
        while q:
            cy, cx = q.popleft()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h_hi and 0 <= nx < w_hi and not bg_hi[ny, nx] and is_white[ny, nx]:
                    bg_hi[ny, nx] = True
                    q.append((ny, nx))
        fg_hi = ~bg_hi
        ys, xs = np.where(fg_hi)
        if len(ys) > 0:
            y0c, y1c = max(0, int(ys.min()) - 2), min(h_hi, int(ys.max()) + 3)
            x0c, x1c = max(0, int(xs.min()) - 2), min(w_hi, int(xs.max()) + 3)
            hi_rgb = hi_rgb[y0c:y1c, x0c:x1c].copy()
            fg_hi = fg_hi[y0c:y1c, x0c:x1c]
            h_hi, w_hi, _ = hi_rgb.shape
            # AI 重绘主体内部纯白提纯（让白色猫身更易映射到清澈 H1 纯白）
            hi_min = hi_rgb.min(axis=2)
            hi_max = hi_rgb.max(axis=2)
            inner_white = (
                fg_hi
                & (hi_min >= 234)
                & ((hi_max - hi_min) <= 20)
                & ~(hi_rgb[:, :, 2].astype(np.int16) > hi_rgb[:, :, 0].astype(np.int16) + 10)
            )
            hi_rgb[inner_white] = [255, 255, 255]
    else:
        fg_hi = np.ones((h_hi, w_hi), dtype=bool)

    if force_square is not None:
        out_w, out_h = force_square, force_square
    else:
        if w_hi >= h_hi:
            out_w = longest_edge
            out_h = max(1, int(round(longest_edge * h_hi / w_hi)))
        else:
            out_h = longest_edge
            out_w = max(1, int(round(longest_edge * w_hi / h_hi)))

    grid_rgb = np.full((out_h, out_w, 3), 255, dtype=np.uint8)
    mask = np.zeros((out_h, out_w), dtype=bool)

    for oy in range(out_h):
        y0 = int(round(oy * h_hi / out_h))
        y1 = max(y0 + 1, int(round((oy + 1) * h_hi / out_h)))
        for ox in range(out_w):
            x0 = int(round(ox * w_hi / out_w))
            x1 = max(x0 + 1, int(round((ox + 1) * w_hi / out_w)))
            p_fg = fg_hi[y0:y1, x0:x1]
            if float(p_fg.mean()) < 0.45:
                continue
            fg_px = hi_rgb[y0:y1, x0:x1][p_fg].astype(np.float64)
            var = float(np.mean(np.var(fg_px, axis=0)))
            if var > 420.0 and fg_px.shape[0] >= 4:
                avg = fg_px.mean(axis=0)
                c1 = avg
                c2 = fg_px[int(np.argmax(np.sum((fg_px - avg) ** 2, axis=1)))]
                for _ in range(3):
                    d1 = np.sum((fg_px - c1) ** 2, axis=1)
                    d2 = np.sum((fg_px - c2) ** 2, axis=1)
                    s1 = d1 <= d2
                    if s1.any():
                        c1 = fg_px[s1].mean(axis=0)
                    if (~s1).any():
                        c2 = fg_px[~s1].mean(axis=0)
                chosen = c1 if int(s1.sum()) >= int((~s1).sum()) else c2
            else:
                chosen = fg_px.mean(axis=0)
            grid_rgb[oy, ox] = np.clip(np.round(chosen), 0, 255).astype(np.uint8)
            mask[oy, ox] = True

    protected = _auto_detect_feature_anchors(grid_rgb, mask, pal, pal_lab)
    fg_lab = skcolor.rgb2lab(grid_rgb[mask].astype(np.float64) / 255.0)
    idx_grid = np.zeros((out_h, out_w), dtype=np.int32)
    idx_grid[mask] = np.argmin(delta_e2000_matrix(fg_lab, pal_lab), axis=1)
    idx_grid = keep_exact_color_count_reduce(
        idx_grid, mask, pal, pal_lab, target_colors, protected, pal_de_mat=pal_de_mat
    )
    return idx_grid, mask, protected


def bfs_beginner_photo_quantize(
    grid_rgb: np.ndarray,
    mask: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
    pal_de_mat: np.ndarray,
    target_colors: int = 14,
) -> tuple[np.ndarray, set[str]]:
    """新手极简版：CIEDE2000 映射 + BFS 孤岛/小区块平滑 + 低损收敛至 14~15 色。"""
    protected = _auto_detect_feature_anchors(grid_rgb, mask, pal, pal_lab)
    fg_lab = skcolor.rgb2lab(grid_rgb[mask].astype(np.float64) / 255.0)
    h, w, _ = grid_rgb.shape
    idx_grid = np.zeros((h, w), dtype=np.int32)
    idx_grid[mask] = np.argmin(delta_e2000_matrix(fg_lab, pal_lab), axis=1)

    # 先清理 1~2 格低对比噪点岛
    visited = np.zeros((h, w), dtype=bool)
    out = idx_grid.copy()
    for r in range(h):
        for c in range(w):
            if not mask[r, c] or visited[r, c]:
                continue
            col = int(out[r, c])
            comp = []
            nbrs = Counter()
            q = deque([(r, c)])
            visited[r, c] = True
            while q:
                cr, cc = q.popleft()
                comp.append((cr, cc))
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = cr + dr, cc + dc
                    if 0 <= nr < h and 0 <= nc < w and mask[nr, nc]:
                        ncol = int(out[nr, nc])
                        if ncol == col:
                            if not visited[nr, nc]:
                                visited[nr, nc] = True
                                q.append((nr, nc))
                        else:
                            nbrs[ncol] += 1
            if len(comp) <= 2 and nbrs and pal[col]["code"] not in protected:
                best_n = max(nbrs.items(), key=lambda kv: kv[1] * 10 - float(pal_de_mat[col, kv[0]]))[0]
                if float(pal_de_mat[col, best_n]) <= 18.0:
                    for cr, cc in comp:
                        out[cr, cc] = best_n

    out = keep_exact_color_count_reduce(
        out, mask, pal, pal_lab, target_colors, protected, pal_de_mat=pal_de_mat
    )
    out = _refill_palette_to_exact_count(
        out, grid_rgb, mask, pal, pal_lab, target_colors
    )
    return out, protected


def run_single_cat_task(task: dict) -> dict:
    """独立进程运行单张猫咪 × 单途径任务。"""
    t0 = time.perf_counter()
    pal, pal_lab = load_palette()
    pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)

    cat_id = task["cat_id"]
    cat_zh = task["cat_zh"]
    kind = task["kind"]
    stem = task["stem"]
    out_dir = Path(task["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    aux_dir = out_dir / "辅助_采购清单与可编辑工程"
    aux_dir.mkdir(parents=True, exist_ok=True)
    src_path = Path(task["src_path"])

    if kind == "fusion_refined":
        rgba = np.array(Image.open(src_path).convert("RGBA"))
        if cat_id == "cat4":
            rgba = calibrate_cat4_calico_rgba(rgba)
        else:
            rgba = super_resolve_lowres_rgba_if_needed(rgba, min_dim_threshold=220, has_white_caption=False)
            if cat_id in ("cat1", "cat3"):
                rgba = neutralize_white_cat_fur_rgba(rgba, cat_id)
        grid_edge, mask = sample_photo_tiles(
            rgba, longest_edge=task["size"], force_square=task["force_square"], mode="edge_aware"
        )
        grid_bead, _ = sample_photo_tiles(
            rgba, longest_edge=task["size"], force_square=task["force_square"], mode="bead"
        )
        diff = np.max(np.abs(grid_edge.astype(np.int16) - grid_bead.astype(np.int16)), axis=2)
        blend = np.round(0.65 * grid_edge.astype(np.float32) + 0.35 * grid_bead.astype(np.float32)).astype(np.uint8)
        grid_fused = np.where(diff[:, :, None] < 40, blend, grid_edge)

        q_colors = max(12, task["colors"] - 2) if cat_id in ("cat3", "cat4") else task["colors"]
        idx_grid, _ = pindou_studio_photo_quantize(
            grid_fused, mask, pal, pal_lab, pal_de_mat,
            max_colors=q_colors, has_outer_alpha=task["has_outer_alpha"]
        )
        idx_grid = refine_cat_face_and_details(cat_id, "fusion_refined", idx_grid, mask, pal)
        if cat_id in ("cat3", "cat4"):
            prot_f = {"H1", "H2", "H7", "H16", "M15", "M2", "F14", "M14", "G13", "H5", "H6"}
            idx_grid = keep_exact_color_count_reduce(
                idx_grid, mask, pal, pal_lab, task["colors"], prot_f, pal_de_mat=pal_de_mat
            )
        title = f"{cat_zh} · 方案1：PindouStudio × PixelBeads 融合精修版"
        if cat_id == "cat4":
            subtitle = f"4x超分降噪 + 竖向椭圆瞳孔 + '干嘛......'锐化精修 · MARD {task['colors']}色"
        elif cat_id == "cat2":
            subtitle = f"4x超分降噪 + 双引擎协同采样 + 五官圆润高光精修 · MARD {task['colors']}色"
        else:
            subtitle = f"双引擎协同采样 + 白毛暖偏校正 + 五官圆润高光精修 · MARD {task['colors']}色"
    elif kind == "ai_refined":
        ai_path = find_ai_image(task["ai_prefix"])
        q_colors = max(12, task["colors"] - 2) if cat_id in ("cat3", "cat4") else task["colors"]
        idx_grid, mask, _ = ai_redraw_photo_quantize(
            ai_path, pal, pal_lab, pal_de_mat,
            longest_edge=task["size"], force_square=task["force_square"],
            strip_outer_white=task["strip_outer_white"], target_colors=q_colors
        )
        if cat_id == "cat3":
            idx_grid, mask = clean_exterior_grey_halo(idx_grid, mask, pal)
        idx_grid = refine_cat_face_and_details(
            cat_id, "ai_refined", idx_grid, mask, pal, source_pixel_path=ai_path
        )
        if cat_id in ("cat3", "cat4"):
            prot_a = {"H1", "H2", "H10", "H11", "H7", "H16", "M15", "M2", "F14", "M14", "G13", "H5", "H6"}
            idx_grid = keep_exact_color_count_reduce(
                idx_grid, mask, pal, pal_lab, task["colors"], prot_a, pal_de_mat=pal_de_mat
            )
        title = f"{cat_zh} · 方案2：AI 像素重绘高精精修版"
        if cat_id == "cat4":
            subtitle = f"4x超分 + 16-bit高清重绘 + 椭圆瞳孔与'干嘛......'精修 · MARD {task['colors']}色"
        else:
            subtitle = f"16-bit 高清网格升级 + 消除菱角眼重绘圆瞳高光 · MARD {task['colors']}色"
    else:
        raise ValueError(f"Unknown kind: {kind}")

    pindou_json_path = aux_dir / f"{stem}.pindou.json"
    export_pindou_json(idx_grid, mask, pal, src_path, stem, pindou_json_path)

    sheet_png = out_dir / f"{stem}_图纸.png"
    bom_csv = aux_dir / f"{stem}_采购清单.csv"

    bom, total_beads = render_sheet_png(
        idx_grid, mask, pal, title, subtitle, sheet_png, cell_px=34, palette_name="MARD"
    )
    write_bom_csv(bom, total_beads, pal, bom_csv, palette_name="MARD")

    CHATGPT_REF_DIR.mkdir(parents=True, exist_ok=True)
    grid_ref_png = CHATGPT_REF_DIR / f"{cat_id}_{kind}_grid_ref.png"
    export_crisp_grid_ref_for_chatgpt(idx_grid, mask, pal, grid_ref_png, cell_px=12)

    phys_baked_jpg = CHATGPT_REF_DIR / f"{cat_id}_{kind}_phys_baked.jpg"
    render_baked_flat_melt_preview(idx_grid, mask, pal, phys_baked_jpg, cell_px=18, seed=42)

    chatgpt_src = find_ai_finished_preview(cat_id, kind)
    if chatgpt_src is not None:
        preview_png = out_dir / f"{stem}_烘烤成品预览图{chatgpt_src.suffix.lower()}"
        shutil.copy2(chatgpt_src, preview_png)
        shutil.copy2(phys_baked_jpg, aux_dir / f"{stem}_物理烘烤模拟图.jpg")
        preview_source = "chatgpt"
    else:
        preview_png = out_dir / f"{stem}_烘烤成品预览图.jpg"
        shutil.copy2(phys_baked_jpg, preview_png)
        preview_source = "physics"

    h, w = idx_grid.shape
    return {
        "cat_id": cat_id,
        "cat_zh": cat_zh,
        "kind": kind,
        "stem": stem,
        "grid": f"{w}×{h}",
        "colors": len(bom),
        "beads": total_beads,
        "elapsed": time.perf_counter() - t0,
        "sheet_png": str(sheet_png),
        "preview_png": str(preview_png),
        "preview_source": preview_source,
        "grid_ref_png": str(grid_ref_png),
        "bom_csv": str(bom_csv),
        "pindou_json": str(pindou_json_path),
    }


def uri(path: Path | str) -> str:
    return "file:///" + str(path).replace("\\", "/")


def slash(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def build_tasks() -> list[dict]:
    """构建 3 张主图 × 2 套精修方案 = 6 项核心并发任务（每张输入图严格对应 4 张主输出图片）。"""
    cat1_src = INPUTS_DIR / "cat1_cat_and_box.png"
    cat2_full = INPUTS_DIR / "cat2_full_face.png"
    cat3_src = INPUTS_DIR / "cat3_cat_with_bedsheet_edge.png"
    cat4_src = INPUTS_DIR / "cat4_calico_face.png"

    d1 = SUMMARY_DIR / "01_图一_箱子小猫_2套精修4图"
    d2 = SUMMARY_DIR / "02_图二_完整猫脸_2套精修4图"
    d3 = SUMMARY_DIR / "03_图三_床单小猫_2套精修4图"
    d4 = SUMMARY_DIR / "04_图四_干嘛三花猫_2套精修4图"

    return [
        # --- 图一：小猫加箱子（88格融合精修 + 92格 AI重绘精修，确保猫耳猫眼与纸箱波浪边完整圆润） ---
        {"cat_id": "cat1", "cat_zh": "图一_箱子小猫", "kind": "fusion_refined", "out_dir": str(d1),
         "stem": "图一_箱子小猫_方案1_融合精修版_88格_MARD20色",
         "src_path": str(cat1_src), "size": 88, "force_square": None, "colors": 20, "has_outer_alpha": False},
        {"cat_id": "cat1", "cat_zh": "图一_箱子小猫", "kind": "ai_refined", "out_dir": str(d1),
         "stem": "图一_箱子小猫_方案2_AI重绘精修版_92格_MARD16色",
         "src_path": str(cat1_src), "ai_prefix": "cat1_ai_pixel", "size": 92, "force_square": None, "colors": 16, "strip_outer_white": True},

        # --- 图二：完整猫脸（双版本均升级至 72×72，锁定双目对称 2×2 纯白眼神光与平滑猫嘴曲线） ---
        {"cat_id": "cat2", "cat_zh": "图二_完整猫脸", "kind": "fusion_refined", "out_dir": str(d2),
         "stem": "图二_完整猫脸_方案1_融合精修版_72x72_MARD18色",
         "src_path": str(cat2_full), "size": 72, "force_square": 72, "colors": 18, "has_outer_alpha": False},
        {"cat_id": "cat2", "cat_zh": "图二_完整猫脸", "kind": "ai_refined", "out_dir": str(d2),
         "stem": "图二_完整猫脸_方案2_AI重绘精修版_72x72_MARD16色",
         "src_path": str(cat2_full), "ai_prefix": "cat2_ai_pixel", "size": 72, "force_square": 72, "colors": 16, "strip_outer_white": False},

        # --- 图三：单独小猫加边缘床单（94格 / 96格横版升级，消除方眼横条并去除外圈抗锯齿灰边） ---
        {"cat_id": "cat3", "cat_zh": "图三_床单小猫", "kind": "fusion_refined", "out_dir": str(d3),
         "stem": "图三_床单小猫_方案1_融合精修版_94格横版_MARD20色",
         "src_path": str(cat3_src), "size": 94, "force_square": None, "colors": 20, "has_outer_alpha": False},
        {"cat_id": "cat3", "cat_zh": "图三_床单小猫", "kind": "ai_refined", "out_dir": str(d3),
         "stem": "图三_床单小猫_方案2_AI重绘精修版_96格横版_MARD16色",
         "src_path": str(cat3_src), "ai_prefix": "cat3_ai_pixel", "size": 96, "force_square": None, "colors": 16, "strip_outer_white": False},
        {"cat_id": "cat4", "cat_zh": "图四_干嘛三花猫", "kind": "fusion_refined", "out_dir": str(d4),
         "stem": "图四_干嘛三花猫_方案1_融合精修版_92格横版_MARD20色",
         "src_path": str(cat4_src), "size": 92, "force_square": None, "colors": 20, "has_outer_alpha": False},
        {"cat_id": "cat4", "cat_zh": "图四_干嘛三花猫", "kind": "ai_refined", "out_dir": str(d4),
         "stem": "图四_干嘛三花猫_方案2_AI重绘精修版_96格横版_MARD16色",
         "src_path": str(cat4_src), "ai_prefix": "cat4_ai_pixel", "size": 96, "force_square": None, "colors": 16, "strip_outer_white": False},
    ]


def main():
    t_wall0 = time.perf_counter()
    if SUMMARY_DIR.exists():
        shutil.rmtree(SUMMARY_DIR)
    raw_dir = SUMMARY_DIR / "00_主体提取原图与AI重绘底图"
    for d in (
        SUMMARY_DIR,
        raw_dir,
        SUMMARY_DIR / "01_图一_箱子小猫_2套精修4图",
        SUMMARY_DIR / "02_图二_完整猫脸_2套精修4图",
        SUMMARY_DIR / "03_图三_床单小猫_2套精修4图",
        SUMMARY_DIR / "04_图四_干嘛三花猫_2套精修4图",
    ):
        d.mkdir(parents=True, exist_ok=True)

    # 提前生成图一/图三/图四升级版灵魂眼神高清像素底图，避免子进程竞争写入
    src_ai1 = AI_SOURCES_DIR / "gemini_cat1_soul_v2_attempt3_1794819258783.jpg"
    if src_ai1.exists():
        generate_cat1_16bit_illustration(src_ai1, AI_DIR / "cat1_ai_pixel.png")
    src_ai3 = AI_SOURCES_DIR / "gemini_cat3_soul_v2_1794819131185.jpg"
    if src_ai3.exists():
        generate_cat3_16bit_illustration(src_ai3, AI_DIR / "cat3_ai_pixel.png", grid_w=96)
    src_ai4 = AI_SOURCES_DIR / "gemini_cat4_fullbleed_v3_1794818414044.jpg"
    ai4 = AI_DIR / "cat4_ai_pixel.png"
    generate_cat4_16bit_illustration(
        INPUTS_DIR / "cat4_calico_face.png", ai4, grid_w=96, grid_h=88,
        ai_src_path=src_ai4 if src_ai4.exists() else None,
    )

    # 复制区域截取原图与 AI 重绘底图到 00 目录（全中文命名）
    ai1 = find_ai_image("cat1_ai_pixel")
    ai2 = find_ai_image("cat2_ai_pixel")
    ai3 = find_ai_image("cat3_ai_pixel")
    raw_items = [
        (INPUTS_DIR / "previews" / "cat1_cat_and_box_white_preview.png", "图一_小猫加箱子_矩形区域截取原图.png", "图一 · 小猫加箱子（矩形区域截取，无切边）"),
        (ai1, f"图一_小猫加箱子_AI像素重绘底图{ai1.suffix.lower()}", "图一 · AI 16-bit 像素重绘底图"),
        (INPUTS_DIR / "cat2_full_face.png", "图二_完整猫脸_降噪满幅原图.png", "图二 · 完整猫脸降噪原图"),
        (ai2, f"图二_完整猫脸_AI像素重绘底图{ai2.suffix.lower()}", "图二 · AI 16-bit 像素重绘底图"),
        (INPUTS_DIR / "previews" / "cat3_cat_with_bedsheet_edge_white_preview.png", "图三_单独小猫加边缘床单_区域截取原图.png", "图三 · 小猫加边缘床单（矩形区域截取，无切边）"),
        (ai3, f"图三_单独小猫加边缘床单_AI像素重绘底图{ai3.suffix.lower()}", "图三 · AI 16-bit 像素重绘底图"),
        (INPUTS_DIR / "cat4_calico_face.png", "图四_干嘛三花猫_原始图.png", "图四 · 干嘛三花猫原图（生成前已自动 4x 超分重建）"),
        (ai4, f"图四_干嘛三花猫_AI像素重绘底图{ai4.suffix.lower()}", "图四 · 4x 超分 + 16-bit 像素重绘底图"),
    ]
    raw_entries = []
    for src, dst_name, lbl in raw_items:
        dst_s = raw_dir / dst_name
        dst_a = ARTIFACT_DIR / dst_name
        shutil.copy2(src, dst_s)
        shutil.copy2(src, dst_a)
        raw_entries.append((lbl, dst_s, dst_a))

    # 并行运行 8 个双路精修拼豆生成任务
    tasks = build_tasks()
    results = []
    max_workers = min(8, os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        fmap = {pool.submit(run_single_cat_task, t): t for t in tasks}
        for fut in as_completed(fmap):
            res = fut.result()
            t_spec = fmap[fut]
            if res["colors"] > t_spec["colors"] + 1:
                raise AssertionError(f"色数明显超出预期: {res['stem']} ({res['colors']} > {t_spec['colors']})")
            results.append(res)

    wall_sec = time.perf_counter() - t_wall0
    seq_sec = sum(r["elapsed"] for r in results)

    cat_order = {"cat1": 1, "cat2": 2, "cat3": 3, "cat4": 4}
    kind_order = {"fusion_refined": 1, "ai_refined": 2}
    results.sort(key=lambda r: (cat_order[r["cat_id"]], kind_order[r["kind"]]))

    art_copies = {}
    for r in results:
        sp = Path(r["sheet_png"])
        pp = Path(r["preview_png"])
        sp_a = ARTIFACT_DIR / sp.name
        pp_a = ARTIFACT_DIR / pp.name
        shutil.copy2(sp, sp_a)
        shutil.copy2(pp, pp_a)
        art_copies[(r["cat_id"], r["kind"])] = (sp_a, pp_a, r["preview_source"])

    kind_zh_map = {
        "fusion_refined": "方案1 · 融合精修版（PindouStudio × PixelBeads）",
        "ai_refined": "方案2 · AI 重绘高精精修版",
    }
    chatgpt_count = sum(1 for r in results if r["preview_source"] == "chatgpt")

    # 撰写完整对比总览报告
    lines = [
        "# 四只猫咪拼豆图纸精修总览（每图 2 套图纸 + 2 张真实烘烤预览图 = 16 张主图）",
        "",
        "> [!NOTE]",
        f"> 本次使用多核并行引擎（{max_workers} 路进程并发完成全部 **4 张原图 × 2 套精修方案（含对应烘烤预览图共 16 张主输出图）**，墙钟耗时 **{wall_sec:.2f} 秒**，单任务累加等效 **{seq_sec:.2f} 秒**），全部输出已保存至 [猫咪拼豆图纸汇总]({uri(SUMMARY_DIR)})。",
        "",
        "## 一、本次升级精修重点说明",
        "",
        "1. **精简聚焦『1 输入图 → 4 张输出图』**：全面取消过低分辨率且容易五官变形的「新手极简实拼版」，仅保留并深化两套精品路线：",
        "   - **方案1（融合精修版）**：结合 `PindouStudio`（CIEDE2000 / 显著性 K-means++ / ICM 平滑 / 孤立豆清理）与 `PixelBeads`（代表色簇聚类 / `.pindou.json` 可编辑工程），并针对低分辨率原图（图二 `132×130`、图四 `130×110`）先做 **4× 超分重建（IBP + 色度降噪）**，同时精修白猫偏色、图四橄榄灰杏仁眼+**竖向椭圆瞳孔**及锐利白色 `'干嘛......'`。",
        "   - **方案2（AI 重绘高精精修版）**：升级至 **`72×72` ~ `96` 格横版**，专门重修眉眼弧度、竖向椭圆瞳孔 / 眼神高光与文字笔顺，消除菱角眼及外缘抗锯齿灰边。",
        f"2. **真实世界拼豆『烘烤定型』质感升级（ChatGPT Plus 实拍渲染 `{chatgpt_count}/{len(results)}` 套 + 物理满焊模拟兜底）**：严格对标真实熨烫拼豆的**圆角小方砖融接咬合、中心孔约 75% 受热闭合与微弱随机针眼凹点、烘焙油纸半哑光微反光**质感，告别失真的空心圆管效果。",
        "",
        "---",
        "",
        "## 二、精修 8 套图纸 × 16 张主输出总表（MARD 色卡）",
        "",
        "| 图片主题 | 精修方案 | 实际网格尺寸 | 用色数 | 总豆数 | 单任务耗时 | 预览图来源 | 输出文件（图片直链 + 辅助清单） |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in results:
        src_badge = "ChatGPT Plus 真实烘烤实拍" if r["preview_source"] == "chatgpt" else "物理满焊仿真模拟"
        lines.append(
            f"| **{r['cat_zh']}** | {kind_zh_map[r['kind']]} | `{r['grid']}` | `{r['colors']}` 色 | `{r['beads']}` 颗 | `{r['elapsed']:.2f}s` | {src_badge} | [施工图纸]({uri(r['sheet_png'])}) ｜ [烘烤成品预览]({uri(r['preview_png'])}) ｜ [采购清单]({uri(r['bom_csv'])}) ｜ [可编辑工程]({uri(r['pindou_json'])}) |"
        )

    lines.extend(["", "---", "", "## 三、主体底图与 16 张精修输出预览轮播", "", "### 0. 提取主体与 AI 重绘底图", "", "````carousel"])
    for i, (lbl, _, dst_a) in enumerate(raw_entries):
        if i > 0:
            lines.append("<!-- slide -->")
        lines.append(f"![{lbl}]({slash(dst_a)})")
    lines.extend(["````"])

    for cat_id, heading in (
        ("cat1", "### 1. 图一 · 箱子小猫（1 输入 → 4 张输出：2 套图纸 + 2 张烘烤成品图）"),
        ("cat2", "### 2. 图二 · 完整猫脸（1 输入 → 4 张输出：2 套图纸 + 2 张烘烤成品图）"),
        ("cat3", "### 3. 图三 · 单独小猫 + 边缘床单（1 输入 → 4 张输出：2 套图纸 + 2 张烘烤成品图）"),
        ("cat4", "### 4. 图四 · 干嘛三花猫（4×超分 + 椭圆瞳孔 + '干嘛......'精修：2 套图纸 + 2 张烘烤成品图）"),
    ):
        lines.extend(["", heading, "", "````carousel"])
        slides = []
        for r in [x for x in results if x["cat_id"] == cat_id]:
            sp_a, pp_a, psrc = art_copies[(cat_id, r["kind"])]
            lbl_src = "ChatGPT 真实烘烤成品" if psrc == "chatgpt" else "真实满焊烘烤模拟成品"
            slides.append((f"{r['stem']}（{r['grid']} · {r['beads']}颗）", sp_a))
            slides.append((f"{r['stem']} · {lbl_src}", pp_a))
        for i, (cap, p) in enumerate(slides):
            if i > 0:
                lines.append("<!-- slide -->")
            lines.append(f"![{cap}]({slash(p)})")
        lines.extend(["````"])

    md_text = "\n".join(lines) + "\n"
    art_md = ARTIFACT_DIR / "cat_pindou_patterns_comparison.md"
    old_md = SUMMARY_DIR / "00_三只猫咪拼豆图纸精选总览.md"
    if old_md.exists():
        old_md.unlink()
    sum_md = SUMMARY_DIR / "00_四只猫咪拼豆图纸精选总览.md"
    art_md.write_text(md_text, encoding="utf-8")
    sum_md.write_text(md_text, encoding="utf-8")

    # 校验全部文件链接与图片路径 100% 存在
    links = re.findall(r"file:///([^)\"\s>]+)", md_text)
    imgs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md_text)
    miss_l = [urllib.parse.unquote(x) for x in links if not Path(urllib.parse.unquote(x)).exists()]
    miss_i = [x for x in imgs if not Path(x).exists()]
    if miss_l or miss_i:
        raise RuntimeError(f"存在缺失路径! links={miss_l}, imgs={miss_i}")

    print(f"PARALLEL_WALL_SEC={wall_sec:.3f}")
    print(f"SEQUENTIAL_EQUIV_SEC={seq_sec:.3f}")
    print(f"WORKERS={max_workers}")
    print(f"CHATGPT_PREVIEWS={chatgpt_count}/{len(results)}")
    for r in results:
        print(
            f"TASK | {r['cat_zh']} | {r['kind']} | {r['grid']} | {r['colors']} colors | {r['beads']} beads | src={r['preview_source']} | {r['elapsed']:.3f}s | {Path(r['sheet_png']).name}"
        )
    print(f"LINKS_VERIFIED={len(links)} (missing=0) | IMGS_VERIFIED={len(imgs)} (missing=0)")


if __name__ == "__main__":
    main()
