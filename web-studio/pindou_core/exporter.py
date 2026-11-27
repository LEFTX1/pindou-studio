# -*- coding: utf-8 -*-
"""
统一拼豆导出与互操作层：
- .pindou.json (schemaVersion 4) 读写
- 5 大国内品牌用豆清点（含 +10% 备豆与物理厘米/拼板规格）
- 高清施工图纸 PNG 渲染（支持任意 5 大品牌直接标注）
- 2.6mm 热熨平融质感 JPG 预览渲染
- UTF-8-SIG 五品牌采购清单 CSV 导出
"""

from __future__ import annotations

import base64
from collections import Counter
import csv
import datetime
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .palette import get_palette_maps, normalize_mard_code, translate_code
from .quantize_helpers import render_baked_flat_melt_preview
from .standards import (
    DEFAULT_BEAD_MM,
    DEFAULT_BRAND,
    DEFAULT_SPARE_RATIO,
    DOMESTIC_BRANDS,
    calc_physical_spec,
)


def _load_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载 Windows 中文与等宽字体，确保网格色号与表头中文清晰渲染。"""
    if mono:
        candidates = [
            r"C:\Windows\Fonts\consolab.ttf" if bold else r"C:\Windows\Fonts\consola.ttf",
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        ]
    else:
        candidates = [
            r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def grid_to_idx_mask(grid: list[list[str | None]]) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """将二维 MARD 色号矩阵转为 (idx_grid, mask, full_palette)。"""
    pal, _, code_to_idx, _, _ = get_palette_maps()
    h = len(grid)
    w = len(grid[0]) if h > 0 else 0
    idx_grid = np.zeros((h, w), dtype=np.int32)
    mask = np.zeros((h, w), dtype=bool)
    fallback_idx = code_to_idx.get("H1", 0)
    for r in range(h):
        row = grid[r]
        for c in range(w):
            cell = row[c] if c < len(row) else None
            if cell is None or str(cell).strip() == "":
                continue
            norm = normalize_mard_code(str(cell))
            idx_grid[r, c] = code_to_idx.get(norm, fallback_idx)
            mask[r, c] = True
    return idx_grid, mask, pal


def idx_mask_to_grid(idx_grid: np.ndarray, mask: np.ndarray, pal: list[dict[str, Any]]) -> list[list[str | None]]:
    """将 (idx_grid, mask) 转回二维 MARD 色号矩阵。"""
    h, w = idx_grid.shape
    return [
        [pal[int(idx_grid[r, c])]["code"] if mask[r, c] else None for c in range(w)]
        for r in range(h)
    ]


def load_pindou_json(source: str | Path | bytes | dict[str, Any]) -> dict[str, Any]:
    """解析 schemaVersion 4 `.pindou.json` 并返回标准网格结构。"""
    if isinstance(source, dict):
        data = source
    elif isinstance(source, bytes):
        data = json.loads(source.decode("utf-8"))
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))

    proj = (data.get("projects") or [{}])[0]
    pattern = proj.get("pattern") or {}
    snap = pattern.get("snapshot") or {}
    w = int(snap.get("w", 0))
    h = int(snap.get("h", 0))
    comp = snap.get("c") or {}
    p_codes = [normalize_mard_code(c) for c in (comp.get("p") or [])]
    size = int(comp.get("s", 1))
    raw = base64.b64decode(comp.get("d", ""))

    grid: list[list[str | None]] = []
    for r in range(h):
        row: list[str | None] = []
        for c in range(w):
            idx = r * w + c
            if size == 1:
                val = raw[idx] if idx < len(raw) else 0
            else:
                off = 2 * idx
                val = (raw[off] | (raw[off + 1] << 8)) if off + 1 < len(raw) else 0
            if val == 0 or val > len(p_codes):
                row.append(None)
            else:
                row.append(p_codes[val - 1])
        grid.append(row)

    name = str(pattern.get("name") or proj.get("name") or "未命名拼豆图纸")
    return {"name": name, "width": w, "height": h, "grid": grid}


def save_pindou_json(
    grid: list[list[str | None]],
    name: str = "豆绘工坊作品",
    out_path: str | Path | None = None,
) -> bytes:
    """将二维 MARD 网格序列化为兼容 Pin Dou / image-to-pindou 的 schemaVersion 4 JSON。"""
    idx_grid, mask, pal = grid_to_idx_mask(grid)
    h, w = idx_grid.shape
    used_codes = sorted({pal[int(idx_grid[r, c])]["code"] for r in range(h) for c in range(w) if mask[r, c]})
    code_to_one = {c: i + 1 for i, c in enumerate(used_codes)}
    size = 1 if len(used_codes) < 255 else 2
    buf = bytearray(h * w * size)

    # 同步构造一张轻量缩略 PNG 作为 sources[0]
    thumb_rgba = np.zeros((max(1, h), max(1, w), 4), dtype=np.uint8)
    for r in range(h):
        for c in range(w):
            pos = r * w + c
            if mask[r, c]:
                entry = pal[int(idx_grid[r, c])]
                val = code_to_one[entry["code"]]
                thumb_rgba[r, c] = [entry["r"], entry["g"], entry["b"], 255]
            else:
                val = 0
            if size == 1:
                buf[pos] = val
            else:
                buf[2 * pos] = val & 255
                buf[2 * pos + 1] = val >> 8

    png_buf = io.BytesIO()
    Image.fromarray(thumb_rgba, "RGBA").resize(
        (max(64, w * 4), max(64, h * 4)),
        Image.Resampling.NEAREST,
    ).save(png_buf, format="PNG")
    src_b64 = base64.b64encode(png_buf.getvalue()).decode("ascii")
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
                "sourceName": f"{name}.png",
                "source": 0,
                "transform": {"rotation": 0, "flipX": False, "flipY": False, "zoom": 1, "offsetX": 0, "offsetY": 0},
                "settings": {
                    "longestEdge": max(w, h),
                    "maxColors": len(used_codes),
                    "paletteSize": 221,
                    "excludedColorIds": [],
                    "processingMode": "domestic_standard",
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
    raw_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if out_path is not None:
        Path(out_path).write_bytes(raw_bytes)
    return raw_bytes


def compute_bom(
    grid: list[list[str | None]],
    brand: str = DEFAULT_BRAND,
    bead_mm: float = DEFAULT_BEAD_MM,
    board_size: int | None = None,
) -> dict[str, Any]:
    """统计任意二维网格的用豆清单、+10% 建议备豆量、5大品牌对照与物理尺寸规格。"""
    target_brand = brand if brand in DOMESTIC_BRANDS else DEFAULT_BRAND
    _, code_to_entry, _, _, _ = get_palette_maps()
    h = len(grid)
    w = len(grid[0]) if h > 0 else 0

    counts: Counter[str] = Counter()
    for row in grid:
        for cell in row:
            if cell is not None and str(cell).strip() != "":
                counts[normalize_mard_code(str(cell))] += 1

    items: list[dict[str, Any]] = []
    total_beads = 0
    total_spare_beads = 0
    for mard_code, cnt in counts.most_common():
        entry = code_to_entry.get(mard_code)
        if not entry:
            continue
        spare = cnt + max(2, math.ceil(cnt * DEFAULT_SPARE_RATIO))
        total_beads += cnt
        total_spare_beads += spare
        items.append(
            {
                "mard_code": mard_code,
                "display_code": entry["brands"].get(target_brand, mard_code),
                "brand": target_brand,
                "hex": entry["hex"],
                "rgb": entry["rgb"],
                "series": entry["series"],
                "name_zh": entry["name_zh"],
                "count": cnt,
                "spare_count": spare,
                "brands": entry["brands"],
            }
        )

    return {
        "brand": target_brand,
        "total_beads": total_beads,
        "total_spare_beads": total_spare_beads,
        "color_count": len(items),
        "items": items,
        "physical": calc_physical_spec(w, h, bead_mm=bead_mm, board_size=board_size),
    }


def render_brand_sheet_png(
    grid: list[list[str | None]],
    title: str = "豆绘工坊拼豆施工图纸",
    brand: str = DEFAULT_BRAND,
    bead_mm: float = DEFAULT_BEAD_MM,
    board_size: int | None = None,
    out_path: str | Path | None = None,
) -> bytes:
    """
    渲染支持国内 5 大品牌直接标的施工高清图 PNG：
    - 顶栏展示标题、选中品牌、网格尺寸、实拼颗数、2.6mm/5mm成品厘米与拼板数量；
    - 四周行列标尺 + 每格居中高对比品牌色号 + 每5/10格加粗辅助线；
    - 右侧清单栏带色块、当前品牌色号（非MARD时附注MARD基准）、中文色名、实拼颗数与备豆建议。
    """
    bom = compute_bom(grid, brand=brand, bead_mm=bead_mm, board_size=board_size)
    phys = bom["physical"]
    w, h = phys["width"], phys["height"]
    target_brand = bom["brand"]
    _, code_to_entry, _, _, _ = get_palette_maps()

    max_dim = max(w, h, 1)
    cell_px = 38 if max_dim <= 44 else (32 if max_dim <= 64 else 26)
    ruler = 34
    header_h = 74
    margin_l = 24
    margin_b = 24
    legend_gap = 28
    legend_w = 345
    grid_px_w = w * cell_px
    grid_px_h = h * cell_px

    row_h = 26
    legend_content_h = 64 + max(1, len(bom["items"])) * row_h + 24
    canvas_w = margin_l + ruler * 2 + grid_px_w + legend_gap + legend_w + 24
    canvas_h = max(header_h + ruler * 2 + grid_px_h + margin_b, header_h + legend_content_h + margin_b)

    img = Image.new("RGB", (canvas_w, canvas_h), (249, 246, 240))
    draw = ImageDraw.Draw(img)

    f_title = _load_font(22, bold=True)
    f_sub = _load_font(13, bold=False)
    f_axis = _load_font(11, bold=True, mono=True)
    f_cell = _load_font(max(9, int(cell_px * 0.34)), bold=True, mono=True)
    f_leg_hdr = _load_font(15, bold=True)
    f_leg = _load_font(12, bold=False)
    f_leg_b = _load_font(12, bold=True, mono=True)

    # 顶栏标题与国内标准信息
    draw.text((margin_l, 16), title, fill=(35, 31, 29), font=f_title)
    subtitle = (
        f"品牌色卡: {target_brand}  |  规格: {w}×{h} 格  |  实拼: {bom['total_beads']} 颗 ({bom['color_count']} 色)  |  "
        f"{phys['bead_mm']}mm 成品约 {phys['width_cm']}×{phys['height_cm']} cm  |  {phys['board_size']}×{phys['board_size']} 拼板 {phys['boards_x']}×{phys['boards_y']} 块"
    )
    draw.text((margin_l, 48), subtitle, fill=(107, 98, 91), font=f_sub)

    gx0 = margin_l + ruler
    gy0 = header_h + ruler

    # 网格底框
    draw.rectangle([gx0, gy0, gx0 + grid_px_w, gy0 + grid_px_h], fill=(255, 255, 255))

    for r in range(h):
        for c in range(w):
            x0 = gx0 + c * cell_px
            y0 = gy0 + r * cell_px
            x1 = x0 + cell_px
            y1 = y0 + cell_px
            cell = grid[r][c] if c < len(grid[r]) else None
            if cell is None or str(cell).strip() == "":
                bg = (248, 245, 239) if ((r + c) % 2 == 0) else (241, 236, 227)
                draw.rectangle([x0, y0, x1, y1], fill=bg)
                continue

            mard_code = normalize_mard_code(str(cell))
            entry = code_to_entry.get(mard_code)
            if not entry:
                continue
            cr, cg, cb = entry["rgb"]
            draw.rectangle([x0, y0, x1, y1], fill=(cr, cg, cb))
            disp = entry["brands"].get(target_brand, mard_code)
            lum = 0.299 * cr + 0.587 * cg + 0.114 * cb
            ink = (25, 22, 20) if lum > 142 else (255, 255, 255)
            # 若目标品牌色号较长（如 4 位字符），适当缩小字号居中绘制
            cell_font = f_cell if len(disp) <= 3 else _load_font(max(8, int(cell_px * 0.27)), bold=True, mono=True)
            draw.text((x0 + cell_px / 2, y0 + cell_px / 2), disp, fill=ink, font=cell_font, anchor="mm")

    # 网格线（1格浅灰 / 5格中灰 / 10格加粗）
    for c in range(w + 1):
        x = gx0 + c * cell_px
        if c % 10 == 0:
            col, width_px = (55, 48, 43), 2
        elif c % 5 == 0:
            col, width_px = (125, 115, 106), 1
        else:
            col, width_px = (210, 202, 193), 1
        draw.line([(x, gy0), (x, gy0 + grid_px_h)], fill=col, width=width_px)

    for r in range(h + 1):
        y = gy0 + r * cell_px
        if r % 10 == 0:
            col, width_px = (55, 48, 43), 2
        elif r % 5 == 0:
            col, width_px = (125, 115, 106), 1
        else:
            col, width_px = (210, 202, 193), 1
        draw.line([(gx0, y), (gx0 + grid_px_w, y)], fill=col, width=width_px)

    # 行列标尺
    for c in range(w):
        cx = gx0 + c * cell_px + cell_px / 2
        lbl = str(c + 1)
        if w <= 56 or (c + 1) % 2 == 1 or (c + 1) % 5 == 0:
            draw.text((cx, gy0 - 12), lbl, fill=(95, 86, 78), font=f_axis, anchor="mm")
            draw.text((cx, gy0 + grid_px_h + 12), lbl, fill=(95, 86, 78), font=f_axis, anchor="mm")

    for r in range(h):
        cy = gy0 + r * cell_px + cell_px / 2
        lbl = str(r + 1)
        if h <= 56 or (r + 1) % 2 == 1 or (r + 1) % 5 == 0:
            draw.text((gx0 - 15, cy), lbl, fill=(95, 86, 78), font=f_axis, anchor="mm")
            draw.text((gx0 + grid_px_w + 15, cy), lbl, fill=(95, 86, 78), font=f_axis, anchor="mm")

    # 右侧采购与色卡图例栏
    lx0 = gx0 + grid_px_w + ruler + legend_gap
    ly0 = gy0
    draw.rounded_rectangle(
        [lx0, ly0, lx0 + legend_w, ly0 + legend_content_h],
        radius=12,
        fill=(255, 253, 249),
        outline=(225, 216, 204),
        width=1,
    )
    draw.text((lx0 + 16, ly0 + 16), f"{target_brand} 采购清单（{bom['color_count']} 色）", fill=(35, 31, 29), font=f_leg_hdr)
    draw.text(
        (lx0 + 16, ly0 + 38),
        f"实拼 {bom['total_beads']} 颗 · 含10%备豆建议 {bom['total_spare_beads']} 颗",
        fill=(107, 98, 91),
        font=_load_font(11),
    )

    for i, item in enumerate(bom["items"]):
        iy = ly0 + 64 + i * row_h
        cr, cg, cb = item["rgb"]
        draw.rounded_rectangle(
            [lx0 + 16, iy + 3, lx0 + 36, iy + row_h - 3],
            radius=4,
            fill=(cr, cg, cb),
            outline=(180, 172, 162),
        )
        code_txt = item["display_code"]
        if target_brand != "MARD":
            code_txt = f"{code_txt} ({item['mard_code']})"
        draw.text((lx0 + 44, iy + row_h / 2), code_txt, fill=(35, 31, 29), font=f_leg_b, anchor="lm")
        draw.text((lx0 + 148, iy + row_h / 2), item["name_zh"][:7], fill=(107, 98, 91), font=f_leg, anchor="lm")
        draw.text(
            (lx0 + legend_w - 16, iy + row_h / 2),
            f"{item['count']} 颗 (备{item['spare_count']})",
            fill=(35, 31, 29),
            font=f_leg_b,
            anchor="rm",
        )

    out_buf = io.BytesIO()
    img.save(out_buf, format="PNG")
    data = out_buf.getvalue()
    if out_path is not None:
        Path(out_path).write_bytes(data)
    return data


def render_baked_preview_jpg(
    grid: list[list[str | None]],
    cell_px: int = 20,
    seed: int = 42,
    out_path: str | Path | None = None,
) -> bytes:
    """渲染真实热熨平融质感 JPG 预览图（返回 JPEG 字节并按需落盘）。"""
    idx_grid, mask, pal = grid_to_idx_mask(grid)
    fd, tmp_name = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        render_baked_flat_melt_preview(idx_grid, mask, pal, tmp_path, cell_px=cell_px, seed=seed)
        data = tmp_path.read_bytes()
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    if out_path is not None:
        Path(out_path).write_bytes(data)
    return data


def export_bom_csv_bytes(grid: list[list[str | None]], brand: str = DEFAULT_BRAND) -> bytes:
    """导出包含当前品牌、MARD基准与全五大品牌对照的 UTF-8-SIG 采购清单 CSV。"""
    bom = compute_bom(grid, brand=brand)
    target_brand = bom["brand"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            f"当前品牌({target_brand})色号",
            "MARD基准色号",
            "色系",
            "中文色名",
            "HEX",
            "实拼颗数",
            "建议采购含10%备豆",
            "MARD",
            "COCO",
            "漫漫",
            "盼盼",
            "咪小窝",
        ]
    )
    for item in bom["items"]:
        b = item["brands"]
        writer.writerow(
            [
                item["display_code"],
                item["mard_code"],
                item["series"],
                item["name_zh"],
                item["hex"],
                item["count"],
                item["spare_count"],
                b.get("MARD", ""),
                b.get("COCO", ""),
                b.get("漫漫", ""),
                b.get("盼盼", ""),
                b.get("咪小窝", ""),
            ]
        )
    return buf.getvalue().encode("utf-8-sig")
