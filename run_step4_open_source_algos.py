import json
import math
import re
import subprocess
from collections import Counter, deque
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
from PIL import Image
from skimage import color as skcolor

from run_pathway_a_and_d import (
    INPUTS_DIR,
    PALETTE_CSV,
    load_palette,
    render_bead_preview,
    render_sheet_png,
    write_bom_csv,
)

BASE = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
REPOS = BASE / "repos"
OUT_ROOT = BASE / "outputs"


def build_zh_map():
    mard_pal, _ = load_palette()
    return {e["code"]: e["name_zh"] for e in mard_pal}


ZH_MAP = build_zh_map()


def normalize_mard_code(code: str) -> str:
    # Unify A01 vs A1 only if matching, keep canonical MARD code string cleanly
    m = re.fullmatch(r"([A-Z]+)0*(\d+)", code.strip().upper())
    if m:
        return f"{m.group(1)}{int(m.group(2))}"
    return code.strip().upper()


def load_medallion_arrays(name: str):
    rgba_64 = np.array(Image.open(INPUTS_DIR / f"{name}_medallion_64x64.png").convert("RGBA"))
    rgba_640 = np.array(Image.open(INPUTS_DIR / f"{name}_medallion_64x64_upscaled.png").convert("RGBA"))
    mask = rgba_64[:, :, 3] > 0
    return rgba_64, rgba_640, mask


def finalize_grid(
    code_grid: list[list[str | None]],
    pal: list[dict],
    code_to_idx: dict[str, int],
    out_dir: Path,
    file_stem: str,
    title: str,
    subtitle: str,
    palette_name: str = "MARD",
    render_bead: bool = False,
):
    out_dir.mkdir(parents=True, exist_ok=True)
    h = len(code_grid)
    w = len(code_grid[0])
    idx_grid = np.zeros((h, w), dtype=np.int32)
    mask = np.zeros((h, w), dtype=bool)
    for r in range(h):
        for c in range(w):
            code = code_grid[r][c]
            if code is not None and code in code_to_idx:
                mask[r, c] = True
                idx_grid[r, c] = code_to_idx[code]

    sheet_png = out_dir / f"{file_stem}.png"
    bom_csv = out_dir / f"{file_stem}_bom.csv"
    bom, total_beads = render_sheet_png(
        idx_grid, mask, pal, title, subtitle, sheet_png, cell_px=34, palette_name=palette_name
    )
    write_bom_csv(bom, total_beads, pal, bom_csv, palette_name=palette_name)
    if render_bead:
        render_bead_preview(idx_grid, mask, pal, out_dir / f"{file_stem}_bead_preview.png", cell_px=16)
    print(f"[{file_stem}] {w}x{h}, {len(bom)} colors, {total_beads} beads -> {sheet_png}")
    return len(bom), total_beads


# ==============================================================================
# Pathway G: Zippland/perler-beads (Oklab Dominant + Flood-Fill Merge)
# ==============================================================================
def rgb_to_oklab_tuple(rgb):
    def lin(v):
        n = v / 255.0
        return n / 12.92 if n <= 0.04045 else ((n + 0.055) / 1.055) ** 2.4

    r, g, b = lin(rgb[0]), lin(rgb[1]), lin(rgb[2])
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    lr = math.copysign(abs(l) ** (1 / 3), l)
    mr = math.copysign(abs(m) ** (1 / 3), m)
    sr = math.copysign(abs(s) ** (1 / 3), s)
    return (
        0.2104542553 * lr + 0.7936177850 * mr - 0.0040720468 * sr,
        1.9779984951 * lr - 2.4285922050 * mr + 0.4505937099 * sr,
        0.0259040371 * lr + 0.7827717662 * mr - 0.8086757660 * sr,
    )


def oklab_dist100(o1, o2):
    return math.sqrt((o1[0] - o2[0]) ** 2 + (o1[1] - o2[1]) ** 2 + (o1[2] - o2[2]) ** 2) * 100.0


def run_pathway_g_zippland():
    mapping = json.loads((REPOS / "Zippland_perler-beads/src/app/colorSystemMapping.json").read_text("utf-8"))
    pal = []
    for hx, systems in mapping.items():
        code = systems["MARD"]
        r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
        norm_c = normalize_mard_code(code)
        pal.append({
            "code": code,
            "hex": hx,
            "rgb": np.array([r, g, b], dtype=np.uint8),
            "oklab": rgb_to_oklab_tuple((r, g, b)),
            "name_zh": ZH_MAP.get(norm_c, ""),
        })
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}

    for name, cn in [("espeon", "太阳伊布"), ("umbreon", "月亮伊布")]:
        _, rgba_640, mask = load_medallion_arrays(name)
        N, M = 64, 64
        oklab_cache = {}

        def nearest_code(rgb_tup):
            if rgb_tup not in oklab_cache:
                o = rgb_to_oklab_tuple(rgb_tup)
                best_c = min(pal, key=lambda p: oklab_dist100(o, p["oklab"]))["code"]
                oklab_cache[rgb_tup] = best_c
            return oklab_cache[rgb_tup]

        grid = [[None] * N for _ in range(M)]
        for row in range(M):
            y0, y1 = int(row * 10), min(640, math.ceil((row + 1) * 10))
            for col in range(N):
                x0, x1 = int(col * 10), min(640, math.ceil((col + 1) * 10))
                block = rgba_640[y0:y1, x0:x1]
                opaque = block[block[:, :, 3] >= 128][:, :3]
                if len(opaque) == 0:
                    continue
                # Zippland PixelationMode.Dominant: most frequent exact RGB
                pts = [tuple(map(int, px)) for px in opaque]
                dom_rgb = Counter(pts).most_common(1)[0][0]
                grid[row][col] = nearest_code(dom_rgb)

        # Flood-fill single-cell speck absorption within Oklab dist <= 8.5 (from floodFillUtils region awareness)
        visited = [[False] * N for _ in range(M)]
        cleaned = [r[:] for r in grid]
        for r in range(M):
            for c in range(N):
                if grid[r][c] is None or visited[r][c]:
                    continue
                target = grid[r][c]
                q = deque([(r, c)])
                visited[r][c] = True
                region = []
                nbrs = Counter()
                while q:
                    cr, cc = q.popleft()
                    region.append((cr, cc))
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < M and 0 <= nc < N and grid[nr][nc] is not None:
                            if grid[nr][nc] == target and not visited[nr][nc]:
                                visited[nr][nc] = True
                                q.append((nr, nc))
                            elif grid[nr][nc] != target:
                                nbrs[grid[nr][nc]] += 1
                if len(region) == 1 and nbrs:
                    top_nbr, _ = nbrs.most_common(1)[0]
                    o1 = pal[code_to_idx[target]]["oklab"]
                    o2 = pal[code_to_idx[top_nbr]]["oklab"]
                    if oklab_dist100(o1, o2) <= 8.5:
                        cleaned[r][c] = top_nbr

        finalize_grid(
            cleaned, pal, code_to_idx,
            OUT_ROOT / "pathway_G_Zippland" / name,
            f"{name}_G_Zippland_Oklab",
            f"{cn} · Zippland/perler-beads (Oklab 主色提取)",
            "Pathway G: Oklab 感知距离 + Dominant 主色池化 + 洪水填充单点吸收 (MARD)",
            palette_name="MARD",
        )


# ==============================================================================
# Pathway H1 / H2: Jett-Wu/Perler_Beads_Generator (cartoon & realistic)
# ==============================================================================
def run_pathway_h_jettwu():
    pts_text = (REPOS / "JettWu_Perler_Beads_Generator/src/palette.ts").read_text("utf-8")
    m = re.search(r"const rawColorsCsv = `([^`]+)`", pts_text)
    assert m, "Could not parse rawColorsCsv in JettWu palette.ts"
    pal = []
    for line in m.group(1).strip().splitlines():
        code, hx = [s.strip() for s in line.split(",")]
        r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
        pal.append({
            "code": code,
            "hex": hx,
            "rgb": np.array([r, g, b], dtype=np.uint8),
            "rgb_t": (r, g, b),
            "name_zh": ZH_MAP.get(code, ""),
        })
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}

    def color_dist(a, b):
        rm = (a[0] + b[0]) / 2.0
        dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
        return math.sqrt((2.0 + rm / 256.0) * dr * dr + 4.0 * dg * dg + (2.0 + (255.0 - rm) / 256.0) * db * db)

    def luma(rgb):
        return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]

    def chroma(rgb):
        return max(rgb) - min(rgb)

    def simplify_rgb(rgb, strength):
        lv = max(0, min(4, round(strength)))
        if lv == 0:
            return rgb
        step = [1, 5, 9, 14, 20][lv]
        neut = [0, 8, 14, 20, 28][lv]
        if chroma(rgb) <= neut:
            v = max(0, min(255, round(luma(rgb) / step) * step))
            return (v, v, v)
        return tuple(max(0, min(255, round(c / step) * step)) for c in rgb)

    def nearest_color(rgb, candidates):
        return min(candidates, key=lambda c: color_dist(rgb, c["rgb_t"]))

    profiles = {
        "cartoon": dict(
            sampleSide=7, bgThresh=0.72, domThresh=0.34,
            candRatio=0.58, distFactor=1.35, bias=1, avgFallback=False, maxColors=20,
        ),
        "realistic": dict(
            sampleSide=5, bgThresh=0.58, domThresh=0.26,
            candRatio=0.95, distFactor=0.65, bias=-1, avgFallback=True, maxColors=24,
        ),
    }

    def are_similar(fr, to, strength, rare):
        if fr is None or to is None or fr["code"] == to["code"]:
            return False
        lv = max(0, min(4, round(strength)))
        base_t = [0, 26, 42, 62, 84][lv]
        if base_t <= 0:
            return False
        fc, tc = chroma(fr["rgb_t"]), chroma(to["rgb_t"])
        fl, tl = luma(fr["rgb_t"]), luma(to["rgb_t"])
        dist = color_dist(fr["rgb_t"], to["rgb_t"])
        both_dark = fl < 84 and tl < 84
        both_light = fl > 188 and tl > 188 and fc < 46 and tc < 46
        both_muted = fl > 96 and tl > 96 and fc < 82 and tc < 82
        thresh = base_t * (1.45 if rare else 1.0)
        if both_dark or both_light or both_muted:
            thresh *= 1.15
        if fc > 78 or tc > 78:
            thresh *= 0.7
        if abs(fc - tc) > 56:
            thresh *= 0.58
        if abs(fl - tl) > 86 and not both_dark:
            thresh *= 0.55
        return dist <= thresh

    for style_key, prof in profiles.items():
        tag = "H1" if style_key == "cartoon" else "H2"
        title_mode = "卡通模式 (Cartoon 20色)" if style_key == "cartoon" else "写实模式 (Realistic 24色)"
        req_speckle = 1
        speckle_str = max(0, min(4, req_speckle + prof["bias"]))
        side = prof["sampleSide"]

        for name, cn in [("espeon", "太阳伊布"), ("umbreon", "月亮伊布")]:
            _, rgba_640, _ = load_medallion_arrays(name)
            sw, sh = 640, 640
            w, h = 64, 64
            sampled = []
            for y in range(h):
                for x in range(w):
                    samples = []
                    bg_cnt = 0
                    sr = sg = sb = 0
                    for sy in range(side):
                        for sx in range(side):
                            px = min(sw - 1, max(0, math.floor(((x + (sx + 0.5) / side) / w) * sw)))
                            py = min(sh - 1, max(0, math.floor(((y + (sy + 0.5) / side) / h) * sh)))
                            r, g, b, a = map(int, rgba_640[py, px])
                            if a < 24:
                                bg_cnt += 1
                                continue
                            simp = simplify_rgb((r, g, b), speckle_str)
                            samples.append(simp)
                            sr += simp[0]
                            sg += simp[1]
                            sb += simp[2]
                    avg = (round(sr / len(samples)), round(sg / len(samples)), round(sb / len(samples))) if samples else None
                    sampled.append((samples, avg, bg_cnt / (side * side)))

            # Rank palette colors
            counts = Counter()
            total_s = 0
            nearest_cache = {}
            for samples, _, bg_sh in sampled:
                if bg_sh >= prof["bgThresh"] or not samples:
                    continue
                for rgb in samples:
                    total_s += 1
                    if rgb not in nearest_cache:
                        nearest_cache[rgb] = nearest_color(rgb, pal)["code"]
                    counts[nearest_cache[rgb]] += 1

            ranked = []
            for code, cnt in counts.items():
                col = pal[code_to_idx[code]]
                ch = chroma(col["rgb_t"])
                lt = luma(col["rgb_t"])
                sh_r = cnt / max(1, total_s)
                ab = 2.25 if ch > 48 else (1.4 if ch > 28 else 1.0)
                mb = 2.45 if (ch > 58 and sh_r < 0.018) else 1.0
                db = 1.55 if lt < 48 else 1.0
                ln = 0.82 if (lt > 210 and ch < 22) else 1.0
                ranked.append({"color": col, "count": cnt, "score": cnt * ab * mb * db * ln})
            ranked.sort(key=lambda e: (-e["score"], -e["count"]))

            max_c = prof["maxColors"]
            lv = max(0, min(4, round(speckle_str)))
            selected = []
            sel_ids = set()

            def add_col(c, allow_sim=False):
                if c["code"] in sel_ids or len(selected) >= max_c:
                    return False
                if not allow_sim and selected:
                    ch = chroma(c["rgb_t"])
                    base_th = 18 if (luma(c["rgb_t"]) < 48 or ch > 58) else 34
                    th = (base_th + lv * (3 if ch > 58 else 7)) * prof["distFactor"]
                    nd = min(color_dist(c["rgb_t"], s["rgb_t"]) for s in selected)
                    if nd < th:
                        return False
                selected.append(c)
                sel_ids.add(c["code"])
                return True

            for e in sorted(ranked, key=lambda x: -x["count"]):
                if len(selected) < math.ceil(max_c * 0.28):
                    add_col(e["color"])

            max_cnt = max(1, ranked[0]["count"])
            prot_slots = max(2, math.ceil(max_c * (0.28 if prof["avgFallback"] else 0.22)))

            def is_feat(e):
                sh_l = e["count"] / max_cnt
                ch = chroma(e["color"]["rgb_t"])
                lt = luma(e["color"]["rgb_t"])
                return (ch > 70 and sh_l > 0.002) or (ch > 52 and sh_l > 0.006) or (lt < 36 and sh_l > 0.003)

            def is_feat_col(c):
                return chroma(c["rgb_t"]) > 48 or luma(c["rgb_t"]) < 45

            def allow_feat_sim(c):
                if not selected:
                    return False
                nd = min(color_dist(c["rgb_t"], s["rgb_t"]) for s in selected)
                return chroma(c["rgb_t"]) > 68 and nd > 14

            feat_cands = []
            for e in ranked:
                if is_feat(e):
                    ch = chroma(e["color"]["rgb_t"])
                    lt = luma(e["color"]["rgb_t"])
                    sd = min((color_dist(e["color"]["rgb_t"], s["rgb_t"]) for s in selected), default=90)
                    fscore = math.sqrt(max(1, e["count"])) * (1 + min(3.2, ch / 34)) * (1.8 if lt < 42 else 1.0) * max(0.8, min(4.5, sd / 22))
                    feat_cands.append((fscore, e))
            feat_cands.sort(key=lambda x: -x[0])
            for _, e in feat_cands:
                if len(selected) < max_c and sum(1 for c in selected if is_feat_col(c)) < prot_slots:
                    add_col(e["color"], allow_feat_sim(e["color"]))
            for e in ranked:
                if is_feat_col(e["color"]):
                    add_col(e["color"], allow_feat_sim(e["color"]))

            target_div = math.ceil(max_c * prof["candRatio"])
            while len(selected) < min(max_c, target_div):
                div_list = []
                for e in ranked:
                    if e["color"]["code"] in sel_ids:
                        continue
                    if not selected:
                        ds = e["score"]
                    else:
                        d = min(color_dist(e["color"]["rgb_t"], s["rgb_t"]) for s in selected)
                        ch = chroma(e["color"]["rgb_t"])
                        lt = luma(e["color"]["rgb_t"])
                        db = max(0.35, min(5.4, (d / 26.0) ** 1.55))
                        fb = 2.15 if (ch > 58 or lt < 48) else (1.36 if ch > 34 else 1.0)
                        ds = math.sqrt(max(1, e["count"])) * db * fb
                    div_list.append((ds, e))
                div_list.sort(key=lambda x: -x[0])
                if not any(add_col(e["color"]) for _, e in div_list):
                    break

            for e in ranked:
                add_col(e["color"])
            if prof["avgFallback"] or len(selected) < min(6, max_c):
                for e in ranked:
                    add_col(e["color"], True)

            # Choose cell color
            cells = []
            for samples, avg, bg_sh in sampled:
                if bg_sh >= prof["bgThresh"] or not samples:
                    cells.append(None)
                    continue
                cc = Counter(nearest_color(rgb, selected)["code"] for rgb in samples)
                prim_c, prim_n = cc.most_common(1)[0]
                if prim_n / len(samples) >= prof["domThresh"] or (not prof["avgFallback"]) or avg is None:
                    cells.append(prim_c)
                else:
                    cells.append(nearest_color(avg, selected)["code"])

            # Post-processing: mergeSimilarColors -> reduceTinyRegions -> reduceSpeckles
            if round(speckle_str) > 0:
                cnt_c = Counter(c for c in cells if c)
                rows = sorted([(c, pal[code_to_idx[c]], n) for c, n in cnt_c.items()], key=lambda x: -x[2])
                tot = sum(x[2] for x in rows)
                repl = {}
                for i, (cid, col_obj, cnt_i) in enumerate(rows):
                    rare = cnt_i <= max(3, tot * (0.006 + round(speckle_str) * 0.003))
                    for c_cid, c_col, _ in rows[:i]:
                        if are_similar(col_obj, c_col, round(speckle_str), rare):
                            repl[cid] = repl.get(c_cid, c_cid)
                            break
                cells = [repl.get(c, c) if c else None for c in cells]

                max_reg = [0, 1, 2, 5, 9][max(0, min(4, round(speckle_str)))]
                if max_reg > 0:
                    nxt = cells[:]
                    vis = [False] * len(cells)
                    for st in range(len(cells)):
                        cid = cells[st]
                        if not cid or vis[st]:
                            continue
                        reg = []
                        bcnt = Counter()
                        q = [st]
                        vis[st] = True
                        cur = 0
                        while cur < len(q):
                            idx = q[cur]
                            cur += 1
                            reg.append(idx)
                            cx, cy = idx % w, idx // w
                            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                                nx, ny = cx + dx, cy + dy
                                if 0 <= nx < w and 0 <= ny < h:
                                    ni = ny * w + nx
                                    nc = cells[ni]
                                    if nc == cid and not vis[ni]:
                                        vis[ni] = True
                                        q.append(ni)
                                    elif nc and nc != cid:
                                        bcnt[nc] += 1
                        if len(reg) <= max_reg and bcnt:
                            for cand_c, _ in bcnt.most_common():
                                if are_similar(pal[code_to_idx[cid]], pal[code_to_idx[cand_c]], speckle_str, True):
                                    for ri in reg:
                                        nxt[ri] = cand_c
                                    break
                    cells = nxt

                iters = max(0, min(4, round(speckle_str)))
                for p_i in range(iters):
                    cur_g = cells[:]
                    cells = cur_g[:]
                    req_m = (3 if p_i == 0 else 4) if iters >= 4 else (4 if p_i == 0 else 5)
                    same_l = (2 if p_i == 0 else 1) if iters >= 4 else (1 if p_i == 0 else 0)
                    for yy in range(h):
                        for xx in range(w):
                            idx = yy * w + xx
                            cid = cur_g[idx]
                            if not cid:
                                continue
                            nbr = []
                            for dy in (-1, 0, 1):
                                for dx in (-1, 0, 1):
                                    if dx == 0 and dy == 0:
                                        continue
                                    nx, ny = xx + dx, yy + dy
                                    if 0 <= nx < w and 0 <= ny < h and cur_g[ny * w + nx]:
                                        nbr.append(cur_g[ny * w + nx])
                            if not nbr:
                                continue
                            maj_c, maj_n = Counter(nbr).most_common(1)[0]
                            same_n = sum(1 for c in nbr if c == cid)
                            if are_similar(pal[code_to_idx[cid]], pal[code_to_idx[maj_c]], speckle_str, False):
                                if same_n <= same_l and maj_n >= req_m:
                                    cells[idx] = maj_c

            code_grid = [cells[r * w : (r + 1) * w] for r in range(h)]
            finalize_grid(
                code_grid, pal, code_to_idx,
                OUT_ROOT / "pathway_H_JettWu" / name,
                f"{name}_{tag}_JettWu_{style_key}",
                f"{cn} · Jett-Wu ({title_mode})",
                f"Pathway {tag}: Jett-Wu {side}×{side}网格采样 + 特征高饱和保色 + 去杂点后处理 (MARD)",
                palette_name="MARD",
            )


# ==============================================================================
# Pathway I: saratran/bead-tune (blockMode + extremeColors + removeStrays KEEP_CONTRAST=30)
# ==============================================================================
def run_pathway_i_beadtune():
    txt = (REPOS / "saratran_bead-tune/src/lib/beadcolors.gen.ts").read_text("utf-8")
    m = re.search(r"export const mard: Row\[\] = \[(.*?)\];", txt, re.S)
    assert m, "Could not parse mard array in beadcolors.gen.ts"
    pal = []
    for code, cname, hx in re.findall(r'\["([^"]+)","([^"]*)","(#[0-9A-Fa-f]{6})"\]', m.group(1)):
        if not re.fullmatch(r"[A-M]\d+", code):
            continue  # mard-221 preset in palettes.ts
        r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
        pal.append({
            "code": code,
            "hex": hx,
            "rgb": np.array([r, g, b], dtype=np.uint8),
            "name_zh": ZH_MAP.get(code, cname),
        })
    pal_rgb = np.stack([p["rgb"] for p in pal], axis=0)
    pal_lab = skcolor.rgb2lab(pal_rgb.astype(np.float64) / 255.0)
    for i, p in enumerate(pal):
        p["lab"] = pal_lab[i]
    code_to_idx = {p["code"]: i for i, p in enumerate(pal)}

    # Pairwise CIEDE2000 matrix between palette entries (N=221 -> fast vectorized)
    n_pal = len(pal)
    q = np.broadcast_to(pal_lab[:, None, :], (n_pal, n_pal, 3))
    p = np.broadcast_to(pal_lab[None, :, :], (n_pal, n_pal, 3))
    pair_de = skcolor.deltaE_ciede2000(q, p)

    for name, cn in [("espeon", "太阳伊布"), ("umbreon", "月亮伊布")]:
        _, rgba_640, _ = load_medallion_arrays(name)
        w, h, k = 64, 64, 10
        sampled_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        fg_mask = np.zeros((h, w), dtype=bool)
        for by in range(h):
            for bx in range(w):
                blk = rgba_640[by * k : (by + 1) * k, bx * k : (bx + 1) * k]
                opq = blk[blk[:, :, 3] >= 128][:, :3]
                if len(opq) * 2 < (k * k):
                    continue
                fg_mask[by, bx] = True
                # 16-level coarse grouping dominant color
                groups = {}
                for px in opq:
                    key = (int(px[0]) >> 4, int(px[1]) >> 4, int(px[2]) >> 4)
                    g_acc = groups.setdefault(key, [0, 0, 0, 0])
                    g_acc[0] += 1
                    g_acc[1] += int(px[0])
                    g_acc[2] += int(px[1])
                    g_acc[3] += int(px[2])
                best_g = max(groups.values(), key=lambda v: v[0])
                sampled_rgb[by, bx] = [
                    round(best_g[1] / best_g[0]),
                    round(best_g[2] / best_g[0]),
                    round(best_g[3] / best_g[0]),
                ]

        # Pass 1: full palette CIEDE2000 match
        fg_labs = skcolor.rgb2lab(sampled_rgb[fg_mask].astype(np.float64) / 255.0)
        q_fg = np.broadcast_to(fg_labs[:, None, :], (fg_labs.shape[0], n_pal, 3))
        p_fg = np.broadcast_to(pal_lab[None, :, :], (fg_labs.shape[0], n_pal, 3))
        first_idx = np.argmin(skcolor.deltaE_ciede2000(q_fg, p_fg), axis=1)

        usage = np.bincount(first_idx, minlength=n_pal).astype(float)

        # extremeColors protection (darkest & brightest 0.5%)
        fg_arr = sampled_rgb[fg_mask].astype(np.float64) / 255.0
        lin_rgb = np.where(fg_arr <= 0.04045, fg_arr / 12.92, ((fg_arr + 0.055) / 1.055) ** 2.4)
        luma = 0.2126 * lin_rgb[:, 0] + 0.7152 * lin_rgb[:, 1] + 0.0722 * lin_rgb[:, 2]
        order_l = np.argsort(luma)
        k_ext = max(1, round(len(luma) * 0.005))
        protect = set()
        for sl in (order_l[:k_ext], order_l[-k_ext:]):
            mean_rgb = fg_arr[sl].mean(axis=0)
            t_lab = skcolor.rgb2lab(mean_rgb.reshape(1, 1, 3))[0, 0]
            used_indices = [idx for idx in range(n_pal) if usage[idx] > 0]
            best_ex = min(used_indices, key=lambda idx: float(skcolor.deltaE_ciede2000(t_lab, pal_lab[idx])))
            protect.add(best_ex)

        # greedy reducePalette(maxColors=20)
        kept = [i for i in range(n_pal) if usage[i] > 0]
        weights = usage.copy()
        while len(kept) > 20:
            worst = -1
            worst_cost = float("inf")
            worst_target = -1
            for a_i, ia in enumerate(kept):
                if ia in protect and len(kept) > len(protect):
                    continue
                nearest_b = min((ib for ib in kept if ib != ia), key=lambda ib: pair_de[ia, ib])
                cost = weights[ia] * pair_de[ia, nearest_b]
                if cost < worst_cost:
                    worst_cost = cost
                    worst = a_i
                    worst_target = nearest_b
            weights[worst_target] += weights[kept[worst]]
            kept.pop(worst)

        # Pass 2: remap onto kept 20 colors
        kept_arr = np.array(kept)
        kept_labs = pal_lab[kept_arr]
        q_k = np.broadcast_to(fg_labs[:, None, :], (fg_labs.shape[0], len(kept_arr), 3))
        p_k = np.broadcast_to(kept_labs[None, :, :], (fg_labs.shape[0], len(kept_arr), 3))
        mapped_kept = kept_arr[np.argmin(skcolor.deltaE_ciede2000(q_k, p_k), axis=1)]

        raw = np.full((h, w), -1, dtype=np.int32)
        raw[fg_mask] = mapped_kept

        # removeStrays(maxSize=2, keepContrast=30) - protect eyes/pupils/sparkles!
        max_size = 2
        keep_contrast = 30.0
        seen = np.zeros((h, w), dtype=bool)
        for sr in range(h):
            for sc in range(w):
                if seen[sr, sc] or raw[sr, sc] == -1:
                    continue
                val = int(raw[sr, sc])
                grp = [(sr, sc)]
                seen[sr, sc] = True
                qi = 0
                while qi < len(grp):
                    cr, cc = grp[qi]
                    qi += 1
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < h and 0 <= nc < w and not seen[nr, nc] and raw[nr, nc] == val:
                            seen[nr, nc] = True
                            grp.append((nr, nc))
                if len(grp) > max_size:
                    continue
                in_grp = set(grp)
                around = Counter()
                for cr, cc in grp:
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < h and 0 <= nc < w and (nr, nc) not in in_grp and raw[nr, nc] >= 0:
                            around[int(raw[nr, nc])] += 1
                if not around:
                    continue
                best_nbr, _ = around.most_common(1)[0]
                if abs(pal_lab[val, 0] - pal_lab[best_nbr, 0]) >= keep_contrast:
                    continue  # contrast guard protects eye/sparkle!
                for cr, cc in grp:
                    raw[cr, cc] = best_nbr

        code_grid = [[pal[raw[r, c]]["code"] if raw[r, c] >= 0 else None for c in range(w)] for r in range(h)]
        finalize_grid(
            code_grid, pal, code_to_idx,
            OUT_ROOT / "pathway_I_bead_tune" / name,
            f"{name}_I_bead_tune",
            f"{cn} · saratran/bead-tune (20色 眼神光对比保护)",
            "Pathway I: blockMode + reducePalette 极端明暗保护 + removeStrays(|ΔL|≥30防误删)",
            palette_name="MARD",
        )


# ==============================================================================
# Pathway J: Ibook000/beadforge (medianCutLab + Atkinson/Floyd-Steinberg + despeckle)
# ==============================================================================
def run_pathway_j_beadforge():
    txt = (REPOS / "Ibook000_beadforge/src/palette/data/mard.ts").read_text("utf-8")
    objs = re.findall(
        r'\{\s*"code":\s*"([^"]+)",\s*"name":\s*"[^"]+",\s*"nameZh":\s*"([^"]+)",\s*"hex":\s*"(#[0-9A-Fa-f]{6})",\s*"rgb":\s*\[\s*(\d+),\s*(\d+),\s*(\d+)\s*\],\s*"lab":\s*\[\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)\s*\]\s*\}',
        txt,
    )
    assert len(objs) >= 200, f"Parsed only {len(objs)} beads from beadforge mard.ts"
    pal = []
    for code, name_zh, hx, r, g, b, L, a_v, b_v in objs:
        pal.append({
            "code": code,
            "hex": hx,
            "rgb": np.array([int(r), int(g), int(b)], dtype=np.uint8),
            "lab": np.array([float(L), float(a_v), float(b_v)], dtype=np.float64),
            "name_zh": name_zh,
        })
    pal_lab = np.stack([p["lab"] for p in pal], axis=0)
    code_to_idx = {p["code"]: i for i, p in enumerate(pal)}

    def srgb_to_lin(c01):
        return c01 / 12.92 if c01 <= 0.04045 else ((c01 + 0.055) / 1.055) ** 2.4

    def lin_to_srgb(lin):
        lin = max(0.0, min(1.0, lin))
        return 12.92 * lin if lin <= 0.0031308 else 1.055 * (lin ** (1 / 2.4)) - 0.055

    def median_cut_lab(colors_rgb, max_colors):
        counts = Counter(colors_rgb)
        entries = []
        for rgb_t, w in counts.items():
            lab = skcolor.rgb2lab(np.array(rgb_t, dtype=np.float64).reshape(1, 1, 3) / 255.0)[0, 0]
            entries.append((lab, w))

        def make_box(ents):
            axis, spread = 0, -1.0
            for k in (0, 1, 2):
                vals = [e[0][k] for e in ents]
                s = max(vals) - min(vals)
                if s > spread:
                    spread = s
                    axis = k
            return {"entries": ents, "spread": spread, "axis": axis}

        boxes = [make_box(entries)]
        while len(boxes) < max_colors:
            splittable = [i for i, b in enumerate(boxes) if len(b["entries"]) > 1]
            if not splittable:
                break
            bi = max(splittable, key=lambda i: boxes[i]["spread"])
            box = boxes.pop(bi)
            ax = box["axis"]
            srt = sorted(box["entries"], key=lambda e: e[0][ax])
            tw = sum(e[1] for e in srt)
            lw = 0
            best_cut, best_sc = 1, -1.0
            for i in range(len(srt) - 1):
                lw += srt[i][1]
                gap = srt[i + 1][0][ax] - srt[i][0][ax]
                sc = gap * (min(lw, tw - lw) / tw)
                if sc > best_sc:
                    best_sc = sc
                    best_cut = i + 1
            boxes.append(make_box(srt[:best_cut]))
            boxes.append(make_box(srt[best_cut:]))

        reps = []
        for box in boxes:
            tw = sum(e[1] for e in box["entries"])
            L = sum(e[0][0] * e[1] for e in box["entries"]) / tw
            a = sum(e[0][1] * e[1] for e in box["entries"]) / tw
            b = sum(e[0][2] * e[1] for e in box["entries"]) / tw
            rgb01 = np.clip(skcolor.lab2rgb(np.array([L, a, b]).reshape(1, 1, 3))[0, 0], 0, 1)
            reps.append(tuple(int(round(v * 255)) for v in rgb01))
        return reps

    KERNELS = {
        "atkinson": [(1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8), (0, 1, 1 / 8), (1, 1, 1 / 8), (0, 2, 1 / 8)],
        "floyd-steinberg": [(1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)],
    }

    for name, cn in [("espeon", "太阳伊布"), ("umbreon", "月亮伊布")]:
        _, rgba_640, _ = load_medallion_arrays(name)
        w, h = 64, 64
        # Step 1: linear RGB average sampling
        sampled = np.zeros((h, w, 3), dtype=np.uint8)
        mask = np.zeros((h, w), dtype=bool)
        for oy in range(h):
            for ox in range(w):
                blk = rgba_640[oy * 10 : (oy + 1) * 10, ox * 10 : (ox + 1) * 10]
                opq = blk[blk[:, :, 3] >= 128][:, :3]
                if len(opq) == 0:
                    continue
                mask[oy, ox] = True
                arr01 = opq.astype(np.float64) / 255.0
                lin = np.where(arr01 <= 0.04045, arr01 / 12.92, ((arr01 + 0.055) / 1.055) ** 2.4).mean(axis=0)
                for ch in range(3):
                    sampled[oy, ox, ch] = round(lin_to_srgb(float(lin[ch])) * 255)

        # J1: medianCutLab(24) + Atkinson dithering + despeckle('weak')
        reps = median_cut_lab([tuple(map(int, sampled[r, c])) for r in range(h) for c in range(w) if mask[r, c]], 24)
        rep_labs = skcolor.rgb2lab(np.array(reps, dtype=np.float64).reshape(-1, 1, 3) / 255.0).reshape(-1, 3)
        quant_rgb = sampled.copy()
        fg_labs_q = skcolor.rgb2lab(sampled[mask].astype(np.float64) / 255.0)
        q_mat = np.broadcast_to(fg_labs_q[:, None, :], (fg_labs_q.shape[0], len(reps), 3))
        p_mat = np.broadcast_to(rep_labs[None, :, :], (fg_labs_q.shape[0], len(reps), 3))
        rep_idx = np.argmin(skcolor.deltaE_ciede2000(q_mat, p_mat), axis=1)
        quant_rgb[mask] = np.array([reps[i] for i in rep_idx], dtype=np.uint8)

        def run_dither(src_rgb, mode_name, do_despeckle_weak):
            match_cache = {}

            def match_ciede(rgb_t):
                if rgb_t not in match_cache:
                    lab = skcolor.rgb2lab(np.array(rgb_t, dtype=np.float64).reshape(1, 1, 3) / 255.0)[0, 0]
                    q_l = np.broadcast_to(lab[None, :], pal_lab.shape)
                    match_cache[rgb_t] = int(np.argmin(skcolor.deltaE_ciede2000(q_l, pal_lab)))
                return match_cache[rgb_t]

            buf = np.zeros((h, w, 3), dtype=np.float64)
            for r in range(h):
                for c in range(w):
                    for ch in range(3):
                        buf[r, c, ch] = srgb_to_lin(src_rgb[r, c, ch] / 255.0)
            cells = np.zeros((h, w), dtype=np.int32)
            kernel = KERNELS[mode_name]
            for y in range(h):
                for x in range(w):
                    if not mask[y, x]:
                        continue
                    rgb_t = tuple(max(0, min(255, round(lin_to_srgb(float(buf[y, x, ch])) * 255))) for ch in range(3))
                    b_idx = match_ciede(rgb_t)
                    cells[y, x] = b_idx
                    chosen = pal[b_idx]["rgb"]
                    err = [buf[y, x, ch] - srgb_to_lin(int(chosen[ch]) / 255.0) for ch in range(3)]
                    for dx, dy, wt in kernel:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h and mask[ny, nx]:
                            for ch in range(3):
                                buf[ny, nx, ch] += err[ch] * wt

            if do_despeckle_weak:
                out = cells.copy()
                for y in range(h):
                    for x in range(w):
                        if not mask[y, x]:
                            continue
                        cnt = Counter()
                        for dy in (-1, 0, 1):
                            for dx in (-1, 0, 1):
                                nx, ny = x + dx, y + dy
                                if 0 <= nx < w and 0 <= ny < h and mask[ny, nx]:
                                    cnt[int(cells[ny, nx])] += 1
                        self_idx = int(cells[y, x])
                        if cnt[self_idx] <= 1:
                            best_v = min(cnt.keys(), key=lambda v: (-cnt[v], v))
                            out[y, x] = best_v
                cells = out

            return [[pal[cells[r, c]]["code"] if mask[r, c] else None for c in range(w)] for r in range(h)]

        g_j1 = run_dither(quant_rgb, "atkinson", True)
        finalize_grid(
            g_j1, pal, code_to_idx,
            OUT_ROOT / "pathway_J_beadforge" / name,
            f"{name}_J1_beadforge_Atkinson",
            f"{cn} · Ibook000/beadforge (medianCut24 + Atkinson抖动)",
            "Pathway J1: Lab medianCut 24色 + linearRGB Atkinson 3/4误差扩散 + 去孤点",
            palette_name="MARD",
        )

        g_j2 = run_dither(sampled, "floyd-steinberg", False)
        finalize_grid(
            g_j2, pal, code_to_idx,
            OUT_ROOT / "pathway_J_beadforge" / name,
            f"{name}_J2_beadforge_FloydSteinberg",
            f"{cn} · Ibook000/beadforge (Floyd-Steinberg 全色抖动)",
            "Pathway J2: linearRGB Floyd-Steinberg 全色误差扩散 + CIEDE2000 (MARD)",
            palette_name="MARD",
        )


# ==============================================================================
# Pathway K: cornelk/beadmachine (Native Compiled Go CLI + Hama Palette)
# ==============================================================================
class BeadmachineHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_row = False
        self.row_class = ""
        self.in_td = False
        self.rows_codes = []
        self.curr_row = []
        self.curr_text = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.row_class = d.get("class", "")
            self.curr_row = []
        elif tag == "td" and self.in_row and "bg" in self.row_class:
            self.in_td = True
            self.curr_text = []

    def handle_data(self, data):
        if self.in_td:
            self.curr_text.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            txt = "".join(self.curr_text).replace("\xa0", "").strip()
            self.curr_row.append(txt)
            self.in_td = False
        elif tag == "tr" and self.in_row:
            if "bg" in self.row_class and self.curr_row:
                self.rows_codes.append(self.curr_row)
            self.in_row = False


def run_pathway_k_beadmachine():
    bm_dir = REPOS / "beadmachine"
    bm_exe = bm_dir / "beadmachine.exe"
    hama_json = json.loads((bm_dir / "colors_hama.json").read_text("utf-8"))
    pal = []
    for full_name, info in hama_json.items():
        if info.get("Translucent") or info.get("fluorescent"):
            continue
        short = full_name.split(" ")[0]
        r, g, b = int(info["r"]), int(info["g"]), int(info["b"])
        hx = f"#{r:02X}{g:02X}{b:02X}"
        label_en = full_name[len(short) + 1 :] if len(full_name) > len(short) + 1 else ""
        pal.append({
            "code": short,
            "hex": hx,
            "rgb": np.array([r, g, b], dtype=np.uint8),
            "name_zh": label_en,
        })
    code_to_idx = {p["code"]: i for i, p in enumerate(pal)}

    for name, cn in [("espeon", "太阳伊布"), ("umbreon", "月亮伊布")]:
        run_dir = OUT_ROOT / "pathway_K_beadmachine" / name
        run_dir.mkdir(parents=True, exist_ok=True)
        in_64 = INPUTS_DIR / f"{name}_medallion_64x64.png"
        raw_png = run_dir / f"{name}_beadmachine_raw.png"
        bead_png = run_dir / f"{name}_beadmachine_beadstyle_raw.png"
        raw_html = run_dir / f"{name}_beadmachine.html"

        subprocess.run(
            [str(bm_exe), "-i", str(in_64), "-o", str(raw_png), "-l", str(raw_html), "-p", "colors_hama.json"],
            cwd=str(bm_dir),
            check=True,
        )
        subprocess.run(
            [str(bm_exe), "-i", str(in_64), "-o", str(bead_png), "-b", "-p", "colors_hama.json"],
            cwd=str(bm_dir),
            check=True,
        )

        parser = BeadmachineHtmlParser()
        parser.feed(raw_html.read_text("utf-8"))
        rows_codes = parser.rows_codes
        assert len(rows_codes) == 64 and len(rows_codes[0]) == 64, f"Unexpected HTML grid {len(rows_codes)}x{len(rows_codes[0])}"

        _, _, fg_mask = load_medallion_arrays(name)
        code_grid = [
            [rows_codes[r][c] if fg_mask[r, c] else None for c in range(64)]
            for r in range(64)
        ]
        finalize_grid(
            code_grid, pal, code_to_idx,
            run_dir,
            f"{name}_K_beadmachine_Hama",
            f"{cn} · cornelk/beadmachine Go CLI (Hama 色卡)",
            "Pathway K: 原生 Go 编译版 CIE2000 (D50) Hama 匹配 + 外框透明剔除",
            palette_name="Hama",
            render_bead=True,
        )


# ==============================================================================
# Pathway L: KerroKapple/Perler (Native Node ESM sRGB Euclidean)
# ==============================================================================
def run_pathway_l_kerrokapple():
    pal, _ = load_palette()
    code_to_idx = {e["code"]: i for i, e in enumerate(pal)}
    pal_hexes = [e["hex"] for e in pal]
    lib_url = (REPOS / "KerroKapple_Perler/src/lib.js").resolve().as_uri()

    for name, cn in [("espeon", "太阳伊布"), ("umbreon", "月亮伊布")]:
        rgba_64, _, fg_mask = load_medallion_arrays(name)
        flat_rgba = rgba_64.reshape(-1).tolist()
        payload = {"rgba": flat_rgba, "w": 64, "h": 64, "palette": pal_hexes}
        js = f"""
        import {{ gridFromImageData }} from {json.dumps(lib_url)};
        const input = JSON.parse(await new Promise(res => {{
          let s = ''; process.stdin.on('data', d => s += d); process.stdin.on('end', () => res(s));
        }}));
        const out = gridFromImageData(Uint8ClampedArray.from(input.rgba), input.w, input.h, input.palette);
        process.stdout.write(JSON.stringify(out));
        """
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", js],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
        idxs = json.loads(proc.stdout)
        code_grid = [
            [pal[idxs[r * 64 + c]]["code"] if fg_mask[r, c] else None for c in range(64)]
            for r in range(64)
        ]
        finalize_grid(
            code_grid, pal, code_to_idx,
            OUT_ROOT / "pathway_L_KerroKapple" / name,
            f"{name}_L_KerroKapple_sRGB",
            f"{cn} · KerroKapple/Perler (纯 sRGB 最近匹配)",
            "Pathway L: 原生 Node ESM gridFromImageData 纯 sRGB 欧氏距离基线 (MARD 221色)",
            palette_name="MARD",
        )


if __name__ == "__main__":
    print("=== Pathway G: Zippland/perler-beads ===")
    run_pathway_g_zippland()
    print("=== Pathway H1/H2: Jett-Wu/Perler_Beads_Generator ===")
    run_pathway_h_jettwu()
    print("=== Pathway I: saratran/bead-tune ===")
    run_pathway_i_beadtune()
    print("=== Pathway J1/J2: Ibook000/beadforge ===")
    run_pathway_j_beadforge()
    print("=== Pathway K: cornelk/beadmachine ===")
    run_pathway_k_beadmachine()
    print("=== Pathway L: KerroKapple/Perler ===")
    run_pathway_l_kerrokapple()
    print("ALL STEP 4 ALGORITHMS COMPLETE.")
