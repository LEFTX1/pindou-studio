import json
import os
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
PINDOU_SKILL = BASE / "repos" / "pindou-skill"
PERLER_SKILL = BASE / "repos" / "perler-beads-skill"
INPUTS_DIR = BASE / "inputs"
OUT_B = BASE / "outputs" / "pathway_B_pindou_skill"
OUT_C = BASE / "outputs" / "pathway_C_perler_beads_skill"
OUT_B.mkdir(parents=True, exist_ok=True)
OUT_C.mkdir(parents=True, exist_ok=True)


def make_raw_svg(img_path: Path, svg_path: Path, bg_rgb=(0, 255, 0)):
    rgba = np.array(Image.open(img_path).convert("RGBA"))
    h, w, _ = rgba.shape
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * 10}" height="{h * 10}" viewBox="0 0 {w} {h}">',
        f'<g data-grid-w="{w}" data-grid-h="{h}">',
    ]
    for r in range(h):
        for c in range(w):
            R, G, B, A = rgba[r, c]
            if A == 0:
                R, G, B = bg_rgb
            lines.append(f'<rect x="{c}" y="{r}" width="1" height="1" data-row="{r}" data-col="{c}" fill="rgb({R},{G},{B})"/>')
    lines.append("</g></svg>")
    svg_path.write_text("\n".join(lines), encoding="utf-8")


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


def run_pathway_b(name: str):
    run_dir = OUT_B / name
    run_dir.mkdir(parents=True, exist_ok=True)
    img_path = INPUTS_DIR / f"{name}_medallion_64x64.png"
    raw_svg = run_dir / "raw.svg"
    make_raw_svg(img_path, raw_svg, bg_rgb=(0, 255, 0))

    spec = {
        "spec_id": f"{name}_pindou_skill",
        "palette_id": "mard_221",
        "grid_w": 64,
        "grid_h": 64,
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

    palette_csv = PINDOU_SKILL / "palettes" / "mard_221.csv"
    subprocess.run(
        [
            "python",
            str(PINDOU_SKILL / "scripts" / "svg_to_grid.py"),
            "--svg", str(raw_svg),
            "--spec", str(spec_path),
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
    svg_to_png_via_sharp(run_dir / "pattern.svg", run_dir / f"{name}_B_pindou_skill.png")


def make_perler_json(img_path: Path, json_path: Path):
    rgba = np.array(Image.open(img_path).convert("RGBA"))
    h, w, _ = rgba.shape
    assert h == w, f"Expected square grid, got {w}x{h}"
    pixel_data = []
    for r in range(h):
        for c in range(w):
            R, G, B, A = rgba[r, c]
            if A == 0:
                pixel_data.append("#FFFFFF")  # empty cell
            elif R >= 242 and G >= 242 and B >= 242:
                pixel_data.append("#FEFFFF")  # real white bead (MARD H02 / Panpan 1)
            else:
                hex_c = f"#{R:02X}{G:02X}{B:02X}"
                if hex_c == "#FFFFFF":
                    hex_c = "#FEFFFF"
                pixel_data.append(hex_c)
    json_path.write_text(
        json.dumps({"gridSize": w, "pixelData": pixel_data}, ensure_ascii=False),
        encoding="utf-8",
    )


def run_pathway_c(name: str, cn_title: str):
    run_dir = OUT_C / name
    run_dir.mkdir(parents=True, exist_ok=True)
    img_path = INPUTS_DIR / f"{name}_medallion_64x64.png"
    in_json = run_dir / f"{name}_64x64.json"
    make_perler_json(img_path, in_json)

    # 1) MARD system via JSON (64x64 medallion, Lab color matching, max 20 colors)
    subprocess.run(
        [
            "node",
            str(PERLER_SKILL / "scripts" / "generate.js"),
            str(in_json),
            "--system", "MARD",
            "--match", "lab",
            "--max-colors", "20",
            "--title", f"{cn_title} · perler-beads-skill (MARD 20色)",
            "--watermark", "perler-beads-skill",
            "--out", str(run_dir / f"{name}_C1_perler_skill_MARD.png"),
            "--csv", str(run_dir / f"{name}_C1_MARD_bom.csv"),
        ],
        check=True,
    )

    # 2) 盼盼 system via JSON (showing multi-brand capability)
    subprocess.run(
        [
            "node",
            str(PERLER_SKILL / "scripts" / "generate.js"),
            str(in_json),
            "--system", "盼盼",
            "--match", "lab",
            "--max-colors", "20",
            "--title", f"{cn_title} · perler-beads-skill (盼盼色号 20色)",
            "--watermark", "perler-beads-skill",
            "--out", str(run_dir / f"{name}_C2_perler_skill_Panpan.png"),
            "--csv", str(run_dir / f"{name}_C2_Panpan_bom.csv"),
        ],
        check=True,
    )


if __name__ == "__main__":
    for name, cn in [("espeon", "太阳伊布"), ("umbreon", "月亮伊布")]:
        print(f"=== Running Pathway B for {name} ===")
        run_pathway_b(name)
        print(f"=== Running Pathway C for {name} ===")
        run_pathway_c(name, cn)
