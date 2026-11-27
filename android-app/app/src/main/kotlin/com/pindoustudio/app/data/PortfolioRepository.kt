package com.pindoustudio.app.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.net.Uri
import com.pindoustudio.app.engine.ExternalBeadRecognizer
import com.pindoustudio.app.model.BeadDiameter
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.PhotoSlot
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

data class PortfolioColorCount(
    val mardCode: String,
    val nameZh: String,
    val series: String,
    val argb: Int,
    val count: Int
)

data class PortfolioWork(
    val id: String,
    val title: String,
    val width: Int,
    val height: Int,
    val beadMm: Float,
    val totalBeads: Int,
    val colorCount: Int,
    val createdAt: Long,
    val manualCompleted: Boolean,
    val patternFilePath: String,
    val refPhotoPath: String?,
    val chartThumbPath: String?,
    val peggedPhotoPath: String?,
    val ironedPhotoPath: String?,
    val colorBreakdown: List<PortfolioColorCount>
) {
    val isCompleted: Boolean
        get() = manualCompleted || !peggedPhotoPath.isNullOrBlank() || !ironedPhotoPath.isNullOrBlank()

    fun photoPathFor(slot: PhotoSlot): String? = when (slot) {
        PhotoSlot.REFERENCE -> refPhotoPath
        PhotoSlot.CHART -> chartThumbPath
        PhotoSlot.PEGGED -> peggedPhotoPath
        PhotoSlot.IRONED -> ironedPhotoPath
    }
}

data class SeriesStat(
    val series: String,
    val label: String,
    val count: Long,
    val sampleArgb: Int
)

data class CraftAchievement(
    val id: String,
    val title: String,
    val desc: String,
    val unlocked: Boolean,
    val progressText: String
)

data class WorkBeadBar(
    val id: String,
    val title: String,
    val beads: Int,
    val colorCount: Int,
    val completed: Boolean
)

data class PortfolioStats(
    val totalWorks: Int,
    val completedWorks: Int,
    val documentedPhotos: Int,
    val totalBeads: Long,
    val completedBeads: Long,
    val uniqueColorsUsed: Int,
    val totalAreaCm2: Double,
    val equivalentBoards52: Double,
    val chainMeters: Double,
    val largestWorkTitle: String?,
    val largestWorkBeads: Int,
    val rankTitle: String,
    val rankNextGoal: Long,
    val rankProgress: Float,
    val topColors: List<PortfolioColorCount>,
    val seriesStats: List<SeriesStat>,
    val workBars: List<WorkBeadBar>,
    val achievements: List<CraftAchievement>
)

/**
 * 本地离线「拼豆作品组合库 + 成就统计盘」持久化仓库：
 * - 每份作品包含：图纸快照 (.pindou.json) + 4 个完全可选图片槽位（参考图 / 拼豆图纸 / 拼好的图 / 烫好的图）；
 * - 所有图片复制压缩存储到应用私有 filesDir/portfolio/media/，相册删图也不丢档案；
 * - 实时汇总全部作品的用豆总数、颜色排行、色系倾向、拼板等效面积与手作称号里程碑。
 */
class PortfolioRepository(private val context: Context) {

    private val rootDir = File(context.filesDir, "portfolio").apply { mkdirs() }
    private val mediaDir = File(rootDir, "media").apply { mkdirs() }
    private val indexFile = File(rootDir, "works_index.json")

    fun loadAll(): List<PortfolioWork> {
        if (!indexFile.exists()) return emptyList()
        return runCatching {
            val arr = JSONArray(indexFile.readText(Charsets.UTF_8))
            buildList {
                for (i in 0 until arr.length()) {
                    add(decodeWork(arr.getJSONObject(i)))
                }
            }.sortedByDescending { it.createdAt }
        }.getOrElse { emptyList() }
    }

    fun saveNewWork(
        pattern: BeadPattern,
        diameter: BeadDiameter,
        paletteRepo: PaletteRepository,
        refBitmap: Bitmap? = null,
        peggedBitmap: Bitmap? = null,
        ironedBitmap: Bitmap? = null,
        markCompleted: Boolean = false
    ): List<PortfolioWork> {
        val workId = UUID.randomUUID().toString().take(12)
        val workDir = File(mediaDir, workId).apply { mkdirs() }

        val patternFile = File(workDir, "pattern.pindou.json")
        patternFile.writeText(PindouJsonCodec.encode(pattern, paletteRepo), Charsets.UTF_8)

        val chartFile = File(workDir, "chart.png")
        renderCrispChartThumb(pattern, paletteRepo, chartFile)

        var refPath: String? = null
        if (refBitmap != null) {
            val refFile = File(workDir, "ref.jpg")
            saveCompressedBitmap(refBitmap, refFile)
            refPath = refFile.absolutePath
        }
        var peggedPath: String? = null
        if (peggedBitmap != null) {
            val peggedFile = File(workDir, "pegged.jpg")
            saveCompressedBitmap(peggedBitmap, peggedFile)
            peggedPath = peggedFile.absolutePath
        }
        var ironedPath: String? = null
        if (ironedBitmap != null) {
            val ironedFile = File(workDir, "ironed.jpg")
            saveCompressedBitmap(ironedBitmap, ironedFile)
            ironedPath = ironedFile.absolutePath
        }

        val bom = paletteRepo.computeBom(pattern, com.pindoustudio.app.model.BeadBrand.MARD, diameter)
        val breakdown = bom.items.map { item ->
            PortfolioColorCount(
                mardCode = item.mardCode,
                nameZh = item.color.nameZh,
                series = item.color.series,
                argb = item.color.argb,
                count = item.count
            )
        }

        val entry = PortfolioWork(
            id = workId,
            title = pattern.name.ifBlank { "未命名拼豆作品" },
            width = pattern.width,
            height = pattern.height,
            beadMm = diameter.mm,
            totalBeads = bom.totalBeads,
            colorCount = bom.colorCount,
            createdAt = System.currentTimeMillis(),
            manualCompleted = markCompleted,
            patternFilePath = patternFile.absolutePath,
            refPhotoPath = refPath,
            chartThumbPath = chartFile.absolutePath,
            peggedPhotoPath = peggedPath,
            ironedPhotoPath = ironedPath,
            colorBreakdown = breakdown
        )

        val updated = listOf(entry) + loadAll()
        persistAll(updated)
        return updated
    }

    fun attachPhotoFromUri(workId: String, slot: PhotoSlot, uri: Uri): List<PortfolioWork> {
        val works = loadAll()
        val target = works.find { it.id == workId } ?: return works
        val workDir = File(mediaDir, workId).apply { mkdirs() }
        val fileName = when (slot) {
            PhotoSlot.REFERENCE -> "ref_${System.currentTimeMillis()}.jpg"
            PhotoSlot.CHART -> "chart_${System.currentTimeMillis()}.jpg"
            PhotoSlot.PEGGED -> "pegged_${System.currentTimeMillis()}.jpg"
            PhotoSlot.IRONED -> "ironed_${System.currentTimeMillis()}.jpg"
        }
        val dstFile = File(workDir, fileName)
        val decoded = ExternalBeadRecognizer.decodeBoundedBitmap(context, uri, maxSide = 2048)
            ?: return works
        try {
            saveCompressedBitmap(decoded, dstFile)
        } finally {
            decoded.recycle()
        }

        // 清理该槽位旧文件防止残留膨胀
        target.photoPathFor(slot)?.let { oldPath ->
            runCatching {
                val f = File(oldPath)
                if (f.exists() && f.absolutePath != dstFile.absolutePath) f.delete()
            }
        }

        val updated = works.map { w ->
            if (w.id != workId) w
            else when (slot) {
                PhotoSlot.REFERENCE -> w.copy(refPhotoPath = dstFile.absolutePath)
                PhotoSlot.CHART -> w.copy(chartThumbPath = dstFile.absolutePath)
                PhotoSlot.PEGGED -> w.copy(peggedPhotoPath = dstFile.absolutePath)
                PhotoSlot.IRONED -> w.copy(ironedPhotoPath = dstFile.absolutePath)
            }
        }
        persistAll(updated)
        return updated
    }

    fun removePhotoSlot(workId: String, slot: PhotoSlot): List<PortfolioWork> {
        val works = loadAll()
        val updated = works.map { w ->
            if (w.id != workId) w
            else {
                w.photoPathFor(slot)?.let { p -> runCatching { File(p).delete() } }
                when (slot) {
                    PhotoSlot.REFERENCE -> w.copy(refPhotoPath = null)
                    PhotoSlot.CHART -> w.copy(chartThumbPath = null)
                    PhotoSlot.PEGGED -> w.copy(peggedPhotoPath = null)
                    PhotoSlot.IRONED -> w.copy(ironedPhotoPath = null)
                }
            }
        }
        persistAll(updated)
        return updated
    }

    fun toggleCompleted(workId: String): List<PortfolioWork> {
        val works = loadAll()
        val updated = works.map { w ->
            if (w.id != workId) w else w.copy(manualCompleted = !w.manualCompleted)
        }
        persistAll(updated)
        return updated
    }

    fun renameWork(workId: String, newTitle: String): List<PortfolioWork> {
        val clean = newTitle.trim()
        val works = loadAll()
        if (clean.isEmpty()) return works
        val updated = works.map { w ->
            if (w.id != workId) {
                w
            } else {
                runCatching {
                    val f = File(w.patternFilePath)
                    if (f.exists()) {
                        val obj = JSONObject(f.readText(Charsets.UTF_8))
                        obj.put("name", clean)
                        f.writeText(obj.toString(2), Charsets.UTF_8)
                    }
                }
                w.copy(title = clean)
            }
        }
        persistAll(updated)
        return updated
    }

    fun deleteWork(workId: String): List<PortfolioWork> {
        val works = loadAll().filterNot { it.id == workId }
        runCatching { File(mediaDir, workId).deleteRecursively() }
        persistAll(works)
        return works
    }

    fun loadPattern(work: PortfolioWork): BeadPattern? {
        val f = File(work.patternFilePath)
        if (!f.exists()) return null
        return runCatching { PindouJsonCodec.decode(f.readText(Charsets.UTF_8)) }.getOrNull()
    }

    fun computeStats(works: List<PortfolioWork>): PortfolioStats {
        var completedWorks = 0
        var documentedPhotos = 0
        var totalBeads = 0L
        var completedBeads = 0L
        var totalAreaCm2 = 0.0
        var chainMmTotal = 0.0
        var largestWorkTitle: String? = null
        var largestWorkBeads = 0

        val colorAgg = HashMap<String, PortfolioColorCount>()
        val seriesAgg = HashMap<String, Pair<Long, Int>>() // series -> (count, sampleArgb)

        for (w in works) {
            totalBeads += w.totalBeads
            if (w.isCompleted) {
                completedWorks++
                completedBeads += w.totalBeads
            }
            if (!w.refPhotoPath.isNullOrBlank()) documentedPhotos++
            if (!w.chartThumbPath.isNullOrBlank()) documentedPhotos++
            if (!w.peggedPhotoPath.isNullOrBlank()) documentedPhotos++
            if (!w.ironedPhotoPath.isNullOrBlank()) documentedPhotos++

            totalAreaCm2 += w.totalBeads * (w.beadMm * w.beadMm / 100.0)
            chainMmTotal += w.totalBeads * w.beadMm
            if (w.totalBeads > largestWorkBeads) {
                largestWorkBeads = w.totalBeads
                largestWorkTitle = w.title
            }
            for (c in w.colorBreakdown) {
                val prev = colorAgg[c.mardCode]
                colorAgg[c.mardCode] = if (prev == null) c else prev.copy(count = prev.count + c.count)

                val sPrev = seriesAgg[c.series]
                val bestArgb = if ((sPrev?.first ?: 0L) >= c.count) (sPrev?.second ?: c.argb) else c.argb
                seriesAgg[c.series] = ((sPrev?.first ?: 0L) + c.count) to bestArgb
            }
        }

        val topColors = colorAgg.values.sortedByDescending { it.count }.take(8)
        val seriesNames = mapOf(
            "A" to "A 黄橙系",
            "B" to "B 绿系",
            "C" to "C 蓝系",
            "D" to "D 紫系",
            "E" to "E 粉系",
            "F" to "F 红系",
            "G" to "G 棕肤系",
            "H" to "H 黑白灰",
            "M" to "M 灰阶",
            "P" to "P 特珠"
        )
        val sortedSeries = seriesAgg.entries.sortedByDescending { it.value.first }
        val seriesStats = buildList {
            sortedSeries.take(5).forEach { (k, v) ->
                add(SeriesStat(k, seriesNames[k] ?: "$k 系", v.first, v.second))
            }
            if (sortedSeries.size > 5) {
                val restSum = sortedSeries.drop(5).sumOf { it.value.first }
                add(SeriesStat("OTHER", "其他色系", restSum, sortedSeries[5].value.second))
            }
        }

        val workBars = works.sortedByDescending { it.totalBeads }.take(5).map { w ->
            WorkBeadBar(w.id, w.title, w.totalBeads, w.colorCount, w.isCompleted)
        }

        val achievements = listOf(
            CraftAchievement(
                "first_work", "初入豆坑", "收录第1份图纸",
                works.isNotEmpty(), "${min(works.size, 1)}/1"
            ),
            CraftAchievement(
                "first_done", "实物完工", "点亮第1件成品",
                completedWorks >= 1, "${min(completedWorks, 1)}/1"
            ),
            CraftAchievement(
                "kilo_beads", "千豆成画", "累计 1,000 颗豆",
                totalBeads >= 1000L, "${min(totalBeads, 1000L)}/1000"
            ),
            CraftAchievement(
                "color_hunter", "色彩玩家", "驾驭 ≥18 种色号",
                colorAgg.size >= 18, "${min(colorAgg.size, 18)}/18"
            ),
            CraftAchievement(
                "photo_album", "四图档案家", "收集 ≥6 张过程图",
                documentedPhotos >= 6, "${min(documentedPhotos, 6)}/6"
            ),
            CraftAchievement(
                "master_5k", "五千豆达成", "累计 5,000 颗豆",
                totalBeads >= 5000L, "${min(totalBeads, 5000L)}/5000"
            )
        )

        val (rankTitle, prevThresh, nextThresh) = when {
            totalBeads >= 40000 -> Triple("殿堂级拼豆宗师", 40000L, 40000L)
            totalBeads >= 15000 -> Triple("全能拼豆师", 15000L, 40000L)
            totalBeads >= 5000 -> Triple("高产手作人", 5000L, 15000L)
            totalBeads >= 1500 -> Triple("熟练豆匠", 1500L, 5000L)
            totalBeads >= 500 -> Triple("入坑豆友", 500L, 1500L)
            else -> Triple("拼豆萌新", 0L, 500L)
        }
        val progress = if (nextThresh <= prevThresh) 1f else {
            ((totalBeads - prevThresh).toFloat() / (nextThresh - prevThresh)).coerceIn(0f, 1f)
        }

        return PortfolioStats(
            totalWorks = works.size,
            completedWorks = completedWorks,
            documentedPhotos = documentedPhotos,
            totalBeads = totalBeads,
            completedBeads = completedBeads,
            uniqueColorsUsed = colorAgg.size,
            totalAreaCm2 = (totalAreaCm2 * 10.0).roundToInt() / 10.0,
            equivalentBoards52 = ((totalBeads / 2704.0) * 10.0).roundToInt() / 10.0,
            chainMeters = ((chainMmTotal / 1000.0) * 10.0).roundToInt() / 10.0,
            largestWorkTitle = largestWorkTitle,
            largestWorkBeads = largestWorkBeads,
            rankTitle = rankTitle,
            rankNextGoal = nextThresh,
            rankProgress = progress,
            topColors = topColors,
            seriesStats = seriesStats,
            workBars = workBars,
            achievements = achievements
        )
    }

    private fun persistAll(works: List<PortfolioWork>) {
        val arr = JSONArray()
        for (w in works) arr.put(encodeWork(w))
        indexFile.writeText(arr.toString(2), Charsets.UTF_8)
    }

    private fun encodeWork(w: PortfolioWork): JSONObject = JSONObject().apply {
        put("id", w.id)
        put("title", w.title)
        put("width", w.width)
        put("height", w.height)
        put("beadMm", w.beadMm.toDouble())
        put("totalBeads", w.totalBeads)
        put("colorCount", w.colorCount)
        put("createdAt", w.createdAt)
        put("manualCompleted", w.manualCompleted)
        put("patternFilePath", w.patternFilePath)
        put("refPhotoPath", w.refPhotoPath ?: JSONObject.NULL)
        put("chartThumbPath", w.chartThumbPath ?: JSONObject.NULL)
        put("peggedPhotoPath", w.peggedPhotoPath ?: JSONObject.NULL)
        put("ironedPhotoPath", w.ironedPhotoPath ?: JSONObject.NULL)
        val cArr = JSONArray()
        for (c in w.colorBreakdown) {
            cArr.put(JSONObject().apply {
                put("code", c.mardCode)
                put("nameZh", c.nameZh)
                put("series", c.series)
                put("argb", c.argb)
                put("count", c.count)
            })
        }
        put("colorBreakdown", cArr)
    }

    private fun decodeWork(obj: JSONObject): PortfolioWork {
        val cArr = obj.optJSONArray("colorBreakdown") ?: JSONArray()
        val colors = List(cArr.length()) { idx ->
            val co = cArr.getJSONObject(idx)
            PortfolioColorCount(
                mardCode = co.getString("code"),
                nameZh = co.optString("nameZh", ""),
                series = co.optString("series", "H"),
                argb = co.getInt("argb"),
                count = co.getInt("count")
            )
        }
        fun optStrOrNull(key: String): String? {
            if (obj.isNull(key)) return null
            val v = obj.optString(key, "").trim()
            return v.ifEmpty { null }
        }
        return PortfolioWork(
            id = obj.getString("id"),
            title = obj.optString("title", "拼豆作品"),
            width = obj.optInt("width", 40),
            height = obj.optInt("height", 40),
            beadMm = obj.optDouble("beadMm", 2.6).toFloat(),
            totalBeads = obj.optInt("totalBeads", 0),
            colorCount = obj.optInt("colorCount", colors.size),
            createdAt = obj.optLong("createdAt", System.currentTimeMillis()),
            manualCompleted = obj.optBoolean("manualCompleted", false),
            patternFilePath = obj.getString("patternFilePath"),
            refPhotoPath = optStrOrNull("refPhotoPath"),
            chartThumbPath = optStrOrNull("chartThumbPath"),
            peggedPhotoPath = optStrOrNull("peggedPhotoPath"),
            ironedPhotoPath = optStrOrNull("ironedPhotoPath"),
            colorBreakdown = colors
        )
    }

    private fun saveCompressedBitmap(src: Bitmap, outFile: File) {
        val maxSide = 1280f
        val ratio = min(1f, maxSide / max(src.width, src.height))
        val bmp = if (ratio < 0.99f) {
            Bitmap.createScaledBitmap(
                src,
                (src.width * ratio).roundToInt().coerceAtLeast(1),
                (src.height * ratio).roundToInt().coerceAtLeast(1),
                true
            )
        } else src
        FileOutputStream(outFile).use { fos ->
            bmp.compress(Bitmap.CompressFormat.JPEG, 88, fos)
            fos.flush()
        }
        if (bmp !== src) bmp.recycle()
    }

    fun renderPatternPreviewBitmap(pattern: BeadPattern, paletteRepo: PaletteRepository, maxSide: Int = 520): Bitmap {
        val cell = (maxSide / max(pattern.width, pattern.height).coerceAtLeast(1)).coerceIn(4, 16)
        val pad = max(4, cell)
        val wPx = pattern.width * cell + pad * 2
        val hPx = pattern.height * cell + pad * 2
        val bmp = Bitmap.createBitmap(wPx, hPx, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        canvas.drawColor(Color.rgb(250, 246, 240))
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val linePaint = Paint().apply {
            color = Color.argb(38, 35, 31, 29)
            strokeWidth = 1f
        }
        for (r in 0 until pattern.height) {
            for (c in 0 until pattern.width) {
                val entry = paletteRepo.findByMardCode(pattern.get(r, c))
                val x0 = (pad + c * cell).toFloat()
                val y0 = (pad + r * cell).toFloat()
                paint.color = entry?.argb ?: if ((r + c) % 2 == 0) Color.rgb(245, 240, 233) else Color.rgb(238, 232, 223)
                canvas.drawRect(x0, y0, x0 + cell, y0 + cell, paint)
            }
        }
        for (c in 0..pattern.width) {
            val x = (pad + c * cell).toFloat()
            canvas.drawLine(x, pad.toFloat(), x, (pad + pattern.height * cell).toFloat(), linePaint)
        }
        for (r in 0..pattern.height) {
            val y = (pad + r * cell).toFloat()
            canvas.drawLine(pad.toFloat(), y, (pad + pattern.width * cell).toFloat(), y, linePaint)
        }
        return bmp
    }

    private fun renderCrispChartThumb(pattern: BeadPattern, paletteRepo: PaletteRepository, outFile: File) {
        val bmp = renderPatternPreviewBitmap(pattern, paletteRepo, maxSide = 440)
        FileOutputStream(outFile).use { fos ->
            bmp.compress(Bitmap.CompressFormat.PNG, 100, fos)
            fos.flush()
        }
        bmp.recycle()
    }
}
