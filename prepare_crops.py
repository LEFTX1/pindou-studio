import os
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, binary_fill_holes, label

INPUTS = {
    "espeon": {
        "path": r"C:/Users/Administrator/.gemini/antigravity/brain/e9d6b73c-8428-402f-96c2-37bcf4c52a6f/.user_uploaded/media_1794766247353_d10c18d1.jpg",
        "tx": 5.770,
        "ty": 5.769,
        "px": 1.769,
        "py": 1.815,
    },
    "umbreon": {
        "path": r"C:/Users/Administrator/.gemini/antigravity/brain/e9d6b73c-8428-402f-96c2-37bcf4c52a6f/.user_uploaded/media_1794766247369_95a51fd8.jpg",
        "tx": 5.040,
        "ty": 5.042,
        "px": 4.050,
        "py": 2.890,
    },
}

OUT_DIR = r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project\inputs"
os.makedirs(OUT_DIR, exist_ok=True)


def sample_grid(cfg: dict) -> np.ndarray:
    arr = np.array(Image.open(cfg["path"]).convert("RGB"), dtype=np.float32)
    tx, ty, px, py = cfg["tx"], cfg["ty"], cfg["px"], cfg["py"]
    k_min, k_max = int(round((150 - px) / tx)), int(round((600 - px) / tx))
    m_min, m_max = int(round((290 - py) / ty)), int(round((710 - py) / ty))
    grid_x = [px + (k + 0.5) * tx for k in range(k_min, k_max)]
    grid_y = [py + (m + 0.5) * ty for m in range(m_min, m_max)]
    G = np.zeros((len(grid_y), len(grid_x), 3), dtype=np.float32)
    for iy, yy in enumerate(grid_y):
        yi = int(round(yy))
        for ix, xx in enumerate(grid_x):
            xi = int(round(xx))
            G[iy, ix] = arr[yi - 1 : yi + 2, xi - 1 : xi + 2].mean(axis=(0, 1))
    return G


def main():
    grids = {}
    interiors = {}
    boxes = {}
    for name, cfg in INPUTS.items():
        G = sample_grid(cfg)
        white_cells = (G[:, :, 0] > 235) & (G[:, :, 1] > 235) & (G[:, :, 2] > 235)
        filled = binary_fill_holes(white_cells)
        labeled_f, _ = label(filled)
        center_label = labeled_f[G.shape[0] // 2, G.shape[1] // 2]
        medallion_interior = labeled_f == center_label
        iy, ix = np.where(medallion_interior)
        grids[name] = G
        interiors[name] = medallion_interior
        boxes[name] = (int(iy.min()), int(iy.max()) + 1, int(ix.min()), int(ix.max()) + 1)

    # Extract exact 64x64 border mask from Espeon (clean light pastel background -> zero ambiguity)
    G_esp = grids["espeon"]
    mi_esp = interiors["espeon"]
    d4 = binary_dilation(mi_esp, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
    b_ref = np.median(G_esp[d4 & (~mi_esp)], axis=0)
    d2 = binary_dilation(mi_esp, structure=np.ones((3, 3)))
    d3 = binary_dilation(d2, structure=np.ones((3, 3)))
    full_esp = mi_esp | ((d3 & (~mi_esp)) & (np.linalg.norm(G_esp - b_ref, axis=2) < 25))
    fy, fx = np.where(full_esp)
    fy0, fy1, fx0, fx1 = int(fy.min()), int(fy.max()) + 1, int(fx.min()), int(fx.max()) + 1
    shared_64_mask = full_esp[fy0:fy1, fx0:fx1]
    assert shared_64_mask.shape == (64, 64), f"Expected 64x64, got {shared_64_mask.shape}"

    # Verify Umbreon interior aligns inside the same 64x64 box (2px margin around 60x60 interior)
    for name in ["espeon", "umbreon"]:
        G = grids[name]
        mi = interiors[name]
        y0, y1, x0, x1 = boxes[name]
        assert (y1 - y0, x1 - x0) == (60, 60), f"{name} interior shape {(y1-y0, x1-x0)}"
        sub_G = G[y0 - 2 : y1 + 2, x0 - 2 : x1 + 2]
        sub_mi = mi[y0 - 2 : y1 + 2, x0 - 2 : x1 + 2]
        # Union with shared 64x64 lace border mask
        med_mask = shared_64_mask | sub_mi

        med_rgb = np.clip(np.round(sub_G), 0, 255).astype(np.uint8)
        med_rgba = np.zeros((64, 64, 4), dtype=np.uint8)
        med_rgba[:, :, :3] = med_rgb
        med_rgba[med_mask, 3] = 255
        med_img = Image.fromarray(med_rgba, mode="RGBA")
        med_img.save(os.path.join(OUT_DIR, f"{name}_medallion_64x64.png"))
        med_img.resize((640, 640), Image.Resampling.NEAREST).save(
            os.path.join(OUT_DIR, f"{name}_medallion_64x64_upscaled.png")
        )

        # Inner sprite without outer lace border & white lace ring
        white_sub = (sub_G[:, :, 0] > 235) & (sub_G[:, :, 1] > 235) & (sub_G[:, :, 2] > 235)
        labeled_w, _ = label(white_sub & sub_mi)
        counts = np.bincount(labeled_w.ravel())
        counts[0] = 0
        ring_label = int(counts.argmax())
        outer_white_ring = labeled_w == ring_label
        inner_mask = sub_mi & (~outer_white_ring)
        iy, ix = np.where(inner_mask)
        ix0, ix1 = int(ix.min()), int(ix.max()) + 1
        iy0, iy1 = int(iy.min()), int(iy.max()) + 1
        in_rgb = med_rgb[iy0:iy1, ix0:ix1]
        in_m = inner_mask[iy0:iy1, ix0:ix1]
        in_rgba = np.zeros((in_rgb.shape[0], in_rgb.shape[1], 4), dtype=np.uint8)
        in_rgba[:, :, :3] = in_rgb
        in_rgba[in_m, 3] = 255
        in_img = Image.fromarray(in_rgba, mode="RGBA")
        in_img.save(os.path.join(OUT_DIR, f"{name}_inner_only.png"))
        in_img.resize((in_img.width * 10, in_img.height * 10), Image.Resampling.NEAREST).save(
            os.path.join(OUT_DIR, f"{name}_inner_only_upscaled.png")
        )
        print(
            f"{name}: medallion={med_img.size} (beads={int(med_mask.sum())}), "
            f"inner={in_img.size} (beads={int(in_m.sum())})"
        )


if __name__ == "__main__":
    main()
