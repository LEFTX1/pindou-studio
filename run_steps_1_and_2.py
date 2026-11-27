import json
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
INPUTS_DIR = BASE / "inputs"
PINDOU_SKILL = BASE / "repos" / "pindou-skill"
PERLER_SKILL = BASE / "repos" / "perler-beads-skill"
KUI_SKILL = BASE / "repos" / "image-to-pindou"

OUT_B = BASE / "outputs" / "pathway_B_pindou_skill"
OUT_C = BASE / "outputs" / "pathway_C_perler_beads_skill"
OUT_E = BASE / "outputs" / "pathway_E_kui_pindou"
OUT_E.mkdir(parents=True, exist_ok=True)


def svg_to_png_via_sharp(svg_path: Path, png_path: Path):
    js = f"""
    const sharp = require({json.dumps(str(PERLER_SKILL / 'node_modules' / 'sharp'))});
    sharp({json.dumps(str(svg_path))}, {{ density: 144 }})
      .png()
      .toFile({json.dumps(str(png_path))})
      .then(() => console.log('Rendered PNG:', {json.dumps(str(png_path))}))
      .catch(err => {{ console.error(err); process.exit(1); }});
    """
    subprocess.run(["node", "-e", js], check=True)


def run_step1_kui_pindou():
    for name in ("espeon", "umbreon"):
        out_dir = OUT_E / name
        out_dir.mkdir(parents=True, exist_ok=True)
        in_img = INPUTS_DIR / f"{name}_medallion_64x64_upscaled.png"
        cmd = [
            "node",
            str(KUI_SKILL / "scripts" / "generate.mjs"),
            str(in_img),
            "--style", "all",
            "--size", "64",
            "--max-colors", "20",
            "--background", "remove",
            "--cell-px", "28",
            "--ai", "off",
            "--out", str(out_dir),
        ]
        print(f"=== Step 1 (E1-E3 kuizuo/pin-dou): {name} ===")
        subprocess.run(cmd, check=True)


def run_step2_b2_quantize_image():
    palette_csv = PINDOU_SKILL / "palettes" / "mard_221.csv"
    for name in ("espeon", "umbreon"):
        run_dir = OUT_B / f"{name}_B2_image_mode"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Composite RGBA medallion onto #00FF00 background so corners strip cleanly while white lace stays intact
        in_rgba = Image.open(INPUTS_DIR / f"{name}_medallion_64x64_upscaled.png").convert("RGBA")
        green_bg = Image.new("RGBA", in_rgba.size, (0, 255, 0, 255))
        green_comp = Image.alpha_composite(green_bg, in_rgba).convert("RGB")
        in_png = run_dir / "input_greenbg.png"
        green_comp.save(in_png)

        spec = {
            "spec_id": f"{name}_pindou_skill_imgmode",
            "palette_id": "mard_221",
            "grid_w": 64,
            "grid_h": 64,
            "ai_draws_grid": False,
            "style": "cartoon",
            "background_mode": "remove",
            "background_color": "#00FF00",
            "max_colors": 20,
            "must_include_colors": [],
            "forbid_colors": [],
            "cell_px": 36,
            "show_grid_numbers": True,
            "show_color_codes": True,
        }
        spec_path = run_dir / "spec.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"=== Step 2 (B2 pindou-skill quantize.py --image): {name} ===")
        subprocess.run(
            [
                "python",
                str(PINDOU_SKILL / "scripts" / "quantize.py"),
                "--spec", str(spec_path),
                "--image", str(in_png),
                "--palette", str(palette_csv),
                "--out-dir", str(run_dir),
            ],
            check=True,
        )
        subprocess.run(
            [
                "python",
                str(PINDOU_SKILL / "scripts" / "render_pattern.py"),
                "--grid", str(run_dir / "grid.json"),
                "--palette", str(palette_csv),
                "--out-dir", str(run_dir),
                "--cell-px", "36",
            ],
            check=True,
        )
        svg_to_png_via_sharp(run_dir / "pattern.svg", run_dir / f"{name}_B2_pindou_skill_image.png")


def run_step2_c3_to_c6():
    gen_js = str(PERLER_SKILL / "scripts" / "generate.js")
    for name, cn, inner_size in [("espeon", "太阳伊布", 54), ("umbreon", "月亮伊布", 53)]:
        run_dir = OUT_C / name
        run_dir.mkdir(parents=True, exist_ok=True)

        # C3: Direct image PNG quantization with --blank-white on square white-background inner sprite
        inner_rgba = Image.open(INPUTS_DIR / f"{name}_inner_only_upscaled.png").convert("RGBA")
        side = max(inner_rgba.width, inner_rgba.height)
        white_sq = Image.new("RGBA", (side, side), (255, 255, 255, 255))
        ox = (side - inner_rgba.width) // 2
        oy = (side - inner_rgba.height) // 2
        white_sq.paste(inner_rgba, (ox, oy), inner_rgba)
        c3_input = run_dir / f"{name}_inner_white_sq.png"
        white_sq.convert("RGB").save(c3_input)

        print(f"=== Step 2 (C3 perler-beads-skill direct PNG --blank-white): {name} ===")
        subprocess.run(
            [
                "node", gen_js, str(c3_input),
                "--size", str(inner_size),
                "--system", "MARD",
                "--match", "lab",
                "--blank-white",
                "--max-colors", "20",
                "--title", f"{cn} · perler-beads-skill PNG直转(MARD 20色)",
                "--watermark", "perler-beads-skill C3",
                "--out", str(run_dir / f"{name}_C3_perler_skill_PNG_MARD.png"),
                "--csv", str(run_dir / f"{name}_C3_MARD_bom.csv"),
            ],
            check=True,
        )

        # C4 / C5 / C6: COCO, 漫漫, 咪小窝 via existing 64x64 JSON
        in_json = run_dir / f"{name}_64x64.json"
        for tag, system, file_tag in [
            ("C4", "COCO", "COCO"),
            ("C5", "漫漫", "Manman"),
            ("C6", "咪小窝", "Mixiaowo"),
        ]:
            print(f"=== Step 2 ({tag} perler-beads-skill {system}): {name} ===")
            subprocess.run(
                [
                    "node", gen_js, str(in_json),
                    "--system", system,
                    "--match", "lab",
                    "--max-colors", "20",
                    "--title", f"{cn} · perler-beads-skill ({system}色号 20色)",
                    "--watermark", "perler-beads-skill",
                    "--out", str(run_dir / f"{name}_{tag}_perler_skill_{file_tag}.png"),
                    "--csv", str(run_dir / f"{name}_{tag}_{file_tag}_bom.csv"),
                ],
                check=True,
            )


if __name__ == "__main__":
    run_step1_kui_pindou()
    run_step2_b2_quantize_image()
    run_step2_c3_to_c6()
    print("ALL STEP 1 & STEP 2 COMPLETE.")
