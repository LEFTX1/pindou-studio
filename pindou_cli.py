# -*- coding: utf-8 -*-
"""
统一国内拼豆 CLI（2.6mm 融合豆 + MARD 221 + 五大品牌互转 + 施工图/烘烤预览/CSV/工程导出）。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image

from pindou_core import (
    DEFAULT_BEAD_MM,
    DEFAULT_BRAND,
    DOMESTIC_BRANDS,
    compute_bom,
    convert_image,
    export_bom_csv_bytes,
    load_pindou_json,
    lookup_color_brands,
    render_baked_preview_jpg,
    render_brand_sheet_png,
    save_pindou_json,
)


def _cmd_convert(args: argparse.Namespace) -> int:
    src = Path(args.image)
    if not src.exists():
        print(f"错误：找不到输入图片 {src}", file=sys.stderr)
        return 1
    out_dir = Path(args.out_dir) if args.out_dir else src.parent / f"{src.stem}_pindou_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(src)
    res = convert_image(
        img,
        mode=args.mode,
        target_w=args.width,
        target_h=args.height,
        max_colors=args.colors,
        suppress_green_cast=not args.no_suppress_green,
        smooth_eyes=not args.no_smooth_eyes,
        remove_bg=args.remove_bg,
        add_outline=args.outline,
    )
    stem = args.name or f"{src.stem}_{res['width']}x{res['height']}_{args.brand}{res['color_count']}色"
    title = f"{stem} · 国内{args.bead_mm}mm标准"

    png_path = out_dir / f"{stem}_图纸.png"
    jpg_path = out_dir / f"{stem}_2.6mm熨烫预览.jpg"
    csv_path = out_dir / f"{stem}_五品牌采购清单.csv"
    json_path = out_dir / f"{stem}.pindou.json"

    render_brand_sheet_png(res["grid"], title=title, brand=args.brand, bead_mm=args.bead_mm, out_path=png_path)
    render_baked_preview_jpg(res["grid"], out_path=jpg_path)
    csv_path.write_bytes(export_bom_csv_bytes(res["grid"], brand=args.brand))
    save_pindou_json(res["grid"], name=stem, out_path=json_path)

    bom = compute_bom(res["grid"], brand=args.brand, bead_mm=args.bead_mm)
    phys = bom["physical"]
    print(f"[完成] {stem}")
    print(f"  网格: {phys['width']}×{phys['height']} 格 | 实拼 {bom['total_beads']} 颗 | {bom['color_count']} 色")
    print(f"  物理规格({phys['bead_mm']}mm): 约 {phys['width_cm']}×{phys['height_cm']} cm | {phys['board_size']}×{phys['board_size']}拼板 {phys['boards_x']}×{phys['boards_y']}块")
    print(f"  输出目录: {out_dir}")
    return 0


def _cmd_translate(args: argparse.Namespace) -> int:
    target = Path(args.target)
    if target.exists() and target.suffix == ".json":
        doc = load_pindou_json(target)
        out_dir = Path(args.out_dir) if args.out_dir else target.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{doc['name']}_{args.brand}版"
        png_path = out_dir / f"{stem}_图纸.png"
        csv_path = out_dir / f"{stem}_采购清单.csv"
        render_brand_sheet_png(doc["grid"], title=stem, brand=args.brand, bead_mm=args.bead_mm, out_path=png_path)
        csv_path.write_bytes(export_bom_csv_bytes(doc["grid"], brand=args.brand))
        print(f"[品牌转码导出] {doc['name']} -> {args.brand}")
        print(f"  图纸: {png_path}")
        print(f"  清单: {csv_path}")
        return 0

    entry = lookup_color_brands(args.target)
    if not entry:
        print(f"未在 MARD 221 五品牌映射中找到色号: {args.target}", file=sys.stderr)
        return 1
    print(f"色号对照: {entry['name_zh']} ({entry['hex']})")
    for b in DOMESTIC_BRANDS:
        print(f"  {b:<5}: {entry['brands'].get(b, '')}")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    p = Path(args.pindou_json)
    if not p.exists():
        print(f"错误：文件不存在 {p}", file=sys.stderr)
        return 1
    doc = load_pindou_json(p)
    bom = compute_bom(doc["grid"], brand=args.brand, bead_mm=args.bead_mm)
    phys = bom["physical"]
    print(f"作品名称: {doc['name']}")
    print(f"品牌视角: {bom['brand']}")
    print(f"网格尺寸: {phys['width']}×{phys['height']} 格 | 实拼 {bom['total_beads']} 颗 | {bom['color_count']} 色 | 建议含备豆 {bom['total_spare_beads']} 颗")
    print(f"物理尺寸({phys['bead_mm']}mm): {phys['width_cm']}×{phys['height_cm']} cm | {phys['board_size']}×{phys['board_size']}拼板 {phys['boards_x']}×{phys['boards_y']}块")
    print("前 8 主力色号:")
    for item in bom["items"][:8]:
        print(f"  {item['display_code']:<5} (MARD {item['mard_code']:<4}) {item['name_zh']:<8} x{item['count']} (备{item['spare_count']})")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("app.server:app", host=args.host, port=args.port, reload=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="国内主流拼豆统一 CLI（2.6mm + MARD221 + 五大品牌）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_conv = sub.add_parser("convert", help="图片转为统一标准拼豆图纸")
    p_conv.add_argument("image")
    p_conv.add_argument("--mode", choices=["photo_fusion", "cutout_outline", "grid_extract"], default="photo_fusion")
    p_conv.add_argument("--width", type=int, default=52)
    p_conv.add_argument("--height", type=int, default=52)
    p_conv.add_argument("--colors", type=int, default=18)
    p_conv.add_argument("--brand", choices=DOMESTIC_BRANDS, default=DEFAULT_BRAND)
    p_conv.add_argument("--bead-mm", type=float, default=DEFAULT_BEAD_MM)
    p_conv.add_argument("--remove-bg", action="store_true")
    p_conv.add_argument("--outline", action="store_true")
    p_conv.add_argument("--no-suppress-green", action="store_true")
    p_conv.add_argument("--no-smooth-eyes", action="store_true")
    p_conv.add_argument("--name", default="")
    p_conv.add_argument("--out-dir", default="")
    p_conv.set_defaults(func=_cmd_convert)

    p_tr = sub.add_parser("translate", help="查询单色号或转换 .pindou.json 至指定国内品牌")
    p_tr.add_argument("target", help="色号（如 H1/A9）或 .pindou.json 路径")
    p_tr.add_argument("--brand", choices=DOMESTIC_BRANDS, default="COCO")
    p_tr.add_argument("--bead-mm", type=float, default=DEFAULT_BEAD_MM)
    p_tr.add_argument("--out-dir", default="")
    p_tr.set_defaults(func=_cmd_translate)

    p_ins = sub.add_parser("inspect", help="查看 .pindou.json 国内标准统计")
    p_ins.add_argument("pindou_json")
    p_ins.add_argument("--brand", choices=DOMESTIC_BRANDS, default=DEFAULT_BRAND)
    p_ins.add_argument("--bead-mm", type=float, default=DEFAULT_BEAD_MM)
    p_ins.set_defaults(func=_cmd_inspect)

    p_srv = sub.add_parser("serve", help="启动 豆绘工坊 Studio Web App")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8787)
    p_srv.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
