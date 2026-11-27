package com.pindoustudio.app.data

import android.content.Context
import android.graphics.Bitmap
import android.util.Base64
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.SampleEntry
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.time.Instant
import java.util.UUID

object PindouJsonCodec {

    fun loadSamplesIndex(context: Context): List<SampleEntry> {
        val raw = context.assets.open("samples/index.json").bufferedReader().use { it.readText() }
        val arr = JSONArray(raw)
        return List(arr.length()) { idx ->
            val obj = arr.getJSONObject(idx)
            SampleEntry(
                id = obj.getString("id"),
                title = obj.getString("title"),
                subtitle = obj.getString("subtitle"),
                file = obj.getString("file")
            )
        }
    }

    fun loadFromAsset(context: Context, assetPath: String): BeadPattern {
        val raw = context.assets.open(assetPath).bufferedReader().use { it.readText() }
        return decode(raw)
    }

    fun decode(jsonText: String): BeadPattern {
        val root = JSONObject(jsonText)
        val projects = root.getJSONArray("projects")
        val proj = projects.getJSONObject(0)
        val patternObj = proj.getJSONObject("pattern")
        val snap = patternObj.getJSONObject("snapshot")
        val w = snap.getInt("w")
        val h = snap.getInt("h")
        val cObj = snap.getJSONObject("c")
        val pArr = cObj.getJSONArray("p")
        val codes = Array(pArr.length()) { i -> PaletteRepository.normalizeMardCode(pArr.getString(i)) }
        val size = cObj.optInt("s", 1)
        val bytes = Base64.decode(cObj.getString("d"), Base64.DEFAULT)

        val cells = ArrayList<String?>(w * h)
        for (i in 0 until w * h) {
            val v = if (size == 1) {
                if (i < bytes.size) bytes[i].toInt() and 0xFF else 0
            } else {
                val off = i * 2
                if (off + 1 < bytes.size) (bytes[off].toInt() and 0xFF) or ((bytes[off + 1].toInt() and 0xFF) shl 8) else 0
            }
            if (v == 0 || v > codes.size) {
                cells.add(null)
            } else {
                cells.add(codes[v - 1])
            }
        }
        val name = patternObj.optString("name", proj.optString("name", "豆绘工坊作品"))
        return BeadPattern(name = name, width = w, height = h, cells = cells)
    }

    fun encode(pattern: BeadPattern, paletteRepo: PaletteRepository): String {
        val usedCodes = pattern.cells.filterNotNull().map { PaletteRepository.normalizeMardCode(it) }.distinct().sorted()
        val codeToOneBased = usedCodes.withIndex().associate { (i, c) -> c to (i + 1) }
        val size = if (usedCodes.size < 255) 1 else 2
        val buf = ByteArray(pattern.width * pattern.height * size)

        val thumb = Bitmap.createBitmap(pattern.width.coerceAtLeast(1), pattern.height.coerceAtLeast(1), Bitmap.Config.ARGB_8888)
        for (r in 0 until pattern.height) {
            for (c in 0 until pattern.width) {
                val idx = r * pattern.width + c
                val code = pattern.get(r, c)?.let { PaletteRepository.normalizeMardCode(it) }
                val value = if (code != null) codeToOneBased[code] ?: 0 else 0
                if (size == 1) {
                    buf[idx] = value.toByte()
                } else {
                    buf[2 * idx] = (value and 0xFF).toByte()
                    buf[2 * idx + 1] = ((value ushr 8) and 0xFF).toByte()
                }
                val entry = if (code != null) paletteRepo.findByMardCode(code) else null
                if (entry != null) {
                    thumb.setPixel(c, r, entry.argb)
                }
            }
        }

        val thumbBytes = ByteArrayOutputStream().use { bos ->
            thumb.compress(Bitmap.CompressFormat.PNG, 100, bos)
            bos.toByteArray()
        }
        thumb.recycle()
        val thumbB64 = Base64.encodeToString(thumbBytes, Base64.NO_WRAP)
        val now = Instant.now().toString()

        val root = JSONObject().apply {
            put("schemaVersion", 4)
            put("exportedAt", now)
            put("sources", JSONArray().put("data:image/png;base64,$thumbB64"))
            put(
                "projects",
                JSONArray().put(
                    JSONObject().apply {
                        put("id", UUID.randomUUID().toString())
                        put("name", pattern.name)
                        put("createdAt", now)
                        put("updatedAt", now)
                        put("sourceName", "${pattern.name}.png")
                        put("source", 0)
                        put(
                            "settings",
                            JSONObject().apply {
                                put("longestEdge", maxOf(pattern.width, pattern.height))
                                put("maxColors", usedCodes.size)
                                put("paletteSize", 221)
                                put("processingMode", "domestic_standard")
                                put("mode", "android_native")
                            }
                        )
                        put(
                            "pattern",
                            JSONObject().apply {
                                put("id", UUID.randomUUID().toString())
                                put("name", pattern.name)
                                put("createdAt", now)
                                put(
                                    "snapshot",
                                    JSONObject().apply {
                                        put("w", pattern.width)
                                        put("h", pattern.height)
                                        put(
                                            "c",
                                            JSONObject().apply {
                                                put("p", JSONArray(usedCodes))
                                                put("d", Base64.encodeToString(buf, Base64.NO_WRAP))
                                                put("s", size)
                                            }
                                        )
                                        put(
                                            "o",
                                            JSONObject().apply {
                                                put("x", 0)
                                                put("y", 0)
                                                put("width", pattern.width)
                                                put("height", pattern.height)
                                            }
                                        )
                                    }
                                )
                            }
                        )
                    }
                )
            )
        }
        return root.toString()
    }
}
