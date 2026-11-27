# -*- coding: utf-8 -*-
"""
纯量化与超采样核心算法（从历史实验脚本剥离硬编码路径后的干净核心库模块）：
- sample_photo_tiles: Alpha 隔离前景网格超采样 + 瞳孔/高光特征保留
- pindou_studio_photo_quantize: 显著性保护图 + 加权 Lab K-means++ + CIEDE2000 + ICM 精炼
- keep_exact_color_count_reduce: 保护型孤立豆清理 + 感知低损颜色归并
"""

from __future__ import annotations

from collections import Counter, deque
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from skimage import color as skcolor

from .palette import delta_e2000_matrix


def _weighted_median_channel(samples_rgb: np.ndarray, channel: int) -> int:
    return int(np.round(np.median(samples_rgb[:, channel])))


def _dominant_cluster_rgb(samples_rgb: np.ndarray) -> np.ndarray:
    """在 4-bit 量化桶中找占比最大的主色簇并返回各通道中位数。"""
    if samples_rgb.shape[0] == 1:
        return samples_rgb[0].astype(np.uint8)
    s_i32 = samples_rgb.astype(np.int32)
    keys = (s_i32[:, 0] >> 4) * 256 + (s_i32[:, 1] >> 4) * 16 + (s_i32[:, 2] >> 4)
    uniq, counts = np.unique(keys, return_counts=True)
    dom_key = uniq[int(np.argmax(counts))]
    cluster = samples_rgb[keys == dom_key]
    return np.array(
        [
            _weighted_median_channel(cluster, 0),
            _weighted_median_channel(cluster, 1),
            _weighted_median_channel(cluster, 2),
        ],
        dtype=np.uint8,
    )


def _representative_rgb(samples_rgb: np.ndarray, mode_kind: str = "bead") -> np.ndarray:
    """保住黑色瞳孔与轮廓、白色高光眼珠点以及粉色/黄色等高饱和特征。"""
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
    """对高分辨率照片进行 alpha 隔离的前景网格超采样，并在特征边缘保留高对比轮廓与高光。"""
    src_h, src_w, _ = rgba.shape
    if force_square is not None:
        out_w, out_h = force_square, force_square
    elif src_w >= src_h:
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
            if float(fg.mean()) < 0.45:
                continue
            fg_px = rgb_all[y0:y1, x0:x1][fg]
            fg_f = fg_px.astype(np.float64)

            rope_px = (fg_px[:, 0] > 200) & (fg_px[:, 1] > 175) & (fg_px[:, 2] < 85)
            if float(rope_px.mean()) >= 0.16:
                rope_mask_grid[oy, ox] = True
                rope_rgb_grid[oy, ox] = np.clip(np.round(np.median(fg_px[rope_px], axis=0)), 0, 255).astype(np.uint8)

            lum_px = fg_f[:, 0] * 0.299 + fg_f[:, 1] * 0.587 + fg_f[:, 2] * 0.114
            if float(lum_px.min()) < 60.0:
                dark_pupil_grid[oy, ox] = True
            catch_px = np.min(fg_px, axis=1) >= 245
            if int(catch_px.sum()) >= 1:
                catch_cand_grid[oy, ox] = True
                catch_rgb_grid[oy, ox] = np.clip(np.round(fg_px[catch_px].mean(axis=0)), 0, 255).astype(np.uint8)

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


def _auto_detect_feature_anchors(
    grid_rgb: np.ndarray,
    mask: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
) -> set[str]:
    fg_rgb = grid_rgb[mask].astype(np.float64)
    fg_lab = skcolor.rgb2lab(fg_rgb / 255.0)
    lum = fg_rgb[:, 0] * 0.299 + fg_rgb[:, 1] * 0.587 + fg_rgb[:, 2] * 0.114
    chroma = fg_rgb.max(axis=1) - fg_rgb.min(axis=1)

    protected = set()
    dark_idx = int(np.argmin(lum))
    if lum[dark_idx] < 65.0:
        de_dark = delta_e2000_matrix(fg_lab[dark_idx : dark_idx + 1], pal_lab)[0]
        protected.add(pal[int(np.argmin(de_dark))]["code"])

    white_cands = np.where((lum >= 225.0) & (chroma <= 26.0))[0]
    if len(white_cands) > 0:
        w_best = white_cands[int(np.argmax(lum[white_cands]))]
        de_w = delta_e2000_matrix(fg_lab[w_best : w_best + 1], pal_lab)[0]
        protected.add(pal[int(np.argmin(de_w))]["code"])

    hi_sat = np.where(chroma >= 82.0)[0]
    if len(hi_sat) >= 2:
        top_s = hi_sat[np.argsort(-chroma[hi_sat])[: min(8, len(hi_sat))]]
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
    """5-step photo quantization: protection map + weighted Lab K-means++ + CIEDE2000 + ICM + despeckle."""
    h, w, _ = grid_rgb.shape
    lab_img = skcolor.rgb2lab(grid_rgb.astype(np.float64) / 255.0)
    fg_labs = lab_img[mask]
    n_fg = fg_labs.shape[0]
    protected_codes = _auto_detect_feature_anchors(grid_rgb, mask, pal, pal_lab)

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

    lum_fg = grid_rgb[:, :, 0] * 0.299 + grid_rgb[:, :, 1] * 0.587 + grid_rgb[:, :, 2] * 0.114
    extreme_face = mask & ((lum_fg <= 48.0) | (lum_fg >= 242.0))
    protection[extreme_face] = np.maximum(protection[extreme_face], 0.72)

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


def keep_exact_color_count_reduce(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    pal_lab: np.ndarray,
    target_colors: int,
    protected_codes: set[str],
    pal_de_mat: np.ndarray | None = None,
) -> np.ndarray:
    """轻微孤点清洗（不抹掉独色亮点）后按感知代价精确归并到 target_colors 种。"""
    if pal_de_mat is None:
        pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)
    h, w = idx_grid.shape
    out = idx_grid.copy()

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
        if best_pair is None:
            break
        src, dst = best_pair
        out[(out == src) & mask] = dst

    return out


def render_baked_flat_melt_preview(
    idx_grid: np.ndarray,
    mask: np.ndarray,
    pal: list,
    out_path: Path,
    cell_px: int = 18,
    seed: int = 42,
) -> None:
    """真实世界拼豆热熨定型物理质感渲染（Squircle 膨胀闭孔 + 烘焙油纸微哑光高光）。"""
    rng = np.random.default_rng(seed)
    h, w = idx_grid.shape
    pad = max(44, int(round(min(h, w) * cell_px * 0.14)))
    cw = w * cell_px + 2 * pad
    ch = h * cell_px + 2 * pad

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
            nx = nx + 0.045 * np.sin(ny * 3.2 + c * 1.3)
            ny = ny + 0.045 * np.cos(nx * 3.2 + r * 1.7)

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

    melted_color = np.zeros_like(color_img)
    w_denom = gaussian_filter(piece_f, sigma=0.60) + 1e-6
    for ch_i in range(3):
        melted_color[:, :, ch_i] = gaussian_filter(color_img[:, :, ch_i] * piece_f, sigma=0.60) / w_denom
    color_img = np.where(piece_mask[:, :, None], 0.56 * color_img + 0.44 * melted_color, color_img)

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

    shadow_alpha = gaussian_filter(piece_f, sigma=cell_px * 0.30)
    off_y, off_x = max(3, cell_px // 4), max(2, cell_px // 5)
    shifted = np.zeros_like(shadow_alpha)
    shifted[off_y:, off_x:] = shadow_alpha[:-off_y, :-off_x]
    ao_shadow = np.clip(shifted * 0.34 + shadow_alpha * 0.18, 0.0, 0.52) * (1.0 - alpha)
    bg_lit = bg_base * (1.0 - ao_shadow[:, :, None])

    comp = shaded * alpha[:, :, None] + bg_lit * (1.0 - alpha[:, :, None])
    out_u8 = np.clip(np.round(comp), 0, 255).astype(np.uint8)
    Image.fromarray(out_u8, "RGB").save(out_path, quality=95)

