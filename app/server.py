# -*- coding: utf-8 -*-
"""
豆绘工坊（Pindou Studio）本地交互式拼豆工坊后端服务。
统一采用国内 2.6mm 融合豆 + MARD 221 主基准 + 五大品牌（MARD / COCO / 漫漫 / 盼盼 / 咪小窝）对照。
"""

from __future__ import annotations

from functools import lru_cache
import io
from pathlib import Path
from typing import Any
import urllib.parse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from pindou_core import (
    BEAD_SPECS,
    BOARD_PRESETS,
    DEFAULT_BEAD_MM,
    DEFAULT_BOARD_SIZE,
    DEFAULT_BRAND,
    DOMESTIC_BRANDS,
    PROJECT_ROOT,
    calc_physical_spec,
    compute_bom,
    convert_image,
    export_bom_csv_bytes,
    load_pindou_json,
    load_standard_palette,
    render_baked_preview_jpg,
    render_brand_sheet_png,
    save_pindou_json,
)

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
GALLERY_ROOT = PROJECT_ROOT / "猫咪拼豆图纸汇总"

app = FastAPI(title="豆绘工坊 · 国内标准拼豆 Studio", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _attachment_header(filename: str, fallback: str) -> dict[str, str]:
    """生成 RFC 5987 UTF-8 安全下载响应头，避免中文文件名触发 latin-1 编码异常。"""
    quoted = urllib.parse.quote(filename, safe="")
    return {"Content-Disposition": f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quoted}'}


@lru_cache(maxsize=1)
def _scan_gallery() -> tuple[list[dict[str, Any]], dict[str, Path]]:
    """扫描已交付目录中的 .pindou.json，生成内置作品库索引。"""
    items: list[dict[str, Any]] = []
    id_to_path: dict[str, Path] = {}
    if not GALLERY_ROOT.exists():
        return items, id_to_path

    paths = sorted(GALLERY_ROOT.rglob("*.pindou.json"))
    for idx, p in enumerate(paths):
        rel = p.relative_to(GALLERY_ROOT)
        pid = f"cat_{idx:02d}"
        try:
            doc = load_pindou_json(p)
            bom = compute_bom(doc["grid"], brand=DEFAULT_BRAND, bead_mm=DEFAULT_BEAD_MM)
            group = rel.parts[0] if len(rel.parts) > 1 else "作品集"
            items.append(
                {
                    "id": pid,
                    "name": doc["name"],
                    "group": group,
                    "width": doc["width"],
                    "height": doc["height"],
                    "bead_count": bom["total_beads"],
                    "color_count": bom["color_count"],
                    "physical_26mm": bom["physical"],
                    "rel_path": str(rel).replace("\\", "/"),
                }
            )
            id_to_path[pid] = p
        except Exception:
            continue
    return items, id_to_path


class ExportGridPayload(BaseModel):
    grid: list[list[str | None]]
    title: str = "豆绘工坊拼豆作品"
    name: str | None = None
    brand: str = DEFAULT_BRAND
    bead_mm: float = DEFAULT_BEAD_MM
    board_size: int | None = Field(default=None)


def _validate_grid(grid: list[list[str | None]]) -> list[list[str | None]]:
    if not grid or not isinstance(grid, list) or not isinstance(grid[0], list):
        raise HTTPException(status_code=400, detail="网格数据不能为空")
    h = len(grid)
    w = len(grid[0])
    if w < 1 or h < 1 or w > 160 or h > 160:
        raise HTTPException(status_code=400, detail="网格尺寸超出允许范围（1~160）")
    return grid


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/standards")
def api_standards() -> dict[str, Any]:
    return {
        "brands": list(DOMESTIC_BRANDS),
        "default_brand": DEFAULT_BRAND,
        "bead_specs": BEAD_SPECS,
        "default_bead_mm": DEFAULT_BEAD_MM,
        "default_board_size": DEFAULT_BOARD_SIZE,
        "board_presets": BOARD_PRESETS,
        "palette": load_standard_palette(),
    }


@app.get("/api/gallery")
def api_gallery() -> dict[str, Any]:
    items, _ = _scan_gallery()
    return {"items": items}


@app.get("/api/gallery/{project_id}")
def api_gallery_item(project_id: str) -> dict[str, Any]:
    _, id_to_path = _scan_gallery()
    p = id_to_path.get(project_id)
    if p is None or not p.exists():
        raise HTTPException(status_code=404, detail=f"未找到作品: {project_id}")
    doc = load_pindou_json(p)
    bom = compute_bom(doc["grid"], brand=DEFAULT_BRAND, bead_mm=DEFAULT_BEAD_MM)
    return {
        "id": project_id,
        "name": doc["name"],
        "width": doc["width"],
        "height": doc["height"],
        "grid": doc["grid"],
        "bom": bom,
        "physical": bom["physical"],
    }


@app.post("/api/convert")
async def api_convert(
    file: UploadFile = File(...),
    mode: str = Form("photo_fusion"),
    width: int = Form(52),
    height: int = Form(52),
    max_colors: int = Form(18),
    remove_bg: bool = Form(False),
    add_outline: bool = Form(False),
    suppress_green_cast: bool = Form(True),
    smooth_eyes: bool = Form(True),
    brand: str = Form(DEFAULT_BRAND),
    bead_mm: float = Form(DEFAULT_BEAD_MM),
    board_size: int = Form(DEFAULT_BOARD_SIZE),
) -> JSONResponse:
    raw = await file.read()
    if not raw or len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="请上传 25MB 以内的有效图片")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"无法识别图片格式: {exc}") from exc

    res = convert_image(
        img,
        mode=mode,
        target_w=width,
        target_h=height,
        max_colors=max_colors,
        suppress_green_cast=suppress_green_cast,
        smooth_eyes=smooth_eyes,
        remove_bg=remove_bg,
        add_outline=add_outline,
    )
    stem = Path(file.filename or "新建拼豆图").stem
    bom = compute_bom(res["grid"], brand=brand, bead_mm=bead_mm, board_size=board_size)
    return JSONResponse(
        {
            "name": f"{stem}_{res['width']}x{res['height']}",
            "width": res["width"],
            "height": res["height"],
            "mode": res["mode"],
            "grid": res["grid"],
            "bom": bom,
            "physical": bom["physical"],
        }
    )


@app.post("/api/import-pindou")
async def api_import_pindou(file: UploadFile = File(...)) -> JSONResponse:
    raw = await file.read()
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="请上传 10MB 以内的 .pindou.json 工程文件")
    try:
        doc = load_pindou_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析 .pindou.json: {exc}") from exc
    if doc["width"] < 1 or doc["height"] < 1:
        raise HTTPException(status_code=400, detail="工程文件网格为空")
    bom = compute_bom(doc["grid"], brand=DEFAULT_BRAND, bead_mm=DEFAULT_BEAD_MM)
    return JSONResponse(
        {
            "name": doc["name"],
            "width": doc["width"],
            "height": doc["height"],
            "grid": doc["grid"],
            "bom": bom,
            "physical": bom["physical"],
        }
    )


@app.post("/api/export/sheet")
def api_export_sheet(payload: ExportGridPayload) -> Response:
    grid = _validate_grid(payload.grid)
    title = payload.title or payload.name or "豆绘工坊拼豆施工图纸"
    png_bytes = render_brand_sheet_png(
        grid,
        title=title,
        brand=payload.brand,
        bead_mm=payload.bead_mm,
        board_size=payload.board_size,
    )
    fname = f"{title}_{payload.brand}版_施工图.png"
    return Response(content=png_bytes, media_type="image/png", headers=_attachment_header(fname, "pindou_sheet.png"))


@app.post("/api/export/baked")
def api_export_baked(payload: ExportGridPayload) -> Response:
    grid = _validate_grid(payload.grid)
    title = payload.title or payload.name or "豆绘工坊作品"
    jpg_bytes = render_baked_preview_jpg(grid, cell_px=20)
    fname = f"{title}_2.6mm熨烫平融预览.jpg"
    return Response(content=jpg_bytes, media_type="image/jpeg", headers=_attachment_header(fname, "pindou_baked.jpg"))


@app.post("/api/export/csv")
def api_export_csv(payload: ExportGridPayload) -> Response:
    grid = _validate_grid(payload.grid)
    title = payload.title or payload.name or "豆绘工坊作品"
    csv_bytes = export_bom_csv_bytes(grid, brand=payload.brand)
    fname = f"{title}_{payload.brand}版_五品牌采购清单.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers=_attachment_header(fname, "pindou_bom.csv"),
    )


@app.post("/api/export/pindou")
def api_export_pindou(payload: ExportGridPayload) -> Response:
    grid = _validate_grid(payload.grid)
    name = payload.name or payload.title or "豆绘工坊作品"
    json_bytes = save_pindou_json(grid, name=name)
    fname = f"{name}.pindou.json"
    return Response(
        content=json_bytes,
        media_type="application/json; charset=utf-8",
        headers=_attachment_header(fname, "pattern.pindou.json"),
    )
