package com.pindoustudio.app.engine

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import com.pindoustudio.app.data.PaletteRepository
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.ConvertMode
import com.pindoustudio.app.model.PaletteColor
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt

/**
 * 纯离线安卓端图转拼豆量化引擎：
 * - 支持照片融合精修 (PHOTO_FUSION) 与异形抠底描边 (CUTOUT_OUTLINE)
 * - 自动抑制白毛偏绿、圆眼/圆形特征抗锯齿圆润化（告别方正棱角）、保留纯白高光与 H5 描边
 */
object NativeBeadConverter {

    fun convert(
        bitmap: Bitmap,
        paletteRepo: PaletteRepository,
        name: String,
        mode: ConvertMode,
        targetW: Int,
        targetH: Int,
        maxColors: Int,
        suppressGreenCast: Boolean,
        smoothEyes: Boolean = true,
        addOutline: Boolean
    ): BeadPattern {
        val tw = targetW.coerceIn(12, 96)
        val th = targetH.coerceIn(12, 96)
        val cap = maxColors.coerceIn(4, 32)
        val subPal = paletteRepo.filteredPalette(suppressGreenCast)

        val sampledRgb = IntArray(tw * th)
        val mask = BooleanArray(tw * th)

        if (mode == ConvertMode.CUTOUT_OUTLINE) {
            sampleCutoutSubject(bitmap, tw, th, margin = if (addOutline) 1 else 0, suppressGreenCast, sampledRgb, mask)
            cleanupIsolatedForeground(mask, tw, th, minSize = max(8, (tw * th) / 70))
        } else {
            sampleCoverPhoto(bitmap, tw, th, suppressGreenCast, sampledRgb, mask)
        }

        // 映射至 MARD 221 子集
        val palIdx = IntArray(tw * th)
        for (i in 0 until tw * th) {
            if (!mask[i]) continue
            val col = sampledRgb[i]
            val lab = PaletteRepository.rgbToLab(Color.red(col), Color.green(col), Color.blue(col))
            var bestIdx = 0
            var bestDist = Double.MAX_VALUE
            for (p in subPal.indices) {
                val entry = subPal[p]
                val d = PaletteRepository.labDist(lab[0], lab[1], lab[2], entry.labL, entry.labA, entry.labB)
                if (d < bestDist) {
                    bestDist = d
                    bestIdx = p
                }
            }
            palIdx[i] = bestIdx
        }

        // 感知低损归并到目标颜色上限（保护轮廓黑/白以及高对比小瞳孔色不被大色块吞并）
        val protectedCodes = HashSet<String>(setOf("H1", "H5", "H16", "H7"))
        for (r in 1 until th - 1) {
            for (c in 1 until tw - 1) {
                val i = r * tw + c
                if (!mask[i]) continue
                val entry = subPal[palIdx[i]]
                if (entry.luminance < 95.0) {
                    var brightNbrs = 0
                    for (dr in -1..1) {
                        for (dc in -1..1) {
                            if (dr == 0 && dc == 0) continue
                            val ni = (r + dr) * tw + (c + dc)
                            if (mask[ni] && subPal[palIdx[ni]].luminance >= 145.0) brightNbrs++
                        }
                    }
                    if (brightNbrs >= 4) protectedCodes.add(entry.code)
                }
            }
        }
        reduceToColorCap(palIdx, mask, subPal, cap, protectedCodes)

        // 转回 MARD 基准色号数组
        val gridCodes = Array<String?>(tw * th) { i ->
            if (mask[i]) subPal[palIdx[i]].code else null
        }

        // 孤立单像素噪点平滑（保留高反差眼睛/高光，去除大色块里的零星杂豆）
        cleanupIsolatedSpeckles(gridCodes, mask, tw, th, paletteRepo)

        // 圆眼配对等大对称对齐 + 抗锯齿圆润化（在最终外描边前进行）
        if (smoothEyes) {
            smoothRoundEyesAndAa(gridCodes, mask, tw, th, subPal, paletteRepo)
        }

        // 异形外圈 1 格 H5 炭灰描边
        if (addOutline) {
            val toOutline = ArrayList<Int>()
            for (r in 0 until th) {
                for (c in 0 until tw) {
                    val idx = r * tw + c
                    if (gridCodes[idx] != null) continue
                    val neighbors = arrayOf(r - 1 to c, r + 1 to c, r to c - 1, r to c + 1)
                    if (neighbors.any { (nr, nc) -> nr in 0 until th && nc in 0 until tw && gridCodes[nr * tw + nc] != null }) {
                        toOutline.add(idx)
                    }
                }
            }
            for (idx in toOutline) {
                gridCodes[idx] = "H5"
            }
        }

        return BeadPattern(
            name = name,
            width = tw,
            height = th,
            cells = gridCodes.toList()
        )
    }

    private data class EyeCandidate(
        val comp: Set<Int>,
        val r0: Int,
        val r1: Int,
        val c0: Int,
        val c1: Int,
        val bh: Int,
        val bw: Int,
        val cy: Double,
        val cx: Double,
        val area: Int,
        val bright: List<Int>,
        val ringBrightRatio: Double,
        val ringAvgLum: Double,
        val darkCode: String,
        val domBgCode: String,
        val avgBgR: Double,
        val avgBgG: Double,
        val avgBgB: Double
    )

    private fun cleanupIsolatedForeground(mask: BooleanArray, w: Int, h: Int, minSize: Int) {
        val visited = BooleanArray(w * h)
        val keep = BooleanArray(w * h)
        var keptAny = false
        for (r in 0 until h) {
            for (c in 0 until w) {
                val start = r * w + c
                if (!mask[start] || visited[start]) continue
                val comp = ArrayList<Int>()
                val q = ArrayDeque<Int>()
                visited[start] = true
                q.addLast(start)
                while (q.isNotEmpty()) {
                    val cur = q.removeFirst()
                    comp.add(cur)
                    val cr = cur / w; val cc = cur % w
                    if (cr > 0 && mask[cur - w] && !visited[cur - w]) { visited[cur - w] = true; q.addLast(cur - w) }
                    if (cr + 1 < h && mask[cur + w] && !visited[cur + w]) { visited[cur + w] = true; q.addLast(cur + w) }
                    if (cc > 0 && mask[cur - 1] && !visited[cur - 1]) { visited[cur - 1] = true; q.addLast(cur - 1) }
                    if (cc + 1 < w && mask[cur + 1] && !visited[cur + 1]) { visited[cur + 1] = true; q.addLast(cur + 1) }
                }
                if (comp.size >= minSize) {
                    keptAny = true
                    for (p in comp) keep[p] = true
                }
            }
        }
        if (keptAny) {
            for (i in mask.indices) mask[i] = keep[i]
        }
    }

    private fun pickNearestCode(
        r: Int,
        g: Int,
        b: Int,
        subPal: List<PaletteColor>,
        usedCodes: Set<String>
    ): String {
        val lab = PaletteRepository.rgbToLab(r, g, b)
        var bestCode = subPal[0].code
        var bestScore = Double.MAX_VALUE
        for (entry in subPal) {
            var d = PaletteRepository.labDist(lab[0], lab[1], lab[2], entry.labL, entry.labA, entry.labB)
            if (entry.code in usedCodes) d -= 2.4
            if (d < bestScore) {
                bestScore = d
                bestCode = entry.code
            }
        }
        return bestCode
    }

    private fun smoothRoundEyesAndAa(
        gridCodes: Array<String?>,
        mask: BooleanArray,
        w: Int,
        h: Int,
        subPal: List<PaletteColor>,
        paletteRepo: PaletteRepository
    ) {
        if (w < 12 || h < 12) return

        val lumGrid = DoubleArray(w * h) { i ->
            val code = gridCodes[i]
            if (!mask[i] || code == null) 255.0 else paletteRepo.findByMardCode(code)?.luminance ?: 255.0
        }
        val usedCodes = gridCodes.filterNotNull().toMutableSet()
        // 同时捕获清晰深黑瞳孔 (<92) 以及被高光白/浅毛围绕的高反差褐/灰瞳 (<122 且比周边平均亮度暗 >=62)
        val darkMask = BooleanArray(w * h) { i ->
            if (!mask[i]) false
            else if (lumGrid[i] < 92.0) true
            else if (lumGrid[i] < 122.0) {
                val r = i / w; val c = i % w
                var sumL = 0.0; var cnt = 0
                for (dr in -1..1) for (dc in -1..1) {
                    if (dr == 0 && dc == 0) continue
                    val nr = r + dr; val nc = c + dc
                    if (nr in 0 until h && nc in 0 until w && mask[nr * w + nc]) {
                        sumL += lumGrid[nr * w + nc]; cnt++
                    }
                }
                cnt >= 5 && (sumL / cnt - lumGrid[i]) >= 62.0
            } else false
        }
        val visited = BooleanArray(w * h)
        val candidates = ArrayList<EyeCandidate>()

        for (r in 0 until h) {
            for (c in 0 until w) {
                val start = r * w + c
                if (!darkMask[start] || visited[start]) continue
                val comp = ArrayList<Int>()
                val q = ArrayDeque<Int>()
                visited[start] = true
                q.addLast(start)
                while (q.isNotEmpty()) {
                    val cur = q.removeFirst()
                    comp.add(cur)
                    val cr = cur / w
                    val cc = cur % w
                    for (dr in -1..1) {
                        for (dc in -1..1) {
                            if (dr == 0 && dc == 0) continue
                            val nr = cr + dr
                            val nc = cc + dc
                            if (nr in 0 until h && nc in 0 until w) {
                                val ni = nr * w + nc
                                if (darkMask[ni] && !visited[ni]) {
                                    visited[ni] = true
                                    q.addLast(ni)
                                }
                            }
                        }
                    }
                }

                if (comp.isEmpty() || comp.size > max(64, (w * h * 0.055).toInt())) continue
                var r0 = h; var r1 = -1; var c0 = w; var c1 = -1
                for (pos in comp) {
                    val pr = pos / w; val pc = pos % w
                    if (pr < r0) r0 = pr
                    if (pr > r1) r1 = pr
                    if (pc < c0) c0 = pc
                    if (pc > c1) c1 = pc
                }
                if (r0 == 0 || r1 == h - 1 || c0 == 0 || c1 == w - 1) continue
                val bh = r1 - r0 + 1
                val bw = c1 - c0 + 1
                if (bh > max(11, (h * 0.24).toInt()) || bw > max(11, (w * 0.24).toInt())) continue
                if (max(bh, bw).toDouble() / max(1, min(bh, bw)) > 2.2) continue

                val compSet = comp.toHashSet()
                val interiorBright = ArrayList<Int>()
                var touchUnmasked = 0
                for (pr in r0..r1) {
                    for (pc in c0..c1) {
                        val pos = pr * w + pc
                        if (pos in compSet) {
                            for ((dr, dc) in arrayOf(-1 to 0, 1 to 0, 0 to -1, 0 to 1)) {
                                val nr = pr + dr; val nc = pc + dc
                                if (nr !in 0 until h || nc !in 0 until w || !mask[nr * w + nc]) {
                                    touchUnmasked++
                                    break
                                }
                            }
                        } else if (mask[pos] && lumGrid[pos] >= 160.0) {
                            var darkNbrs = 0
                            for ((dr, dc) in arrayOf(-1 to 0, 1 to 0, 0 to -1, 0 to 1)) {
                                val nr = pr + dr; val nc = pc + dc
                                if (nr in r0..r1 && nc in c0..c1 && (nr * w + nc) in compSet) darkNbrs++
                            }
                            if (darkNbrs >= 3) interiorBright.add(pos)
                        }
                    }
                }
                val rawFill = comp.size.toDouble() / max(1, bh * bw)
                val fillRatio = (comp.size + interiorBright.size).toDouble() / max(1, bh * bw)
                if (rawFill < 0.50 || fillRatio < 0.54 || touchUnmasked > 1) continue

                // 统计眼眶周围一圈的毛发/面部底色亮度，剔除深色衣褶/毯子误判
                val codeCounts = HashMap<String, Int>()
                for (pos in compSet) {
                    val code = gridCodes[pos] ?: continue
                    codeCounts[code] = (codeCounts[code] ?: 0) + 1
                }
                val darkCode = codeCounts.entries.maxWithOrNull { a, b ->
                    val la = paletteRepo.findByMardCode(a.key)?.luminance ?: 99.0
                    val lb = paletteRepo.findByMardCode(b.key)?.luminance ?: 99.0
                    val cmp = a.value.compareTo(b.value)
                    if (cmp != 0) cmp else lb.compareTo(la)
                }?.key ?: continue

                val bgEntries = ArrayList<PaletteColor>()
                val bgCounts = HashMap<String, Int>()
                var ringTotal = 0
                var ringBright = 0
                var ringLumSum = 0.0
                for (rr in max(0, r0 - 2)..min(h - 1, r1 + 2)) {
                    for (cc in max(0, c0 - 2)..min(w - 1, c1 + 2)) {
                        val pos = rr * w + cc
                        if (!mask[pos] || pos in compSet || pos in interiorBright) continue
                        val lum = lumGrid[pos]
                        ringTotal++
                        ringLumSum += lum
                        if (lum >= 115.0) ringBright++
                        if (lum >= 95.0) {
                            val cCode = gridCodes[pos] ?: continue
                            paletteRepo.findByMardCode(cCode)?.let { bgEntries.add(it) }
                            bgCounts[cCode] = (bgCounts[cCode] ?: 0) + 1
                        }
                    }
                }
                if (bgEntries.isEmpty() || ringTotal == 0) continue
                val ringBrightRatio = ringBright.toDouble() / ringTotal
                val ringAvgLum = ringLumSum / ringTotal
                if (comp.size <= 2 && (ringBrightRatio < 0.62 || ringAvgLum < 125.0)) continue

                candidates.add(
                    EyeCandidate(
                        comp = compSet,
                        r0 = r0,
                        r1 = r1,
                        c0 = c0,
                        c1 = c1,
                        bh = bh,
                        bw = bw,
                        cy = (r0 + r1) / 2.0,
                        cx = (c0 + c1) / 2.0,
                        area = comp.size + interiorBright.size,
                        bright = interiorBright,
                        ringBrightRatio = ringBrightRatio,
                        ringAvgLum = ringAvgLum,
                        darkCode = darkCode,
                        domBgCode = bgCounts.maxByOrNull { it.value }?.key ?: continue,
                        avgBgR = bgEntries.map { it.r }.average(),
                        avgBgG = bgEntries.map { it.g }.average(),
                        avgBgB = bgEntries.map { it.b }.average()
                    )
                )
            }
        }

        if (candidates.isEmpty()) return

        // 配对验证对称双眼，优先选择亮度对比最清晰、大小/高度最接近的对组
        val pairCandidates = ArrayList<Triple<Int, Int, Double>>()
        for (i in candidates.indices) {
            val ci = candidates[i]
            if (ci.ringBrightRatio < 0.50 || ci.cy > h * 0.74) continue
            for (j in i + 1 until candidates.size) {
                val cj = candidates[j]
                if (cj.ringBrightRatio < 0.50 || cj.cy > h * 0.74) continue
                val dy = abs(ci.cy - cj.cy)
                val dx = abs(ci.cx - cj.cx)
                val ratio = min(ci.area, cj.area).toDouble() / max(1, max(ci.area, cj.area))
                if (dy <= max(2.2, h * 0.055) && dx >= 3.0 && dx <= w * 0.45 && ratio >= 0.25 && abs(ci.ringAvgLum - cj.ringAvgLum) <= 58.0) {
                    val score = (ci.ringBrightRatio + cj.ringBrightRatio) * 10.0 - dy * 2.0 + min(ci.area, cj.area) * 0.4
                    pairCandidates.add(Triple(i, j, score))
                }
            }
        }
        pairCandidates.sortByDescending { it.third }

        val pairedUsed = HashSet<Int>()
        val eyePairs = ArrayList<Pair<Int, Int>>()
        for ((i, j, _) in pairCandidates) {
            if (i !in pairedUsed && j !in pairedUsed) {
                pairedUsed.add(i)
                pairedUsed.add(j)
                eyePairs.add(i to j)
            }
        }

        val confirmedEyes = HashSet<Int>()
        for ((i, j) in eyePairs) {
            confirmedEyes.add(i)
            confirmedEyes.add(j)
        }
        for (i in candidates.indices) {
            val ci = candidates[i]
            if (ci.bright.isNotEmpty() && ci.area >= 6) confirmedEyes.add(i)
        }

        // 1) 对成对确认的双眼执行「尺寸、形状与色度强对称等大校准」
        for ((i, j) in eyePairs) {
            val left = if (candidates[i].cx <= candidates[j].cx) candidates[i] else candidates[j]
            val right = if (candidates[i].cx <= candidates[j].cx) candidates[j] else candidates[i]
            val li = paletteRepo.findByMardCode(left.darkCode)?.luminance ?: 99.0
            val lj = paletteRepo.findByMardCode(right.darkCode)?.luminance ?: 99.0
            val darkerOrig = if (li <= lj) left.darkCode else right.darkCode
            val minEyeLum = min(li, lj)
            // 若在浅毛脸上瞳孔偏浅 (>62)，统一收深至高对比深棕/纯黑瞳，双眸神采与大小完全一致
            val sharedDarkCode = if (minEyeLum > 62.0 && max(left.ringAvgLum, right.ringAvgLum) >= 145.0) {
                if (paletteRepo.findByMardCode("H7") != null) "H7" else darkerOrig
            } else {
                darkerOrig
            }
            val dx = abs(left.cx - right.cx)

            val maxArea = max(left.area, right.area)
            if (maxArea <= 4) {
                // 小格实拍图（如 40x40 / 52x52 全身猫）：彻底抹平因像素网格错位导致的大小眼
                val th: Int
                val tw: Int
                if (dx <= 5.2 || maxArea <= 2) {
                    // 小脸双眸统一校准为 1x1 清晰对称圆瞳
                    th = 1; tw = 1
                } else {
                    th = 2; tw = 2
                }
                val sameRow = abs(left.cy - right.cy) <= 1.15
                val targetR0 = if (sameRow) ((left.cy + right.cy) / 2.0).roundToInt() else left.r0
                val rightR0 = if (sameRow) targetR0 else right.r0
                stampSymmetricSmallEye(gridCodes, mask, w, h, left, targetR0, left.cx.roundToInt(), th, tw, sharedDarkCode)
                stampSymmetricSmallEye(gridCodes, mask, w, h, right, rightR0, right.cx.roundToInt(), th, tw, sharedDarkCode)
            } else {
                // 较大圆眼（>=3x3）：计算统一规范椭圆核心模板，保证左右眼像素颗数、宽高、眼神光位置严格一致
                val targetH = max(3, ((left.bh + right.bh) / 2.0).roundToInt())
                val targetW = max(3, ((left.bw + right.bw) / 2.0).roundToInt())
                val sameRow = abs(left.cy - right.cy) <= 1.15
                val sharedCy = if (sameRow) (left.cy + right.cy) / 2.0 else left.cy
                stampCanonicalLargeEye(gridCodes, mask, lumGrid, paletteRepo, subPal, usedCodes, w, h, left, targetH, targetW, sharedCy, sharedDarkCode)
                stampCanonicalLargeEye(gridCodes, mask, lumGrid, paletteRepo, subPal, usedCodes, w, h, right, targetH, targetW, if (sameRow) sharedCy else right.cy, sharedDarkCode)
            }
        }

        // 2) 未成对的孤立大圆特征（如鼻头、侧脸单眼）仍走圆形圆润化处理（跳过小 1-2px 孤立杂点）
        for ((cid, feat) in candidates.withIndex()) {
            if (cid in pairedUsed) continue
            if (feat.bh < 3 || feat.bw < 3) continue
            val darkEntry = paletteRepo.findByMardCode(feat.darkCode) ?: continue

            val ry = max(1.0, feat.bh / 2.0)
            val rx = max(1.0, feat.bw / 2.0)
            val coreSet = HashSet<Int>()
            for (rr in feat.r0..feat.r1) {
                for (cc in feat.c0..feat.c1) {
                    val pos = rr * w + cc
                    if (!mask[pos]) continue
                    if (feat.bh == 3 && feat.bw == 3) {
                        if ((rr == feat.r0 || rr == feat.r1) && (cc == feat.c0 || cc == feat.c1)) continue
                        coreSet.add(pos)
                    } else {
                        val d2 = ((rr - feat.cy) / ry).pow(2) + ((cc - feat.cx) / rx).pow(2)
                        if (d2 <= 0.90) coreSet.add(pos)
                    }
                }
            }
            if (coreSet.isEmpty()) continue

            val preservedBright = feat.bright.filter { it in coreSet }.toHashSet()
            for (pos in coreSet) {
                if (pos !in preservedBright) gridCodes[pos] = feat.darkCode
            }

            val applySoftAa = feat.bh >= 5 && feat.bw >= 5
            for (rr in max(0, feat.r0 - 1)..min(h - 1, feat.r1 + 1)) {
                for (cc in max(0, feat.c0 - 1)..min(w - 1, feat.c1 + 1)) {
                    val pos = rr * w + cc
                    if (!mask[pos] || pos in coreSet) continue
                    var coreOrtho = 0
                    for ((dr, dc) in arrayOf(-1 to 0, 1 to 0, 0 to -1, 0 to 1)) {
                        val nr = rr + dr; val nc = cc + dc
                        if (nr in 0 until h && nc in 0 until w && (nr * w + nc) in coreSet) coreOrtho++
                    }
                    val isCorner = (rr == feat.r0 || rr == feat.r1) && (cc == feat.c0 || cc == feat.c1)
                    if (applySoftAa && (coreOrtho >= 2 || (isCorner && pos in feat.comp && coreOrtho >= 1))) {
                        val aaCode = pickNearestCode(
                            (0.26 * darkEntry.r + 0.74 * feat.avgBgR).roundToInt(),
                            (0.26 * darkEntry.g + 0.74 * feat.avgBgG).roundToInt(),
                            (0.26 * darkEntry.b + 0.74 * feat.avgBgB).roundToInt(),
                            subPal,
                            usedCodes
                        )
                        gridCodes[pos] = aaCode
                        usedCodes.add(aaCode)
                    } else if (pos in feat.comp) {
                        gridCodes[pos] = feat.domBgCode
                    }
                }
            }

            if (cid in confirmedEyes && (preservedBright.isNotEmpty() || (feat.bh >= 4 && feat.bw >= 4 && coreSet.size >= 10))) {
                if (preservedBright.isNotEmpty()) {
                    for (bp in preservedBright) gridCodes[bp] = "H1"
                } else {
                    val hr = (feat.cy - max(0.5, feat.bh * 0.22)).roundToInt().coerceIn(feat.r0, feat.r1)
                    val hc = (feat.cx - max(0.5, feat.bw * 0.22)).roundToInt().coerceIn(feat.c0, feat.c1)
                    val hPos = hr * w + hc
                    if (hPos in coreSet) gridCodes[hPos] = "H1"
                }
            }
        }
    }

    private fun stampSymmetricSmallEye(
        gridCodes: Array<String?>,
        mask: BooleanArray,
        w: Int,
        h: Int,
        orig: EyeCandidate,
        targetCenterR: Int,
        targetCenterC: Int,
        th: Int,
        tw: Int,
        darkCode: String
    ) {
        // 先把原眼区全部退回邻近局部底色，避免遗留多余暗点形成大小眼
        for (pos in orig.comp) {
            if (mask[pos]) gridCodes[pos] = orig.domBgCode
        }
        val rStart = if (th == 1) targetCenterR else (targetCenterR - (th - 1) / 2.0).roundToInt()
        val cStart = if (tw == 1) targetCenterC else (orig.cx - (tw - 1) / 2.0).roundToInt()
        for (dr in 0 until th) {
            for (dc in 0 until tw) {
                val rr = rStart + dr
                val cc = cStart + dc
                if (rr in 0 until h && cc in 0 until w && mask[rr * w + cc]) {
                    gridCodes[rr * w + cc] = darkCode
                }
            }
        }
    }

    private fun stampCanonicalLargeEye(
        gridCodes: Array<String?>,
        mask: BooleanArray,
        lumGrid: DoubleArray,
        paletteRepo: PaletteRepository,
        subPal: List<PaletteColor>,
        usedCodes: MutableSet<String>,
        w: Int,
        h: Int,
        orig: EyeCandidate,
        targetH: Int,
        targetW: Int,
        targetCy: Double,
        darkCode: String
    ) {
        for (pos in orig.comp) {
            if (mask[pos]) gridCodes[pos] = orig.domBgCode
        }
        val r0 = (targetCy - (targetH - 1) / 2.0).roundToInt().coerceIn(1, h - targetH - 1)
        val c0 = (orig.cx - (targetW - 1) / 2.0).roundToInt().coerceIn(1, w - targetW - 1)
        val r1 = r0 + targetH - 1
        val c1 = c0 + targetW - 1
        val cy = (r0 + r1) / 2.0
        val cx = (c0 + c1) / 2.0
        val ry = max(1.0, targetH / 2.0)
        val rx = max(1.0, targetW / 2.0)

        val coreSet = HashSet<Int>()
        for (rr in r0..r1) {
            for (cc in c0..c1) {
                val pos = rr * w + cc
                if (!mask[pos]) continue
                if (targetH == 3 && targetW == 3) {
                    if ((rr == r0 || rr == r1) && (cc == c0 || cc == c1)) continue
                    coreSet.add(pos)
                } else {
                    val d2 = ((rr - cy) / ry).pow(2) + ((cc - cx) / rx).pow(2)
                    if (d2 <= 0.90) coreSet.add(pos)
                }
            }
        }
        for (pos in coreSet) gridCodes[pos] = darkCode

        val darkEntry = paletteRepo.findByMardCode(darkCode)
        if (targetH >= 5 && targetW >= 5 && darkEntry != null) {
            for (rr in max(0, r0 - 1)..min(h - 1, r1 + 1)) {
                for (cc in max(0, c0 - 1)..min(w - 1, c1 + 1)) {
                    val pos = rr * w + cc
                    if (!mask[pos] || pos in coreSet) continue
                    var coreOrtho = 0
                    for ((dr, dc) in arrayOf(-1 to 0, 1 to 0, 0 to -1, 0 to 1)) {
                        val nr = rr + dr; val nc = cc + dc
                        if (nr in 0 until h && nc in 0 until w && (nr * w + nc) in coreSet) coreOrtho++
                    }
                    if (coreOrtho >= 2 && lumGrid[pos] >= 95.0) {
                        val aaCode = pickNearestCode(
                            (0.26 * darkEntry.r + 0.74 * orig.avgBgR).roundToInt(),
                            (0.26 * darkEntry.g + 0.74 * orig.avgBgG).roundToInt(),
                            (0.26 * darkEntry.b + 0.74 * orig.avgBgB).roundToInt(),
                            subPal,
                            usedCodes
                        )
                        gridCodes[pos] = aaCode
                        usedCodes.add(aaCode)
                    }
                }
            }
        }

        if (targetH >= 4 && targetW >= 4 && coreSet.size >= 10) {
            val hr = (cy - max(0.5, targetH * 0.22)).roundToInt().coerceIn(r0, r1)
            val hc = (cx - max(0.5, targetW * 0.22)).roundToInt().coerceIn(c0, c1)
            val hPos = hr * w + hc
            if (hPos in coreSet) gridCodes[hPos] = "H1"
        }
    }

    private fun neutralizeGreenCastPixel(argb: Int): Int {
        val a = Color.alpha(argb)
        if (a < 128) return argb
        var r = Color.red(argb)
        var g = Color.green(argb)
        var b = Color.blue(argb)
        val lum = 0.299 * r + 0.587 * g + 0.114 * b
        val maxC = max(r, max(g, b))
        val minC = min(r, min(g, b))
        if (lum >= 186.0 && (maxC - minC) <= 42) {
            if (g >= r && g >= b) {
                g = min(g, min(r, b) + 3)
            }
            // 温和校准室内暖黄阴影下的白毛（如肚子阴影泛红/橘），保持洁净象牙/纯白毛色
            val targetW = if (lum >= 216.0) min(255.0, lum + 14.0) else lum
            val blendW = if (lum >= 210.0) 0.60 else 0.42
            r = (r * (1.0 - blendW) + targetW * blendW).roundToInt().coerceIn(0, 255)
            g = (g * (1.0 - blendW) + targetW * blendW).roundToInt().coerceIn(0, 255)
            b = (b * (1.0 - blendW) + targetW * blendW).roundToInt().coerceIn(0, 255)
            return Color.argb(a, r, g, b)
        }
        return argb
    }

    private fun cleanupIsolatedSpeckles(
        gridCodes: Array<String?>,
        mask: BooleanArray,
        w: Int,
        h: Int,
        paletteRepo: PaletteRepository
    ) {
        if (w < 6 || h < 6) return
        val snapshot = gridCodes.copyOf()
        for (r in 1 until h - 1) {
            for (c in 1 until w - 1) {
                val pos = r * w + c
                val cur = snapshot[pos] ?: continue
                if (!mask[pos]) continue
                val entry = paletteRepo.findByMardCode(cur) ?: continue
                // 保留深色瞳孔与纯白高光，避免误消小细节
                if (entry.luminance < 76.0 || entry.luminance > 235.0) continue

                val nbrs = arrayOf(
                    snapshot[(r - 1) * w + c],
                    snapshot[(r + 1) * w + c],
                    snapshot[r * w + (c - 1)],
                    snapshot[r * w + (c + 1)]
                )
                if (nbrs.any { it == cur || it == null }) continue
                val counts = HashMap<String, Int>(4)
                for (n in nbrs) {
                    if (n != null) counts[n] = (counts[n] ?: 0) + 1
                }
                val best = counts.maxByOrNull { it.value } ?: continue
                if (best.value >= 3) {
                    gridCodes[pos] = best.key
                }
            }
        }
    }

    // 预计算 sRGB <-> 线性光查找表，避免暗部与亮部平均时发灰发泥
    private val srgbToLin = DoubleArray(256) { v -> (v / 255.0).pow(2.2) }

    private fun linearAvgToRgb(sumLinR: Double, sumLinG: Double, sumLinB: Double, count: Int): Int {
        val inv = 1.0 / max(1, count)
        val r = ((sumLinR * inv).coerceIn(0.0, 1.0).pow(1.0 / 2.2) * 255.0).roundToInt().coerceIn(0, 255)
        val g = ((sumLinG * inv).coerceIn(0.0, 1.0).pow(1.0 / 2.2) * 255.0).roundToInt().coerceIn(0, 255)
        val b = ((sumLinB * inv).coerceIn(0.0, 1.0).pow(1.0 / 2.2) * 255.0).roundToInt().coerceIn(0, 255)
        return Color.rgb(r, g, b)
    }

    /**
     * 特征保真格内采样：线性光均值之外单独跟踪「深瞳孔像素簇」与「纯白眼神高光」。
     * 当格内存在高反差小黑瞳 (占比 >= 14% 且明显暗于全格均值) 时优先锁住瞳孔深色，避免被周边亮毛稀释成灰点或丢失。
     */
    private class CellAccumulator {
        var sumR = 0.0; var sumG = 0.0; var sumB = 0.0; var cnt = 0
        var darkR = 0.0; var darkG = 0.0; var darkB = 0.0; var darkCnt = 0
        var minLum = 255.0

        fun add(argb: Int) {
            val r = Color.red(argb)
            val g = Color.green(argb)
            val b = Color.blue(argb)
            val lr = srgbToLin[r]; val lg = srgbToLin[g]; val lb = srgbToLin[b]
            sumR += lr; sumG += lg; sumB += lb; cnt++
            val lum = 0.299 * r + 0.587 * g + 0.114 * b
            if (lum < minLum) minLum = lum
            if (lum < 94.0) {
                darkR += lr; darkG += lg; darkB += lb; darkCnt++
            }
        }

        fun resolveRgb(): Int {
            val avgRgb = linearAvgToRgb(sumR, sumG, sumB, cnt)
            val avgLum = 0.299 * Color.red(avgRgb) + 0.587 * Color.green(avgRgb) + 0.114 * Color.blue(avgRgb)
            if (darkCnt > 0) {
                val darkFrac = darkCnt.toDouble() / max(1, cnt)
                val darkRgb = linearAvgToRgb(darkR, darkG, darkB, darkCnt)
                val darkLum = 0.299 * Color.red(darkRgb) + 0.587 * Color.green(darkRgb) + 0.114 * Color.blue(darkRgb)
                val highContrastTinyPupil = minLum < 72.0 && darkFrac >= 0.14 && (avgLum - darkLum) >= 56.0
                if ((darkFrac >= 0.14 && (avgLum - darkLum) >= 48.0) || highContrastTinyPupil) {
                    if (darkFrac >= 0.22 || highContrastTinyPupil) return darkRgb
                    return Color.rgb(
                        (Color.red(darkRgb) * 0.80 + Color.red(avgRgb) * 0.20).roundToInt(),
                        (Color.green(darkRgb) * 0.80 + Color.green(avgRgb) * 0.20).roundToInt(),
                        (Color.blue(darkRgb) * 0.80 + Color.blue(avgRgb) * 0.20).roundToInt()
                    )
                }
            }
            return avgRgb
        }
    }

    private fun sampleCoverPhoto(
        src: Bitmap,
        tw: Int,
        th: Int,
        suppressGreen: Boolean,
        outRgb: IntArray,
        outMask: BooleanArray
    ) {
        val scale = max(1, min(8, 512 / max(tw, th)))
        val cw = tw * scale
        val ch = th * scale
        val scaled = Bitmap.createBitmap(cw, ch, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(scaled)
        val ratio = max(cw.toFloat() / src.width, ch.toFloat() / src.height)
        val dw = src.width * ratio
        val dh = src.height * ratio
        val left = (cw - dw) / 2f
        val top = (ch - dh) / 2f
        val srcScaled = Bitmap.createScaledBitmap(src, dw.roundToInt().coerceAtLeast(1), dh.roundToInt().coerceAtLeast(1), true)
        canvas.drawColor(Color.WHITE)
        canvas.drawBitmap(srcScaled, left, top, null)
        if (srcScaled !== src) srcScaled.recycle()

        val px = IntArray(cw * ch)
        scaled.getPixels(px, 0, cw, 0, 0, cw, ch)
        scaled.recycle()

        for (r in 0 until th) {
            for (c in 0 until tw) {
                val acc = CellAccumulator()
                for (sy in r * scale until (r + 1) * scale) {
                    for (sx in c * scale until (c + 1) * scale) {
                        var p = px[sy * cw + sx]
                        if (suppressGreen) p = neutralizeGreenCastPixel(p)
                        acc.add(p)
                    }
                }
                val i = r * tw + c
                outMask[i] = true
                outRgb[i] = acc.resolveRgb()
            }
        }
    }

    private fun sampleCutoutSubject(
        src: Bitmap,
        tw: Int,
        th: Int,
        margin: Int,
        suppressGreen: Boolean,
        outRgb: IntArray,
        outMask: BooleanArray
    ) {
        val maxDim = 320f
        val sRatio = min(1f, maxDim / max(src.width, src.height))
        val sw = (src.width * sRatio).roundToInt().coerceAtLeast(16)
        val sh = (src.height * sRatio).roundToInt().coerceAtLeast(16)
        val work = Bitmap.createScaledBitmap(src, sw, sh, true)
        val px = IntArray(sw * sh)
        work.getPixels(px, 0, sw, 0, 0, sw, sh)
        if (work !== src) work.recycle()

        val alphaTransparentRatio = px.count { Color.alpha(it) < 128 }.toFloat() / px.size
        val fg = BooleanArray(sw * sh) { i -> Color.alpha(px[i]) >= 128 }

        if (alphaTransparentRatio < 0.04f) {
            val bgColor = px[0]
            val bgR = Color.red(bgColor)
            val bgG = Color.green(bgColor)
            val bgB = Color.blue(bgColor)
            val visited = BooleanArray(sw * sh)
            val queue = ArrayDeque<Int>()
            for (seed in intArrayOf(0, sw - 1, (sh - 1) * sw, sh * sw - 1)) {
                visited[seed] = true
                queue.addLast(seed)
            }
            val threshSq = 32 * 32 * 3
            while (queue.isNotEmpty()) {
                val cur = queue.removeFirst()
                val col = px[cur]
                val dr = Color.red(col) - bgR
                val dg = Color.green(col) - bgG
                val db = Color.blue(col) - bgB
                if (dr * dr + dg * dg + db * db <= threshSq) {
                    fg[cur] = false
                    val r = cur / sw
                    val c = cur % sw
                    if (r > 0 && !visited[cur - sw]) { visited[cur - sw] = true; queue.addLast(cur - sw) }
                    if (r + 1 < sh && !visited[cur + sw]) { visited[cur + sw] = true; queue.addLast(cur + sw) }
                    if (c > 0 && !visited[cur - 1]) { visited[cur - 1] = true; queue.addLast(cur - 1) }
                    if (c + 1 < sw && !visited[cur + 1]) { visited[cur + 1] = true; queue.addLast(cur + 1) }
                }
            }
        }

        var minX = sw; var maxX = 0; var minY = sh; var maxY = 0
        for (r in 0 until sh) {
            for (c in 0 until sw) {
                if (fg[r * sw + c]) {
                    if (c < minX) minX = c
                    if (c > maxX) maxX = c
                    if (r < minY) minY = r
                    if (r > maxY) maxY = r
                }
            }
        }
        if (maxX < minX) {
            sampleCoverPhoto(src, tw, th, suppressGreen, outRgb, outMask)
            return
        }

        val boxW = (maxX - minX + 1).toFloat()
        val boxH = (maxY - minY + 1).toFloat()
        val innerW = max(1, tw - margin * 2).toFloat()
        val innerH = max(1, th - margin * 2).toFloat()
        val fitScale = min(innerW / boxW, innerH / boxH)
        val drawW = boxW * fitScale
        val drawH = boxH * fitScale
        val offX = (tw - drawW) / 2f
        val offY = (th - drawH) / 2f

        for (r in 0 until th) {
            for (c in 0 until tw) {
                val srcX0 = ((c - offX) / fitScale + minX).roundToInt()
                val srcX1 = ((c + 1f - offX) / fitScale + minX).roundToInt().coerceAtLeast(srcX0 + 1)
                val srcY0 = ((r - offY) / fitScale + minY).roundToInt()
                val srcY1 = ((r + 1f - offY) / fitScale + minY).roundToInt().coerceAtLeast(srcY0 + 1)
                val acc = CellAccumulator()
                var totalCnt = 0
                for (sy in max(0, srcY0) until min(sh, srcY1)) {
                    for (sx in max(0, srcX0) until min(sw, srcX1)) {
                        totalCnt++
                        val idx = sy * sw + sx
                        if (fg[idx]) {
                            var p = px[idx]
                            if (suppressGreen) p = neutralizeGreenCastPixel(p)
                            acc.add(p)
                        }
                    }
                }
                val cellIdx = r * tw + c
                if (totalCnt > 0 && acc.cnt.toFloat() / totalCnt >= 0.42f) {
                    outMask[cellIdx] = true
                    outRgb[cellIdx] = acc.resolveRgb()
                }
            }
        }
    }

    private fun reduceToColorCap(
        palIdx: IntArray,
        mask: BooleanArray,
        pal: List<PaletteColor>,
        targetColors: Int,
        protectedCodes: Set<String>
    ) {
        while (true) {
            val counts = HashMap<Int, Int>()
            for (i in palIdx.indices) {
                if (mask[i]) counts[palIdx[i]] = (counts[palIdx[i]] ?: 0) + 1
            }
            if (counts.size <= targetColors) break

            val present = counts.keys.toList()
            var bestSrc = -1
            var bestDst = -1
            var bestCost = Double.MAX_VALUE

            for (pass in 0..1) {
                for (src in present) {
                    if (pass == 0 && pal[src].code in protectedCodes) continue
                    val e1 = pal[src]
                    val cSrc = counts[src] ?: 0
                    for (dst in present) {
                        if (dst == src) continue
                        val e2 = pal[dst]
                        val de = PaletteRepository.labDist(e1.labL, e1.labA, e1.labB, e2.labL, e2.labA, e2.labB)
                        val cost = cSrc * de.pow(1.4)
                        if (cost < bestCost) {
                            bestCost = cost
                            bestSrc = src
                            bestDst = dst
                        }
                    }
                }
                if (bestSrc != -1) break
            }
            if (bestSrc == -1) break
            for (i in palIdx.indices) {
                if (mask[i] && palIdx[i] == bestSrc) palIdx[i] = bestDst
            }
        }
    }
}
