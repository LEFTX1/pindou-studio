package com.pindoustudio.app.engine

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import com.pindoustudio.app.data.PaletteRepository
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.PaletteColor
import com.pindoustudio.app.model.PhotoSlot
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

enum class ExternalImportHint(val label: String, val desc: String) {
    AUTO("智能判断", "自动区分外部图纸网格与实物拼豆照"),
    CHART("外部拼豆图纸", "小红书/其他生成器导出的网格色号图"),
    CRAFT("拼好/烫好成品照", "抠除桌面反光与豆孔阴影还原像素格")
}

enum class DetectedSourceType(val label: String) {
    EXTERNAL_CHART("外部网格图纸"),
    CRAFT_PITCH_LOCKED("实物成品（豆格精准锁定）"),
    CRAFT_SHAPE_ESTIMATED("实物成品（轮廓比例估算）")
}

data class RecognitionResult(
    val pattern: BeadPattern,
    val detectedType: DetectedSourceType,
    val confidenceLabel: String,
    val hasCellTextCodes: Boolean,
    val detectedPitchPx: Float,
    val suggestedSlot: PhotoSlot,
    val markCompletedByDefault: Boolean
)

/**
 * 纯离线外部拼豆图纸 & 实物成品照片智能识别引擎：
 * 1. 外部图纸：自相关基频去谐波检测（跳过 5/10 格加粗线）+ 两遍边界锁定 + 标尺栏剥离 + 避让格内色号字样的内环中位采色；
 * 2. 实物照片：边缘背景自适应泛洪抠底 + 豆格周期估算 + 环形塑性采色（避开中心黑孔与表面高光）+ 室内偏色校准。
 */
object ExternalBeadRecognizer {

    fun decodeBoundedBitmap(context: Context, uri: Uri, maxSide: Int = 2048): Bitmap? {
        val optsBounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        val stream1 = context.contentResolver.openInputStream(uri) ?: return null
        stream1.use {
            BitmapFactory.decodeStream(it, null, optsBounds)
        }
        val srcW = optsBounds.outWidth
        val srcH = optsBounds.outHeight
        if (srcW <= 0 || srcH <= 0) return null

        var sampleSize = 1
        while (max(srcW / sampleSize, srcH / sampleSize) > (maxSide * 1.5f).roundToInt()) {
            sampleSize *= 2
        }

        val optsDecode = BitmapFactory.Options().apply {
            inSampleSize = sampleSize
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val decoded = context.contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, optsDecode)
        } ?: return null

        val curMax = max(decoded.width, decoded.height)
        if (curMax <= maxSide) return decoded

        val scale = maxSide.toFloat() / curMax.toFloat()
        val dstW = max(1, (decoded.width * scale).roundToInt())
        val dstH = max(1, (decoded.height * scale).roundToInt())
        val scaled = Bitmap.createScaledBitmap(decoded, dstW, dstH, true)
        if (scaled != decoded) decoded.recycle()
        return scaled
    }

    fun recognize(
        bitmap: Bitmap,
        paletteRepo: PaletteRepository,
        title: String,
        hint: ExternalImportHint = ExternalImportHint.AUTO,
        overrideWidth: Int? = null,
        overrideHeight: Int? = null,
        craftMaxColors: Int = 14
    ): RecognitionResult {
        val cleanTitle = title.ifBlank { "导入拼豆作品" }
        val w = bitmap.width.coerceAtLeast(1)
        val h = bitmap.height.coerceAtLeast(1)
        val pixels = IntArray(w * h)
        bitmap.getPixels(pixels, 0, w, 0, 0, w, h)

        val rgb = IntArray(w * h)
        val alpha = IntArray(w * h)
        var transparentCount = 0
        for (i in pixels.indices) {
            val p = pixels[i]
            val a = Color.alpha(p)
            alpha[i] = a
            if (a < 128) transparentCount++
            if (a == 255) {
                rgb[i] = p
            } else {
                val af = a / 255f
                val r = (Color.red(p) * af + 255f * (1f - af)).roundToInt().coerceIn(0, 255)
                val g = (Color.green(p) * af + 255f * (1f - af)).roundToInt().coerceIn(0, 255)
                val b = (Color.blue(p) * af + 255f * (1f - af)).roundToInt().coerceIn(0, 255)
                rgb[i] = Color.rgb(r, g, b)
            }
        }
        val hasAlpha = transparentCount > (w * h * 0.05).roundToInt()

        if (hint == ExternalImportHint.AUTO || hint == ExternalImportHint.CHART) {
            val chartRes = tryRecognizeChart(
                rgb = rgb,
                w = w,
                h = h,
                paletteRepo = paletteRepo,
                title = cleanTitle,
                forceChart = (hint == ExternalImportHint.CHART),
                overrideW = overrideWidth,
                overrideH = overrideHeight
            )
            if (chartRes != null) return chartRes
        }

        return recognizeCraftPhoto(
            rgb = rgb,
            alpha = alpha,
            hasAlpha = hasAlpha,
            w = w,
            h = h,
            paletteRepo = paletteRepo,
            title = cleanTitle,
            overrideW = overrideWidth,
            overrideH = overrideHeight,
            craftMaxColors = craftMaxColors
        )
    }

    private data class PitchEstimate(
        val pitch: Float,
        val phase: Float,
        val score: Float,
        val highPass: FloatArray
    )

    private fun evalFixedPitch(hp: FloatArray, pInit: Float, startIdx: Int, endIdx: Int): Triple<Float, Float, Float> {
        val n = hp.size
        var bestS = -1e9f
        var bestP = pInit
        var bestPh = 0f
        var pSum = 0f
        for (v in hp) pSum += v
        val hpMean = (pSum / max(1, n)) + 1e-6f

        val dps = floatArrayOf(-0.4f, -0.2f, 0f, 0.2f, 0.4f)
        for (dp in dps) {
            val p = pInit + dp
            if (p < 6f) continue
            val nPh = max(14, (p * 2f).roundToInt())
            for (phI in 0 until nPh) {
                val ph = phI * (p / nPh)
                val k0 = ceil(((startIdx - ph) / p).toDouble()).toInt()
                val k1 = floor(((endIdx - ph) / p).toDouble()).toInt()
                if (k1 - k0 < 5) continue

                val lineVals = FloatArray(k1 - k0 + 1)
                var li = 0
                for (k in k0..k1) {
                    val idx = (ph + k * p).roundToInt().coerceIn(1, n - 2)
                    lineVals[li++] = max(hp[idx], max(hp[idx - 1], hp[idx + 1]))
                }
                val midVals = FloatArray(max(1, k1 - k0))
                var mi = 0
                for (k in k0 until k1) {
                    val idx = (ph + (k + 0.5f) * p).roundToInt().coerceIn(0, n - 1)
                    midVals[mi++] = hp[idx]
                }
                val p35 = percentileSorted(lineVals, 0.35f)
                val med = percentileSorted(lineVals, 0.50f)
                val mid = percentileSorted(midVals, 0.50f)
                val score = p35 + 0.4f * med - 1.2f * mid
                if (score > bestS) {
                    bestS = score
                    bestP = p
                    bestPh = ph
                }
            }
        }
        return Triple(bestP, bestPh, bestS / hpMean)
    }

    private fun detectFundamentalPitch(sig: FloatArray, minP: Float = 7f, maxP: Float = 110f): PitchEstimate? {
        val n = sig.size
        if (n < 32) return null
        val hp = FloatArray(n)
        for (i in 0 until n) {
            var sum = 0f
            var cnt = 0
            for (d in -2..2) {
                val j = i + d
                if (j in 0 until n) {
                    sum += sig[j]
                    cnt++
                }
            }
            hp[i] = max(0f, sig[i] - sum / max(1, cnt))
        }

        val i0 = (n * 0.08f).roundToInt()
        val i1 = (n * 0.92f).roundToInt()
        val maxLag = min(maxP.toInt(), n / 5)
        if (maxLag <= minP.toInt() + 1) return null

        val ac = FloatArray(maxLag + 1)
        var acMax = 1e-9f
        for (lag in minP.toInt()..maxLag) {
            var sum = 0.0
            val count = n - lag
            for (i in 0 until count) {
                sum += hp[i] * hp[i + lag]
            }
            val v = (sum / max(1, count)).toFloat()
            ac[lag] = v
            if (v > acMax) acMax = v
        }

        val acPeaks = ArrayList<Pair<Float, Float>>()
        for (lag in (minP.toInt() + 1) until maxLag) {
            if (ac[lag] >= ac[lag - 1] && ac[lag] >= ac[lag + 1] && ac[lag] > acMax * 0.12f) {
                acPeaks.add(ac[lag] to lag.toFloat())
            }
        }
        acPeaks.sortByDescending { it.first }

        val candidates = ArrayList<Float>()
        val divs = intArrayOf(1, 2, 3, 4, 5, 6, 8, 10)
        for ((_, lag) in acPeaks.take(8)) {
            for (div in divs) {
                val p = lag / div.toFloat()
                if (p in minP..maxP && candidates.none { abs(it - p) < 0.8f }) {
                    candidates.add(p)
                }
            }
        }
        if (candidates.isEmpty()) return null

        data class ScoredPitch(val p: Float, val ph: Float, val normScore: Float, val p35: Float, val medMid: Float)

        val scored = ArrayList<ScoredPitch>(candidates.size)
        for (p0 in candidates) {
            val (p, ph, normS) = evalFixedPitch(hp, p0, i0, i1)
            val k0 = ceil(((i0 - ph) / p).toDouble()).toInt()
            val k1 = floor(((i1 - ph) / p).toDouble()).toInt()
            if (k1 - k0 < 5) continue
            val lineVals = FloatArray(k1 - k0 + 1)
            for (k in k0..k1) {
                val idx = (ph + k * p).roundToInt().coerceIn(1, n - 2)
                lineVals[k - k0] = max(hp[idx], max(hp[idx - 1], hp[idx + 1]))
            }
            val midVals = FloatArray(max(1, k1 - k0))
            for (k in k0 until k1) {
                val idx = (ph + (k + 0.5f) * p).roundToInt().coerceIn(0, n - 1)
                midVals[k - k0] = hp[idx]
            }
            scored.add(
                ScoredPitch(
                    p = p,
                    ph = ph,
                    normScore = normS,
                    p35 = percentileSorted(lineVals, 0.35f),
                    medMid = percentileSorted(midVals, 0.50f)
                )
            )
        }
        if (scored.isEmpty()) return null
        scored.sortByDescending { it.normScore }
        val topS = scored[0].normScore
        val valid = scored.filter { it.normScore >= topS * 0.45f && it.p35 > max(0.008f, it.medMid * 2.2f) }
        val chosen = if (valid.isNotEmpty()) valid.minBy { it.p } else scored[0]
        return PitchEstimate(chosen.p, chosen.ph, chosen.normScore, hp)
    }

    private fun tryRecognizeChart(
        rgb: IntArray,
        w: Int,
        h: Int,
        paletteRepo: PaletteRepository,
        title: String,
        forceChart: Boolean,
        overrideW: Int?,
        overrideH: Int?
    ): RecognitionResult? {
        val vEdge = BooleanArray((w - 1) * h)
        val colEdgeSum = IntArray(w - 1)
        val hEdge = BooleanArray(w * (h - 1))
        val rowEdgeSum = IntArray(h - 1)

        for (y in 0 until h) {
            val rowOff = y * w
            val vOff = y * (w - 1)
            for (x in 0 until w - 1) {
                val p1 = rgb[rowOff + x]
                val p2 = rgb[rowOff + x + 1]
                val diff = max(
                    abs(Color.red(p1) - Color.red(p2)),
                    max(abs(Color.green(p1) - Color.green(p2)), abs(Color.blue(p1) - Color.blue(p2)))
                )
                if (diff > 10) {
                    vEdge[vOff + x] = true
                    colEdgeSum[x]++
                }
            }
        }
        for (y in 0 until h - 1) {
            val r1 = y * w
            val r2 = (y + 1) * w
            var rowCnt = 0
            for (x in 0 until w) {
                val p1 = rgb[r1 + x]
                val p2 = rgb[r2 + x]
                val diff = max(
                    abs(Color.red(p1) - Color.red(p2)),
                    max(abs(Color.green(p1) - Color.green(p2)), abs(Color.blue(p1) - Color.blue(p2)))
                )
                if (diff > 10) {
                    hEdge[r1 + x] = true
                    rowCnt++
                }
            }
            rowEdgeSum[y] = rowCnt
        }

        val colSig = FloatArray(w - 1) { colEdgeSum[it].toFloat() / h }
        val rowSig = FloatArray(h - 1) { rowEdgeSum[it].toFloat() / w }

        val estX = detectFundamentalPitch(colSig) ?: return null
        val estY = detectFundamentalPitch(rowSig) ?: return null

        var px = estX.pitch
        var phx = estX.phase
        var sx = estX.score
        var py = estY.pitch
        var phy = estY.phase
        var sy = estY.score

        if (abs(px - py) / max(px, py) > 0.08f) {
            if (sx >= sy) {
                val (p2, ph2, s2) = evalFixedPitch(estY.highPass, px, (h * 0.08f).roundToInt(), (h * 0.92f).roundToInt())
                if (s2 > 2.5f) {
                    py = p2; phy = ph2; sy = s2
                }
            } else {
                val (p2, ph2, s2) = evalFixedPitch(estX.highPass, py, (w * 0.08f).roundToInt(), (w * 0.92f).roundToInt())
                if (s2 > 2.5f) {
                    px = p2; phx = ph2; sx = s2
                }
            }
        }

        if (!forceChart && (sx < 7.2f || sy < 6.8f || abs(px - py) / max(px, py) > 0.10f)) {
            return null
        }

        val xsAll = ArrayList<Float>()
        run {
            val kMin = floor((-phx / px).toDouble()).toInt()
            val kMax = ceil(((w - phx) / px).toDouble()).toInt()
            for (k in kMin..kMax) {
                val pos = phx + k * px
                if (pos >= 0f && pos < w.toFloat()) xsAll.add(pos)
            }
        }
        val ysAll = ArrayList<Float>()
        run {
            val kMin = floor((-phy / py).toDouble()).toInt()
            val kMax = ceil(((h - phy) / py).toDouble()).toInt()
            for (k in kMin..kMax) {
                val pos = phy + k * py
                if (pos >= 0f && pos < h.toFloat()) ysAll.add(pos)
            }
        }
        if (xsAll.size < 6 || ysAll.size < 6) return null

        fun scoreXLines(y0: Int, y1: Int): FloatArray {
            val span = max(1, y1 - y0)
            return FloatArray(xsAll.size) { li ->
                val x = xsAll[li].roundToInt()
                val xa = max(0, x - 1)
                val xb = min(w - 2, x + 1)
                var hits = 0
                for (y in y0 until y1) {
                    val off = y * (w - 1)
                    var any = false
                    for (xx in xa..xb) {
                        if (vEdge[off + xx]) { any = true; break }
                    }
                    if (any) hits++
                }
                hits.toFloat() / span
            }
        }

        fun scoreYLines(x0: Int, x1: Int): FloatArray {
            val span = max(1, x1 - x0)
            return FloatArray(ysAll.size) { li ->
                val y = ysAll[li].roundToInt()
                val ya = max(0, y - 1)
                val yb = min(h - 2, y + 1)
                var hits = 0
                for (x in x0 until x1) {
                    var any = false
                    for (yy in ya..yb) {
                        if (hEdge[yy * w + x]) { any = true; break }
                    }
                    if (any) hits++
                }
                hits.toFloat() / span
            }
        }

        val xs1 = scoreXLines(0, h)
        val ys1 = scoreYLines(0, w)
        var (c0, c1) = bestContiguousRun(xs1, max(0.08f, percentileSorted(xs1.copyOf(), 0.75f) * 0.42f), maxGap = 1)
        var (r0, r1) = bestContiguousRun(ys1, max(0.08f, percentileSorted(ys1.copyOf(), 0.75f) * 0.42f), maxGap = 1)
        if (c1 - c0 < 6 || r1 - r0 < 6) return null

        val gx0 = xsAll[c0].roundToInt().coerceIn(0, w - 1)
        val gx1 = xsAll[c1 - 1].roundToInt().coerceIn(gx0 + 1, w)
        val gy0 = ysAll[r0].roundToInt().coerceIn(0, h - 1)
        val gy1 = ysAll[r1 - 1].roundToInt().coerceIn(gy0 + 1, h)

        val xs2 = scoreXLines(gy0, gy1)
        val ys2 = scoreYLines(gx0, gx1)
        val runX2 = bestContiguousRun(xs2, max(0.24f, percentileSorted(xs2.copyOf(), 0.70f) * 0.42f), maxGap = 2)
        val runY2 = bestContiguousRun(ys2, max(0.24f, percentileSorted(ys2.copyOf(), 0.70f) * 0.42f), maxGap = 2)
        c0 = runX2.first; c1 = runX2.second
        r0 = runY2.first; r1 = runY2.second

        val xsSub = xsAll.subList(c0, c1).toMutableList()
        val ysSub = ysAll.subList(r0, r1).toMutableList()
        if (xsSub.isNotEmpty()) {
            val remX = w - xsSub.last()
            if (remX in (0.85f * px)..(1.25f * px)) xsSub.add((w - 1).toFloat())
        }
        if (ysSub.isNotEmpty()) {
            val remY = h - ysSub.last()
            if (remY in (0.85f * py)..(1.25f * py)) ysSub.add((h - 1).toFloat())
        }

        if (xsSub.size < 8 || ysSub.size < 8) return null

        // 若用户指定覆盖行列数，则在锁定的网格外框内均匀细分
        val finalXs: FloatArray
        val finalYs: FloatArray
        if (overrideW != null && overrideH != null && overrideW in 10..128 && overrideH in 10..128) {
            val left = xsSub.first(); val right = xsSub.last()
            val top = ysSub.first(); val bottom = ysSub.last()
            finalXs = FloatArray(overrideW + 1) { left + (right - left) * it / overrideW }
            finalYs = FloatArray(overrideH + 1) { top + (bottom - top) * it / overrideH }
        } else {
            var rawW = xsSub.size - 1
            var rawH = ysSub.size - 1
            if (max(rawW, rawH) > 128) {
                val scale = 128f / max(rawW, rawH)
                rawW = max(8, (rawW * scale).roundToInt())
                rawH = max(8, (rawH * scale).roundToInt())
                val left = xsSub.first(); val right = xsSub.last()
                val top = ysSub.first(); val bottom = ysSub.last()
                finalXs = FloatArray(rawW + 1) { left + (right - left) * it / rawW }
                finalYs = FloatArray(rawH + 1) { top + (bottom - top) * it / rawH }
            } else {
                finalXs = xsSub.toFloatArray()
                finalYs = ysSub.toFloatArray()
            }
        }

        var gw = finalXs.size - 1
        var gh = finalYs.size - 1
        if (gw < 6 || gh < 6) return null

        val bgR = FloatArray(gw * gh)
        val bgG = FloatArray(gw * gh)
        val bgB = FloatArray(gw * gh)
        val inkRatio = FloatArray(gw * gh)
        val cellMad = FloatArray(gw * gh)

        val ringR = ArrayList<Int>(128)
        val ringG = ArrayList<Int>(128)
        val ringB = ArrayList<Int>(128)

        for (r in 0 until gh) {
            val y0 = finalYs[r]
            val y1 = finalYs[r + 1]
            val ch = y1 - y0
            for (c in 0 until gw) {
                val x0 = finalXs[c]
                val x1 = finalXs[c + 1]
                val cw = x1 - x0
                val ix0 = max(0, (x0 + cw * 0.15f).roundToInt())
                val ix1 = min(w, (x0 + cw * 0.85f).roundToInt())
                val iy0 = max(0, (y0 + ch * 0.15f).roundToInt())
                val iy1 = min(h, (y0 + ch * 0.85f).roundToInt())
                val pw = ix1 - ix0
                val ph = iy1 - iy0
                val idx = r * gw + c
                if (pw < 2 || ph < 2) continue

                val mx = max(1, (pw * 0.22f).roundToInt())
                val my = max(1, (ph * 0.22f).roundToInt())
                ringR.clear(); ringG.clear(); ringB.clear()
                for (yy in 0 until ph) {
                    val inTopOrBot = yy < my || yy >= ph - my
                    val rowOff = (iy0 + yy) * w
                    for (xx in 0 until pw) {
                        if (inTopOrBot || xx < mx || xx >= pw - mx) {
                            val p = rgb[rowOff + ix0 + xx]
                            ringR.add(Color.red(p))
                            ringG.add(Color.green(p))
                            ringB.add(Color.blue(p))
                        }
                    }
                }
                if (ringR.isEmpty()) continue
                val mr = medianInt(ringR)
                val mg = medianInt(ringG)
                val mb = medianInt(ringB)
                bgR[idx] = mr
                bgG[idx] = mg
                bgB[idx] = mb

                val devs = FloatArray(ringR.size) { i ->
                    (abs(ringR[i] - mr) + abs(ringG[i] - mg) + abs(ringB[i] - mb)) / 3f
                }
                cellMad[idx] = percentileSorted(devs, 0.50f)

                var inkHits = 0
                var centerCnt = 0
                val cyStart = if (ph > 2 * my) my else 0
                val cyEnd = if (ph > 2 * my) ph - my else ph
                val cxStart = if (pw > 2 * mx) mx else 0
                val cxEnd = if (pw > 2 * mx) pw - mx else pw
                for (yy in cyStart until cyEnd) {
                    val rowOff = (iy0 + yy) * w
                    for (xx in cxStart until cxEnd) {
                        val p = rgb[rowOff + ix0 + xx]
                        val d = max(
                            abs(Color.red(p) - mr),
                            max(abs(Color.green(p) - mg), abs(Color.blue(p) - mb))
                        )
                        if (d > 38f) inkHits++
                        centerCnt++
                    }
                }
                inkRatio[idx] = if (centerCnt > 0) inkHits.toFloat() / centerCnt else 0f
            }
        }

        val flatness = percentileSorted(cellMad.copyOf(), 0.50f)
        if (!forceChart && flatness > 9.5f) {
            return null
        }

        // 剥离四边坐标标尺框（仅保留纯图区）
        var rStart = 0
        var rEnd = gh
        var cStart = 0
        var cEnd = gw

        fun stripRow(rowIdx: Int): Boolean {
            val rs = FloatArray(cEnd - cStart)
            val gs = FloatArray(cEnd - cStart)
            val bs = FloatArray(cEnd - cStart)
            var inkInner = 0
            for (c in cStart until cEnd) {
                val i = rowIdx * gw + c
                val rV = bgR[i]; val gV = bgG[i]; val bV = bgB[i]
                val lum = 0.299f * rV + 0.587f * gV + 0.114f * bV
                val sat = max(rV, max(gV, bV)) - min(rV, min(gV, bV))
                if (lum < 215f || sat > 12f) return false
                rs[c - cStart] = rV; gs[c - cStart] = gV; bs[c - cStart] = bV
                if (c > cStart && c < cEnd - 1 && inkRatio[i] > 0.008f) inkInner++
            }
            val std = max(stdDev(rs), max(stdDev(gs), stdDev(bs)))
            if (std > 6.5f) return false
            val cornersBlank = inkRatio[rowIdx * gw + cStart] < 0.015f && inkRatio[rowIdx * gw + (cEnd - 1)] < 0.015f
            val innerCount = max(1, (cEnd - cStart) - 2)
            return cornersBlank && (inkInner.toFloat() / innerCount) >= 0.78f
        }

        fun stripCol(colIdx: Int): Boolean {
            val rs = FloatArray(rEnd - rStart)
            val gs = FloatArray(rEnd - rStart)
            val bs = FloatArray(rEnd - rStart)
            var inkInner = 0
            for (r in rStart until rEnd) {
                val i = r * gw + colIdx
                val rV = bgR[i]; val gV = bgG[i]; val bV = bgB[i]
                val lum = 0.299f * rV + 0.587f * gV + 0.114f * bV
                val sat = max(rV, max(gV, bV)) - min(rV, min(gV, bV))
                if (lum < 215f || sat > 12f) return false
                rs[r - rStart] = rV; gs[r - rStart] = gV; bs[r - rStart] = bV
                if (r > rStart && r < rEnd - 1 && inkRatio[i] > 0.008f) inkInner++
            }
            val std = max(stdDev(rs), max(stdDev(gs), stdDev(bs)))
            if (std > 6.5f) return false
            val cornersBlank = inkRatio[rStart * gw + colIdx] < 0.015f && inkRatio[(rEnd - 1) * gw + colIdx] < 0.015f
            val innerCount = max(1, (rEnd - rStart) - 2)
            return cornersBlank && (inkInner.toFloat() / innerCount) >= 0.78f
        }

        if (overrideW == null || overrideH == null) {
            if (rEnd - rStart > 6 && stripRow(rStart)) rStart++
            if (rEnd - rStart > 6 && stripRow(rEnd - 1)) rEnd--
            if (cEnd - cStart > 6 && stripCol(cStart)) cStart++
            if (cEnd - cStart > 6 && stripCol(cEnd - 1)) cEnd--

            // 裁剪全白空边距行/列（邻接行/列高度填满时）
            fun isAllWhiteRow(rIdx: Int): Boolean {
                for (c in cStart until cEnd) {
                    val i = rIdx * gw + c
                    val lum = 0.299f * bgR[i] + 0.587f * bgG[i] + 0.114f * bgB[i]
                    val sat = max(bgR[i], max(bgG[i], bgB[i])) - min(bgR[i], min(bgG[i], bgB[i]))
                    if (lum < 242f || sat > 10f || inkRatio[i] >= 0.015f) return false
                }
                return true
            }
            fun rowFillRatio(rIdx: Int): Float {
                var cnt = 0
                for (c in cStart until cEnd) {
                    val i = rIdx * gw + c
                    val lum = 0.299f * bgR[i] + 0.587f * bgG[i] + 0.114f * bgB[i]
                    val sat = max(bgR[i], max(bgG[i], bgB[i])) - min(bgR[i], min(bgG[i], bgB[i]))
                    if (lum < 242f || sat > 10f || inkRatio[i] >= 0.015f) cnt++
                }
                return cnt.toFloat() / max(1, cEnd - cStart)
            }
            fun isAllWhiteCol(cIdx: Int): Boolean {
                for (r in rStart until rEnd) {
                    val i = r * gw + cIdx
                    val lum = 0.299f * bgR[i] + 0.587f * bgG[i] + 0.114f * bgB[i]
                    val sat = max(bgR[i], max(bgG[i], bgB[i])) - min(bgR[i], min(bgG[i], bgB[i]))
                    if (lum < 242f || sat > 10f || inkRatio[i] >= 0.015f) return false
                }
                return true
            }
            fun colFillRatio(cIdx: Int): Float {
                var cnt = 0
                for (r in rStart until rEnd) {
                    val i = r * gw + cIdx
                    val lum = 0.299f * bgR[i] + 0.587f * bgG[i] + 0.114f * bgB[i]
                    val sat = max(bgR[i], max(bgG[i], bgB[i])) - min(bgR[i], min(bgG[i], bgB[i]))
                    if (lum < 242f || sat > 10f || inkRatio[i] >= 0.015f) cnt++
                }
                return cnt.toFloat() / max(1, rEnd - rStart)
            }
            if (rEnd - rStart > 6 && isAllWhiteRow(rStart) && rowFillRatio(rStart + 1) > 0.70f) rStart++
            if (rEnd - rStart > 6 && isAllWhiteRow(rEnd - 1) && rowFillRatio(rEnd - 2) > 0.70f) rEnd--
            if (cEnd - cStart > 6 && isAllWhiteCol(cStart) && colFillRatio(cStart + 1) > 0.70f) cStart++
            if (cEnd - cStart > 6 && isAllWhiteCol(cEnd - 1) && colFillRatio(cEnd - 2) > 0.70f) cEnd--
        }

        val outW = cEnd - cStart
        val outH = rEnd - rStart
        if (outW < 5 || outH < 5) return null

        var coloredCnt = 0
        var coloredWithInk = 0
        for (r in rStart until rEnd) {
            for (c in cStart until cEnd) {
                val i = r * gw + c
                val lum = 0.299f * bgR[i] + 0.587f * bgG[i] + 0.114f * bgB[i]
                val sat = max(bgR[i], max(bgG[i], bgB[i])) - min(bgR[i], min(bgG[i], bgB[i]))
                if (lum < 236f || sat > 16f) {
                    coloredCnt++
                    if (inkRatio[i] > 0.02f) coloredWithInk++
                }
            }
        }
        val hasTextCodes = coloredCnt > 5 && (coloredWithInk.toFloat() / coloredCnt) > 0.35f

        val cells = MutableList<String?>(outW * outH) { null }
        val isWhiteBgCell = BooleanArray(outW * outH)
        for (rr in 0 until outH) {
            for (cc in 0 until outW) {
                val srcI = (rStart + rr) * gw + (cStart + cc)
                val lum = 0.299f * bgR[srcI] + 0.587f * bgG[srcI] + 0.114f * bgB[srcI]
                val sat = max(bgR[srcI], max(bgG[srcI], bgB[srcI])) - min(bgR[srcI], min(bgG[srcI], bgB[srcI]))
                val isWhite = lum >= 242f && sat <= 10f
                if (isWhite) {
                    isWhiteBgCell[rr * outW + cc] = true
                    if (hasTextCodes && inkRatio[srcI] >= 0.015f) {
                        cells[rr * outW + cc] = matchNearestCode(bgR[srcI].roundToInt(), bgG[srcI].roundToInt(), bgB[srcI].roundToInt(), paletteRepo.palette)
                    }
                } else {
                    cells[rr * outW + cc] = matchNearestCode(bgR[srcI].roundToInt(), bgG[srcI].roundToInt(), bgB[srcI].roundToInt(), paletteRepo.palette)
                }
            }
        }

        // 若是无文字缩略格子图：保留内部闭合白豆，只清除四周连通背景白格
        if (!hasTextCodes) {
            val outerBg = BooleanArray(outW * outH)
            val q = ArrayDeque<Int>()
            for (cc in 0 until outW) {
                if (isWhiteBgCell[cc]) { outerBg[cc] = true; q.addLast(cc) }
                val bot = (outH - 1) * outW + cc
                if (isWhiteBgCell[bot] && !outerBg[bot]) { outerBg[bot] = true; q.addLast(bot) }
            }
            for (rr in 0 until outH) {
                val left = rr * outW
                if (isWhiteBgCell[left] && !outerBg[left]) { outerBg[left] = true; q.addLast(left) }
                val right = rr * outW + (outW - 1)
                if (isWhiteBgCell[right] && !outerBg[right]) { outerBg[right] = true; q.addLast(right) }
            }
            while (q.isNotEmpty()) {
                val cur = q.removeFirst()
                val cr = cur / outW
                val cc = cur % outW
                val nbrs = intArrayOf(
                    if (cr > 0) cur - outW else -1,
                    if (cr + 1 < outH) cur + outW else -1,
                    if (cc > 0) cur - 1 else -1,
                    if (cc + 1 < outW) cur + 1 else -1
                )
                for (nIdx in nbrs) {
                    if (nIdx >= 0 && isWhiteBgCell[nIdx] && !outerBg[nIdx]) {
                        outerBg[nIdx] = true
                        q.addLast(nIdx)
                    }
                }
            }
            for (i in cells.indices) {
                if (isWhiteBgCell[i] && !outerBg[i]) {
                    val r = i / outW
                    val c = i % outW
                    val srcI = (rStart + r) * gw + (cStart + c)
                    cells[i] = matchNearestCode(bgR[srcI].roundToInt(), bgG[srcI].roundToInt(), bgB[srcI].roundToInt(), paletteRepo.palette)
                }
            }
        }

        val pattern = BeadPattern(name = title, width = outW, height = outH, cells = cells)
        return RecognitionResult(
            pattern = pattern,
            detectedType = DetectedSourceType.EXTERNAL_CHART,
            confidenceLabel = if (hasTextCodes) "已锁定标准格线 · 避让字码采色" else "已锁定高清网格线",
            hasCellTextCodes = hasTextCodes,
            detectedPitchPx = (px + py) * 0.5f,
            suggestedSlot = PhotoSlot.REFERENCE,
            markCompletedByDefault = false
        )
    }

    private fun recognizeCraftPhoto(
        rgb: IntArray,
        alpha: IntArray,
        hasAlpha: Boolean,
        w: Int,
        h: Int,
        paletteRepo: PaletteRepository,
        title: String,
        overrideW: Int?,
        overrideH: Int?,
        craftMaxColors: Int
    ): RecognitionResult {
        val fg = BooleanArray(w * h)
        if (hasAlpha) {
            for (i in fg.indices) fg[i] = alpha[i] >= 128
        } else {
            // 四周边框采样背景色 + 降采样边缘泛洪抠底
            val borderR = ArrayList<Int>(w * 2 + h * 2)
            val borderG = ArrayList<Int>(w * 2 + h * 2)
            val borderB = ArrayList<Int>(w * 2 + h * 2)
            for (x in 0 until w) {
                val pTop = rgb[x]; val pBot = rgb[(h - 1) * w + x]
                borderR.add(Color.red(pTop)); borderG.add(Color.green(pTop)); borderB.add(Color.blue(pTop))
                borderR.add(Color.red(pBot)); borderG.add(Color.green(pBot)); borderB.add(Color.blue(pBot))
            }
            for (y in 0 until h) {
                val pL = rgb[y * w]; val pR = rgb[y * w + w - 1]
                borderR.add(Color.red(pL)); borderG.add(Color.green(pL)); borderB.add(Color.blue(pL))
                borderR.add(Color.red(pR)); borderG.add(Color.green(pR)); borderB.add(Color.blue(pR))
            }
            val bgR = medianInt(borderR)
            val bgG = medianInt(borderG)
            val bgB = medianInt(borderB)
            val bDist = FloatArray(borderR.size) { i ->
                val dr = borderR[i] - bgR
                val dg = borderG[i] - bgG
                val db = borderB[i] - bgB
                sqrt((dr * dr + dg * dg + db * db).toDouble()).toFloat()
            }
            val bgSpread = percentileSorted(bDist, 0.85f)
            val thresh = (bgSpread * 1.9f + 14f).coerceIn(24f, 58f)

            val scale = min(1f, 320f / max(w, h))
            val sw = max(32, (w * scale).roundToInt())
            val sh = max(32, (h * scale).roundToInt())
            val sdiff = FloatArray(sw * sh)
            for (sy in 0 until sh) {
                val ySrc = ((sy + 0.5f) * h / sh).toInt().coerceIn(0, h - 1)
                for (sx in 0 until sw) {
                    val xSrc = ((sx + 0.5f) * w / sw).toInt().coerceIn(0, w - 1)
                    val p = rgb[ySrc * w + xSrc]
                    val dr = Color.red(p) - bgR
                    val dg = Color.green(p) - bgG
                    val db = Color.blue(p) - bgB
                    sdiff[sy * sw + sx] = sqrt((dr * dr + dg * dg + db * db).toDouble()).toFloat()
                }
            }
            val bgMaskSmall = BooleanArray(sw * sh)
            val q = ArrayDeque<Int>()
            for (x in 0 until sw) {
                for (y in intArrayOf(0, sh - 1)) {
                    val idx = y * sw + x
                    if (sdiff[idx] <= thresh && !bgMaskSmall[idx]) { bgMaskSmall[idx] = true; q.addLast(idx) }
                }
            }
            for (y in 0 until sh) {
                for (x in intArrayOf(0, sw - 1)) {
                    val idx = y * sw + x
                    if (sdiff[idx] <= thresh && !bgMaskSmall[idx]) { bgMaskSmall[idx] = true; q.addLast(idx) }
                }
            }
            while (q.isNotEmpty()) {
                val cur = q.removeFirst()
                val cy = cur / sw
                val cx = cur % sw
                val curD = sdiff[cur]
                val nbrs = intArrayOf(
                    if (cy > 0) cur - sw else -1,
                    if (cy + 1 < sh) cur + sw else -1,
                    if (cx > 0) cur - 1 else -1,
                    if (cx + 1 < sw) cur + 1 else -1
                )
                for (nIdx in nbrs) {
                    if (nIdx >= 0 && !bgMaskSmall[nIdx]) {
                        val nd = sdiff[nIdx]
                        if (nd <= thresh || (abs(nd - curD) < 10f && nd <= thresh * 1.35f)) {
                            bgMaskSmall[nIdx] = true
                            q.addLast(nIdx)
                        }
                    }
                }
            }
            for (y in 0 until h) {
                val sy = (y * sh / h).coerceIn(0, sh - 1)
                for (x in 0 until w) {
                    val sx = (x * sw / w).coerceIn(0, sw - 1)
                    fg[y * w + x] = !bgMaskSmall[sy * sw + sx]
                }
            }
        }

        // 保留最大主体，清理桌面零星反光小噪点
        keepMainSubjectComponents(fg, w, h, minArea = max(60, (w * h) / 140))

        var x0 = w; var x1 = 0; var y0 = h; var y1 = 0
        for (y in 0 until h) {
            for (x in 0 until w) {
                if (fg[y * w + x]) {
                    if (x < x0) x0 = x
                    if (x + 1 > x1) x1 = x + 1
                    if (y < y0) y0 = y
                    if (y + 1 > y1) y1 = y + 1
                }
            }
        }
        if (x1 <= x0 || y1 <= y0) {
            x0 = 0; x1 = w; y0 = 0; y1 = h
            fg.fill(true)
        }
        val rw = x1 - x0
        val rh = y1 - y0

        var gw: Int
        var gh: Int
        var detectedType: DetectedSourceType
        var pitchPx = 0f

        if (overrideW != null && overrideH != null && overrideW in 10..96 && overrideH in 10..96) {
            gw = overrideW
            gh = overrideH
            detectedType = DetectedSourceType.CRAFT_PITCH_LOCKED
        } else {
            var lumSum = 0.0
            var lumCnt = 0
            val roiGray = FloatArray(rw * rh)
            for (ry in 0 until rh) {
                val sy = y0 + ry
                for (rx in 0 until rw) {
                    val sx = x0 + rx
                    val i = sy * w + sx
                    val p = rgb[i]
                    val l = 0.299f * Color.red(p) + 0.587f * Color.green(p) + 0.114f * Color.blue(p)
                    roiGray[ry * rw + rx] = l
                    if (fg[i]) { lumSum += l; lumCnt++ }
                }
            }
            val fgMean = (lumSum / max(1, lumCnt)).toFloat()
            for (ry in 0 until rh) {
                for (rx in 0 until rw) {
                    if (!fg[(y0 + ry) * w + (x0 + rx)]) roiGray[ry * rw + rx] = fgMean
                }
            }
            val colSig = FloatArray(max(1, rw - 1))
            for (rx in 0 until rw - 1) {
                var sum = 0f
                for (ry in 0 until rh) sum += abs(roiGray[ry * rw + rx + 1] - roiGray[ry * rw + rx])
                colSig[rx] = sum / rh
            }
            val rowSig = FloatArray(max(1, rh - 1))
            for (ry in 0 until rh - 1) {
                var sum = 0f
                for (rx in 0 until rw) sum += abs(roiGray[(ry + 1) * rw + rx] - roiGray[ry * rw + rx])
                rowSig[ry] = sum / rw
            }
            val minP = max(8f, min(rw, rh) / 56f)
            val maxP = max(minP + 4f, min(rw, rh) / 10f)
            val estX = detectFundamentalPitch(colSig, minP, maxP)
            val estY = detectFundamentalPitch(rowSig, minP, maxP)
            if (estX != null && estY != null && estX.score >= 4.2f && estY.score >= 4.2f &&
                abs(estX.pitch - estY.pitch) / max(estX.pitch, estY.pitch) < 0.16f
            ) {
                pitchPx = 0.5f * (estX.pitch + estY.pitch)
                gw = (rw / pitchPx).roundToInt().coerceIn(12, 64)
                gh = (rh / pitchPx).roundToInt().coerceIn(12, 64)
                detectedType = DetectedSourceType.CRAFT_PITCH_LOCKED
            } else {
                val maxCells = 32
                if (rw >= rh) {
                    gw = maxCells
                    gh = (maxCells.toFloat() * rh / rw).roundToInt().coerceIn(10, maxCells)
                } else {
                    gh = maxCells
                    gw = (maxCells.toFloat() * rw / rh).roundToInt().coerceIn(10, maxCells)
                }
                detectedType = DetectedSourceType.CRAFT_SHAPE_ESTIMATED
            }
        }

        val cw = rw.toFloat() / gw
        val ch = rh.toFloat() / gh
        val subPal = paletteRepo.filteredPalette(suppressGreenCast = true)
        val mask = BooleanArray(gw * gh)
        val sampledR = IntArray(gw * gh)
        val sampledG = IntArray(gw * gh)
        val sampledB = IntArray(gw * gh)

        for (r in 0 until gh) {
            val cy0 = (r * ch).roundToInt().coerceIn(0, rh - 1)
            val cy1 = ((r + 1) * ch).roundToInt().coerceIn(cy0 + 1, rh)
            for (c in 0 until gw) {
                val cx0 = (c * cw).roundToInt().coerceIn(0, rw - 1)
                val cx1 = ((c + 1) * cw).roundToInt().coerceIn(cx0 + 1, rw)
                var fgCnt = 0
                var totCnt = 0
                for (ry in cy0 until cy1) {
                    val sy = y0 + ry
                    for (rx in cx0 until cx1) {
                        totCnt++
                        if (fg[sy * w + x0 + rx]) fgCnt++
                    }
                }
                if (totCnt == 0 || fgCnt.toFloat() / totCnt < 0.42f) continue

                val ph = max(1, cy1 - cy0)
                val pw = max(1, cx1 - cx0)
                val ringPts = ArrayList<Int>(ph * pw)
                val allPts = ArrayList<Int>(ph * pw)
                for (ry in cy0 until cy1) {
                    val dy = (ry - cy0 + 0.5f) / ph - 0.5f
                    val sy = y0 + ry
                    for (rx in cx0 until cx1) {
                        val sx = x0 + rx
                        if (!fg[sy * w + sx]) continue
                        val p = rgb[sy * w + sx]
                        allPts.add(p)
                        val dx = (rx - cx0 + 0.5f) / pw - 0.5f
                        val rad = sqrt((dx * dx + dy * dy).toDouble()).toFloat()
                        if (rad in 0.16f..0.44f) ringPts.add(p)
                    }
                }
                val pts = if (ringPts.size >= 4) ringPts else allPts
                if (pts.isEmpty()) continue
                pts.sortBy { p ->
                    0.299f * Color.red(p) + 0.587f * Color.green(p) + 0.114f * Color.blue(p)
                }
                val lo = (pts.size * 0.28f).toInt().coerceIn(0, pts.size - 1)
                val hi = (pts.size * 0.88f).toInt().coerceIn(lo + 1, pts.size)
                val rs = ArrayList<Int>(hi - lo)
                val gs = ArrayList<Int>(hi - lo)
                val bs = ArrayList<Int>(hi - lo)
                for (i in lo until hi) {
                    val p = pts[i]
                    rs.add(Color.red(p)); gs.add(Color.green(p)); bs.add(Color.blue(p))
                }
                var mr = medianInt(rs).roundToInt()
                var mg = medianInt(gs).roundToInt()
                var mb = medianInt(bs).roundToInt()

                // 室内偏暖/阴影白豆还原为纯白
                val lum = 0.299f * mr + 0.587f * mg + 0.114f * mb
                val sat = max(mr, max(mg, mb)) - min(mr, min(mg, mb))
                if (lum >= 218f && sat <= 15) {
                    mr = (mr * 0.55f + 255f * 0.45f).roundToInt().coerceIn(0, 255)
                    mg = (mg * 0.55f + 255f * 0.45f).roundToInt().coerceIn(0, 255)
                    mb = (mb * 0.55f + 255f * 0.45f).roundToInt().coerceIn(0, 255)
                }

                val cellIdx = r * gw + c
                mask[cellIdx] = true
                sampledR[cellIdx] = mr
                sampledG[cellIdx] = mg
                sampledB[cellIdx] = mb
            }
        }

        // 映射调色板 + 合并光影微小杂色
        val palIdx = IntArray(gw * gh)
        for (i in mask.indices) {
            if (!mask[i]) continue
            palIdx[i] = matchNearestIndex(sampledR[i], sampledG[i], sampledB[i], subPal)
        }
        val protectedCodes = hashSetOf("H1", "H5", "H7", "H16")
        reduceToColorCap(palIdx, mask, subPal, craftMaxColors.coerceIn(4, 28), protectedCodes)

        val gridCodes = Array<String?>(gw * gh) { i -> if (mask[i]) subPal[palIdx[i]].code else null }
        smoothIsolatedGlare(gridCodes, mask, gw, gh, paletteRepo)

        val pattern = BeadPattern(name = title, width = gw, height = gh, cells = gridCodes.toList())
        return RecognitionResult(
            pattern = pattern,
            detectedType = detectedType,
            confidenceLabel = if (detectedType == DetectedSourceType.CRAFT_PITCH_LOCKED) {
                "已锁定实拍豆距约 ${pitchPx.roundToInt()}px · 避孔去反光采样"
            } else {
                "已自动抠底并按实物长宽比采样（可微调格数）"
            },
            hasCellTextCodes = false,
            detectedPitchPx = pitchPx,
            suggestedSlot = PhotoSlot.IRONED,
            markCompletedByDefault = true
        )
    }

    private fun keepMainSubjectComponents(fg: BooleanArray, w: Int, h: Int, minArea: Int) {
        val visited = BooleanArray(w * h)
        val keep = BooleanArray(w * h)
        var anyKept = false
        for (y in 0 until h) {
            for (x in 0 until w) {
                val start = y * w + x
                if (!fg[start] || visited[start]) continue
                val comp = ArrayList<Int>()
                val q = ArrayDeque<Int>()
                visited[start] = true
                q.addLast(start)
                while (q.isNotEmpty()) {
                    val cur = q.removeFirst()
                    comp.add(cur)
                    val cy = cur / w; val cx = cur % w
                    if (cy > 0 && fg[cur - w] && !visited[cur - w]) { visited[cur - w] = true; q.addLast(cur - w) }
                    if (cy + 1 < h && fg[cur + w] && !visited[cur + w]) { visited[cur + w] = true; q.addLast(cur + w) }
                    if (cx > 0 && fg[cur - 1] && !visited[cur - 1]) { visited[cur - 1] = true; q.addLast(cur - 1) }
                    if (cx + 1 < w && fg[cur + 1] && !visited[cur + 1]) { visited[cur + 1] = true; q.addLast(cur + 1) }
                }
                if (comp.size >= minArea) {
                    anyKept = true
                    for (p in comp) keep[p] = true
                }
            }
        }
        if (anyKept) {
            for (i in fg.indices) fg[i] = keep[i]
        }
    }

    private fun smoothIsolatedGlare(
        gridCodes: Array<String?>,
        mask: BooleanArray,
        w: Int,
        h: Int,
        paletteRepo: PaletteRepository
    ) {
        val copy = gridCodes.copyOf()
        for (r in 1 until h - 1) {
            for (c in 1 until w - 1) {
                val idx = r * w + c
                if (!mask[idx]) continue
                val cur = copy[idx] ?: continue
                val nbrs = arrayOf(copy[(r - 1) * w + c], copy[(r + 1) * w + c], copy[r * w + (c - 1)], copy[r * w + (c + 1)])
                if (nbrs.any { it == null }) continue
                val uniq = nbrs.filterNotNull().toSet()
                if (uniq.size == 1 && uniq.first() != cur) {
                    val curL = paletteRepo.findByMardCode(cur)?.luminance ?: 128.0
                    val nbrL = paletteRepo.findByMardCode(uniq.first())?.luminance ?: 128.0
                    // 若仅是局部反光引起的同色块单点跳变则平滑，保留高反差瞳孔/描边
                    if (abs(curL - nbrL) < 75.0) {
                        gridCodes[idx] = uniq.first()
                    }
                }
            }
        }
    }

    private fun reduceToColorCap(
        palIdx: IntArray,
        mask: BooleanArray,
        subPal: List<PaletteColor>,
        cap: Int,
        protectedCodes: Set<String>
    ) {
        val counts = HashMap<Int, Int>()
        for (i in palIdx.indices) {
            if (mask[i]) counts[palIdx[i]] = (counts[palIdx[i]] ?: 0) + 1
        }
        if (counts.size <= cap) return
        val mergeMap = HashMap<Int, Int>(counts.size)
        for (k in counts.keys) mergeMap[k] = k

        while (counts.size > cap) {
            val nonProtected = counts.entries
                .filter { subPal[it.key].code !in protectedCodes }
                .minByOrNull { it.value }
                ?: counts.entries.minByOrNull { it.value }
                ?: break
            val minKey = nonProtected.key
            val c1 = subPal[minKey]
            var bestTarget = -1
            var bestDist = Double.MAX_VALUE
            for (otherKey in counts.keys) {
                if (otherKey == minKey) continue
                val c2 = subPal[otherKey]
                val d = PaletteRepository.labDist(c1.labL, c1.labA, c1.labB, c2.labL, c2.labA, c2.labB)
                if (d < bestDist) { bestDist = d; bestTarget = otherKey }
            }
            if (bestTarget < 0) break
            counts[bestTarget] = (counts[bestTarget] ?: 0) + nonProtected.value
            counts.remove(minKey)
            for ((orig, mapped) in mergeMap) {
                if (mapped == minKey) mergeMap[orig] = bestTarget
            }
        }
        for (i in palIdx.indices) {
            if (mask[i]) palIdx[i] = mergeMap[palIdx[i]] ?: palIdx[i]
        }
    }

    private fun matchNearestCode(r: Int, g: Int, b: Int, palette: List<PaletteColor>): String {
        return palette[matchNearestIndex(r, g, b, palette)].code
    }

    private fun matchNearestIndex(r: Int, g: Int, b: Int, palette: List<PaletteColor>): Int {
        val lab = PaletteRepository.rgbToLab(r.coerceIn(0, 255), g.coerceIn(0, 255), b.coerceIn(0, 255))
        var bestIdx = 0
        var bestDist = Double.MAX_VALUE
        for (i in palette.indices) {
            val e = palette[i]
            val d = PaletteRepository.labDist(lab[0], lab[1], lab[2], e.labL, e.labA, e.labB)
            if (d < bestDist) {
                bestDist = d
                bestIdx = i
            }
        }
        return bestIdx
    }

    private fun bestContiguousRun(scores: FloatArray, thresh: Float, maxGap: Int): Pair<Int, Int> {
        val active = BooleanArray(scores.size) { scores[it] >= thresh }
        if (maxGap > 0) {
            for (i in active.indices) {
                if (!active[i]) {
                    var lOk = false
                    for (k in max(0, i - maxGap) until i) if (scores[k] >= thresh) { lOk = true; break }
                    var rOk = false
                    for (k in (i + 1) until min(scores.size, i + 1 + maxGap)) if (scores[k] >= thresh) { rOk = true; break }
                    if (lOk && rOk) active[i] = true
                }
            }
        }
        var bestStart = 0
        var bestEnd = 0
        var curStart = -1
        for (i in active.indices) {
            if (active[i]) {
                if (curStart < 0) curStart = i
            } else {
                if (curStart >= 0) {
                    if (i - curStart > bestEnd - bestStart) { bestStart = curStart; bestEnd = i }
                    curStart = -1
                }
            }
        }
        if (curStart >= 0 && active.size - curStart > bestEnd - bestStart) {
            bestStart = curStart; bestEnd = active.size
        }
        return bestStart to bestEnd
    }

    private fun percentileSorted(arr: FloatArray, q: Float): Float {
        if (arr.isEmpty()) return 0f
        arr.sort()
        val pos = (q * (arr.size - 1)).roundToInt().coerceIn(0, arr.size - 1)
        return arr[pos]
    }

    private fun medianInt(list: List<Int>): Float {
        if (list.isEmpty()) return 0f
        val arr = list.toIntArray()
        arr.sort()
        val m = arr.size / 2
        return if (arr.size % 2 == 1) arr[m].toFloat() else (arr[m - 1] + arr[m]) * 0.5f
    }

    private fun stdDev(arr: FloatArray): Float {
        if (arr.size <= 1) return 0f
        var sum = 0.0
        for (v in arr) sum += v
        val mean = sum / arr.size
        var sq = 0.0
        for (v in arr) { val d = v - mean; sq += d * d }
        return sqrt(sq / arr.size).toFloat()
    }
}
