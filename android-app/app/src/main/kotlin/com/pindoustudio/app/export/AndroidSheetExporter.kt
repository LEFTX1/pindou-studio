package com.pindoustudio.app.export

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import com.pindoustudio.app.data.PaletteRepository
import com.pindoustudio.app.data.PindouJsonCodec
import com.pindoustudio.app.engine.BakedPhysicsRenderer
import com.pindoustudio.app.model.BeadBrand
import com.pindoustudio.app.model.BeadDiameter
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.calcPhysicalSpec
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.ceil

object AndroidSheetExporter {

    private fun timestampSuffix(): String =
        SimpleDateFormat("HHmmss", Locale.US).format(Date())

    fun renderSheetBitmap(
        pattern: BeadPattern,
        paletteRepo: PaletteRepository,
        brand: BeadBrand,
        diameter: BeadDiameter
    ): Bitmap {
        val bom = paletteRepo.computeBom(pattern, brand, diameter)
        val phys = bom.physical
        val w = pattern.width
        val h = pattern.height
        val cellPx = if (maxOf(w, h) <= 44) 36 else 28
        val ruler = 34
        val headerH = 88
        val pad = 28
        val gridPxW = w * cellPx
        val gridPxH = h * cellPx

        val colsPerLeg = 2
        val legRows = ceil(bom.items.size.toDouble() / colsPerLeg).toInt().coerceAtLeast(1)
        val legH = 72 + legRows * 38 + 24
        val canvasW = maxOf(880, pad * 2 + ruler * 2 + gridPxW)
        val canvasH = headerH + ruler * 2 + gridPxH + legH + pad

        val bmp = Bitmap.createBitmap(canvasW, canvasH, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        canvas.drawColor(Color.rgb(249, 246, 240))

        val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(35, 31, 29)
            textSize = 30f
            typeface = Typeface.DEFAULT_BOLD
        }
        val subPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(107, 98, 91)
            textSize = 18f
        }
        canvas.drawText("${pattern.name} · ${brand.label} 施工图纸", pad.toFloat(), 40f, titlePaint)
        canvas.drawText(
            "规格 ${w}×${h}格 | 实拼 ${bom.totalBeads}颗 (${bom.colorCount}色) | ${phys.beadMm}mm成品 ${phys.widthCm}×${phys.heightCm}cm | ${phys.boardSize}板 ${phys.boardsX}×${phys.boardsY}块",
            pad.toFloat(),
            70f,
            subPaint
        )

        val gx0 = ((canvasW - gridPxW) / 2f)
        val gy0 = (headerH + ruler).toFloat()

        val fillPaint = Paint()
        val cellTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textAlign = Paint.Align.CENTER
            typeface = Typeface.MONOSPACE
            isFakeBoldText = true
            textSize = (cellPx * 0.34f).coerceAtLeast(9f)
        }

        for (r in 0 until h) {
            for (c in 0 until w) {
                val x = gx0 + c * cellPx
                val y = gy0 + r * cellPx
                val mard = pattern.get(r, c)
                val entry = paletteRepo.findByMardCode(mard)
                if (entry == null) {
                    fillPaint.color = if ((r + c) % 2 == 0) Color.rgb(248, 245, 239) else Color.rgb(240, 235, 226)
                    canvas.drawRect(x, y, x + cellPx, y + cellPx, fillPaint)
                } else {
                    fillPaint.color = entry.argb
                    canvas.drawRect(x, y, x + cellPx, y + cellPx, fillPaint)
                    val disp = entry.codeFor(brand)
                    cellTextPaint.color = if (entry.luminance > 142) Color.rgb(25, 22, 20) else Color.WHITE
                    val fm = cellTextPaint.fontMetrics
                    val cy = y + cellPx / 2f - (fm.ascent + fm.descent) / 2f
                    canvas.drawText(disp, x + cellPx / 2f, cy, cellTextPaint)
                }
            }
        }

        val gridPaint = Paint()
        for (c in 0..w) {
            val x = gx0 + c * cellPx
            when {
                c % 10 == 0 -> { gridPaint.color = Color.rgb(55, 48, 43); gridPaint.strokeWidth = 2.2f }
                c % 5 == 0 -> { gridPaint.color = Color.rgb(125, 115, 106); gridPaint.strokeWidth = 1.4f }
                else -> { gridPaint.color = Color.rgb(205, 196, 186); gridPaint.strokeWidth = 0.8f }
            }
            canvas.drawLine(x, gy0, x, gy0 + gridPxH, gridPaint)
        }
        for (r in 0..h) {
            val y = gy0 + r * cellPx
            when {
                r % 10 == 0 -> { gridPaint.color = Color.rgb(55, 48, 43); gridPaint.strokeWidth = 2.2f }
                r % 5 == 0 -> { gridPaint.color = Color.rgb(125, 115, 106); gridPaint.strokeWidth = 1.4f }
                else -> { gridPaint.color = Color.rgb(205, 196, 186); gridPaint.strokeWidth = 0.8f }
            }
            canvas.drawLine(gx0, y, gx0 + gridPxW, y, gridPaint)
        }

        val axisPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(95, 86, 78)
            textSize = 11f
            typeface = Typeface.MONOSPACE
            textAlign = Paint.Align.CENTER
        }
        for (c in 0 until w) {
            if (w <= 48 || (c + 1) % 2 == 1 || (c + 1) % 5 == 0) {
                canvas.drawText("${c + 1}", gx0 + (c + 0.5f) * cellPx, gy0 - 8f, axisPaint)
            }
        }
        axisPaint.textAlign = Paint.Align.RIGHT
        for (r in 0 until h) {
            if (h <= 48 || (r + 1) % 2 == 1 || (r + 1) % 5 == 0) {
                canvas.drawText("${r + 1}", gx0 - 8f, gy0 + (r + 0.65f) * cellPx, axisPaint)
            }
        }

        val ly0 = gy0 + gridPxH + ruler + 18f
        canvas.drawText(
            "${brand.label} 采购清单（含10%备豆建议共 ${bom.totalSpareBeads} 颗）",
            pad.toFloat(),
            ly0 + 18f,
            Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(35, 31, 29); textSize = 22f; typeface = Typeface.DEFAULT_BOLD }
        )
        val colW = (canvasW - pad * 2) / colsPerLeg.toFloat()
        val legPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(35, 31, 29); textSize = 18f }
        bom.items.forEachIndexed { idx, item ->
            val col = idx % colsPerLeg
            val row = idx / colsPerLeg
            val ix = pad + col * colW
            val iy = ly0 + 48f + row * 38f
            fillPaint.color = item.color.argb
            canvas.drawRoundRect(RectF(ix, iy - 18f, ix + 24f, iy + 6f), 5f, 5f, fillPaint)
            val mardNote = if (brand != BeadBrand.MARD) " (${item.mardCode})" else ""
            canvas.drawText(
                "${item.displayCode}$mardNote ${item.color.nameZh}  ×${item.count}颗 (备${item.spareCount})",
                ix + 34f,
                iy,
                legPaint
            )
        }
        return bmp
    }

    fun renderBakedBitmap(
        pattern: BeadPattern,
        paletteRepo: PaletteRepository,
        diameter: BeadDiameter = BeadDiameter.MM_26
    ): Bitmap {
        val rendered = BakedPhysicsRenderer.render(
            pattern = pattern,
            paletteRepo = paletteRepo,
            maxCanvasPx = 1080
        )
        val out = Bitmap.createBitmap(rendered.width, rendered.height + 42, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(out)
        canvas.drawColor(Color.rgb(229, 220, 208))
        canvas.drawBitmap(rendered, 0f, 0f, null)
        rendered.recycle()

        val phys = calcPhysicalSpec(pattern.width, pattern.height, diameter)
        val capPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.rgb(107, 98, 91)
            textSize = 20f
            textAlign = Paint.Align.CENTER
        }
        val tag = "${pattern.name} · ${diameter.shortLabel} 成品实寸约 ${phys.widthCm}×${phys.heightCm} cm"
        canvas.drawText(tag, out.width / 2f, out.height - 16f, capPaint)
        return out
    }

    private fun saveBitmapToGallery(
        context: Context,
        bmp: Bitmap,
        filename: String,
        mimeType: String,
        format: Bitmap.CompressFormat,
        quality: Int
    ): String {
        val resolver = context.contentResolver
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, filename)
                put(MediaStore.Images.Media.MIME_TYPE, mimeType)
                put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/豆绘工坊")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: error("无法写入系统相册")
            resolver.openOutputStream(uri)?.use { os ->
                if (!bmp.compress(format, quality, os)) error("图片编码失败")
            } ?: error("无法打开相册输出流")
            values.clear()
            values.put(MediaStore.Images.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            return "Pictures/豆绘工坊/$filename"
        } else {
            @Suppress("DEPRECATION")
            val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), "豆绘工坊").apply { mkdirs() }
            val outFile = File(dir, filename)
            FileOutputStream(outFile).use { os -> bmp.compress(format, quality, os) }
            MediaScannerConnection.scanFile(context, arrayOf(outFile.absolutePath), arrayOf(mimeType), null)
            return "Pictures/豆绘工坊/$filename"
        }
    }

    private fun saveBytesToDownloads(
        context: Context,
        bytes: ByteArray,
        filename: String,
        mimeType: String
    ): String {
        val resolver = context.contentResolver
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, filename)
                put(MediaStore.Downloads.MIME_TYPE, mimeType)
                put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/豆绘工坊")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: error("无法写入系统下载目录")
            resolver.openOutputStream(uri)?.use { it.write(bytes) } ?: error("无法打开下载输出流")
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            return "Download/豆绘工坊/$filename"
        } else {
            @Suppress("DEPRECATION")
            val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "豆绘工坊").apply { mkdirs() }
            val outFile = File(dir, filename)
            outFile.writeBytes(bytes)
            MediaScannerConnection.scanFile(context, arrayOf(outFile.absolutePath), arrayOf(mimeType), null)
            return "Download/豆绘工坊/$filename"
        }
    }

    fun exportPngToGallery(
        context: Context,
        pattern: BeadPattern,
        repo: PaletteRepository,
        brand: BeadBrand,
        diameter: BeadDiameter
    ): String {
        val bmp = renderSheetBitmap(pattern, repo, brand, diameter)
        val filename = "${pattern.name}_${brand.key}_施工图_${timestampSuffix()}.png"
        return try {
            saveBitmapToGallery(context, bmp, filename, "image/png", Bitmap.CompressFormat.PNG, 100)
        } finally {
            bmp.recycle()
        }
    }

    fun exportBakedJpgToGallery(
        context: Context,
        pattern: BeadPattern,
        repo: PaletteRepository,
        diameter: BeadDiameter = BeadDiameter.MM_26
    ): String {
        val bmp = renderBakedBitmap(pattern, repo, diameter)
        val filename = "${pattern.name}_成品效果图_${timestampSuffix()}.jpg"
        return try {
            saveBitmapToGallery(context, bmp, filename, "image/jpeg", Bitmap.CompressFormat.JPEG, 95)
        } finally {
            bmp.recycle()
        }
    }

    fun sharePng(
        context: Context,
        pattern: BeadPattern,
        repo: PaletteRepository,
        brand: BeadBrand,
        diameter: BeadDiameter
    ): String {
        val bmp = renderSheetBitmap(pattern, repo, brand, diameter)
        val dir = File(context.cacheDir, "exports").apply { mkdirs() }
        val file = File(dir, "${pattern.name}_${brand.key}_图纸.png")
        FileOutputStream(file).use { fos -> bmp.compress(Bitmap.CompressFormat.PNG, 100, fos) }
        bmp.recycle()
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "image/png"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        val chooser = Intent.createChooser(intent, "分享拼豆施工图").apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(chooser)
        return file.name
    }

    fun exportCsvToDownloads(
        context: Context,
        pattern: BeadPattern,
        repo: PaletteRepository,
        brand: BeadBrand,
        diameter: BeadDiameter
    ): String {
        val bom = repo.computeBom(pattern, brand, diameter)
        val sb = StringBuilder("\uFEFF")
        sb.appendLine("当前品牌(${brand.key})色号,MARD基准色号,色系,中文色名,HEX,实拼颗数,建议采购含10%备豆,MARD,COCO,漫漫,盼盼,咪小窝")
        for (item in bom.items) {
            val b = item.color.brands
            sb.appendLine(
                listOf(
                    item.displayCode,
                    item.mardCode,
                    item.color.series,
                    item.color.nameZh,
                    item.color.hex,
                    item.count,
                    item.spareCount,
                    b["MARD"].orEmpty(),
                    b["COCO"].orEmpty(),
                    b["漫漫"].orEmpty(),
                    b["盼盼"].orEmpty(),
                    b["咪小窝"].orEmpty()
                ).joinToString(",")
            )
        }
        val filename = "${pattern.name}_${brand.key}_五品牌采购清单_${timestampSuffix()}.csv"
        return saveBytesToDownloads(context, sb.toString().toByteArray(Charsets.UTF_8), filename, "text/csv")
    }

    fun exportPindouJsonToDownloads(
        context: Context,
        pattern: BeadPattern,
        repo: PaletteRepository
    ): String {
        val json = PindouJsonCodec.encode(pattern, repo)
        val filename = "${pattern.name}_${timestampSuffix()}.pindou.json"
        return saveBytesToDownloads(context, json.toByteArray(Charsets.UTF_8), filename, "application/json")
    }
}
