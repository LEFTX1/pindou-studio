# -*- coding: utf-8 -*-
"""整理全部 23 条拼豆途径 × 双角色输出为全中文命名汇总目录与报告。"""

import csv
import os
import re
import shutil
import urllib.parse

PROJECT_ROOT = r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project"
OUTPUTS_ROOT = os.path.join(PROJECT_ROOT, "outputs")
ARTIFACT_DIR = r"C:\Users\Administrator\.gemini\antigravity\brain\e9d6b73c-8428-402f-96c2-37bcf4c52a6f"
SUMMARY_DIR = os.path.join(PROJECT_ROOT, "拼豆图纸汇总")

DIR_RAW = os.path.join(SUMMARY_DIR, "00_去背景原图与AI重绘")
DIR_ESPEON = os.path.join(SUMMARY_DIR, "01_太阳伊布_全套图纸与采购清单")
DIR_UMBREON = os.path.join(SUMMARY_DIR, "02_月亮伊布_全套图纸与采购清单")


def inspect_bom(csv_path: str) -> tuple[int, int]:
    """读取采购清单 CSV 并返回 (用色数, 总豆数)。"""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        raise ValueError(f"BOM为空或异常: {csv_path}")
    header = [c.strip() for c in rows[0]]
    count_idx = len(header) - 1
    data_rows = rows[1:]
    if data_rows and ("总计" in data_rows[-1][0] or "total" in data_rows[-1][0].lower()):
        data_rows = data_rows[:-1]
    colors = len(data_rows)
    beads = sum(int(r[count_idx]) for r in data_rows)
    return colors, beads


def build_specs():
    """定义全部 23 条分支与双角色的中文命名规范和源文件路径。"""
    chars = [
        ("espeon", "太阳伊布", DIR_ESPEON),
        ("umbreon", "月亮伊布", DIR_UMBREON),
    ]

    branches = [
        {
            "id": "A1",
            "title": "自研锁相完整圆章",
            "palette": {"espeon": "MARD31色", "umbreon": "MARD48色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_A_precision/{c}_A1_medallion_pattern.png",
                "preview": "pathway_A_precision/{c}_A1_bead_preview.png",
                "bom": "pathway_A_precision/{c}_A1_medallion_bom.csv",
            },
            "desc": "自研锁相 + JPEG 降噪 + `CIEDE2000`（完整圆章）",
            "palette_sys": "MARD 221",
            "note": "**原图还原度最高**：外紫圈与白底统一无噪点，带 5/10 格加重线及圆珠立体预览；花丛色彩丰富",
        },
        {
            "id": "A2",
            "title": "自研纯主体省豆版",
            "palette": {"espeon": "MARD30色", "umbreon": "MARD48色"},
            "grid": {"espeon": "54×49", "umbreon": "53×52"},
            "src_fmt": {
                "pattern": "pathway_A_precision/{c}_A2_inner_pattern.png",
                "preview": "pathway_A_precision/{c}_A2_bead_preview.png",
                "bom": "pathway_A_precision/{c}_A2_inner_bom.csv",
            },
            "desc": "自研纯主体无白圈剥离版",
            "palette_sys": "MARD 221",
            "note": "**最省白豆与紫边豆**：立省约 1400–1600 颗，2×2 拼板（58×58）轻松放下",
        },
        {
            "id": "B1",
            "title": "pindou技能矢量管线",
            "palette": {"espeon": "MARD20色", "umbreon": "MARD20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_B_pindou_skill/{c}/{c}_B_pindou_skill.png",
                "svg": "pathway_B_pindou_skill/{c}/pattern.svg",
                "bom": "pathway_B_pindou_skill/{c}/bom.csv",
            },
            "desc": "`CIawevy/pindou-skill` 原生管线（SVG 1:1 输入）",
            "palette_sys": "MARD 221",
            "note": "**自带分层矢量 SVG**：可用矢量软件二改；无 JPEG 预处理导致白底微裂为 `H1/H2/H13`",
        },
        {
            "id": "B2",
            "title": "pindou技能图片绿幕对照",
            "palette": {"espeon": "MARD20色", "umbreon": "MARD20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_B_pindou_skill/{c}_B2_image_mode/{c}_B2_pindou_skill_image.png",
                "svg": "pathway_B_pindou_skill/{c}_B2_image_mode/pattern.svg",
                "bom": "pathway_B_pindou_skill/{c}_B2_image_mode/bom.csv",
            },
            "desc": "`CIawevy/pindou-skill` 直接图片模式（`quantize.py` + 绿幕抠底 + LANCZOS）",
            "palette_sys": "MARD 221",
            "note": "**典型抗锯齿绿边现象对照**：LANCZOS 重采样使绿幕 `#00FF00` 与外圈混合，外缘出现 `B2/B4` 绿边",
        },
        {
            "id": "C1",
            "title": "perler技能",
            "palette": {"espeon": "MARD20色", "umbreon": "MARD20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_C_perler_beads_skill/{c}/{c}_C1_perler_skill_MARD.png",
                "bom": "pathway_C_perler_beads_skill/{c}/{c}_C1_MARD_bom.csv",
            },
            "desc": "`liangdabiao/perler-beads-skill` JSON 管线（`--match lab`）",
            "palette_sys": "**MARD**",
            "note": "排版带深色表头与 10 格加重线；通用 20 色收拢均衡",
        },
        {
            "id": "C2",
            "title": "perler技能",
            "palette": {"espeon": "盼盼20色", "umbreon": "盼盼20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_C_perler_beads_skill/{c}/{c}_C2_perler_skill_Panpan.png",
                "bom": "pathway_C_perler_beads_skill/{c}/{c}_C2_Panpan_bom.csv",
            },
            "desc": "`liangdabiao/perler-beads-skill` 品牌转换",
            "palette_sys": "**盼盼**",
            "note": "一键映射**盼盼**数字色号",
        },
        {
            "id": "C3",
            "title": "perler技能纯主体PNG直转",
            "palette": {"espeon": "MARD20色", "umbreon": "MARD20色"},
            "grid": {"espeon": "54×54", "umbreon": "53×53"},
            "src_fmt": {
                "pattern": "pathway_C_perler_beads_skill/{c}/{c}_C3_perler_skill_PNG_MARD.png",
                "bom": "pathway_C_perler_beads_skill/{c}/{c}_C3_MARD_bom.csv",
            },
            "desc": "`liangdabiao/perler-beads-skill` 纯主体 PNG 直转（`--blank-white`）",
            "palette_sys": "**MARD**",
            "note": "直接对白底 PNG 抠空；因全局剔除近白色，月亮伊布白色小虎牙一并留空",
        },
        {
            "id": "C4",
            "title": "perler技能",
            "palette": {"espeon": "COCO20色", "umbreon": "COCO20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_C_perler_beads_skill/{c}/{c}_C4_perler_skill_COCO.png",
                "bom": "pathway_C_perler_beads_skill/{c}/{c}_C4_COCO_bom.csv",
            },
            "desc": "`liangdabiao/perler-beads-skill` 品牌转换",
            "palette_sys": "**COCO**",
            "note": "一键映射 **COCO** 色号",
        },
        {
            "id": "C5",
            "title": "perler技能",
            "palette": {"espeon": "漫漫20色", "umbreon": "漫漫20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_C_perler_beads_skill/{c}/{c}_C5_perler_skill_Manman.png",
                "bom": "pathway_C_perler_beads_skill/{c}/{c}_C5_Manman_bom.csv",
            },
            "desc": "`liangdabiao/perler-beads-skill` 品牌转换",
            "palette_sys": "**漫漫**",
            "note": "一键映射 **漫漫** 色号",
        },
        {
            "id": "C6",
            "title": "perler技能",
            "palette": {"espeon": "咪小窝20色", "umbreon": "咪小窝20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_C_perler_beads_skill/{c}/{c}_C6_perler_skill_Mixiaowo.png",
                "bom": "pathway_C_perler_beads_skill/{c}/{c}_C6_Mixiaowo_bom.csv",
            },
            "desc": "`liangdabiao/perler-beads-skill` 品牌转换",
            "palette_sys": "**咪小窝**",
            "note": "一键映射 **咪小窝** 色号",
        },
        {
            "id": "D",
            "title": "BFS新手极简版",
            "palette": {"espeon": "MARD14色", "umbreon": "MARD14色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_D_bfs_simplified/{c}_D_bfs_14colors.png",
                "preview": "pathway_D_bfs_simplified/{c}_D_bead_preview.png",
                "bom": "pathway_D_bfs_simplified/{c}_D_bfs_14colors_bom.csv",
            },
            "desc": "自研 BFS 连通域合并（七卡瓦新手极简版）",
            "palette_sys": "MARD 221",
            "note": "**新手实拼首选**：仅 14 色即可完整覆盖角色、花叶与高光（月亮伊布小虎牙 `H1` 与粉舌 `F9` 保留完整）",
        },
        {
            "id": "E1",
            "title": "kuizuo忠实模式",
            "palette": {"espeon": "MARD291色卡20色", "umbreon": "MARD291色卡20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_E_kui_pindou/{c}/faithful/pattern.png",
                "svg": "pathway_E_kui_pindou/{c}/faithful/pattern.svg",
                "bom": "pathway_E_kui_pindou/{c}/faithful/bom.csv",
            },
            "desc": "`kuizuo/pin-dou`（内置 `image-to-pindou` `faithful` 忠实模式）",
            "palette_sys": "MARD 291",
            "note": "Lanczos3 均值采样 + 291 色卡（含 `T1/ZG6/Q4`），无额外杂点消除",
        },
        {
            "id": "E2",
            "title": "kuizuo拼豆默认模式",
            "palette": {"espeon": "MARD291色卡20色", "umbreon": "MARD291色卡20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_E_kui_pindou/{c}/bead/pattern.png",
                "svg": "pathway_E_kui_pindou/{c}/bead/pattern.svg",
                "bom": "pathway_E_kui_pindou/{c}/bead/bom.csv",
            },
            "desc": "`kuizuo/pin-dou`（`bead` 拼豆默认模式）",
            "palette_sys": "MARD 291",
            "note": "按视觉边缘 `ΔE ≥ 10` 切换主色采样 + ≤2 格孤立小块合并",
        },
        {
            "id": "E3",
            "title": "kuizuo卡通锐边模式",
            "palette": {"espeon": "MARD291色卡20色", "umbreon": "MARD291色卡20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_E_kui_pindou/{c}/cartoon/pattern.png",
                "svg": "pathway_E_kui_pindou/{c}/cartoon/pattern.svg",
                "bom": "pathway_E_kui_pindou/{c}/cartoon/bom.csv",
            },
            "desc": "`kuizuo/pin-dou`（`cartoon` 卡通锐边模式）",
            "palette_sys": "MARD 291",
            "note": "全局加权中位主色 + ≤3 格孤立块融合，轮廓最锐利",
        },
        {
            "id": "F",
            "title": "AI像素重绘精简版",
            "palette": {"espeon": "MARD16色", "umbreon": "MARD16色"},
            "grid": {"espeon": "52×52", "umbreon": "52×52"},
            "src_fmt": {
                "pattern": "pathway_F_ai_redraw/{c}/{c}_F_ai_redraw_MARD.png",
                "bom": "pathway_F_ai_redraw/{c}/{c}_F_ai_redraw_bom.csv",
            },
            "desc": "**AI 像素重绘优化路径**（Q 版白底 16-bit 改绘 + 边界白晕 BFS 清洗 + `perler-beads-skill`）",
            "palette_sys": "MARD",
            "note": "**全新重绘精简版**：去除蕾丝框，16 色、约 1560 颗大色块纯主体，干净好拼且无外围灰边杂点",
        },
        {
            "id": "G",
            "title": "Zippland_Oklab色彩匹配",
            "palette": {"espeon": "MARD48色", "umbreon": "MARD62色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_G_Zippland/{c}/{c}_G_Zippland_Oklab.png",
                "bom": "pathway_G_Zippland/{c}/{c}_G_Zippland_Oklab_bom.csv",
            },
            "desc": "`Zippland/perler-beads`（Oklab 主色池化 + 洪水填充单点合并）",
            "palette_sys": "MARD 291",
            "note": "在感知均匀的 **Oklab** 空间匹配色彩并用洪水填充消除单点噪点，阴影层次细腻",
        },
        {
            "id": "H1",
            "title": "JettWu卡通模式",
            "palette": {"espeon": "MARD20色", "umbreon": "MARD16色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_H_JettWu/{c}/{c}_H1_JettWu_cartoon.png",
                "bom": "pathway_H_JettWu/{c}/{c}_H1_JettWu_cartoon_bom.csv",
            },
            "desc": "`Jett-Wu/Perler_Beads_Generator`（`cartoon` 7×7 卡通模式）",
            "palette_sys": "MARD 221",
            "note": "**无杂边锐利风**：优先保护高饱和/深色轮廓并自动收拢相近浅灰（月亮伊布仅 16 色，零杂点）",
        },
        {
            "id": "H2",
            "title": "JettWu写实模式",
            "palette": {"espeon": "MARD24色", "umbreon": "MARD24色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_H_JettWu/{c}/{c}_H2_JettWu_realistic.png",
                "bom": "pathway_H_JettWu/{c}/{c}_H2_JettWu_realistic_bom.csv",
            },
            "desc": "`Jett-Wu/Perler_Beads_Generator`（`realistic` 5×5 写实模式）",
            "palette_sys": "MARD 221",
            "note": "允许更多灰阶过渡与均值回退，保留花朵渐层纹理",
        },
        {
            "id": "I",
            "title": "beadtune对比保护",
            "palette": {"espeon": "MARD20色", "umbreon": "MARD20色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_I_bead_tune/{c}/{c}_I_bead_tune.png",
                "bom": "pathway_I_bead_tune/{c}/{c}_I_bead_tune_bom.csv",
            },
            "desc": "`saratran/bead-tune`（`blockMode` + 极端明暗保护 + `|ΔL|≥30` 防误删）",
            "palette_sys": "MARD 221",
            "note": "**极高质量 20 色版**：贪心低损消减色数，同时以 Lab 亮度差 ≥30 保护瞳孔与高光点不被当成杂点清除",
        },
        {
            "id": "J1",
            "title": "beadforge_Atkinson抖动去孤点",
            "palette": {"espeon": "MARD37色", "umbreon": "MARD34色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_J_beadforge/{c}/{c}_J1_beadforge_Atkinson.png",
                "bom": "pathway_J_beadforge/{c}/{c}_J1_beadforge_Atkinson_bom.csv",
            },
            "desc": "`Ibook000/beadforge`（Lab `medianCut 24` + LinearRGB **Atkinson** 3/4 抖动 + 去孤点）",
            "palette_sys": "MARD",
            "note": "只扩散 3/4 量化误差并做 `3×3` 非级联去孤点，渐变柔和且孤立单豆明显少于传统抖动",
        },
        {
            "id": "J2",
            "title": "beadforge_FloydSteinberg全色抖动",
            "palette": {"espeon": "MARD93色", "umbreon": "MARD104色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_J_beadforge/{c}/{c}_J2_beadforge_FloydSteinberg.png",
                "bom": "pathway_J_beadforge/{c}/{c}_J2_beadforge_FloydSteinberg_bom.csv",
            },
            "desc": "`Ibook000/beadforge`（LinearRGB **Floyd–Steinberg** 全色抖动）",
            "palette_sys": "MARD",
            "note": "传统全误差扩散基线，微粒纹理最丰富但色号数暴增（不建议直接照此购买 100 种豆子）",
        },
        {
            "id": "K",
            "title": "beadmachine_Go命令行",
            "palette": {"espeon": "Hama15色", "umbreon": "Hama26色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_K_beadmachine/{c}/{c}_K_beadmachine_Hama.png",
                "preview": "pathway_K_beadmachine/{c}/{c}_K_beadmachine_Hama_bead_preview.png",
                "html": "pathway_K_beadmachine/{c}/{c}_beadmachine.html",
                "bom": "pathway_K_beadmachine/{c}/{c}_K_beadmachine_Hama_bom.csv",
            },
            "desc": "`cornelk/beadmachine`（原生编译 **Go CLI** + D50 CIE2000）",
            "palette_sys": "**Hama**",
            "note": "欧洲经典 **Hama** 豆色卡实战，太阳伊布仅 15 色；附带 HTML 网格与圆珠拼板预览",
        },
        {
            "id": "L",
            "title": "KerroKapple纯sRGB基线",
            "palette": {"espeon": "MARD39色", "umbreon": "MARD56色"},
            "grid": {"espeon": "64×64", "umbreon": "64×64"},
            "src_fmt": {
                "pattern": "pathway_L_KerroKapple/{c}/{c}_L_KerroKapple_sRGB.png",
                "bom": "pathway_L_KerroKapple/{c}/{c}_L_KerroKapple_sRGB_bom.csv",
            },
            "desc": "`KerroKapple/Perler`（原生 Node ESM 纯 sRGB 欧氏距离基线）",
            "palette_sys": "MARD 221",
            "note": "用于对比感知色差（Lab / Oklab / CIEDE2000）与纯 sRGB 欧氏距离在浅灰紫、花瓣上的色偏差异",
        },
    ]

    raw_sources = [
        (
            "espeon",
            "太阳伊布",
            "太阳伊布 · 64×64 完整蕾丝圆章去背景提取",
            os.path.join(ARTIFACT_DIR, "espeon_medallion_64x64_upscaled.png"),
            "太阳伊布_01_64x64_去背景完整圆章原图.png",
        ),
        (
            "espeon",
            "太阳伊布",
            "太阳伊布 · 54×49 纯主体去白圈提取",
            os.path.join(ARTIFACT_DIR, "espeon_inner_only_upscaled.png"),
            "太阳伊布_02_54x49_去白圈纯主体原图.png",
        ),
        (
            "espeon",
            "太阳伊布",
            "太阳伊布 · 途径 F AI 像素重绘原图",
            os.path.join(ARTIFACT_DIR, "espeon_pixel_redraw_1794768075450.jpg"),
            "太阳伊布_03_途径F_AI像素重绘原图.jpg",
        ),
        (
            "umbreon",
            "月亮伊布",
            "月亮伊布 · 64×64 完整蕾丝圆章去背景提取",
            os.path.join(ARTIFACT_DIR, "umbreon_medallion_64x64_upscaled.png"),
            "月亮伊布_01_64x64_去背景完整圆章原图.png",
        ),
        (
            "umbreon",
            "月亮伊布",
            "月亮伊布 · 53×52 纯主体去白圈提取",
            os.path.join(ARTIFACT_DIR, "umbreon_inner_only_upscaled.png"),
            "月亮伊布_02_53x52_去白圈纯主体原图.png",
        ),
        (
            "umbreon",
            "月亮伊布",
            "月亮伊布 · 途径 F AI 像素重绘原图",
            os.path.join(ARTIFACT_DIR, "umbreon_ai_pixel_redraw_1794768110715.jpg"),
            "月亮伊布_03_途径F_AI像素重绘原图.jpg",
        ),
    ]
    return chars, branches, raw_sources


def uri(path: str) -> str:
    return "file:///" + path.replace("\\", "/")


def slash(path: str) -> str:
    return path.replace("\\", "/")


def main():
    for d in (SUMMARY_DIR, DIR_RAW, DIR_ESPEON, DIR_UMBREON):
        os.makedirs(d, exist_ok=True)

    chars, branches, raw_sources = build_specs()
    copied_summary = []
    copied_artifacts = []

    # 1. 复制去背景原图与 AI 重绘底图
    raw_records = []
    for char_en, char_zh, label, src_path, dst_name in raw_sources:
        if not os.path.exists(src_path):
            raise FileNotFoundError(f"缺少原图文件: {src_path}")
        dst_sum = os.path.join(DIR_RAW, dst_name)
        dst_art = os.path.join(ARTIFACT_DIR, dst_name)
        shutil.copy2(src_path, dst_sum)
        shutil.copy2(src_path, dst_art)
        copied_summary.append(dst_sum)
        copied_artifacts.append(dst_art)
        raw_records.append((char_en, char_zh, label, dst_sum, dst_art))

    # 2. 复制全部 23 条分支 × 双角色文件
    ext_map = {
        "pattern": ("图纸", ".png"),
        "preview": ("圆珠预览", ".png"),
        "bom": ("采购清单", ".csv"),
        "svg": ("矢量图", ".svg"),
        "html": ("交互图表", ".html"),
    }

    records = {b["id"]: {} for b in branches}
    for b in branches:
        bid = b["id"]
        for char_en, char_zh, target_dir in chars:
            stem = f"{char_zh}_{bid}_{b['title']}_{b['palette'][char_en]}"
            bom_src = os.path.join(OUTPUTS_ROOT, b["src_fmt"]["bom"].format(c=char_en))
            if not os.path.exists(bom_src):
                raise FileNotFoundError(f"缺少BOM文件: {bom_src}")
            n_colors, n_beads = inspect_bom(bom_src)
            expected_colors = int(re.search(r"(\d+)色$", b["palette"][char_en]).group(1))
            if n_colors != expected_colors:
                raise AssertionError(
                    f"色数不匹配 {char_en} {bid}: BOM={n_colors}, 命名={expected_colors}"
                )

            item_files = {}
            for kind, rel_tpl in b["src_fmt"].items():
                src_path = os.path.join(OUTPUTS_ROOT, rel_tpl.format(c=char_en))
                if not os.path.exists(src_path):
                    raise FileNotFoundError(f"缺少输出文件: {src_path}")
                zh_suffix, ext = ext_map[kind]
                dst_name = f"{stem}_{zh_suffix}{ext}"
                dst_sum = os.path.join(target_dir, dst_name)
                shutil.copy2(src_path, dst_sum)
                copied_summary.append(dst_sum)
                item_files[kind] = dst_sum

                if ext in (".png", ".jpg"):
                    dst_art = os.path.join(ARTIFACT_DIR, dst_name)
                    shutil.copy2(src_path, dst_art)
                    copied_artifacts.append(dst_art)
                    item_files[f"{kind}_art"] = dst_art

            records[bid][char_en] = {
                "colors": n_colors,
                "beads": n_beads,
                "files": item_files,
            }

    # 3. 生成更新后的中文路径版对比报告
    lines = [
        "# 太阳伊布 & 月亮伊布 · 拼豆图纸全途径全工具对比总览（共 23 条分支 × 双图 = 46 套图纸）",
        "",
        "> [!NOTE]",
        "> 两张原图均为带渐变星云壁纸的手机壁纸，中心本身是 **64×64 格像素画圆章**。所有途径均已严格执行 **“只要中间图案、不要壁纸背景”**：原生圆章途径保持 **3161 颗**纯前景豆（四角透明留空）；去白圈/AI 改绘途径则仅保留中间主体。所有输出文件已按中文名称整理至 [拼豆图纸汇总](file:///C:/Users/Administrator/.gemini/antigravity/scratch/pindou-project/拼豆图纸汇总)。",
        "",
        "---",
        "",
        "## 一、全途径横向对比一览（按工具与算法分类）",
        "",
        "| 途径编号 | 核心原理 / 工具来源 | 网格尺寸 | 总豆数（太阳 / 月亮） | 用色数（太阳 / 月亮） | 色卡体系 | 实测特点、优势与局限 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for b in branches:
        bid = b["id"]
        es = records[bid]["espeon"]
        um = records[bid]["umbreon"]
        grid = (
            f"`{b['grid']['espeon']}`"
            if b["grid"]["espeon"] == b["grid"]["umbreon"]
            else f"`{b['grid']['espeon']}` / `{b['grid']['umbreon']}`"
        )
        lines.append(
            f"| **{bid}** | {b['desc']} | {grid} | `{es['beads']} / {um['beads']}` | `{es['colors']} / {um['colors']}` | {b['palette_sys']} | {b['note']} |"
        )

    lines.extend(["", "---", "", "## 二、去背景原图提取 & AI 重绘原图对照", "", "````carousel"])
    for idx, (_, _, label, _, dst_art) in enumerate(raw_records):
        if idx > 0:
            lines.append("<!-- slide -->")
        lines.append(f"![{label}]({slash(dst_art)})")
    lines.extend(["````", "", "---", "", "## 三、太阳伊布（Espeon）全途径图纸轮播", "", "````carousel"])

    espeon_slides = []
    for b in branches:
        bid = b["id"]
        es = records[bid]["espeon"]
        cap = f"途径 {bid}：太阳伊布 {b['title']}（{b['palette']['espeon']} · {es['beads']}颗）"
        espeon_slides.append((cap, es["files"]["pattern_art"]))
        if "preview_art" in es["files"]:
            espeon_slides.append((f"途径 {bid}：太阳伊布 {b['title']} 圆珠立体预览", es["files"]["preview_art"]))

    for idx, (cap, art_path) in enumerate(espeon_slides):
        if idx > 0:
            lines.append("<!-- slide -->")
        lines.append(f"![{cap}]({slash(art_path)})")

    lines.extend(["````", "", "---", "", "## 四、月亮伊布（Umbreon）全途径图纸轮播", "", "````carousel"])

    umbreon_slides = []
    for b in branches:
        bid = b["id"]
        um = records[bid]["umbreon"]
        cap = f"途径 {bid}：月亮伊布 {b['title']}（{b['palette']['umbreon']} · {um['beads']}颗）"
        umbreon_slides.append((cap, um["files"]["pattern_art"]))
        if "preview_art" in um["files"]:
            umbreon_slides.append((f"途径 {bid}：月亮伊布 {b['title']} 圆珠立体预览", um["files"]["preview_art"]))

    for idx, (cap, art_path) in enumerate(umbreon_slides):
        if idx > 0:
            lines.append("<!-- slide -->")
        lines.append(f"![{cap}]({slash(art_path)})")

    lines.extend(["````", "", "---", "", "## 五、全套中文命名图纸、矢量 SVG、HTML 与 CSV 采购清单目录"])

    kind_labels = {
        "pattern": "图纸 PNG",
        "preview": "圆珠预览",
        "svg": "矢量 SVG",
        "html": "交互图表 HTML",
        "bom": "采购清单 CSV",
    }

    lines.extend(["", "### 0. 去背景原图与 AI 重绘底图（00_去背景原图与AI重绘）"])
    for _, _, label, dst_sum, _ in raw_records:
        fname = os.path.basename(dst_sum)
        lines.append(f"- **{label}**：[{fname}]({uri(dst_sum)})")

    for char_en, char_zh, _ in chars:
        folder_name = "01_太阳伊布_全套图纸与采购清单" if char_en == "espeon" else "02_月亮伊布_全套图纸与采购清单"
        lines.extend(["", f"### {char_zh}（{folder_name}）"])
        for b in branches:
            bid = b["id"]
            rec = records[bid][char_en]
            fdict = rec["files"]
            parts = []
            for k in ("pattern", "preview", "svg", "html", "bom"):
                if k in fdict:
                    parts.append(f"[{kind_labels[k]}]({uri(fdict[k])})")
            lines.append(
                f"- **{bid} {b['title']}（{b['palette'][char_en]} · {rec['beads']}颗）**：" + " ｜ ".join(parts)
            )

    lines.extend([
        "",
        "---",
        "",
        "## 六、挑选与实拼最终建议",
        "",
        "1. **最推荐新手直接买豆实拼（完整圆章）**：**途径 D（14 色 BFS 精简版）** 或 **途径 H1（`Jett-Wu` 卡通模式：太阳 20 色 / 月亮 16 色）** — 几乎零杂点、色号最少且保留蓝耳/金环/红眼/粉舌等特征细节。",
        "2. **20 色以内画面最干净利落**：**途径 I（`saratran/bead-tune`）** 与 **途径 E3（`kuizuo/pin-dou` cartoon）** — `bead-tune` 独特的 Lab 亮度对比保护（`|ΔL|≥30`）保住了瞳孔和高光，`pin-dou` cartoon 轮廓非常硬朗。",
        "3. **想要最省豆、2×2 小板直接拼纯主体**：**途径 A2（纯主体剥离版）** 或 **途径 F（AI 像素重绘 16 色 `52×52`）** — 只需 **1560–1716 颗**豆子，四块 29×29 标准小板即可装下。",
        "4. **追求原图 100% 色彩渐变还原**：**途径 A1（原生 1:1 精准版）**。",
        "5. **需要特定国内/国际品牌豆子**：**COCO / 漫漫 / 咪小窝 / 盼盼** → **C2 / C4 / C5 / C6**；**Hama 豆子** → **K（`beadmachine` Go 版，太阳伊布仅 15 色）**。",
    ])

    md_content = "\n".join(lines) + "\n"
    artifact_md = os.path.join(ARTIFACT_DIR, "pindou_patterns_comparison.md")
    summary_md = os.path.join(SUMMARY_DIR, "00_拼豆图纸全途径对比总览.md")
    for p in (artifact_md, summary_md):
        with open(p, "w", encoding="utf-8") as f:
            f.write(md_content)

    # 4. 校验所有链接和图片 100% 存在
    links = re.findall(r"file:///([^)\"\s>]+)", md_content)
    imgs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md_content)
    missing_links = [urllib.parse.unquote(r) for r in links if not os.path.exists(urllib.parse.unquote(r))]
    missing_imgs = [p for p in imgs if not os.path.exists(p)]

    print(f"Summary dir files copied: {len(copied_summary)}")
    print(f"Artifact dir Chinese image copies: {len(copied_artifacts)}")
    print(f"Markdown file:/// links verified: {len(links)} (missing: {len(missing_links)})")
    print(f"Markdown carousel images verified: {len(imgs)} (missing: {len(missing_imgs)})")
    if missing_links or missing_imgs:
        raise RuntimeError(f"存在缺失路径! links={missing_links}, imgs={missing_imgs}")


if __name__ == "__main__":
    main()
