# -*- coding: utf-8 -*-
"""
MARD 221 主基准色卡 + 国内五大品牌（MARD / COCO / 漫漫 / 盼盼 / 咪小窝）统一色号映射库。
"""

from __future__ import annotations

import csv
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
from skimage import color as skcolor

from .standards import DEFAULT_BRAND, DOMESTIC_BRANDS, PROJECT_ROOT

DATA_DIR = Path(__file__).resolve().parent / "data"
PALETTE_JSON_PATH = DATA_DIR / "domestic_standard_palette.json"
MARD_CSV_PATH = PROJECT_ROOT / "repos" / "pindou-skill" / "palettes" / "mard_221.csv"
ZIPPLAND_MAP_PATH = PROJECT_ROOT / "repos" / "Zippland_perler-beads" / "src" / "app" / "colorSystemMapping.json"

# 白色/浅灰宠物毛发最容易误选的灰绿偏色陷阱色号
GREEN_CAST_TRAP_CODES: frozenset[str] = frozenset({
    "G15",
    "H18",
    "H21",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M7",
})


def normalize_mard_code(code: str) -> str:
    """将零填充色号（如 A01、H09）规范化为 MARD 标准非补零格式（A1、H9）。"""
    clean = str(code or "").strip().upper()
    return re.sub(r"^([A-Z]+)0+(\d+)$", r"\1\2", clean)


def delta_e2000_matrix(labs_a: np.ndarray, labs_b: np.ndarray) -> np.ndarray:
    """向量化计算两组 CIELAB 颜色之间的 CIEDE2000 矩阵，形状为 (N, M)。"""
    return skcolor.deltaE_ciede2000(labs_a[:, None, :], labs_b[None, :, :])


def build_standard_palette_data(save_json: bool = True) -> list[dict[str, Any]]:
    """合并 MARD 221 基准与 Zippland 五大品牌映射，输出统一标准色卡列表。"""
    if not MARD_CSV_PATH.exists():
        raise FileNotFoundError(f"缺少 MARD 221 色卡 CSV: {MARD_CSV_PATH}")

    zippland_by_mard: dict[str, dict[str, str]] = {}
    if ZIPPLAND_MAP_PATH.exists():
        raw_map = json.loads(ZIPPLAND_MAP_PATH.read_text(encoding="utf-8"))
        for _hex_key, brand_obj in raw_map.items():
            mard_norm = normalize_mard_code(brand_obj.get("MARD", ""))
            if not mard_norm:
                continue
            zippland_by_mard[mard_norm] = {
                "MARD": mard_norm,
                "COCO": str(brand_obj.get("COCO", mard_norm)).strip(),
                "漫漫": str(brand_obj.get("漫漫", mard_norm)).strip(),
                "盼盼": str(brand_obj.get("盼盼", mard_norm)).strip(),
                "咪小窝": str(brand_obj.get("咪小窝", mard_norm)).strip(),
            }

    palette: list[dict[str, Any]] = []
    with MARD_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = normalize_mard_code(row["code"])
            r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
            hex_val = f"#{r:02X}{g:02X}{b:02X}"
            brands = zippland_by_mard.get(
                code,
                {brand: code for brand in DOMESTIC_BRANDS},
            )
            palette.append(
                {
                    "id": int(row["id"]),
                    "code": code,
                    "hex": hex_val,
                    "r": r,
                    "g": g,
                    "b": b,
                    "rgb": [r, g, b],
                    "series": str(row.get("series", code[0])).strip(),
                    "name_zh": str(row.get("name_zh", "")).strip(),
                    "name_en": str(row.get("name_en", "")).strip(),
                    "brands": brands,
                }
            )

    if save_json:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PALETTE_JSON_PATH.write_text(
            json.dumps(palette, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return palette


@lru_cache(maxsize=1)
def load_standard_palette() -> list[dict[str, Any]]:
    """加载缓存的 221 色国内标准色卡；如本地 JSON 不存在则自动构建。"""
    if PALETTE_JSON_PATH.exists():
        data = json.loads(PALETTE_JSON_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) == 221:
            return data
    return build_standard_palette_data(save_json=True)


@lru_cache(maxsize=1)
def get_palette_maps() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int], np.ndarray, np.ndarray]:
    """返回 (palette_list, code_to_entry, code_to_idx, pal_lab, pal_de_mat)。"""
    pal = load_standard_palette()
    code_to_entry = {entry["code"]: entry for entry in pal}
    code_to_idx = {entry["code"]: idx for idx, entry in enumerate(pal)}
    rgb_arr = np.array([entry["rgb"] for entry in pal], dtype=np.float64) / 255.0
    pal_lab = skcolor.rgb2lab(rgb_arr.reshape(1, -1, 3)).reshape(-1, 3)
    pal_de_mat = delta_e2000_matrix(pal_lab, pal_lab)
    return pal, code_to_entry, code_to_idx, pal_lab, pal_de_mat


def filter_palette_subset(
    suppress_green_cast: bool = False,
) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    """根据是否启用白毛防偏绿过滤，返回可用色卡子集及对应 Lab 与 CIEDE2000 矩阵。"""
    pal, _, _, pal_lab, pal_de_mat = get_palette_maps()
    if not suppress_green_cast:
        return pal, pal_lab, pal_de_mat
    keep_indices = [i for i, e in enumerate(pal) if e["code"] not in GREEN_CAST_TRAP_CODES]
    sub_pal = [pal[i] for i in keep_indices]
    sub_lab = pal_lab[keep_indices]
    sub_de = pal_de_mat[np.ix_(keep_indices, keep_indices)]
    return sub_pal, sub_lab, sub_de


def translate_code(mard_code: str, brand: str = DEFAULT_BRAND) -> str:
    """将 MARD 基准色号转换为目标国内品牌色号。"""
    norm = normalize_mard_code(mard_code)
    if not norm:
        return ""
    _, code_to_entry, _, _, _ = get_palette_maps()
    entry = code_to_entry.get(norm)
    if not entry:
        return norm
    target_brand = brand if brand in DOMESTIC_BRANDS else DEFAULT_BRAND
    return entry["brands"].get(target_brand, norm)


def lookup_color_brands(code_query: str) -> dict[str, Any] | None:
    """支持输入任意品牌色号或 MARD 色号，反查完整 5 品牌对照色卡记录。"""
    q = str(code_query or "").strip()
    if not q:
        return None
    norm = normalize_mard_code(q)
    pal, code_to_entry, _, _, _ = get_palette_maps()
    if norm in code_to_entry:
        return code_to_entry[norm]
    q_upper = q.upper()
    for entry in pal:
        for b_code in entry["brands"].values():
            if b_code.upper() == q_upper or normalize_mard_code(b_code) == norm:
                return entry
    return None
