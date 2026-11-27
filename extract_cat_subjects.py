# -*- coding: utf-8 -*-
"""
高精度提取三张猫咪照片的拼豆主体 + 面向 MARD 221 色卡的白点拉伸与局部特征增强：
- 图一：白猫+葡萄纸箱+黄绳（白猫提纯进 H1/H2/H10，强保粉耳/黄绳 A5/绿葡萄 B9/B23）
- 图二：完整猫脸（白鼻梁/白嘴套提亮，暖橘纹饱和度拉升，锁定双目 H1 眼神高光）
- 图三：单独白猫+蓝格床单包边（白猫提纯，蓝床单冷蓝还原至 C29/C12/D3/C20）
"""

from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from skimage import color as skcolor

PROJECT_ROOT = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project")
INPUTS_DIR = PROJECT_ROOT / "inputs"
PREVIEW_DIR = INPUTS_DIR / "previews"

SRC_IMG1 = Path(r"C:/Users/Administrator/.gemini/antigravity/brain/e9d6b73c-8428-402f-96c2-37bcf4c52a6f/.user_uploaded/media_1794769053783_713fd652.jpg")
SRC_IMG2 = Path(r"C:/Users/Administrator/.gemini/antigravity/brain/e9d6b73c-8428-402f-96c2-37bcf4c52a6f/.user_uploaded/media_1794769055622_d8550817.png")
SRC_IMG3 = Path(r"C:/Users/Administrator/.gemini/antigravity/brain/e9d6b73c-8428-402f-96c2-37bcf4c52a6f/.user_uploaded/media_1794769063556_5bf63f50.jpg")


def tight_crop_rgba(rgba: np.ndarray, pad: int = 4) -> np.ndarray:
    """按非透明区域做紧凑裁剪，保留四边少量安全边距。"""
    alpha = rgba[:, :, 3] > 0
    ys, xs = np.where(alpha)
    if len(ys) == 0:
        return rgba
    y0 = max(0, int(ys.min()) - pad)
    y1 = min(rgba.shape[0], int(ys.max()) + 1 + pad)
    x0 = max(0, int(xs.min()) - pad)
    x1 = min(rgba.shape[1], int(xs.max()) + 1 + pad)
    return rgba[y0:y1, x0:x1]


def fill_internal_holes(mask_bool: np.ndarray) -> np.ndarray:
    """填充掩码内部所有不接触图像四边的封闭孔洞。"""
    u8 = mask_bool.astype(np.uint8)
    inv = 1 - u8
    n_l, labels, _, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    border_labels = (
        set(np.unique(labels[0, :]))
        | set(np.unique(labels[-1, :]))
        | set(np.unique(labels[:, 0]))
        | set(np.unique(labels[:, -1]))
    )
    out = u8.copy()
    for lid in range(1, n_l):
        if lid not in border_labels:
            out[labels == lid] = 1
    return out > 0


def save_rgba_and_white_preview(rgba: np.ndarray, out_png: Path, preview_png: Path) -> None:
    """保存透明底 RGBA PNG 及白底检查预览 PNG。"""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    preview_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(out_png)
    bg = np.full((rgba.shape[0], rgba.shape[1], 3), 255, dtype=np.float32)
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    comp = np.clip(np.round(rgba[:, :, :3].astype(np.float32) * a + bg * (1.0 - a)), 0, 255).astype(np.uint8)
    Image.fromarray(comp, mode="RGB").save(preview_png)


def whiten_white_cat_for_mard(
    rgb: np.ndarray,
    fur_mask: np.ndarray,
    high_l_pivot: float = 73.0,
    pink_boost_mask: np.ndarray | None = None,
) -> np.ndarray:
    """
    面向 MARD 色卡（H1=255, H2=251, H10=235, H12=253/246/238）的白猫连续白点拉伸：
    1) 平滑权重避开黑眼珠 (L<46) 与粉红耳鼻 (a*>7)；
    2) 强效去除暖光偏黄 b* 并拉高亮度 L*，使主受光毛发稳定进入 L* ∈ [94, 100]（落入 H1/H2/H12），
       同时保留阴影层的 H10/H19/M4 过渡而不产生任何硬斑块边缘；
    3) 可选对粉红耳鼻微提粉嫩度使其匹配 F14/F21/F20。
    """
    lab = skcolor.rgb2lab(rgb.astype(np.float64) / 255.0)
    l_ch = lab[:, :, 0]
    a_ch = lab[:, :, 1]
    b_ch = lab[:, :, 2]

    # 高斯平滑连续毛发权重：避开暗眼珠与高饱和粉耳鼻
    w_l = np.clip((l_ch - 48.0) / 22.0, 0.0, 1.0)
    w_pink = np.clip(1.0 - (a_ch - 5.5) / 8.5, 0.0, 1.0)
    w_yellow_ear = np.clip(1.0 - (b_ch - 14.0) / 14.0, 0.0, 1.0)
    raw_w = np.where(fur_mask, w_l * w_pink * w_yellow_ear, 0.0).astype(np.float32)
    smooth_w = cv2.GaussianBlur(raw_w, (27, 27), 0)
    smooth_w = np.where(fur_mask, smooth_w, 0.0)

    # 白点拉伸：以猫毛 85 分位亮度为参考上锚点，将高光区平滑拉升到 97~100
    pos_l = l_ch[fur_mask & (raw_w > 0.35)]
    p_hi = float(np.percentile(pos_l, 82)) if pos_l.size > 0 else 86.0
    p_hi = max(p_hi, high_l_pivot)

    # S 型白点映射：低于 pivot 的阴影轻微提升，高于 pivot 的白毛平滑冲顶至 97~100
    norm_l = np.clip((l_ch - 48.0) / max(10.0, p_hi - 48.0), 0.0, 1.15)
    stretched_l = np.where(
        norm_l >= 0.55,
        88.5 + 11.3 * np.clip((norm_l - 0.55) / 0.50, 0.0, 1.0) ** 0.72,
        60.0 + 28.5 * (norm_l / 0.55),
    )
    lab[:, :, 0] = np.clip(l_ch * (1.0 - smooth_w) + stretched_l * smooth_w, 0.0, 99.8)

    # 剥离暖灯偏黄 b* 与弱偏红 a*：越接近高光区越趋近纯白 (a=0, b=0.8)
    clean_b = np.clip(b_ch * 0.22 - 0.4, -1.0, 3.2)
    clean_a = np.where(a_ch > 0.0, a_ch * 0.30, a_ch)
    lab[:, :, 2] = b_ch * (1.0 - smooth_w * 0.92) + clean_b * (smooth_w * 0.92)
    lab[:, :, 1] = a_ch * (1.0 - smooth_w * 0.85) + clean_a * (smooth_w * 0.85)

    # 可选温和提粉内耳/鼻头
    if pink_boost_mask is not None:
        pw = np.where(pink_boost_mask, np.clip((a_ch - 4.0) / 10.0, 0.0, 1.0), 0.0).astype(np.float32)
        pw = cv2.GaussianBlur(pw, (15, 15), 0)
        lab[:, :, 1] = np.clip(lab[:, :, 1] + pw * 11.0, -50.0, 60.0)
        lab[:, :, 0] = np.clip(lab[:, :, 0] + pw * 6.0, 0.0, 96.0)
        lab[:, :, 2] = np.clip(lab[:, :, 2] - pw * 4.5, -20.0, 40.0)

    fixed_rgb = np.clip(np.round(skcolor.lab2rgb(lab) * 255.0), 0, 255).astype(np.uint8)
    out = rgb.copy()
    out[fur_mask] = fixed_rgb[fur_mask]
    return out


def extract_image1_cat_and_box() -> tuple[Path, Path]:
    """
    采用非破坏性安全矩形区域截取图一（472×466：完整囊括白猫全貌、葡萄纸箱与底部黄色提绳，
    四周仅留适量地砖余量、避开右缘桌布与左上角家具），彻底杜绝细碎抠图造成的耳缘/眼睛/箱角割残；
    同时在区域内完成白猫高光拉伸、黄绳明黄保护与绿葡萄纹理强化。
    """
    rgb = np.array(Image.open(SRC_IMG1).convert("RGB"))
    h, w, _ = rgb.shape

    y0_crop, y1_crop = 212, 678
    x0_crop, x1_crop = 122, 594
    crop_mask = np.zeros((h, w), dtype=bool)
    crop_mask[y0_crop:y1_crop, x0_crop:x1_crop] = True

    img_lab = skcolor.rgb2lab(rgb.astype(np.float64) / 255.0)
    r_ch = rgb[:, :, 0].astype(np.int16)
    g_ch = rgb[:, :, 1].astype(np.int16)
    b_ch = rgb[:, :, 2].astype(np.int16)
    is_yellow_rope = (r_ch >= 130) & (g_ch >= 100) & (b_ch <= 76) & ((r_ch - b_ch) >= 72)

    # 1) 白猫高光白点拉伸（仅作用于猫毛亮部色域，避免碰触四周地砖与纸箱）+ 粉红耳鼻保护提粉
    cat_zone = np.zeros((h, w), dtype=bool)
    cat_zone[225:495, 195:560] = True
    fur_only = crop_mask & cat_zone & (b_ch >= 104) & (img_lab[:, :, 0] >= 53.0) & (img_lab[:, :, 2] <= 21.0)
    pink_head = np.zeros((h, w), dtype=bool)
    pink_head[265:345, 420:552] = True
    rgb_cal = whiten_white_cat_for_mard(rgb, fur_only, high_l_pivot=72.0, pink_boost_mask=pink_head & fur_only)

    # 2) 底部黄色提绳识别、加粗 1px 与明黄增强（准确吸附至 MARD A5/A8 金黄）
    rope_zone = np.zeros((h, w), dtype=bool)
    rope_zone[545:655, 290:530] = True
    rope_seed = (crop_mask & rope_zone & is_yellow_rope).astype(np.uint8)
    rope_thick = (cv2.dilate(rope_seed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0) & crop_mask
    rope_orig = rgb_cal[rope_thick].astype(np.float32)
    rgb_cal[rope_thick] = np.clip(np.round(0.35 * rope_orig + 0.65 * np.array([244.0, 218.0, 60.0])), 0, 255).astype(np.uint8)

    # 3) 纸箱葡萄图案绿调微增，便于在拼豆中保留绿叶葡萄层次
    grape_roi = np.zeros((h, w), dtype=bool)
    grape_roi[426:505, 405:546] = True
    grape_roi[536:632, 248:342] = True
    is_grape_print = crop_mask & grape_roi & (g_ch >= r_ch - 18) & (r_ch <= 122)
    g_out = rgb_cal.astype(np.int16)
    g_out[is_grape_print, 0] = np.clip(g_out[is_grape_print, 0] - 18, 0, 255)
    g_out[is_grape_print, 1] = np.clip(g_out[is_grape_print, 1] + 22, 0, 255)
    g_out[is_grape_print, 2] = np.clip(g_out[is_grape_print, 2] - 12, 0, 255)
    rgb_cal = g_out.astype(np.uint8)

    # 整块实心区域导出，无抠边缺失
    sub_rgb = rgb_cal[y0_crop:y1_crop, x0_crop:x1_crop]
    rgba_crop = np.dstack([sub_rgb, np.full((sub_rgb.shape[0], sub_rgb.shape[1]), 255, dtype=np.uint8)])

    out_png = INPUTS_DIR / "cat1_cat_and_box.png"
    prev_png = PREVIEW_DIR / "cat1_cat_and_box_white_preview.png"
    save_rgba_and_white_preview(rgba_crop, out_png, prev_png)
    print(f"[图一] 区域截取+校准完成: {rgba_crop.shape[1]}x{rgba_crop.shape[0]} -> {out_png}")
    return out_png, prev_png


def extract_image2_cat_face() -> tuple[Path, Path]:
    """
    提取图二完整猫脸 + 全脸白平衡与橘白对比度校准：
    - 白鼻梁与嘴套平滑提纯到 H1/H2/H12/G15
    - 橘色虎斑提升暖橘饱和度 (A9/G10/F18/G3)
    - 锁定左右眼瞳孔内 2x2 高光点为纯白 (255,255,255)
    """
    rgb = np.array(Image.open(SRC_IMG2).convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    smooth_bgr = cv2.bilateralFilter(bgr, d=5, sigmaColor=20, sigmaSpace=5)
    smooth_rgb = cv2.cvtColor(smooth_bgr, cv2.COLOR_BGR2RGB)

    eye_mask = np.zeros(rgb.shape[:2], dtype=bool)
    eye_mask[28:66, 2:130] = True
    blend_rgb = smooth_rgb.copy()
    blend_rgb[eye_mask] = np.clip(
        np.round(0.65 * rgb[eye_mask].astype(np.float32) + 0.35 * smooth_rgb[eye_mask].astype(np.float32)),
        0,
        255,
    ).astype(np.uint8)

    h, w, _ = blend_rgb.shape
    lab = skcolor.rgb2lab(blend_rgb.astype(np.float64) / 255.0)
    l_ch, a_ch, b_ch = lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]

    # 1) 白色鼻梁与白嘴套空间掩码（排除眼睛和橘耳）
    r_f = blend_rgb[:, :, 0].astype(np.float32)
    b_f = blend_rgb[:, :, 2].astype(np.float32)
    white_fur_score = np.clip((l_ch - 56.0) / 18.0, 0.0, 1.0) * np.clip(1.0 - ((r_f - b_f) - 24.0) / 22.0, 0.0, 1.0)
    # 加强鼻梁中央与左右白腮区权重，避开顶部深褐背景(y<20)与粉鼻(y=72..106,x=44..84)
    face_white_roi = np.zeros((h, w), dtype=np.float32)
    cv2.ellipse(face_white_roi, (60, 48), (15, 28), 0, 0, 360, 1.0, -1)   # 鼻梁
    cv2.ellipse(face_white_roi, (30, 96), (26, 26), 0, 0, 360, 1.0, -1)   # 左白腮
    cv2.ellipse(face_white_roi, (96, 94), (26, 25), 0, 0, 360, 1.0, -1)   # 右白腮
    face_white_roi[0:20, :] = 0.0
    face_white_roi = cv2.GaussianBlur(face_white_roi, (15, 15), 0)
    w_white = np.clip(white_fur_score * (0.45 + 0.55 * face_white_roi), 0.0, 1.0)
    # 平滑减去暖暗色偏并拉升至 H1/H2/H12/G15
    lab[:, :, 0] = np.clip(l_ch + w_white * (0.85 * (98.5 - l_ch)), 0.0, 99.5)
    lab[:, :, 2] = b_ch * (1.0 - 0.72 * w_white) + 2.0 * (0.72 * w_white)
    lab[:, :, 1] = a_ch * (1.0 - 0.75 * w_white)

    # 2) 额头与双颊橘毛增强（保护深褐背景 y<20 与黑眼 l<38）
    orange_w = np.clip((r_f - b_f - 32.0) / 24.0, 0.0, 1.0) * np.clip((l_ch - 38.0) / 16.0, 0.0, 1.0)
    orange_w[0:15, 22:110] = 0.0
    orange_w = cv2.GaussianBlur(orange_w.astype(np.float32), (9, 9), 0)
    lab[:, :, 0] = np.clip(lab[:, :, 0] + orange_w * 9.0, 0.0, 90.0)
    lab[:, :, 1] = np.clip(lab[:, :, 1] + orange_w * 8.5, -20.0, 45.0)
    lab[:, :, 2] = np.clip(lab[:, :, 2] + orange_w * 15.0, -20.0, 62.0)

    # 3) 粉色鼻头微调 (y=75..104, x=46..80)
    nose_mask = np.zeros((h, w), dtype=np.float32)
    cv2.ellipse(nose_mask, (60, 91), (15, 11), 0, 0, 360, 1.0, -1)
    nose_mask = cv2.GaussianBlur(nose_mask, (9, 9), 0) * np.clip((68.0 - l_ch) / 20.0, 0.0, 1.0)
    lab[:, :, 1] = np.clip(lab[:, :, 1] + nose_mask * 9.5, -20.0, 45.0)
    lab[:, :, 0] = np.clip(lab[:, :, 0] + nose_mask * 5.0, 0.0, 88.0)

    cal_rgb = np.clip(np.round(skcolor.lab2rgb(lab) * 255.0), 0, 255).astype(np.uint8)

    # 4) 锁定双目瞳孔内 2x2 高光点为纯白 (255, 255, 255) —— 对应原图左瞳孔真实反光及对称右瞳孔高光
    cal_rgb[43:46, 13:16] = [255, 255, 255]
    cal_rgb[43:46, 102:105] = [255, 255, 255]

    full_rgba = np.dstack([cal_rgb, np.full((h, w), 255, dtype=np.uint8)])
    out_full = INPUTS_DIR / "cat2_full_face.png"
    prev_full = PREVIEW_DIR / "cat2_full_face_white_preview.png"
    save_rgba_and_white_preview(full_rgba, out_full, prev_full)

    head_poly = np.array([
        [0, 20], [4, 4], [24, 14], [37, 13], [52, 6],
        [72, 6], [96, 13], [113, 10], [131, 0], [131, 129], [0, 129],
    ], dtype=np.int32)
    alpha_clean = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(alpha_clean, [head_poly], 255)
    clean_rgba = np.dstack([cal_rgb, alpha_clean])
    out_clean = INPUTS_DIR / "cat2_face_clean_top.png"
    prev_clean = PREVIEW_DIR / "cat2_face_clean_top_white_preview.png"
    save_rgba_and_white_preview(clean_rgba, out_clean, prev_clean)
    print(f"[图二] 校准完成: 完整脸 {w}x{h} -> {out_full} | 去顶背景轮廓 -> {out_clean}")
    return out_full, out_clean


def extract_image3_cat_with_bedsheet_edge() -> tuple[Path, Path]:
    """
    采用安全矩形区域截取图三（598×480：完整白猫 + 四周干净蓝格床单余边），
    自然裁掉上方碎花被、左侧其他猫爪与下方木地板，绝不做边缘强行切割；
    对白猫执行高光白点拉伸 (H1/H2/H10)，对床单周边做冷蓝白平衡还原 (C29/C12/D3/C20)。
    """
    rgb = np.array(Image.open(SRC_IMG3).convert("RGB"))
    h, w, _ = rgb.shape

    y0_c, y1_c = 335, 815
    x0_c, x1_c = 88, 686
    rect_zone = np.zeros((h, w), dtype=bool)
    rect_zone[y0_c:y1_c, x0_c:x1_c] = True

    r3 = rgb[:, :, 0].astype(np.int16)
    b3 = rgb[:, :, 2].astype(np.int16)

    # 仅定位猫身用于内部分区白平衡校准，不切割透明度掩码
    roi_cat = np.zeros((h, w), dtype=bool)
    roi_cat[395:776, 114:632] = True
    cat_cand = roi_cat & (r3 >= 128) & ((r3 - b3) >= 14)

    num_l, labels, stats, _ = cv2.connectedComponentsWithStats(cat_cand.astype(np.uint8), connectivity=8)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    cat_seed = (labels == largest).astype(np.uint8)
    cat_closed = cv2.morphologyEx(cat_seed, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)))
    cat_mask = fill_internal_holes(cat_closed > 0)

    # 1) 保护粉橘双耳区，同时对白猫毛发做高光白点拉伸
    ear_pink_mask = np.zeros((h, w), dtype=bool)
    ear_pink_mask[402:492, 480:630] = True
    rgb_cal = whiten_white_cat_for_mard(
        rgb, cat_mask, high_l_pivot=74.0, pink_boost_mask=ear_pink_mask & cat_mask
    )

    # 2) 对矩形区四周蓝格床单做冷蓝白平衡还原（避开猫身 4px 平滑过渡带，避免硬边缘）
    cat_dil9 = cv2.dilate(cat_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) > 0
    sheet_ring = rect_zone & (~cat_dil9)
    sh_f = rgb_cal.astype(np.float32)
    r_s, g_s, b_s = sh_f[:, :, 0], sh_f[:, :, 1], sh_f[:, :, 2]
    lum_s = 0.299 * r_s + 0.587 * g_s + 0.114 * b_s
    is_stripe = sheet_ring & (lum_s >= 148.0) & ((r_s - b_s) >= -8.0)
    sh_out = sh_f.copy()
    is_blue_cloth = sheet_ring & (~is_stripe)
    sh_out[is_blue_cloth, 0] = np.clip(r_s[is_blue_cloth] * 0.78 - 8.0, 0, 255)
    sh_out[is_blue_cloth, 1] = np.clip(g_s[is_blue_cloth] * 0.96 + 4.0, 0, 255)
    sh_out[is_blue_cloth, 2] = np.clip(b_s[is_blue_cloth] * 1.24 + 22.0, 0, 255)

    sh_out[is_stripe, 0] = np.clip(r_s[is_stripe] * 1.10, 0, 255)
    sh_out[is_stripe, 1] = np.clip(g_s[is_stripe] * 1.14, 0, 255)
    sh_out[is_stripe, 2] = np.clip(b_s[is_stripe] * 1.24, 0, 255)
    rgb_cal[sheet_ring] = np.clip(np.round(sh_out[sheet_ring]), 0, 255).astype(np.uint8)

    sub_rgb = rgb_cal[y0_c:y1_c, x0_c:x1_c]
    rgba_crop = np.dstack([sub_rgb, np.full((sub_rgb.shape[0], sub_rgb.shape[1]), 255, dtype=np.uint8)])

    out_png = INPUTS_DIR / "cat3_cat_with_bedsheet_edge.png"
    prev_png = PREVIEW_DIR / "cat3_cat_with_bedsheet_edge_white_preview.png"
    save_rgba_and_white_preview(rgba_crop, out_png, prev_png)
    print(f"[图三] 区域截取+校准完成: {rgba_crop.shape[1]}x{rgba_crop.shape[0]} -> {out_png}")
    return out_png, prev_png


def main():
    extract_image1_cat_and_box()
    extract_image2_cat_face()
    extract_image3_cat_with_bedsheet_edge()


if __name__ == "__main__":
    main()
