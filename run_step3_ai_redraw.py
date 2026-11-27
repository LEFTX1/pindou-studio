import subprocess
from collections import deque
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
PERLER_SKILL = BASE / "repos" / "perler-beads-skill"
ARTIFACT_DIR = Path(r"C:\Users\Administrator\.gemini\antigravity\brain\e9d6b73c-8428-402f-96c2-37bcf4c52a6f")
OUT_F = BASE / "outputs" / "pathway_F_ai_redraw"
OUT_F.mkdir(parents=True, exist_ok=True)


def prepare_clean_white_square(src_jpg: Path, dst_png: Path):
    arr = np.array(Image.open(src_jpg).convert("RGB"), dtype=np.int16)
    h, w, _ = arr.shape

    # Flood-fill outer neutral off-white JPEG halo from image borders -> pure #FFFFFF
    max_c = arr.max(axis=2)
    min_c = arr.min(axis=2)
    is_outer_white = (min_c >= 205) & ((max_c - min_c) <= 18)

    visited = np.zeros((h, w), dtype=bool)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if is_outer_white[y, x] and not visited[y, x]:
                visited[y, x] = True
                q.append((y, x))
    for y in range(1, h - 1):
        for x in (0, w - 1):
            if is_outer_white[y, x] and not visited[y, x]:
                visited[y, x] = True
                q.append((y, x))

    while q:
        cy, cx = q.popleft()
        arr[cy, cx] = (255, 255, 255)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and is_outer_white[ny, nx]:
                visited[ny, nx] = True
                q.append((ny, nx))

    fg = ~visited
    ys, xs = np.where(fg)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    cropped = Image.fromarray(arr[y0:y1, x0:x1].astype(np.uint8), mode="RGB")

    side = max(cropped.width, cropped.height)
    pad = max(8, round(side * 0.03))
    canvas_side = side + 2 * pad
    canvas = Image.new("RGB", (canvas_side, canvas_side), (255, 255, 255))
    ox = (canvas_side - cropped.width) // 2
    oy = (canvas_side - cropped.height) // 2
    canvas.paste(cropped, (ox, oy))
    canvas.save(dst_png)
    print(f"Cleaned white halo -> {dst_png.name}: bbox=({x0},{y0})-({x1},{y1}) -> {canvas.size}")


def main():
    gen_js = str(PERLER_SKILL / "scripts" / "generate.js")
    items = [
        ("espeon", "太阳伊布", ARTIFACT_DIR / "espeon_pixel_redraw_1794768075450.jpg"),
        ("umbreon", "月亮伊布", ARTIFACT_DIR / "umbreon_ai_pixel_redraw_1794768110715.jpg"),
    ]
    for name, cn, src_img in items:
        run_dir = OUT_F / name
        run_dir.mkdir(parents=True, exist_ok=True)
        tight_png = run_dir / f"{name}_ai_tight_white_sq.png"
        prepare_clean_white_square(src_img, tight_png)

        out_png = run_dir / f"{name}_F_ai_redraw_MARD.png"
        out_csv = run_dir / f"{name}_F_ai_redraw_bom.csv"
        subprocess.run(
            [
                "node", gen_js, str(tight_png),
                "--size", "52",
                "--system", "MARD",
                "--match", "lab",
                "--blank-white",
                "--white-threshold", "240",
                "--max-colors", "16",
                "--title", f"{cn} · AI像素改绘优化 Path F (MARD 16色)",
                "--watermark", "AI Redraw + perler-beads-skill",
                "--out", str(out_png),
                "--csv", str(out_csv),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
