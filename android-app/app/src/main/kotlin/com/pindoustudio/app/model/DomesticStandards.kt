package com.pindoustudio.app.model

import kotlin.math.ceil
import kotlin.math.round

enum class BeadBrand(val key: String, val label: String) {
    MARD("MARD", "MARD"),
    COCO("COCO", "COCO"),
    MANMAN("漫漫", "漫漫"),
    PANPAN("盼盼", "盼盼"),
    MIXIAOWO("咪小窝", "咪小窝")
}

enum class BeadDiameter(val mm: Float, val boardSize: Int, val label: String, val shortLabel: String) {
    MM_26(2.6f, 52, "2.6mm 融合豆", "2.6mm"),
    MM_50(5.0f, 29, "5.0mm 大豆", "5mm")
}

enum class ViewMode(val label: String) {
    GRID("色号图"),
    BAKED("成品预览")
}

enum class DrawTool(val label: String) {
    BRUSH("画笔"),
    ERASER("橡皮"),
    EYEDROPPER("吸管"),
    FILL("填充")
}

enum class ConvertMode(val label: String, val desc: String) {
    PHOTO_FUSION("照片融合精修", "边缘保真 + 色彩聚合 · 适合实拍图"),
    CUTOUT_OUTLINE("异形描边镂空", "自动抠底 + 1格 H5 炭灰描边")
}

enum class MainTab(val label: String) {
    CANVAS("工作台"),
    BOM("用豆清单"),
    CONVERT("图片转图"),
    ARCHIVE("作品馆")
}

enum class PhotoSlot(val label: String, val optionalHint: String) {
    REFERENCE("参考图", "可选"),
    CHART("拼豆图纸", "可选"),
    PEGGED("拼好的图", "可选"),
    IRONED("烫好的图", "可选")
}

data class BoardPreset(
    val id: String,
    val label: String,
    val width: Int,
    val height: Int
)

val DOMESTIC_BOARD_PRESETS = listOf(
    BoardPreset("mini_29", "29×29 迷你板", 29, 29),
    BoardPreset("cutout_40", "40×40 异形小图", 40, 40),
    BoardPreset("medium_48", "48×48 精致中图", 48, 48),
    BoardPreset("standard_52", "52×52 标准大板", 52, 52),
    BoardPreset("fine_72", "72×72 高精大图", 72, 72)
)

data class PaletteColor(
    val id: Int,
    val code: String,
    val hex: String,
    val r: Int,
    val g: Int,
    val b: Int,
    val argb: Int,
    val series: String,
    val nameZh: String,
    val brands: Map<String, String>,
    val labL: Double,
    val labA: Double,
    val labB: Double
) {
    fun codeFor(brand: BeadBrand): String = brands[brand.key] ?: code

    val luminance: Double
        get() = 0.299 * r + 0.587 * g + 0.114 * b
}

data class PhysicalSpec(
    val width: Int,
    val height: Int,
    val beadMm: Float,
    val boardSize: Int,
    val widthCm: Double,
    val heightCm: Double,
    val boardsX: Int,
    val boardsY: Int,
    val totalBoards: Int
)

data class BomItem(
    val mardCode: String,
    val displayCode: String,
    val color: PaletteColor,
    val count: Int,
    val spareCount: Int
)

data class BomSummary(
    val brand: BeadBrand,
    val totalBeads: Int,
    val totalSpareBeads: Int,
    val colorCount: Int,
    val items: List<BomItem>,
    val physical: PhysicalSpec
)

data class BeadPattern(
    val name: String,
    val width: Int,
    val height: Int,
    val cells: List<String?> // size = width * height, row-major
) {
    fun get(r: Int, c: Int): String? {
        if (r !in 0 until height || c !in 0 until width) return null
        return cells[r * width + c]
    }

    fun withUpdatedCells(updated: List<String?>): BeadPattern = copy(cells = updated)
}

data class SampleEntry(
    val id: String,
    val title: String,
    val subtitle: String,
    val file: String
)

fun calcPhysicalSpec(width: Int, height: Int, diameter: BeadDiameter): PhysicalSpec {
    val w = width.coerceAtLeast(1)
    val h = height.coerceAtLeast(1)
    val board = diameter.boardSize
    val wCm = round((w * diameter.mm / 10.0) * 10.0) / 10.0
    val hCm = round((h * diameter.mm / 10.0) * 10.0) / 10.0
    val bx = ceil(w.toDouble() / board).toInt().coerceAtLeast(1)
    val by = ceil(h.toDouble() / board).toInt().coerceAtLeast(1)
    return PhysicalSpec(
        width = w,
        height = h,
        beadMm = diameter.mm,
        boardSize = board,
        widthCm = wCm,
        heightCm = hCm,
        boardsX = bx,
        boardsY = by,
        totalBoards = bx * by
    )
}
