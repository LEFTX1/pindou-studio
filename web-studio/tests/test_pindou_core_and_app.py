# -*- coding: utf-8 -*-
"""
统一标准 core (`pindou_core`) 与 `豆绘工坊` FastAPI 后端自动化测试套件。
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient
from PIL import Image

WEB_STUDIO_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = WEB_STUDIO_ROOT.parent
if str(WEB_STUDIO_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_STUDIO_ROOT))

from app.server import GALLERY_ROOT, app  # noqa: E402
from pindou_core import (  # noqa: E402
    DOMESTIC_BRANDS,
    calc_physical_spec,
    compute_bom,
    convert_image,
    export_bom_csv_bytes,
    load_pindou_json,
    load_standard_palette,
    normalize_mard_code,
    render_baked_preview_jpg,
    render_brand_sheet_png,
    save_pindou_json,
    translate_code,
)


def _find_sample_image() -> Path:
    builtin_demo = REPO_ROOT / "android-app" / "app" / "src" / "main" / "assets" / "samples" / "demo_cat.jpg"
    if builtin_demo.is_file():
        return builtin_demo
    candidates = sorted((REPO_ROOT / "inputs").glob("*.*"))
    for p in candidates:
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return p
    raise FileNotFoundError("未找到可用于测试的样本图片")


class TestPindouCoreAndApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.sample_image = _find_sample_image()

    def test_palette_221_five_brands_complete(self) -> None:
        pal = load_standard_palette()
        self.assertEqual(len(pal), 221)
        for entry in pal:
            self.assertEqual(entry["code"], normalize_mard_code(entry["code"]))
            for brand in DOMESTIC_BRANDS:
                val = entry["brands"].get(brand, "")
                self.assertTrue(bool(val), f"{entry['code']} 缺少品牌 {brand} 映射")
        self.assertEqual(translate_code("A01", "COCO"), "E02")
        self.assertEqual(translate_code("H1", "漫漫"), "F1")
        self.assertEqual(translate_code("H5", "COCO"), "B06")

    def test_physical_spec_domestic_boards(self) -> None:
        spec52 = calc_physical_spec(52, 52, bead_mm=2.6, board_size=52)
        self.assertEqual(spec52["width_cm"], 13.5)
        self.assertEqual(spec52["height_cm"], 13.5)
        self.assertEqual(spec52["total_boards"], 1)
        self.assertTrue(spec52["fits_single_52"])

        spec72 = calc_physical_spec(72, 72, bead_mm=2.6, board_size=52)
        self.assertEqual(spec72["width_cm"], 18.7)
        self.assertEqual(spec72["boards_x"], 2)
        self.assertEqual(spec72["total_boards"], 4)

    def test_all_delivered_pindou_json_roundtrip(self) -> None:
        files = sorted(GALLERY_ROOT.rglob("*.pindou.json"))
        self.assertGreaterEqual(len(files), 4)
        for p in files:
            doc = load_pindou_json(p)
            self.assertGreater(doc["width"], 10)
            self.assertGreater(doc["height"], 10)
            bom = compute_bom(doc["grid"], brand="COCO")
            self.assertGreater(bom["total_beads"], 100)
            encoded = save_pindou_json(doc["grid"], name=doc["name"])
            re_doc = load_pindou_json(encoded)
            self.assertEqual(re_doc["grid"], doc["grid"])

    def test_pipeline_all_three_modes(self) -> None:
        img = Image.open(self.sample_image)
        for mode, outline in (("photo_fusion", False), ("cutout_outline", True), ("grid_extract", False)):
            res = convert_image(
                img,
                mode=mode,
                target_w=32,
                target_h=32,
                max_colors=12,
                suppress_green_cast=True,
                remove_bg=(mode == "cutout_outline"),
                add_outline=outline,
            )
            self.assertEqual(res["width"], 32)
            self.assertEqual(res["height"], 32)
            self.assertGreater(res["bead_count"], 50)
            limit = 13 if outline else 12
            self.assertLessEqual(res["color_count"], limit)

    def test_exports_render_cleanly(self) -> None:
        sample_grid = [
            ["H1", "H5", "A9", None],
            ["H5", "G10", "H1", "H5"],
            [None, "F10", "H16", None],
        ]
        png_bytes = render_brand_sheet_png(sample_grid, title="单元测试图纸", brand="漫漫", bead_mm=2.6)
        im_png = Image.open(io.BytesIO(png_bytes))
        self.assertEqual(im_png.format, "PNG")

        jpg_bytes = render_baked_preview_jpg(sample_grid, cell_px=14)
        im_jpg = Image.open(io.BytesIO(jpg_bytes))
        self.assertEqual(im_jpg.format, "JPEG")

        csv_text = export_bom_csv_bytes(sample_grid, brand="盼盼").decode("utf-8-sig")
        self.assertIn("当前品牌(盼盼)色号", csv_text)
        self.assertIn("MARD,COCO,漫漫,盼盼,咪小窝", csv_text)

    def test_fastapi_endpoints_end_to_end(self) -> None:
        r_home = self.client.get("/")
        self.assertEqual(r_home.status_code, 200)
        self.assertIn("豆绘工坊", r_home.text)

        r_std = self.client.get("/api/standards")
        self.assertEqual(r_std.status_code, 200)
        std = r_std.json()
        self.assertEqual(len(std["palette"]), 221)
        self.assertEqual(std["brands"], list(DOMESTIC_BRANDS))

        r_gal = self.client.get("/api/gallery")
        self.assertEqual(r_gal.status_code, 200)
        items = r_gal.json()["items"]
        self.assertGreaterEqual(len(items), 4)

        first_id = items[0]["id"]
        r_item = self.client.get(f"/api/gallery/{first_id}")
        self.assertEqual(r_item.status_code, 200)
        item_data = r_item.json()
        grid = item_data["grid"]

        with self.sample_image.open("rb") as fh:
            r_conv = self.client.post(
                "/api/convert",
                files={"file": (self.sample_image.name, fh, "image/jpeg")},
                data={"mode": "photo_fusion", "width": "29", "height": "29", "max_colors": "12", "brand": "COCO"},
            )
        self.assertEqual(r_conv.status_code, 200)
        conv = r_conv.json()
        self.assertEqual(conv["width"], 29)
        self.assertEqual(conv["bom"]["brand"], "COCO")

        small_grid = [row[:16] for row in grid[:16]]
        r_sheet = self.client.post("/api/export/sheet", json={"grid": small_grid, "title": "测试猫", "brand": "COCO"})
        self.assertEqual(r_sheet.status_code, 200)
        self.assertEqual(r_sheet.headers["content-type"], "image/png")

        r_baked = self.client.post("/api/export/baked", json={"grid": small_grid, "title": "测试猫"})
        self.assertEqual(r_baked.status_code, 200)
        self.assertEqual(r_baked.headers["content-type"], "image/jpeg")

        r_csv = self.client.post("/api/export/csv", json={"grid": small_grid, "title": "测试猫", "brand": "咪小窝"})
        self.assertEqual(r_csv.status_code, 200)
        self.assertIn("当前品牌(咪小窝)色号", r_csv.content.decode("utf-8-sig"))

        r_pindou = self.client.post("/api/export/pindou", json={"grid": small_grid, "name": "测试导出"})
        self.assertEqual(r_pindou.status_code, 200)
        p_json = json.loads(r_pindou.content.decode("utf-8"))
        self.assertEqual(p_json["schemaVersion"], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
