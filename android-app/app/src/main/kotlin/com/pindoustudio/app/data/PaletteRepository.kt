package com.pindoustudio.app.data

import android.content.Context
import android.graphics.Color
import com.pindoustudio.app.model.BeadBrand
import com.pindoustudio.app.model.BeadDiameter
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.BomItem
import com.pindoustudio.app.model.BomSummary
import com.pindoustudio.app.model.PaletteColor
import com.pindoustudio.app.model.calcPhysicalSpec
import org.json.JSONArray
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.PI
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

class PaletteRepository(context: Context) {

    val palette: List<PaletteColor>
    private val codeMap: Map<String, PaletteColor>

    init {
        val raw = context.assets.open("domestic_standard_palette.json").bufferedReader().use { it.readText() }
        val arr = JSONArray(raw)
        val list = ArrayList<PaletteColor>(arr.length())
        for (i in 0 until arr.length()) {
            val obj = arr.getJSONObject(i)
            val r = obj.getInt("r")
            val g = obj.getInt("g")
            val b = obj.getInt("b")
            val brandsObj = obj.getJSONObject("brands")
            val brands = HashMap<String, String>(5)
            for (brand in BeadBrand.entries) {
                brands[brand.key] = brandsObj.optString(brand.key, obj.getString("code"))
            }
            val lab = rgbToLab(r, g, b)
            list.add(
                PaletteColor(
                    id = obj.getInt("id"),
                    code = normalizeMardCode(obj.getString("code")),
                    hex = obj.getString("hex"),
                    r = r,
                    g = g,
                    b = b,
                    argb = Color.rgb(r, g, b),
                    series = obj.optString("series", "A"),
                    nameZh = obj.optString("name_zh", ""),
                    brands = brands,
                    labL = lab[0],
                    labA = lab[1],
                    labB = lab[2]
                )
            )
        }
        palette = list
        codeMap = list.associateBy { it.code }
    }

    fun findByMardCode(code: String?): PaletteColor? {
        if (code.isNullOrBlank()) return null
        return codeMap[normalizeMardCode(code)]
    }

    fun translateCode(mardCode: String?, brand: BeadBrand): String {
        val norm = normalizeMardCode(mardCode.orEmpty())
        val entry = codeMap[norm] ?: return norm
        return entry.codeFor(brand)
    }

    fun filteredPalette(suppressGreenCast: Boolean): List<PaletteColor> {
        if (!suppressGreenCast) return palette
        return palette.filter { it.code !in GREEN_CAST_TRAP_CODES }
    }

    fun computeBom(
        pattern: BeadPattern,
        brand: BeadBrand,
        diameter: BeadDiameter
    ): BomSummary {
        val counts = HashMap<String, Int>()
        for (cell in pattern.cells) {
            if (!cell.isNullOrBlank()) {
                val norm = normalizeMardCode(cell)
                counts[norm] = (counts[norm] ?: 0) + 1
            }
        }
        var totalBeads = 0
        var totalSpare = 0
        val items = counts.entries
            .mapNotNull { (code, cnt) ->
                val color = codeMap[code] ?: return@mapNotNull null
                val spare = cnt + max(2, ceil(cnt * 0.10).toInt())
                totalBeads += cnt
                totalSpare += spare
                BomItem(
                    mardCode = code,
                    displayCode = color.codeFor(brand),
                    color = color,
                    count = cnt,
                    spareCount = spare
                )
            }
            .sortedByDescending { it.count }

        return BomSummary(
            brand = brand,
            totalBeads = totalBeads,
            totalSpareBeads = totalSpare,
            colorCount = items.size,
            items = items,
            physical = calcPhysicalSpec(pattern.width, pattern.height, diameter)
        )
    }

    companion object {
        private val MARD_PAD_REGEX = Regex("^([A-Z]+)0+(\\d+)$")
        val GREEN_CAST_TRAP_CODES = setOf("G15", "H18", "H21", "M1", "M2", "M3", "M4", "M5", "M6", "M7")

        fun normalizeMardCode(code: String): String {
            val clean = code.trim().uppercase()
            return MARD_PAD_REGEX.replace(clean, "$1$2")
        }

        fun rgbToLab(r: Int, g: Int, b: Int): DoubleArray {
            fun lin(c: Int): Double {
                val v = c / 255.0
                return if (v <= 0.04045) v / 12.92 else ((v + 0.055) / 1.055).pow(2.4)
            }
            val lr = lin(r)
            val lg = lin(g)
            val lb = lin(b)
            val x = (lr * 0.4124564 + lg * 0.3575761 + lb * 0.1804375) / 0.95047
            val y = (lr * 0.2126729 + lg * 0.7151522 + lb * 0.0721750) / 1.00000
            val z = (lr * 0.0193339 + lg * 0.1191920 + lb * 0.9503041) / 1.08883
            fun f(t: Double): Double = if (t > 0.008856) t.pow(1.0 / 3.0) else (7.787 * t) + 16.0 / 116.0
            val fx = f(x)
            val fy = f(y)
            val fz = f(z)
            return doubleArrayOf(116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))
        }

        fun labDist(l1: Double, a1: Double, b1: Double, l2: Double, a2: Double, b2: Double): Double {
            val dl = l1 - l2
            val da = a1 - a2
            val db = b1 - b2
            return sqrt(dl * dl + da * da + db * db)
        }

        /**
         * 标准 CIEDE2000 感知色差（Sharma, Wu & Dalal, 2005；kL = kC = kH = 1.0）。
         */
        fun ciede2000(l1: Double, a1: Double, b1: Double, l2: Double, a2: Double, b2: Double): Double {
            val c1 = sqrt(a1 * a1 + b1 * b1)
            val c2 = sqrt(a2 * a2 + b2 * b2)
            val cBar = 0.5 * (c1 + c2)
            val cBar7 = cBar * cBar * cBar * cBar * cBar * cBar * cBar
            val pow257 = 6103515625.0 // 25^7
            val g = 0.5 * (1.0 - sqrt(cBar7 / (cBar7 + pow257)))

            val a1p = (1.0 + g) * a1
            val a2p = (1.0 + g) * a2
            val c1p = sqrt(a1p * a1p + b1 * b1)
            val c2p = sqrt(a2p * a2p + b2 * b2)

            fun hueDeg(b: Double, ap: Double): Double {
                if (ap == 0.0 && b == 0.0) return 0.0
                var h = atan2(b, ap) * (180.0 / PI)
                if (h < 0.0) h += 360.0
                return h
            }
            val h1p = hueDeg(b1, a1p)
            val h2p = hueDeg(b2, a2p)

            val dLp = l2 - l1
            val dCp = c2p - c1p
            val c12p = c1p * c2p
            val dhp = when {
                c12p == 0.0 -> 0.0
                abs(h2p - h1p) <= 180.0 -> h2p - h1p
                h2p - h1p > 180.0 -> (h2p - h1p) - 360.0
                else -> (h2p - h1p) + 360.0
            }
            val dHp = 2.0 * sqrt(c12p) * sin(0.5 * dhp * (PI / 180.0))

            val lBarP = 0.5 * (l1 + l2)
            val cBarP = 0.5 * (c1p + c2p)
            val hBarP = when {
                c12p == 0.0 -> h1p + h2p
                abs(h1p - h2p) <= 180.0 -> 0.5 * (h1p + h2p)
                h1p + h2p < 360.0 -> 0.5 * (h1p + h2p + 360.0)
                else -> 0.5 * (h1p + h2p - 360.0)
            }

            val rad = PI / 180.0
            val t = 1.0 -
                0.17 * cos((hBarP - 30.0) * rad) +
                0.24 * cos((2.0 * hBarP) * rad) +
                0.32 * cos((3.0 * hBarP + 6.0) * rad) -
                0.20 * cos((4.0 * hBarP - 63.0) * rad)

            val dt = (hBarP - 275.0) / 25.0
            val deltaTheta = 30.0 * exp(-(dt * dt))
            val cBarP7 = cBarP * cBarP * cBarP * cBarP * cBarP * cBarP * cBarP
            val rC = 2.0 * sqrt(cBarP7 / (cBarP7 + pow257))
            val lDiffSq = (lBarP - 50.0) * (lBarP - 50.0)
            val sL = 1.0 + (0.015 * lDiffSq) / sqrt(20.0 + lDiffSq)
            val sC = 1.0 + 0.045 * cBarP
            val sH = 1.0 + 0.015 * cBarP * t
            val rT = -sin((2.0 * deltaTheta) * rad) * rC

            val termL = dLp / sL
            val termC = dCp / sC
            val termH = dHp / sH
            return sqrt(termL * termL + termC * termC + termH * termH + rT * termC * termH)
        }
    }
}
