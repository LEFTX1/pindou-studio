# -*- coding: utf-8 -*-
"""
国内主流拼豆统一核心库（2.6mm 融合豆 + MARD 221 主基准 + 五大品牌映射 + 52×52 / 29×29 拼板规范）。
"""

from .standards import (
    BEAD_SPECS,
    BOARD_PRESETS,
    DEFAULT_BEAD_MM,
    DEFAULT_BOARD_SIZE,
    DEFAULT_BRAND,
    DEFAULT_SPARE_RATIO,
    DOMESTIC_BRANDS,
    PROJECT_ROOT,
    calc_physical_spec,
)
from .palette import (
    GREEN_CAST_TRAP_CODES,
    delta_e2000_matrix,
    filter_palette_subset,
    get_palette_maps,
    load_standard_palette,
    lookup_color_brands,
    normalize_mard_code,
    translate_code,
)
from .pipeline import convert_image
from .exporter import (
    compute_bom,
    export_bom_csv_bytes,
    grid_to_idx_mask,
    idx_mask_to_grid,
    load_pindou_json,
    render_baked_preview_jpg,
    render_brand_sheet_png,
    save_pindou_json,
)

__all__ = [
    "BEAD_SPECS",
    "BOARD_PRESETS",
    "DEFAULT_BEAD_MM",
    "DEFAULT_BOARD_SIZE",
    "DEFAULT_BRAND",
    "DEFAULT_SPARE_RATIO",
    "DOMESTIC_BRANDS",
    "GREEN_CAST_TRAP_CODES",
    "PROJECT_ROOT",
    "calc_physical_spec",
    "compute_bom",
    "convert_image",
    "delta_e2000_matrix",
    "export_bom_csv_bytes",
    "filter_palette_subset",
    "get_palette_maps",
    "grid_to_idx_mask",
    "idx_mask_to_grid",
    "load_pindou_json",
    "load_standard_palette",
    "lookup_color_brands",
    "normalize_mard_code",
    "render_baked_preview_jpg",
    "render_brand_sheet_png",
    "save_pindou_json",
    "translate_code",
]
