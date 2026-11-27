# -*- coding: utf-8 -*-
"""
国内拼豆物理规格与五大品牌通用标准定义。
以 2.6mm 融合豆（mini 豆）+ MARD 221 常规纯色为主基准，兼容 COCO / 漫漫 / 盼盼 / 咪小窝。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DOMESTIC_BRANDS: tuple[str, ...] = ("MARD", "COCO", "漫漫", "盼盼", "咪小窝")
DEFAULT_BRAND: str = "MARD"
DEFAULT_BEAD_MM: float = 2.6
DEFAULT_BOARD_SIZE: int = 52
DEFAULT_SPARE_RATIO: float = 0.10

BEAD_SPECS: dict[str, dict[str, Any]] = {
    "2.6mm": {
        "mm": 2.6,
        "label": "2.6mm 融合豆（国内主流）",
        "short_label": "2.6mm 融合豆",
        "default_board": 52,
    },
    "5.0mm": {
        "mm": 5.0,
        "label": "5.0mm 大豆（儿童/入门）",
        "short_label": "5.0mm 大豆",
        "default_board": 29,
    },
}

BOARD_PRESETS: list[dict[str, Any]] = [
    {
        "id": "mini_29",
        "label": "29×29 迷你板",
        "w": 29,
        "h": 29,
        "desc": "挂件 / 钥匙扣小图",
    },
    {
        "id": "cutout_40",
        "label": "40×40 异形小图",
        "w": 40,
        "h": 40,
        "desc": "手拼轻松 · 适合异形描边",
    },
    {
        "id": "medium_48",
        "label": "48×48 精致中图",
        "w": 48,
        "h": 48,
        "desc": "单块 52 大板轻松容纳",
    },
    {
        "id": "standard_52",
        "label": "52×52 标准大板",
        "w": 52,
        "h": 52,
        "desc": "国内 2.6mm 单板满格基准",
    },
    {
        "id": "fine_72",
        "label": "72×72 高精大图",
        "w": 72,
        "h": 72,
        "desc": "约 2×2 拼板 · 照片高还原",
    },
]


def calc_physical_spec(
    width: int,
    height: int,
    bead_mm: float = DEFAULT_BEAD_MM,
    board_size: int | None = None,
) -> dict[str, Any]:
    """根据网格行列数与豆径（2.6mm 或 5.0mm）计算成品厘米数和拼板需求。"""
    w = max(1, int(width))
    h = max(1, int(height))
    mm = float(bead_mm) if bead_mm in (2.6, 5.0) else DEFAULT_BEAD_MM
    if board_size is None:
        board = 29 if abs(mm - 5.0) < 0.2 else 52
    else:
        board = max(1, int(board_size))

    boards_x = math.ceil(w / board)
    boards_y = math.ceil(h / board)
    return {
        "width": w,
        "height": h,
        "bead_mm": mm,
        "board_size": board,
        "width_cm": round(w * mm / 10.0, 1),
        "height_cm": round(h * mm / 10.0, 1),
        "boards_x": boards_x,
        "boards_y": boards_y,
        "total_boards": boards_x * boards_y,
        "fits_single_52": bool(w <= 52 and h <= 52),
        "fits_single_29": bool(w <= 29 and h <= 29),
    }
