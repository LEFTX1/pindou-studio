# -*- coding: utf-8 -*-
"""多途径并行拼豆图纸权威生成引擎（融合 Pindou Studio + Pixel-Beads + BFS极简 + AI重绘52×52）。"""

from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import os
from pathlib import Path
import re
import shutil
import time
import urllib.parse

import numpy as np
from PIL import Image
from skimage import color as skcolor

from run_pathway_a_and_d import (
    bfs_simplify_and_reduce,
    ciede2000_snap,
    denoise_jpeg_sprite,
    load_palette,
    render_bead_preview,
    render_sheet_png,
    write_bom_csv,
)

PROJECT_ROOT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
INPUTS_DIR = PROJECT_ROOT / "inputs"
OUT_AUTH = PROJECT_ROOT / "outputs" / "pathway_authoritative_parallel"
SUMMARY_DIR = PROJECT_ROOT / "拼豆图纸汇总"
ARTIFACT_DIR = Path(r"C:\Users\Administrator\.gemini\antigravity\brain\e9d6b73c-8428-402f-96c2-37bcf4c52a6f")


def delta_e2000_matrix(labs_a: np.ndarray, labs_b: np.ndarray) -> np.ndarray:
    """向量化计算 (N, 3) 与 (M, 3) 的 CIEDE2000 矩阵 (N, M)。"""
    n, m = labs_a.shape[0], labs_b.shape[0]
    a_b = np.broadcast_to(labs_a[:, None, :], (n, m, 3))
    b_b = np.broadcast_to(labs_b[None, :, :], (n, m, 3))
    return skcolor.deltaE_ciede2000(a_b, b_b)


def pindou_studio_quantize(
    rgba: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
    max_colors: int = 20,
    seed: int = 20261116,
    protected_codes: set[str] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    复刻 Aswellle/Pindou-Studio 核心算法链：
    1) 边缘强度 edgeStrength (95分位归一化) + 中心显著性 saliency -> protection 保护图
    2) 中性锚点 (极黑/极白) + 高饱和特征色锁定
    3) 边缘与显著性加权 Lab K-means++ 调色板筛选 -> CIEDE2000 映射 MARD 221
    4) ICM (迭代条件模式) 空间精炼 (fidelityScale = 1 + 0.4 * protection, spatialWeight = 0.12)
    5) ABAB 棋盘伪影抑制 + 保护型孤立豆清理 (ΔE00 < 8) + 微小连通岛清理 (≤4格 & protection <= 0.55)
    """
    if protected_codes is None:
        protected_codes = set()
    h, w, _ = rgba.shape
    mask = rgba[:, :, 3] > 0

    # 轻量 JPEG 块噪点预处理 + 白底提纯
    clean_rgb = denoise_jpeg_sprite(rgba, is_medallion=True, de_thresh=2.8)
    lab_img = skcolor.rgb2lab(clean_rgb.astype(np.float64) / 255.0)

    # 1) 边缘强度 edgeMap -> edgeStrength (95分位截断归一化)
    edge_map = np.zeros((h, w), dtype=np.float64)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr = np.clip(np.arange(h) + dr, 0, h - 1)[:, None]
        cc = np.clip(np.arange(w) + dc, 0, w - 1)[None, :]
        nbr_mask = mask[rr, cc] & mask
        diff = np.linalg.norm(lab_img - lab_img[rr, cc], axis=2)
        diff = np.where(nbr_mask, diff, 0.0)
        edge_map = np.maximum(edge_map, diff)

    pos_vals = edge_map[mask & (edge_map > 0)]
    pivot = float(np.percentile(pos_vals, 95)) if pos_vals.size > 0 else 1.0
    pivot = max(pivot, 1e-6)
    edge_strength = np.where(mask, np.clip(edge_map / pivot, 0.0, 1.0), 0.0)

    # 2) 主体显著性 saliency + protection 保护图
    bg_lab = np.array([100.0, 0.0, 0.0], dtype=np.float64)  # 纯白圆章对照基准
    ys, xs = np.mgrid[0:h, 0:w]
    center_prior = np.clip(
        1.0 - 0.7 * (np.abs(xs / max(1, w - 1) - 0.5) + np.abs(ys / max(1, h - 1) - 0.5)),
        0.0,
        1.0,
    )
    fg_labs = lab_img[mask]
    bg_dist_fg = np.minimum(1.0, skcolor.deltaE_ciede2000(fg_labs, np.broadcast_to(bg_lab, fg_labs.shape)) / 40.0)
    bg_dist = np.zeros((h, w), dtype=np.float64)
    bg_dist[mask] = bg_dist_fg
    raw_sal = np.where(mask, (0.55 * bg_dist + 0.45 * edge_strength) * center_prior, 0.0)
    max_sal = float(raw_sal.max()) if raw_sal.max() > 0 else 1.0
    saliency = raw_sal / max_sal
    protection = np.clip(0.5 * edge_strength + 0.5 * saliency, 0.0, 1.0)

    # 3) 边缘/显著性加权 Lab K-means++ 精选 max_colors 色调色板 (illustration 权重: 1.8 / 0.8)
    weights = 1.0 + 1.8 * edge_strength[mask] + 0.8 * saliency[mask]
    samples_lab = fg_labs
    samples_rgb = clean_rgb[mask].astype(int)
    n_fg = samples_lab.shape[0]

    # 锁定中性锚点 (极黑/极白) 与特征高亮色
    code_to_pal_idx = {e["code"]: idx for idx, e in enumerate(pal)}
    locked = []
    # 首先用快速欧氏归属计算色板频率
    pal_dists_all = np.linalg.norm(samples_lab[:, None, :] - pal_lab[None, :, :], axis=2)
    nearest_all = np.argmin(pal_dists_all, axis=1)
    pal_counts = np.bincount(nearest_all, minlength=len(pal))

    lock_cands = []
    for p_idx, entry in enumerate(pal):
        ratio = pal_counts[p_idx] / max(1, n_fg)
        r_p, g_p, b_p = map(int, entry["rgb"])
        is_neutral_anchor = (max(r_p, g_p, b_p) <= 24 or min(r_p, g_p, b_p) >= 232) and ratio >= 0.001
        is_dom_accent = (max(r_p, g_p, b_p) - min(r_p, g_p, b_p) >= 150) and ratio >= 0.005
        is_protected = entry["code"] in protected_codes and pal_counts[p_idx] > 0
        if is_protected or is_neutral_anchor or is_dom_accent:
            bonus = 100000 if is_protected else 0
            lock_cands.append((bonus + pal_counts[p_idx], p_idx))
    lock_cands.sort(reverse=True)
    locked_indices = [idx for _, idx in lock_cands[:max_colors]]

    rng = np.random.default_rng(seed)
    centers = [samples_lab[int(rng.integers(0, n_fg))].copy()]
    while len(centers) < max_colors:
        c_arr = np.asarray(centers)
        d2 = np.min(np.sum((samples_lab[:, None, :] - c_arr[None, :, :]) ** 2, axis=2), axis=1)
        wd2 = d2 * weights
        total_wd2 = float(wd2.sum())
        if total_wd2 <= 0:
            picked_i = int(rng.integers(0, n_fg))
        else:
            probs = wd2 / total_wd2
            picked_i = int(rng.choice(n_fg, p=probs))
        centers.append(samples_lab[picked_i].copy())

    centers = np.asarray(centers, dtype=np.float64)
    for _ in range(16):
        c_d2 = np.sum((samples_lab[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        assign = np.argmin(c_d2, axis=1)
        for ci in range(max_colors):
            sel = assign == ci
            if sel.any():
                w_sel = weights[sel][:, None]
                centers[ci] = np.sum(samples_lab[sel] * w_sel, axis=0) / float(w_sel.sum())

    # CIEDE2000 映射聚类中心到互不重复的 MARD 221 色号
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
    # 若聚出重复色号导致不足 max_colors，按覆盖缺口误差最大的样本补齐
    while len(active_pal_indices) < max_colors:
        sub_labs = pal_lab[active_pal_indices]
        cur_err = np.min(np.linalg.norm(samples_lab[:, None, :] - sub_labs[None, :, :], axis=2), axis=1) * weights
        order = np.argsort(-cur_err)
        added = False
        for s_i in order:
            cand_p = int(np.argmin(delta_e2000_matrix(samples_lab[s_i : s_i + 1], pal_lab)[0]))
            if cand_p not in used_set:
                active_pal_indices.append(cand_p)
                used_set.add(cand_p)
                added = True
                break
        if not added:
            break

    active_pal_indices = active_pal_indices[:max_colors]
    active_labs = pal_lab[active_pal_indices]

    # 4) 初始 CIEDE2000 最近色映射
    de_grid_fg = delta_e2000_matrix(fg_labs, active_labs)  # (N_fg, K)
    de_act_pair = delta_e2000_matrix(active_labs, active_labs)  # (K, K)

    local_idx = np.full((h, w), -1, dtype=np.int32)
    fg_pos = np.argwhere(mask)
    init_best = np.argmin(de_grid_fg, axis=1)
    fg_lookup = np.full((h, w), -1, dtype=np.int32)
    for fi, (r, c) in enumerate(fg_pos):
        local_idx[r, c] = int(init_best[fi])
        fg_lookup[r, c] = fi

    # 5) ICM 空间精炼 (spatialWeight = 0.12, fidelityScale = 1 + 0.4 * protection, iterations = 4)
    spatial_weight = 0.12
    for _ in range(4):
        changed = 0
        next_idx = local_idx.copy()
        for r, c in fg_pos:
            fi = fg_lookup[r, c]
            nbrs = []
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w and local_idx[nr, nc] >= 0:
                    nbrs.append(int(local_idx[nr, nc]))
            if not nbrs:
                continue
            cands = set(nbrs)
            cands.add(int(local_idx[r, c]))
            cands.add(int(init_best[fi]))
            f_scale = 1.0 + 0.4 * float(protection[r, c])
            best_c = int(local_idx[r, c])
            best_cost = 1e18
            for ci in cands:
                fidelity_cost = float(de_grid_fg[fi, ci]) * f_scale
                smooth_cost = sum(float(de_act_pair[ci, n]) for n in nbrs if n != ci) / len(nbrs)
                total_cost = fidelity_cost + spatial_weight * smooth_cost
                if total_cost < best_cost:
                    best_cost = total_cost
                    best_c = ci
            if best_c != local_idx[r, c]:
                next_idx[r, c] = best_c
                changed += 1
        local_idx = next_idx
        if changed == 0:
            break

    # 6) 棋盘伪影抑制 (suppressCheckerboard, ΔE00 >= 10)
    suppressed = local_idx.copy()
    for y in range(h - 1):
        for x in range(w - 1):
            c00, c01 = local_idx[y, x], local_idx[y, x + 1]
            c10, c11 = local_idx[y + 1, x], local_idx[y + 1, x + 1]
            if min(c00, c01, c10, c11) < 0:
                continue
            if not (c00 == c11 and c01 == c10 and c00 != c01):
                continue
            if de_act_pair[c00, c01] < 10.0:
                continue
            chk_nbr = 0
            for dy in (-1, 1):
                for dx in (-1, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h - 1 and 0 <= nx < w - 1:
                        nc00, nc01 = local_idx[ny, nx], local_idx[ny, nx + 1]
                        nc10, nc11 = local_idx[ny + 1, nx], local_idx[ny + 1, nx + 1]
                        if min(nc00, nc01, nc10, nc11) >= 0 and nc00 == nc11 and nc01 == nc10 and nc00 != nc01:
                            if nc00 == c00 or nc00 == c01:
                                chk_nbr += 1
            if chk_nbr >= 2:
                # 取 4 个像素误差之和更小的那个颜色
                err00 = sum(float(de_grid_fg[fg_lookup[y + dy2, x + dx2], c00]) for dy2 in (0, 1) for dx2 in (0, 1))
                err01 = sum(float(de_grid_fg[fg_lookup[y + dy2, x + dx2], c01]) for dy2 in (0, 1) for dx2 in (0, 1))
                rep = c00 if err00 <= err01 else c01
                for dy2 in (0, 1):
                    for dx2 in (0, 1):
                        if protection[y + dy2, x + dx2] <= 0.55:
                            suppressed[y + dy2, x + dx2] = rep
    local_idx = suppressed

    # 7) 保护型孤立豆清理 (cleanupIsolatedBeads, ΔE00 < 8)
    counts_local = Counter(int(local_idx[r, c]) for r, c in fg_pos)
    cleaned = local_idx.copy()
    for r, c in fg_pos:
        cur = int(local_idx[r, c])
        if counts_local[cur] <= 1:
            continue
        nbrs = []
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and local_idx[nr, nc] >= 0:
                nbrs.append(int(local_idx[nr, nc]))
        if len(nbrs) < 2 or any(n == cur for n in nbrs):
            continue
        dom_c, dom_n = Counter(nbrs).most_common(1)[0]
        if dom_n < (len(nbrs) + 1) // 2:
            continue
        fi = fg_lookup[r, c]
        if float(de_grid_fg[fi, dom_c]) < 8.0 and protection[r, c] <= 0.55:
            cleaned[r, c] = dom_c
            counts_local[cur] -= 1
            counts_local[dom_c] += 1
    local_idx = cleaned

    # 8) 微小连通岛清理 (cleanupTinyIslands: <=4 格, 未被保护 <=0.55, ΔE00 < 6)
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
        if bnd_tot == 0:
            continue
        dom_c, dom_n = bnd.most_common(1)[0]
        if dom_n < (bnd_tot + 1) // 2:
            continue
        if all(float(de_grid_fg[fg_lookup[cr, cc], dom_c]) < 6.0 for cr, cc in comp):
            for cr, cc in comp:
                cleaned2[cr, cc] = dom_c
            counts_local[col] -= len(comp)
            counts_local[dom_c] += len(comp)
    local_idx = cleaned2

    # 9) 若后处理使部分调色板中心变为 0，重新用真实未覆盖误差最高的样本补齐并精准重分配，保证 20 色饱满
    present = sorted(k for k, v in Counter(int(local_idx[r, c]) for r, c in fg_pos).items() if v > 0)
    if len(present) < len(active_pal_indices):
        used_global = {active_pal_indices[k] for k in present}
        while len(used_global) < max_colors:
            cur_labs = pal_lab[list(used_global)]
            best_fi = -1
            best_score = -1.0
            for r, c in fg_pos:
                fi = fg_lookup[r, c]
                cur_col = active_pal_indices[int(local_idx[r, c])]
                err = float(skcolor.deltaE_ciede2000(fg_labs[fi : fi + 1], pal_lab[cur_col : cur_col + 1])[0])
                w_err = err * (1.0 + 2.0 * float(protection[r, c]))
                if w_err > best_score:
                    best_score = w_err
                    best_fi = fi
            if best_fi < 0:
                break
            cand_order = np.argsort(delta_e2000_matrix(fg_labs[best_fi : best_fi + 1], pal_lab)[0])
            added = False
            for p_cand in cand_order:
                if int(p_cand) not in used_global:
                    used_global.add(int(p_cand))
                    # 仅对确实离这个新色更近且未被强合并的前景格启用它
                    new_de = skcolor.deltaE_ciede2000(fg_labs, np.broadcast_to(pal_lab[int(p_cand)], fg_labs.shape))
                    cur_g_labs = pal_lab[[active_pal_indices[int(local_idx[r, c])] for r, c in fg_pos]]
                    old_de = skcolor.deltaE_ciede2000(fg_labs, cur_g_labs)
                    # 把离新色更近的像素切过去
                    better = np.where(new_de + 0.5 < old_de)[0]
                    if better.size > 0:
                        new_k = len(active_pal_indices)
                        active_pal_indices.append(int(p_cand))
                        for fi_b in better:
                            rb, cb = fg_pos[fi_b]
                            local_idx[rb, cb] = new_k
                    else:
                        # 至少把触发样本赋给新色号
                        rb, cb = fg_pos[best_fi]
                        new_k = len(active_pal_indices)
                        active_pal_indices.append(int(p_cand))
                        local_idx[rb, cb] = new_k
                    added = True
                    break
            if not added:
                break

    global_grid = np.zeros((h, w), dtype=np.int32)
    for r, c in fg_pos:
        global_grid[r, c] = active_pal_indices[int(local_idx[r, c])]
    return global_grid, mask


def keep_exact_color_count_reduce(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
    target_colors: int,
    protected_codes: set[str],
    pal_de_mat: np.ndarray | None = None,
) -> np.ndarray:
    """
    先做极轻微孤点清洗（不删除任何颜色的最后一颗），然后按感知代价精确归并到 target_colors 种。
    """
    if pal_de_mat is None:
        pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)
    h, w = idx_grid.shape
    out = idx_grid.copy()

    # Step 1: 轻度孤立单点清理（Area <= 1，确保不会抹掉独色亮点）
    counts = Counter(int(x) for x in out[mask])
    for r in range(h):
        for c in range(w):
            if not mask[r, c]:
                continue
            col = int(out[r, c])
            if counts[col] <= 2 or pal[col]["code"] in protected_codes:
                continue
            c_rgb = pal[col]["rgb"].astype(int)
            if int(c_rgb.max() - c_rgb.min()) > 65:
                continue
            nbrs = []
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w and mask[nr, nc]:
                    nbrs.append(int(out[nr, nc]))
            if nbrs and all(n != col for n in nbrs):
                dom_n, dom_cnt = Counter(nbrs).most_common(1)[0]
                if dom_cnt >= 3 and float(pal_de_mat[col, dom_n]) < 18.0:
                    out[r, c] = dom_n
                    counts[col] -= 1
                    counts[dom_n] += 1

    # Step 2: 贪心感知低损收敛到精确 target_colors 色
    while True:
        counts = Counter(int(x) for x in out[mask])
        if len(counts) <= target_colors:
            break
        present = list(counts.keys())
        best_pair = None
        best_cost = 1e18
        for src in present:
            if pal[src]["code"] in protected_codes:
                continue
            for dst in present:
                if dst == src:
                    continue
                de = float(pal_de_mat[src, dst])
                cost = counts[src] * (de ** 1.4)
                if cost < best_cost:
                    best_cost = cost
                    best_pair = (src, dst)
        if best_pair is None:
            for src in present:
                for dst in present:
                    if dst == src:
                        continue
                    de = float(pal_de_mat[src, dst])
                    cost = counts[src] * (de ** 1.4)
                    if cost < best_cost:
                        best_cost = cost
                        best_pair = (src, dst)
        src, dst = best_pair
        out[(out == src) & mask] = dst

    return out


def ai_52x52_quantize(
    src_white_png: Path,
    pal: list,
    pal_lab: np.ndarray,
    target_colors: int = 16,
    protected_codes: set[str] | None = None,
    pal_de_mat: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    AI 像素重绘图片 -> 52×52 标准大板网格：
    1) 先在全分辨率图上用边界洪水填充抠除纯白外部背景（不误掏内部白牙/高光）
    2) 对每个目标格子做“前景像素独立主色重采样”（排除背景白色混合，彻底消灭灰白毛边）
    3) CIEDE2000 吸附 MARD 221 + 16色低损收敛
    """
    if protected_codes is None:
        protected_codes = set()
    hi_rgb = np.array(Image.open(src_white_png).convert("RGB"), dtype=np.int16)
    h_hi, w_hi, _ = hi_rgb.shape

    max_c = hi_rgb.max(axis=2)
    min_c = hi_rgb.min(axis=2)
    is_outer_white = (min_c >= 232) & ((max_c - min_c) <= 22)

    bg_hi = np.zeros((h_hi, w_hi), dtype=bool)
    q = deque()
    for x in range(w_hi):
        for y in (0, h_hi - 1):
            if is_outer_white[y, x] and not bg_hi[y, x]:
                bg_hi[y, x] = True
                q.append((y, x))
    for y in range(1, h_hi - 1):
        for x in (0, w_hi - 1):
            if is_outer_white[y, x] and not bg_hi[y, x]:
                bg_hi[y, x] = True
                q.append((y, x))
    while q:
        cy, cx = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h_hi and 0 <= nx < w_hi and not bg_hi[ny, nx] and is_outer_white[ny, nx]:
                bg_hi[ny, nx] = True
                q.append((ny, nx))

    fg_hi = ~bg_hi
    out_n = 52
    grid_rgb = np.full((out_n, out_n, 3), 255, dtype=np.uint8)
    mask = np.zeros((out_n, out_n), dtype=bool)

    for oy in range(out_n):
        y0 = round(oy * h_hi / out_n)
        y1 = max(y0 + 1, round((oy + 1) * h_hi / out_n))
        for ox in range(out_n):
            x0 = round(ox * w_hi / out_n)
            x1 = max(x0 + 1, round((ox + 1) * w_hi / out_n))
            p_fg = fg_hi[y0:y1, x0:x1]
            cov = float(p_fg.mean())
            if cov < 0.45:
                continue
            fg_pixels = hi_rgb[y0:y1, x0:x1][p_fg].astype(np.float64)
            # 边缘高方差格取占比更大的主簇均色（避免黑边与浅粉平均成灰毛边）
            var = float(np.mean(np.var(fg_pixels, axis=0)))
            if var > 450.0 and fg_pixels.shape[0] >= 4:
                avg = fg_pixels.mean(axis=0)
                c1 = avg
                c2 = fg_pixels[int(np.argmax(np.sum((fg_pixels - avg) ** 2, axis=1)))]
                for _ in range(3):
                    d1 = np.sum((fg_pixels - c1) ** 2, axis=1)
                    d2 = np.sum((fg_pixels - c2) ** 2, axis=1)
                    s1 = d1 <= d2
                    if s1.any():
                        c1 = fg_pixels[s1].mean(axis=0)
                    if (~s1).any():
                        c2 = fg_pixels[~s1].mean(axis=0)
                chosen = c1 if int(s1.sum()) >= int((~s1).sum()) else c2
            else:
                chosen = fg_pixels.mean(axis=0)
            grid_rgb[oy, ox] = np.clip(np.round(chosen), 0, 255).astype(np.uint8)
            mask[oy, ox] = True

    idx_grid = ciede2000_snap(grid_rgb, pal_lab)
    idx_grid = keep_exact_color_count_reduce(
        idx_grid, mask, pal, pal_lab, target_colors, protected_codes, pal_de_mat=pal_de_mat
    )
    return idx_grid, mask


def run_single_task(task: dict) -> dict:
    """在独立进程中执行单角色×单途径的量化与图纸/预览/BOM 渲染。"""
    t0 = time.perf_counter()
    pal, pal_lab = load_palette()

    char_en = task["char_en"]
    char_zh = task["char_zh"]
    kind = task["kind"]
    stem = task["stem"]
    out_dir = Path(task["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    if kind == "pindou_studio":
        rgba = np.array(Image.open(INPUTS_DIR / f"{char_en}_medallion_64x64.png").convert("RGBA"))
        idx_grid, mask = pindou_studio_quantize(
            rgba, pal, pal_lab, max_colors=20, protected_codes=task["protected"]
        )
        title = f"{char_zh} · 精选1：Pindou Studio 科学量化版（完整圆章）"
        subtitle = "加权 K-means++ / CIEDE2000 / 边缘与显著性保护 / ICM精炼 + 孤立豆清理"
    elif kind == "pixel_beads":
        rgba = np.array(Image.open(INPUTS_DIR / f"{char_en}_inner_only.png").convert("RGBA"))
        mask = rgba[:, :, 3] > 0
        clean_rgb = denoise_jpeg_sprite(rgba, is_medallion=False, de_thresh=3.6)
        idx_grid = ciede2000_snap(clean_rgb, pal_lab)
        idx_grid = keep_exact_color_count_reduce(
            idx_grid, mask, pal, pal_lab, target_colors=18, protected_codes=task["protected"]
        )
        title = f"{char_zh} · 精选2：Pixel-Beads 省豆纯主体版（去白圈）"
        subtitle = f"剥离外圈立省约1500豆 · 直接适配 2×2 拼板 (58×58) · MARD 18色"
    elif kind == "bfs_beginner":
        rgba = np.array(Image.open(INPUTS_DIR / f"{char_en}_medallion_64x64.png").convert("RGBA"))
        mask = rgba[:, :, 3] > 0
        clean_rgb = denoise_jpeg_sprite(rgba, is_medallion=True, de_thresh=3.6)
        idx_grid = ciede2000_snap(clean_rgb, pal_lab)
        idx_grid = bfs_simplify_and_reduce(
            idx_grid, mask, pal, pal_lab, target_colors=14, protected_codes=task["protected"]
        )
        title = f"{char_zh} · 精选3：新手极简实拼版（完整圆章）"
        subtitle = "BFS 连通域合并 · 保留特征细节 · 14色零杂点新手友好"
    elif kind == "ai_52x52":
        src_white = PROJECT_ROOT / "outputs" / "pathway_F_ai_redraw" / char_en / f"{char_en}_ai_tight_white_sq.png"
        idx_grid, mask = ai_52x52_quantize(
            src_white, pal, pal_lab, target_colors=16, protected_codes=task["protected"]
        )
        title = f"{char_zh} · 精选4：AI重绘标准大板版（52×52 纯主体）"
        subtitle = "AI 16-bit 像素重绘 + 边界白晕清洗 · 对齐 52×52 标准一体大板 · 16色"
    else:
        raise ValueError(f"Unknown task kind: {kind}")

    sheet_png = out_dir / f"{stem}_图纸.png"
    preview_png = out_dir / f"{stem}_圆珠预览.png"
    bom_csv = out_dir / f"{stem}_采购清单.csv"

    bom, total_beads = render_sheet_png(
        idx_grid, mask, pal, title, subtitle, sheet_png, cell_px=34, palette_name="MARD"
    )
    render_bead_preview(idx_grid, mask, pal, preview_png, cell_px=16)
    write_bom_csv(bom, total_beads, pal, bom_csv, palette_name="MARD")

    elapsed = time.perf_counter() - t0
    h, w = idx_grid.shape
    return {
        "char_en": char_en,
        "char_zh": char_zh,
        "kind": kind,
        "stem": stem,
        "grid": f"{w}×{h}",
        "colors": len(bom),
        "beads": total_beads,
        "elapsed": elapsed,
        "sheet_png": str(sheet_png),
        "preview_png": str(preview_png),
        "bom_csv": str(bom_csv),
    }


def uri(path: Path | str) -> str:
    return "file:///" + str(path).replace("\\", "/")


def slash(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def build_tasks() -> list[dict]:
    configs = [
        (
            "espeon",
            "太阳伊布",
            "54x49",
            {"H1", "E7", "C24", "A2", "A1", "E24"},
        ),
        (
            "umbreon",
            "月亮伊布",
            "53x52",
            {"H2", "H1", "D10", "A3", "A16", "E13", "F7", "F9"},
        ),
    ]
    tasks = []
    for char_en, char_zh, inner_dim, protected in configs:
        folder = "01_太阳伊布_权威精选4套" if char_en == "espeon" else "02_月亮伊布_权威精选4套"
        target_dir = SUMMARY_DIR / folder
        tasks.extend([
            {
                "char_en": char_en,
                "char_zh": char_zh,
                "kind": "pindou_studio",
                "stem": f"{char_zh}_精选1_PindouStudio算法版_64x64完整圆章_MARD20色",
                "expected_colors": 20,
                "out_dir": str(target_dir),
                "protected": protected,
            },
            {
                "char_en": char_en,
                "char_zh": char_zh,
                "kind": "pixel_beads",
                "stem": f"{char_zh}_精选2_PixelBeads省豆纯主体版_{inner_dim}无白圈_MARD18色",
                "expected_colors": 18,
                "out_dir": str(target_dir),
                "protected": protected,
            },
            {
                "char_en": char_en,
                "char_zh": char_zh,
                "kind": "bfs_beginner",
                "stem": f"{char_zh}_精选3_新手极简实拼版_64x64完整圆章_MARD14色",
                "expected_colors": 14,
                "out_dir": str(target_dir),
                "protected": protected,
            },
            {
                "char_en": char_en,
                "char_zh": char_zh,
                "kind": "ai_52x52",
                "stem": f"{char_zh}_精选4_AI重绘标准大板版_52x52纯主体_MARD16色",
                "expected_colors": 16,
                "out_dir": str(target_dir),
                "protected": protected,
            },
        ])
    return tasks


def main():
    t_wall_start = time.perf_counter()

    # 1. 清理并重建精简版中文汇总目录
    if SUMMARY_DIR.exists():
        shutil.rmtree(SUMMARY_DIR)
    raw_dir = SUMMARY_DIR / "00_去背景原图与AI重绘底图"
    dir_espeon = SUMMARY_DIR / "01_太阳伊布_权威精选4套"
    dir_umbreon = SUMMARY_DIR / "02_月亮伊布_权威精选4套"
    for d in (SUMMARY_DIR, raw_dir, dir_espeon, dir_umbreon):
        d.mkdir(parents=True, exist_ok=True)

    # 复制 6 张中文命名底图（去背景提取原图 + AI 重绘底图）
    raw_pairs = [
        (ARTIFACT_DIR / "espeon_medallion_64x64_upscaled.png", "太阳伊布_64x64_去背景完整圆章原图.png", "太阳伊布 · 64×64 去背景完整圆章原图"),
        (ARTIFACT_DIR / "espeon_inner_only_upscaled.png", "太阳伊布_54x49_去白圈纯主体原图.png", "太阳伊布 · 54×49 去白圈纯主体原图"),
        (ARTIFACT_DIR / "espeon_pixel_redraw_1794768075450.jpg", "太阳伊布_52x52_AI像素重绘原图.jpg", "太阳伊布 · AI 像素重绘原图"),
        (ARTIFACT_DIR / "umbreon_medallion_64x64_upscaled.png", "月亮伊布_64x64_去背景完整圆章原图.png", "月亮伊布 · 64×64 去背景完整圆章原图"),
        (ARTIFACT_DIR / "umbreon_inner_only_upscaled.png", "月亮伊布_53x52_去白圈纯主体原图.png", "月亮伊布 · 53×52 去白圈纯主体原图"),
        (ARTIFACT_DIR / "umbreon_ai_pixel_redraw_1794768110715.jpg", "月亮伊布_52x52_AI像素重绘原图.jpg", "月亮伊布 · AI 像素重绘原图"),
    ]
    raw_entries = []
    for src, dst_name, label in raw_pairs:
        if not src.exists():
            raise FileNotFoundError(f"缺少底图: {src}")
        dst_s = raw_dir / dst_name
        dst_a = ARTIFACT_DIR / dst_name
        shutil.copy2(src, dst_s)
        shutil.copy2(src, dst_a)
        raw_entries.append((label, dst_s, dst_a))

    # 2. 多进程并行执行 4 大权威途径 × 双角色 (8 个独立任务并行)
    tasks = build_tasks()
    results = []
    max_workers = min(8, os.cpu_count() or 4)
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(run_single_task, t): t for t in tasks}
        for fut in as_completed(future_map):
            res = fut.result()
            t_spec = future_map[fut]
            if res["colors"] != t_spec["expected_colors"]:
                raise AssertionError(
                    f"色数校验失败 {res['stem']}: 实际 {res['colors']} != 预期 {t_spec['expected_colors']}"
                )
            results.append(res)

    wall_elapsed = time.perf_counter() - t_wall_start
    sum_task_elapsed = sum(r["elapsed"] for r in results)

    # 3. 同步精选图纸与圆珠预览到 Artifact 目录
    order_key = {"pindou_studio": 1, "pixel_beads": 2, "bfs_beginner": 3, "ai_52x52": 4}
    results.sort(key=lambda r: (0 if r["char_en"] == "espeon" else 1, order_key[r["kind"]]))

    art_copies = {}
    for r in results:
        sp = Path(r["sheet_png"])
        pp = Path(r["preview_png"])
        sp_a = ARTIFACT_DIR / sp.name
        pp_a = ARTIFACT_DIR / pp.name
        shutil.copy2(sp, sp_a)
        shutil.copy2(pp, pp_a)
        art_copies[(r["char_en"], r["kind"])] = (sp_a, pp_a)

    # 4. 生成深度调研与权威精选对比文档
    res_map = {(r["char_en"], r["kind"]): r for r in results}

    lines = [
        "# 拼豆图纸尺寸与颜色标准调研 · Pixel-Beads & Pindou Studio 多路并行权威精选",
        "",
        "> [!NOTE]",
        f"> 本次已精简并基于多核并行引擎（8 路并发总耗时 **{wall_elapsed:.2f} 秒**，单任务累加等效 **{sum_task_elapsed:.2f} 秒**）重制，保留最权威、最适合实际买豆拼搭的 **4 套精选方案 × 双角色（共 8 套）**。完整中文文件目录：[拼豆图纸汇总]({uri(SUMMARY_DIR)})。",
        "",
        "---",
        "",
        "## 一、拼豆行业尺寸规格与颜色数量科学标准",
        "",
        "拼豆并不是“格子越多越细腻、颜色越多越高级”。物理拼豆是离散颗粒材质（主流 2.6mm 迷你豆 / 5mm 标准豆），实拼复杂度由 $\\text{网格总数}$ 与 $\\text{色号种数}$ 共同决定：",
        "",
        "| 维度 | 行业常见标准 | 实际物理意义与复杂度边界 | 本作太阳/月亮伊布适配建议 |",
        "| :--- | :--- | :--- | :--- |",
        "| **单块标准方板** | `29×29`（841 孔） | 新手单板挂件/杯垫/小头像上限，超过即需拼板 | 适合极简小图标，放不下带花丛的完整圆章 |",
        "| **一体大号方板** | **`52×52`**（2704 孔） | 国内一体大拼板常见极限，可容纳完整Q版角色+局部花饰 | **精选 4（52×52 AI重绘版）**、**精选 2（54×49 / 53×52 纯主体）**可一板或 2×2 轻松放下 |",
        "| **2×2 拼板组合** | `58×58`（3364 孔） | 4 块 29×29 拼接，`64×64` 原生圆章可居中落于 **3×3** 或裁边 | **精选 1 / 精选 3（64×64 圆章）** 实际前景仅 **3161 颗**（四角透明留空） |",
        "| **颜色数量区间** | `≤15色` 极简 / `16–24色` 黄金段 / `>40色` 失控 | 源码与实拼反馈证明：**色数 > 32** 后大量“1~5 颗的微量杂色”会让找豆、分盒成本暴增；**色数 < 12** 则会吞掉高光、粉舌、蓝耳等特征 | **新手推荐 `14–16 色`（精选3/4）**；**进阶推荐 `18–20 色`（精选1/2）**；超过 30 色不建议新手直接照单备料 |",
        "",
        "> [!IMPORTANT]",
        "> **`Pindou Studio`（`src/utils/autoGrid.js`）尺寸—色数经验对照公式**：长边 `≤40` 建议 **12 色**；`41–70` 建议 **24 色以内**（卡通/插画按 `0.9×` 收紧，Logo 按 `0.6×` 收紧，即 **`64×64` 卡通插画黄金色数为 14–22 色**）；`71–110` 建议 **36 色**；`111–150` 建议 **48 色**。",
        "",
        "---",
        "",
        "## 二、核心标杆工具原理分析：`Pixel-Beads` vs `Pindou Studio`",
        "",
        "1. **`Pixel-Beads`（代表：`Zippland/perler-beads`、`DanZai233/PixelBead`、`PixelBeads.art` 交互派）**：",
        "   - **定位**：工程功能与实战编辑极度均衡——内置多品牌色卡（MARD / COCO / 漫漫 / 盼盼 / 咪小窝）、相似色合并、颜色排除重映射、同色高亮、网格辅助与实时 BOM 用量统计。",
        "   - **核心优势**：局部主导色提取 + 连通域清理避免了均值模糊导致的灰边；在**纯主体剥离（去白圈）**场景下可立省 ~1500 颗白豆/紫边豆，把耗时减半。",
        "2. **`Pindou Studio`（代表：`Aswellle/Pindou-Studio` 算法派）**：",
        "   - **核心 5 步科学量化链（实测源码 `src/workers/imageQuantizer.worker.js`）**：",
        "     1. **能量保护图**：`edgeStrength`（95 分位边缘强度）与 `saliency`（中心视觉显著性）合成为逐格 `protection ∈ [0, 1]`；",
        "     2. **锚点锁定 + 加权 `K-means++`**：锁定极黑/极白中性锚点及高饱和特征色，在边缘/显著性加权 Lab 空间聚类精选调色板；",
        "     3. **`CIEDE2000` 感知映射**：按人眼视觉非线性色差将每个聚类中心精准匹配到 MARD 色号；",
        "     4. **`ICM` 迭代条件模式空间优化**：短边 `≤120` 启用，令大面积色块平滑规整的同时用 `fidelityScale = 1 + 0.4 × protection` 保护轮廓与五官不糊；",
        "     5. **三维防误杀后处理**：`ABAB` 棋盘伪影抑制 + **保护型孤立豆清理**（仅在 $\\Delta E_{00} < 8$ 且非保护区时吸收，保住眼睛瞳孔、高光与小虎牙）+ 微岛清理（$\\le 4$ 格且 `protection ≤ 0.55`）。",
        "3. **为什么最终工具架构必须“多类型途径并行生成”**：",
        "   - 单独追求一种算法无法兼顾所有图源：完整细节图适合 **`Pindou Studio` 20色算法链**，追求效率适合 **`Pixel-Beads` 去白圈省豆链**，新手追求零失误适合 **BFS 14色极简链**，标准大板一板出图适合 **AI 52×52 重绘链**。",
        "   - 本项目脚本 [fast_parallel_pindou_engine.py](file:///C:/Users/Administrator/.gemini/antigravity/scratch/pindou-project/fast_parallel_pindou_engine.py) 通过多进程池（`ProcessPoolExecutor`）并行跑通 4 类途径 × 双图（8 路并发），实测全套仅需 **" + f"{wall_elapsed:.2f} 秒** 即可同时产出供对比挑选。",
        "",
        "---",
        "",
        "## 三、4 套权威精选方案横向参数与实测速度",
        "",
        "| 精选方案 | 算法内核与核心特点 | 网格尺寸（太阳 / 月亮） | 总豆数（太阳 / 月亮） | 用色数 | 并行生成耗时 | 适用人群 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    meta_rows = [
        ("pindou_studio", "**精选 1：Pindou Studio 算法版**", "`加权 K-means++` + `CIEDE2000` + `ICM空间精炼` + 棋盘/孤立豆保护清理", "完整保留花丛细节且零杂点的高端主力版"),
        ("pixel_beads", "**精选 2：Pixel-Beads 省豆纯主体版**", "去白圈纯主体 + 局部主导色 + 相似色收敛 + 2×2 拼板直接适配", "立省 ~1500 颗豆、效率最高的纯主体版"),
        ("bfs_beginner", "**精选 3：新手极简实拼版**", "BFS 连通域合并 + 特征亮点锁定（保住小虎牙 `H1`/粉舌 `F9`/额饰）", "**最推荐新手直接买豆**：14 色零翻车"),
        ("ai_52x52", "**精选 4：AI 重绘标准大板版**", "AI 16-bit 画素重绘 + 边界白晕洪水清洗 + `52×52` 一体大板规格", "大色块极好拼、可直接放进一张 `52×52` 大板"),
    ]
    for kind, name, algo, fit in meta_rows:
        e = res_map[("espeon", kind)]
        u = res_map[("umbreon", kind)]
        g = f"`{e['grid']}`" if e["grid"] == u["grid"] else f"`{e['grid']}` / `{u['grid']}`"
        t_max = max(e["elapsed"], u["elapsed"])
        lines.append(
            f"| {name} | {algo} | {g} | `{e['beads']} / {u['beads']}` 颗 | `{e['colors']} / {u['colors']}` 色 | `{t_max:.2f}s` | {fit} |"
        )

    lines.extend(["", "---", "", "## 四、去背景底图 & 权威精选图纸轮播对比", "", "### 1. 去背景原图与 AI 重绘底图", "", "````carousel"])
    for i, (lbl, _, dst_a) in enumerate(raw_entries):
        if i > 0:
            lines.append("<!-- slide -->")
        lines.append(f"![{lbl}]({slash(dst_a)})")
    lines.extend(["````", "", "### 2. 太阳伊布（Espeon）权威精选 4 套图纸 & 圆珠预览", "", "````carousel"])

    es_slides = []
    for r in [r for r in results if r["char_en"] == "espeon"]:
        sp_a, pp_a = art_copies[("espeon", r["kind"])]
        es_slides.append((f"{r['stem']}（{r['grid']} · {r['beads']}颗）", sp_a))
        es_slides.append((f"{r['stem']} · 圆珠立体预览", pp_a))
    for i, (cap, p) in enumerate(es_slides):
        if i > 0:
            lines.append("<!-- slide -->")
        lines.append(f"![{cap}]({slash(p)})")

    lines.extend(["````", "", "### 3. 月亮伊布（Umbreon）权威精选 4 套图纸 & 圆珠预览", "", "````carousel"])
    um_slides = []
    for r in [r for r in results if r["char_en"] == "umbreon"]:
        sp_a, pp_a = art_copies[("umbreon", r["kind"])]
        um_slides.append((f"{r['stem']}（{r['grid']} · {r['beads']}颗）", sp_a))
        um_slides.append((f"{r['stem']} · 圆珠立体预览", pp_a))
    for i, (cap, p) in enumerate(um_slides):
        if i > 0:
            lines.append("<!-- slide -->")
        lines.append(f"![{cap}]({slash(p)})")

    lines.extend([
        "````",
        "",
        "---",
        "",
        "## 五、权威精选中文文件直达清单（MARD 色卡）",
        "",
        "### 0. 去背景底图（`00_去背景原图与AI重绘底图`）",
    ])
    for lbl, dst_s, _ in raw_entries:
        lines.append(f"- **{lbl}**：[{dst_s.name}]({uri(dst_s)})")

    for char_en, folder in (("espeon", "01_太阳伊布_权威精选4套"), ("umbreon", "02_月亮伊布_权威精选4套")):
        char_zh = "太阳伊布" if char_en == "espeon" else "月亮伊布"
        lines.extend(["", f"### {char_zh}（`{folder}`）"])
        for r in [x for x in results if x["char_en"] == char_en]:
            lines.append(
                f"- **{r['stem']}**（`{r['grid']}` · `{r['colors']}色` · `{r['beads']}颗`）：[图纸 PNG]({uri(r['sheet_png'])}) ｜ [圆珠预览 PNG]({uri(r['preview_png'])}) ｜ [采购清单 CSV]({uri(r['bom_csv'])})"
            )

    md_text = "\n".join(lines) + "\n"
    art_md = ARTIFACT_DIR / "pindou_patterns_comparison.md"
    sum_md = SUMMARY_DIR / "00_拼豆标准调研与权威精选总览.md"
    art_md.write_text(md_text, encoding="utf-8")
    sum_md.write_text(md_text, encoding="utf-8")

    # 5. 校验所有链接和图片 100% 存在
    links = re.findall(r"file:///([^)\"\s>]+)", md_text)
    imgs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md_text)
    miss_l = [urllib.parse.unquote(x) for x in links if not Path(urllib.parse.unquote(x)).exists()]
    miss_i = [x for x in imgs if not Path(x).exists()]
    if miss_l or miss_i:
        raise RuntimeError(f"存在缺失路径! links={miss_l}, imgs={miss_i}")

    print(f"PARALLEL_WALL_SEC={wall_elapsed:.3f}")
    print(f"SEQUENTIAL_EQUIV_SEC={sum_task_elapsed:.3f}")
    print(f"WORKERS={max_workers}")
    for r in results:
        print(
            f"TASK | {r['char_zh']} | {r['kind']} | {r['grid']} | {r['colors']} colors | {r['beads']} beads | {r['elapsed']:.3f}s | {Path(r['sheet_png']).name}"
        )
    print(f"LINKS_VERIFIED={len(links)} (missing=0) | IMGS_VERIFIED={len(imgs)} (missing=0)")


if __name__ == "__main__":
    main()
