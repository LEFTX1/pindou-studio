package com.pindoustudio.app.engine

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import com.pindoustudio.app.data.PaletteRepository
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.ConvertMode
import com.pindoustudio.app.model.PaletteColor
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sqrt

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

        // 1) 对成对确认的双眼执行「尺寸、形状与色度强对称等大校准」（杜绝出现 3×3 十字纽扣眼）
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
            val avgBh = ((left.bh + right.bh) / 2.0).roundToInt()
            val avgBw = ((left.bw + right.bw) / 2.0).roundToInt()
            if (maxArea <= 6 || avgBh <= 3 || avgBw <= 3) {
                // 小/中格实拍图：使用 1×1 圆点或 2×2 饱满方块瞳孔（配合柔和自然过渡，彻底告别十字纽扣形状）
                val th: Int
                val tw: Int
                if (dx <= 5.2 || maxArea <= 2) {
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
                // 大圆眼（>=4×4）：统一规范饱满椭圆模板 + 四角柔和抗锯齿 + 眼神光
                val targetH = max(4, avgBh)
                val targetW = max(4, avgBw)
                val sameRow = abs(left.cy - right.cy) <= 1.15
                val sharedCy = if (sameRow) (left.cy + right.cy) / 2.0 else left.cy
                stampCanonicalLargeEye(gridCodes, mask, lumGrid, paletteRepo, subPal, usedCodes, w, h, left, targetH, targetW, sharedCy, sharedDarkCode)
                stampCanonicalLargeEye(gridCodes, mask, lumGrid, paletteRepo, subPal, usedCodes, w, h, right, targetH, targetW, if (sameRow) sharedCy else right.cy, sharedDarkCode)
            }
        }

        // 2) 未成对的孤立大圆特征（如大特写侧脸单眼 >= 4×4）才做椭圆柔和化；<=3×3 保留自然采样抗锯齿，绝不强制切成「十字」
        for ((cid, feat) in candidates.withIndex()) {
            if (cid in pairedUsed) continue
            if (feat.bh < 4 || feat.bw < 4) continue
            val darkEntry = paletteRepo.findByMardCode(feat.darkCode) ?: continue

            val ry = max(1.0, feat.bh / 2.0)
            val rx = max(1.0, feat.bw / 2.0)
            val coreSet = HashSet<Int>()
            for (rr in feat.r0..feat.r1) {
                for (cc in feat.c0..feat.c1) {
                    val pos = rr * w + cc
                    if (!mask[pos]) continue
                    val d2 = ((rr - feat.cy) / ry).pow(2) + ((cc - feat.cx) / rx).pow(2)
                    if (d2 <= 0.96) coreSet.add(pos)
                }
            }
            if (coreSet.isEmpty()) continue

            val preservedBright = feat.bright.filter { it in coreSet }.toHashSet()
            for (pos in coreSet) {
                if (pos !in preservedBright) gridCodes[pos] = feat.darkCode
            }

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
                    if (coreOrtho >= 2 || (isCorner && pos in feat.comp && coreOrtho >= 1)) {
                        val aaCode = pickNearestCode(
                            (0.32 * darkEntry.r + 0.68 * feat.avgBgR).roundToInt(),
                            (0.32 * darkEntry.g + 0.68 * feat.avgBgG).roundToInt(),
                            (0.32 * darkEntry.b + 0.68 * feat.avgBgB).roundToInt(),
                            subPal,
                            usedCodes
                        )
                        gridCodes[pos] = aaCode
                        usedCodes.add(aaCode)
                    } else if (pos in feat.comp && lumGrid[pos] < 95.0) {
                        gridCodes[pos] = feat.domBgCode
                    }
                }
            }

            if (cid in confirmedEyes && (preservedBright.isNotEmpty() || coreSet.size >= 10)) {
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
                val d2 = ((rr - cy) / ry).pow(2) + ((cc - cx) / rx).pow(2)
                if (d2 <= 0.96) coreSet.add(pos)
            }
        }
        for (pos in coreSet) gridCodes[pos] = darkCode

        val darkEntry = paletteRepo.findByMardCode(darkCode)
        if (targetH >= 4 && targetW >= 4 && darkEntry != null) {
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
                if (darkFrac >= 0.18 && (avgLum - darkLum) >= 48.0) {
                    // 仅当深瞳像素在格子中占比足够高 (>=0.38) 才完全锁定纯黑瞳孔；
                    // 占比 0.18~0.37 的眼周轮廓格保留柔和混色过渡，避免膨大后变成突兀十字形状
                    if (darkFrac >= 0.38 || (minLum < 68.0 && darkFrac >= 0.28 && (avgLum - darkLum) >= 58.0)) {
                        return darkRgb
                    }
                    val darkWeight = (0.45 + 0.45 * ((darkFrac - 0.18) / 0.20)).coerceIn(0.45, 0.90)
                    return Color.rgb(
                        (Color.red(darkRgb) * darkWeight + Color.red(avgRgb) * (1.0 - darkWeight)).roundToInt(),
                        (Color.green(darkRgb) * darkWeight + Color.green(avgRgb) * (1.0 - darkWeight)).roundToInt(),
                        (Color.blue(darkRgb) * darkWeight + Color.blue(avgRgb) * (1.0 - darkWeight)).roundToInt()
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
        val maxDim = 200f
        val sRatio = min(1f, maxDim / max(src.width, src.height))
        val sw = (src.width * sRatio).roundToInt().coerceAtLeast(16)
        val sh = (src.height * sRatio).roundToInt().coerceAtLeast(16)
        val work = Bitmap.createScaledBitmap(src, sw, sh, true)
        val px = IntArray(sw * sh)
        work.getPixels(px, 0, sw, 0, 0, sw, sh)
        if (work !== src) work.recycle()

        val fg = segmentCutoutForeground(px, sw, sh)

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

    /**
     * 三模态纯离线前景抠图：
     * 1) 透明底 PNG 直接走 Alpha 通道；
     * 2) 极纯色插画/贴纸背景走边缘统一色阈值漫水填充；
     * 3) 实拍照片走边界色彩聚类的边沿梯度+纹理测地线扩散，并联合地砖细线开运算剥离
     *    及多轴凹陷桥接（修复猫颈/耳根因阴影反光与背景相近而被斜向切割的问题）。
     */
    private fun segmentCutoutForeground(px: IntArray, sw: Int, sh: Int): BooleanArray {
        val n = sw * sh
        var transparentCnt = 0
        for (i in 0 until n) {
            if (Color.alpha(px[i]) < 128) transparentCnt++
        }
        val fg = BooleanArray(n) { i -> Color.alpha(px[i]) >= 128 }
        if (transparentCnt.toFloat() / n >= 0.04f) {
            return fg
        }

        // 计算原始与 5x5 高斯平滑 CIE Lab（抑制地板缝隙与高频噪点，避免毛发过糊）
        val rawR = FloatArray(n)
        val rawG = FloatArray(n)
        val rawB = FloatArray(n)
        val labRawL = FloatArray(n)
        val labRawA = FloatArray(n)
        val labRawB = FloatArray(n)
        for (i in 0 until n) {
            val col = px[i]
            val r = Color.red(col)
            val g = Color.green(col)
            val b = Color.blue(col)
            rawR[i] = r.toFloat()
            rawG[i] = g.toFloat()
            rawB[i] = b.toFloat()
            val lab = PaletteRepository.rgbToLab(r, g, b)
            labRawL[i] = lab[0].toFloat()
            labRawA[i] = lab[1].toFloat()
            labRawB[i] = lab[2].toFloat()
        }

        val smR = gaussianSmooth5(rawR, sw, sh)
        val smG = gaussianSmooth5(rawG, sw, sh)
        val smB = gaussianSmooth5(rawB, sw, sh)
        val labL = FloatArray(n)
        val labA = FloatArray(n)
        val labB = FloatArray(n)
        for (i in 0 until n) {
            val lab = PaletteRepository.rgbToLab(
                smR[i].roundToInt().coerceIn(0, 255),
                smG[i].roundToInt().coerceIn(0, 255),
                smB[i].roundToInt().coerceIn(0, 255)
            )
            labL[i] = lab[0].toFloat()
            labA[i] = lab[1].toFloat()
            labB[i] = lab[2].toFloat()
        }

        // 边界环带采样
        val bw = max(2, min(sw, sh) / 40)
        val borderIdxList = IntArray(n)
        var bCount = 0
        for (r in 0 until sh) {
            for (c in 0 until sw) {
                if (r < bw || r >= sh - bw || c < bw || c >= sw - bw) {
                    borderIdxList[bCount++] = r * sw + c
                }
            }
        }
        val borderIndices = borderIdxList.copyOf(bCount)

        // Mode 2: 边界单色均匀性检测（插画/贴纸等纯白或纯色底）
        val bL = FloatArray(bCount) { labL[borderIndices[it]] }
        val bA = FloatArray(bCount) { labA[borderIndices[it]] }
        val bB = FloatArray(bCount) { labB[borderIndices[it]] }
        val medL = percentileFloat(bL, 0.50f)
        val medA = percentileFloat(bA, 0.50f)
        val medB = percentileFloat(bB, 0.50f)
        val singleDists = FloatArray(bCount) { k ->
            val dl = bL[k] - medL
            val da = bA[k] - medA
            val db = bB[k] - medB
            sqrt(dl * dl + da * da + db * db)
        }
        val singleP50 = percentileFloat(singleDists, 0.50f)
        val singleP85 = percentileFloat(singleDists, 0.85f)

        if (singleP85 < 4.5f && singleP50 < 2.2f) {
            val thresh = max(8.0f, singleP85 * 2.2f + 4.0f)
            val bg = BooleanArray(n)
            val q = IntArray(n)
            var qHead = 0
            var qTail = 0
            fun trySeed(idx: Int) {
                if (bg[idx]) return
                val dl = labRawL[idx] - medL
                val da = labRawA[idx] - medA
                val db = labRawB[idx] - medB
                if (dl * dl + da * da + db * db <= thresh * thresh) {
                    bg[idx] = true
                    q[qTail++] = idx
                }
            }
            for (r in 0 until sh) {
                trySeed(r * sw)
                trySeed(r * sw + sw - 1)
            }
            for (c in 0 until sw) {
                trySeed(c)
                trySeed((sh - 1) * sw + c)
            }
            while (qHead < qTail) {
                val cur = q[qHead++]
                val cr = cur / sw
                val cc = cur % sw
                if (cr > 0) trySeed(cur - sw)
                if (cr + 1 < sh) trySeed(cur + sw)
                if (cc > 0) trySeed(cur - 1)
                if (cc + 1 < sw) trySeed(cur + 1)
            }
            val flatFg = BooleanArray(n) { !bg[it] }
            fillInteriorHoles(flatFg, sw, sh)
            keepMainComponents(flatFg, sw, sh, minAbs = 16, minFrac = 0.03f)
            return flatFg
        }

        // Mode 3: 边界多簇色彩建模（保留主簇与同色系受光照变化影响的背景簇）
        val clusters = kmeansLabClusters(bL, bA, bB, maxK = 4, iters = 8)
        val primary = clusters[0]
        val domClusters = ArrayList<FloatArray>(3)
        domClusters.add(primary)
        for (k in 1 until clusters.size) {
            if (domClusters.size >= 3) break
            val cl = clusters[k]
            val chromaD = hypot(cl[1] - primary[1], cl[2] - primary[2])
            val fullD = sqrt(
                (cl[0] - primary[0]) * (cl[0] - primary[0]) +
                    (cl[1] - primary[1]) * (cl[1] - primary[1]) +
                    (cl[2] - primary[2]) * (cl[2] - primary[2])
            )
            if (chromaD <= 18.0f && fullD <= 32.0f) {
                domClusters.add(cl)
            }
        }

        // 对色度 (a, b) 加权 1.35，有助于区分暖色地砖与冷灰白猫颈部阴影
        val dBg = FloatArray(n)
        for (i in 0 until n) {
            val l = labL[i]
            val a = labA[i]
            val b = labB[i]
            var best = Float.MAX_VALUE
            for (cl in domClusters) {
                val dl = l - cl[0]
                val da = (a - cl[1]) * 1.35f
                val db = (b - cl[2]) * 1.35f
                val d = sqrt(dl * dl + da * da + db * db)
                if (d < best) best = d
            }
            dBg[i] = best
        }

        val borderDbg = FloatArray(bCount) { dBg[borderIndices[it]] }
        val borderP70 = percentileFloat(borderDbg, 0.70f)
        val borderP85 = percentileFloat(borderDbg, 0.85f)

        val y0 = (sh * 0.25f).toInt()
        val y1 = (sh * 0.75f).toInt()
        val x0 = (sw * 0.25f).toInt()
        val x1 = (sw * 0.75f).toInt()
        val centerThresh = max(12.0f, borderP70 * 1.4f)
        var centerTotal = 0
        var centerFg = 0
        for (r in y0 until y1) {
            for (c in x0 until x1) {
                centerTotal++
                if (dBg[r * sw + c] > centerThresh) centerFg++
            }
        }
        val centerFgRatio = if (centerTotal > 0) centerFg.toFloat() / centerTotal else 1f

        // 满幅特写保护：若主体充满四边，保留整图避免撕裂面部
        if (borderP70 > 13.0f || centerFgRatio < 0.22f) {
            val fullFg = BooleanArray(n) { true }
            return fullFg
        }

        // 测地线最短路径开销场（梯度屏障 + 局部毛发纹理 + 中心保护）
        val stepCost = FloatArray(n)
        val baseTol = (borderP70 * 1.35f + 3.0f).coerceIn(7.0f, 14.0f)
        val halfW = sw * 0.5f
        val halfH = sh * 0.5f
        for (r in 0 until sh) {
            for (c in 0 until sw) {
                val i = r * sw + c
                val gxL = if (c in 1 until sw - 1) (labL[i + 1] - labL[i - 1]) * 0.5f else 0f
                val gxA = if (c in 1 until sw - 1) (labA[i + 1] - labA[i - 1]) * 0.5f else 0f
                val gxB = if (c in 1 until sw - 1) (labB[i + 1] - labB[i - 1]) * 0.5f else 0f
                val gyL = if (r in 1 until sh - 1) (labL[i + sw] - labL[i - sw]) * 0.5f else 0f
                val gyA = if (r in 1 until sh - 1) (labA[i + sw] - labA[i - sw]) * 0.5f else 0f
                val gyB = if (r in 1 until sh - 1) (labB[i + sw] - labB[i - sw]) * 0.5f else 0f
                val gx = sqrt(gxL * gxL + gxA * gxA + gxB * gxB)
                val gy = sqrt(gyL * gyL + gyA * gyA + gyB * gyB)
                val grad = hypot(gx, gy)

                val tL = labRawL[i] - labL[i]
                val tA = labRawA[i] - labA[i]
                val tB = labRawB[i] - labB[i]
                val tex = sqrt(tL * tL + tA * tA + tB * tB)

                val rad = hypot((c - halfW) / halfW, (r - halfH) / halfH)
                val centerW = (1.0f - rad).coerceIn(0f, 1f)
                val excess = max(0f, dBg[i] - baseTol)
                stepCost[i] = 0.14f +
                    excess * 1.45f +
                    max(0f, grad - 3.5f) * 1.30f +
                    max(0f, tex - 2.8f) * 0.80f +
                    centerW * 0.50f
            }
        }

        val dist = FloatArray(n) { 1e9f }
        val heapIdx = IntArray(n * 4 + 16)
        val heapDist = FloatArray(n * 4 + 16)
        var heapSize = 0
        fun heapPush(idx: Int, d: Float) {
            var pos = ++heapSize
            if (pos >= heapIdx.size) return
            heapIdx[pos] = idx
            heapDist[pos] = d
            while (pos > 1) {
                val parent = pos ushr 1
                if (heapDist[parent] <= heapDist[pos]) break
                val ti = heapIdx[parent]; val td = heapDist[parent]
                heapIdx[parent] = heapIdx[pos]; heapDist[parent] = heapDist[pos]
                heapIdx[pos] = ti; heapDist[pos] = td
                pos = parent
            }
        }
        fun heapPop(): Int {
            val top = heapIdx[1]
            heapIdx[1] = heapIdx[heapSize]
            heapDist[1] = heapDist[heapSize]
            heapSize--
            var pos = 1
            while (true) {
                val left = pos shl 1
                if (left > heapSize) break
                val right = left + 1
                val smallest = if (right <= heapSize && heapDist[right] < heapDist[left]) right else left
                if (heapDist[pos] <= heapDist[smallest]) break
                val ti = heapIdx[pos]; val td = heapDist[pos]
                heapIdx[pos] = heapIdx[smallest]; heapDist[pos] = heapDist[smallest]
                heapIdx[smallest] = ti; heapDist[smallest] = td
                pos = smallest
            }
            return top
        }

        val seedTol = max(11.0f, borderP85 * 1.30f + 3.0f)
        for (r in 0 until sh) {
            val leftIdx = r * sw
            if (dBg[leftIdx] <= seedTol && dist[leftIdx] > 0f) {
                dist[leftIdx] = 0f
                heapPush(leftIdx, 0f)
            }
            val rightIdx = r * sw + sw - 1
            if (dBg[rightIdx] <= seedTol && dist[rightIdx] > 0f) {
                dist[rightIdx] = 0f
                heapPush(rightIdx, 0f)
            }
        }
        for (c in 0 until sw) {
            if (dBg[c] <= seedTol && dist[c] > 0f) {
                dist[c] = 0f
                heapPush(c, 0f)
            }
            val botIdx = (sh - 1) * sw + c
            if (dBg[botIdx] <= seedTol && dist[botIdx] > 0f) {
                dist[botIdx] = 0f
                heapPush(botIdx, 0f)
            }
        }

        while (heapSize > 0) {
            val d = heapDist[1]
            val cur = heapPop()
            if (d > dist[cur] + 1e-4f) continue
            if (d > 65.0f) break
            val cr = cur / sw
            val cc = cur % sw
            val l0 = labL[cur]; val a0 = labA[cur]; val b0 = labB[cur]
            fun relax(nr: Int, nc: Int) {
                val ni = nr * sw + nc
                val dl = labL[ni] - l0
                val da = labA[ni] - a0
                val db = labB[ni] - b0
                val stepLab = sqrt(dl * dl + da * da + db * db)
                val nd = d + stepCost[ni] + max(0f, stepLab - 4.0f) * 1.5f
                if (nd < dist[ni]) {
                    dist[ni] = nd
                    heapPush(ni, nd)
                }
            }
            if (cr > 0) relax(cr - 1, cc)
            if (cr + 1 < sh) relax(cr + 1, cc)
            if (cc > 0) relax(cr, cc - 1)
            if (cc + 1 < sw) relax(cr, cc + 1)
        }

        var photoFg = BooleanArray(n) { dist[it] > 38.0f }

        // 先做开运算去除地砖细缝毛刺（r=2 保护猫耳尖）
        photoFg = morphErode8(photoFg, sw, sh, 2)
        photoFg = morphDilate8(photoFg, sw, sh, 2)
        // 先保留所有中小连通域（包含可能暂时分离的头部/耳朵），再执行凹陷桥接！
        keepMainComponents(photoFg, sw, sh, minAbs = 16, minFrac = 0.015f)

        // 两轮多轴凹陷桥接，将阴影脖颈与身体无缝缝合
        photoFg = healConcaveBays(photoFg, sw, sh, maxSpanFrac = 0.22f, minAxes = 2)
        photoFg = healConcaveBays(photoFg, sw, sh, maxSpanFrac = 0.20f, minAxes = 2)

        // 闭运算平滑外轮廓 + 填洞 + 最终保留主连通轮廓
        photoFg = morphDilate8(photoFg, sw, sh, 4)
        photoFg = morphErode8(photoFg, sw, sh, 4)
        fillInteriorHoles(photoFg, sw, sh)
        keepMainComponents(photoFg, sw, sh, minAbs = 30, minFrac = 0.10f)

        var fgSum = 0
        for (b in photoFg) if (b) fgSum++
        if (fgSum < (n * 0.12f).toInt()) {
            photoFg.fill(true)
        }
        return photoFg
    }

    private fun gaussianSmooth5(src: FloatArray, w: Int, h: Int): FloatArray {
        val k0 = 1f / 16f
        val k1 = 4f / 16f
        val k2 = 6f / 16f
        val tmp = FloatArray(w * h)
        for (r in 0 until h) {
            val row = r * w
            for (c in 0 until w) {
                val cL2 = src[row + (c - 2).coerceIn(0, w - 1)]
                val cL1 = src[row + (c - 1).coerceIn(0, w - 1)]
                val c0 = src[row + c]
                val cR1 = src[row + (c + 1).coerceIn(0, w - 1)]
                val cR2 = src[row + (c + 2).coerceIn(0, w - 1)]
                tmp[row + c] = (cL2 + cR2) * k0 + (cL1 + cR1) * k1 + c0 * k2
            }
        }
        val out = FloatArray(w * h)
        for (r in 0 until h) {
            val rU2 = (r - 2).coerceIn(0, h - 1) * w
            val rU1 = (r - 1).coerceIn(0, h - 1) * w
            val r0 = r * w
            val rD1 = (r + 1).coerceIn(0, h - 1) * w
            val rD2 = (r + 2).coerceIn(0, h - 1) * w
            for (c in 0 until w) {
                out[r0 + c] = (tmp[rU2 + c] + tmp[rD2 + c]) * k0 +
                    (tmp[rU1 + c] + tmp[rD1 + c]) * k1 +
                    tmp[r0 + c] * k2
            }
        }
        return out
    }

    private fun percentileFloat(vals: FloatArray, frac: Float): Float {
        if (vals.isEmpty()) return 0f
        val copy = vals.copyOf()
        copy.sort()
        val idx = ((copy.size - 1) * frac).roundToInt().coerceIn(0, copy.size - 1)
        return copy[idx]
    }

    private fun kmeansLabClusters(
        ptsL: FloatArray,
        ptsA: FloatArray,
        ptsB: FloatArray,
        maxK: Int,
        iters: Int
    ): List<FloatArray> {
        val n = ptsL.size
        if (n == 0) return listOf(floatArrayOf(50f, 0f, 0f))
        val k = min(maxK, n)
        val cL = FloatArray(k)
        val cA = FloatArray(k)
        val cB = FloatArray(k)
        val step = max(1, n / k)
        for (j in 0 until k) {
            val idx = min(n - 1, j * step)
            cL[j] = ptsL[idx]; cA[j] = ptsA[idx]; cB[j] = ptsB[idx]
        }
        val lbl = IntArray(n)
        val sumL = FloatArray(k)
        val sumA = FloatArray(k)
        val sumB = FloatArray(k)
        val cnt = IntArray(k)
        repeat(iters) {
            sumL.fill(0f); sumA.fill(0f); sumB.fill(0f); cnt.fill(0)
            for (i in 0 until n) {
                val l = ptsL[i]; val a = ptsA[i]; val b = ptsB[i]
                var bestJ = 0
                var bestD = Float.MAX_VALUE
                for (j in 0 until k) {
                    val dl = l - cL[j]; val da = a - cA[j]; val db = b - cB[j]
                    val d = dl * dl + da * da + db * db
                    if (d < bestD) { bestD = d; bestJ = j }
                }
                lbl[i] = bestJ
                sumL[bestJ] += l; sumA[bestJ] += a; sumB[bestJ] += b; cnt[bestJ]++
            }
            for (j in 0 until k) {
                if (cnt[j] > 0) {
                    cL[j] = sumL[j] / cnt[j]
                    cA[j] = sumA[j] / cnt[j]
                    cB[j] = sumB[j] / cnt[j]
                }
            }
        }
        cnt.fill(0)
        for (i in 0 until n) {
            val l = ptsL[i]; val a = ptsA[i]; val b = ptsB[i]
            var bestJ = 0
            var bestD = Float.MAX_VALUE
            for (j in 0 until k) {
                val dl = l - cL[j]; val da = a - cA[j]; val db = b - cB[j]
                val d = dl * dl + da * da + db * db
                if (d < bestD) { bestD = d; bestJ = j }
            }
            cnt[bestJ]++
        }
        val indexed = (0 until k)
            .filter { cnt[it].toFloat() / n >= 0.05f }
            .sortedByDescending { cnt[it] }
        if (indexed.isEmpty()) {
            val top = (0 until k).maxBy { cnt[it] }
            return listOf(floatArrayOf(cL[top], cA[top], cB[top]))
        }
        return indexed.map { floatArrayOf(cL[it], cA[it], cB[it]) }
    }

    private fun morphErode8(mask: BooleanArray, w: Int, h: Int, radius: Int): BooleanArray {
        var cur = mask.copyOf()
        repeat(radius) {
            val next = BooleanArray(w * h)
            for (r in 1 until h - 1) {
                val row = r * w
                for (c in 1 until w - 1) {
                    val i = row + c
                    if (cur[i - w - 1] && cur[i - w] && cur[i - w + 1] &&
                        cur[i - 1] && cur[i] && cur[i + 1] &&
                        cur[i + w - 1] && cur[i + w] && cur[i + w + 1]
                    ) {
                        next[i] = true
                    }
                }
            }
            cur = next
        }
        return cur
    }

    private fun morphDilate8(mask: BooleanArray, w: Int, h: Int, radius: Int): BooleanArray {
        var cur = mask.copyOf()
        repeat(radius) {
            val next = BooleanArray(w * h)
            for (r in 0 until h) {
                for (c in 0 until w) {
                    var any = false
                    for (dr in -1..1) {
                        val nr = r + dr
                        if (nr !in 0 until h) continue
                        val nRow = nr * w
                        for (dc in -1..1) {
                            val nc = c + dc
                            if (nc in 0 until w && cur[nRow + nc]) {
                                any = true; break
                            }
                        }
                        if (any) break
                    }
                    next[r * w + c] = any
                }
            }
            cur = next
        }
        return cur
    }

    private fun fillInteriorHoles(fg: BooleanArray, w: Int, h: Int) {
        val n = w * h
        val ext = BooleanArray(n)
        val q = IntArray(n)
        var head = 0
        var tail = 0
        fun tryExt(idx: Int) {
            if (!fg[idx] && !ext[idx]) {
                ext[idx] = true
                q[tail++] = idx
            }
        }
        for (c in 0 until w) {
            tryExt(c)
            tryExt((h - 1) * w + c)
        }
        for (r in 0 until h) {
            tryExt(r * w)
            tryExt(r * w + w - 1)
        }
        while (head < tail) {
            val cur = q[head++]
            val cr = cur / w
            val cc = cur % w
            if (cr > 0) tryExt(cur - w)
            if (cr + 1 < h) tryExt(cur + w)
            if (cc > 0) tryExt(cur - 1)
            if (cc + 1 < w) tryExt(cur + 1)
        }
        for (i in 0 until n) {
            if (!ext[i]) fg[i] = true
        }
    }

    private fun keepMainComponents(fg: BooleanArray, w: Int, h: Int, minAbs: Int, minFrac: Float) {
        val n = w * h
        val visited = BooleanArray(n)
        val compSizes = ArrayList<IntArray>()
        val q = IntArray(n)
        for (i in 0 until n) {
            if (!fg[i] || visited[i]) continue
            var head = 0
            var tail = 0
            visited[i] = true
            q[tail++] = i
            while (head < tail) {
                val cur = q[head++]
                val cr = cur / w; val cc = cur % w
                if (cr > 0 && fg[cur - w] && !visited[cur - w]) { visited[cur - w] = true; q[tail++] = cur - w }
                if (cr + 1 < h && fg[cur + w] && !visited[cur + w]) { visited[cur + w] = true; q[tail++] = cur + w }
                if (cc > 0 && fg[cur - 1] && !visited[cur - 1]) { visited[cur - 1] = true; q[tail++] = cur - 1 }
                if (cc + 1 < w && fg[cur + 1] && !visited[cur + 1]) { visited[cur + 1] = true; q[tail++] = cur + 1 }
            }
            compSizes.add(q.copyOf(tail))
        }
        if (compSizes.isEmpty()) return
        var maxSz = 0
        for (comp in compSizes) if (comp.size > maxSz) maxSz = comp.size
        val thresh = max(minAbs, (maxSz * minFrac).toInt())
        fg.fill(false)
        for (comp in compSizes) {
            if (comp.size >= thresh) {
                for (p in comp) fg[p] = true
            }
        }
    }

    /**
     * 沿 4 组对向轴（水平、垂直、正斜、反斜）计算 O(W*H) 有向距离，
     * 凡在 >= minAxes 条轴上两侧均为前景且总跨度 <= maxSpanFrac * max(W, H) 的背景凹槽，判定为被主体半包围的阴影（如猫颈、耳窝），予以桥接闭合。
     */
    private fun healConcaveBays(
        fg: BooleanArray,
        w: Int,
        h: Int,
        maxSpanFrac: Float,
        minAxes: Int
    ): BooleanArray {
        val n = w * h
        val inf = 99999
        val maxSpan = max(10, (max(w, h) * maxSpanFrac).roundToInt())
        val axes = arrayOf(
            intArrayOf(0, -1, 0, 1),
            intArrayOf(-1, 0, 1, 0),
            intArrayOf(-1, -1, 1, 1),
            intArrayOf(-1, 1, 1, -1)
        )
        fun distInDir(dr: Int, dc: Int): IntArray {
            val d = IntArray(n) { inf }
            val rRange = if (dr <= 0) (0 until h) else (h - 1 downTo 0)
            val cRange = if (dc <= 0) (0 until w) else (w - 1 downTo 0)
            for (r in rRange) {
                for (c in cRange) {
                    val i = r * w + c
                    if (fg[i]) {
                        d[i] = 0
                    } else {
                        val pr = r + dr
                        val pc = c + dc
                        if (pr in 0 until h && pc in 0 until w) {
                            val pd = d[pr * w + pc]
                            if (pd < inf) d[i] = pd + 1
                        }
                    }
                }
            }
            return d
        }
        val enclosed = IntArray(n)
        for (ax in axes) {
            val d1 = distInDir(ax[0], ax[1])
            val d2 = distInDir(ax[2], ax[3])
            val limit = if (ax[0] != 0 && ax[1] != 0) (maxSpan / 1.414f).toInt() else maxSpan
            for (i in 0 until n) {
                if (!fg[i] && d1[i] < inf && d2[i] < inf && d1[i] + d2[i] <= limit) {
                    enclosed[i]++
                }
            }
        }
        return BooleanArray(n) { i -> fg[i] || enclosed[i] >= minAxes }
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
