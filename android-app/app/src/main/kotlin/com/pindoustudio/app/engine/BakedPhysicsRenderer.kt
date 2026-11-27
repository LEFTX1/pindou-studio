package com.pindoustudio.app.engine

import android.graphics.Bitmap
import android.graphics.Color
import com.pindoustudio.app.data.PaletteRepository
import com.pindoustudio.app.model.BeadPattern
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * 物理级真实热熨成品光学渲染器：
 * - 模拟真实 2.6mm 拼豆在烘焙油纸下熨烫熔合后的自然质感：
 *   1. 同色邻接塑料无缝融合（消除假棋盘格线），仅在异色交界保留温和熔痕与有机波纹变形；
 *   2. 区域平滑热压场 + 约74%融平闭孔，微孔仅做材质随色半透浅凹陷（拒绝假黑点）；
 *   3. 蜡质次表面融色浸润 + 斜向油纸缎面高光 + 连续 3D 外沿厚度与柔和桌面接触投影。
 */
object BakedPhysicsRenderer {

    fun render(
        pattern: BeadPattern,
        paletteRepo: PaletteRepository,
        maxCanvasPx: Int = 680
    ): Bitmap {
        val w = pattern.width.coerceAtLeast(1)
        val h = pattern.height.coerceAtLeast(1)
        val cellPx = (maxCanvasPx / max(w, h)).coerceIn(6, 24)
        val pad = max(32, (min(w, h) * cellPx * 0.14f).roundToInt())
        val cw = w * cellPx + pad * 2
        val ch = h * cellPx + pad * 2
        val nPix = cw * ch

        val pieceMask = BooleanArray(nPix)
        val colR = FloatArray(nPix)
        val colG = FloatArray(nPix)
        val colB = FloatArray(nPix)
        val heightMap = FloatArray(nPix)
        val seamMap = FloatArray(nPix)
        val holeShade = FloatArray(nPix)

        val cellCodes = Array(w * h) { idx ->
            val code = pattern.get(idx / w, idx % w)
            if (paletteRepo.findByMardCode(code) != null) code else null
        }

        for (r in 0 until h) {
            for (c in 0 until w) {
                val code = cellCodes[r * w + c] ?: continue
                val entry = paletteRepo.findByMardCode(code) ?: continue

                val topCode = if (r > 0) cellCodes[(r - 1) * w + c] else null
                val botCode = if (r + 1 < h) cellCodes[(r + 1) * w + c] else null
                val leftCode = if (c > 0) cellCodes[r * w + (c - 1)] else null
                val rightCode = if (c + 1 < w) cellCodes[r * w + (c + 1)] else null

                val hasTop = topCode != null
                val hasBot = botCode != null
                val hasLeft = leftCode != null
                val hasRight = rightCode != null
                val adj = (if (hasTop) 1 else 0) + (if (hasBot) 1 else 0) + (if (hasLeft) 1 else 0) + (if (hasRight) 1 else 0)

                // 同色豆子受热几乎完全融合无黑缝；异色接壤或外边才呈现柔和熔缝
                val diffTop = if (hasTop && topCode != code) 1.0f else 0.12f
                val diffBot = if (hasBot && botCode != code) 1.0f else 0.12f
                val diffLeft = if (hasLeft && leftCode != code) 1.0f else 0.12f
                val diffRight = if (hasRight && rightCode != code) 1.0f else 0.12f

                val seed = (r * 73856093) xor (c * 19349663) xor 0x5f3759df
                val jx = (hashUnit(seed, 1) - 0.5f) * 0.95f
                val jy = (hashUnit(seed, 2) - 0.5f) * 0.95f
                val br = (entry.r + (hashUnit(seed, 3) - 0.5f) * 3.8f).coerceIn(0f, 255f)
                val bg = (entry.g + (hashUnit(seed, 4) - 0.5f) * 3.8f).coerceIn(0f, 255f)
                val bb = (entry.b + (hashUnit(seed, 5) - 0.5f) * 3.8f).coerceIn(0f, 255f)

                // 连续热压分布场：部分区域压得更平全封闭，相邻处偶有浅微孔（不再是满屏规律黑点）
                val ironZone = 0.5f + 0.5f * kotlin.math.sin((r * 0.34f + c * 0.27f).toDouble()).toFloat()
                val pinRoll = hashUnit(seed, 6) * 0.72f + ironZone * 0.28f
                val holeR = if (pinRoll > 0.72f) 0.12f + hashUnit(seed, 7) * 0.08f else 0f

                val x0 = pad + c * cellPx
                val y0 = pad + r * cellPx
                val ox0 = max(0, x0 - 1)
                val oy0 = max(0, y0 - 1)
                val ox1 = min(cw, x0 + cellPx + 1)
                val oy1 = min(ch, y0 + cellPx + 1)
                val half = cellPx * 0.5f
                val centerX = x0 + half + jx
                val centerY = y0 + half + jy

                for (py in oy0 until oy1) {
                    val nyRaw = (py - centerY) / half
                    val rowOff = py * cw
                    for (px in ox0 until ox1) {
                        val nxRaw = (px - centerX) / half
                        // 微幅液态热融波动，消除数码直边
                        val wobble = 0.055f * kotlin.math.sin((nxRaw * 3.1f + py * 0.22f).toDouble()).toFloat()
                        val nx = nxRaw + wobble
                        val ny = nyRaw - wobble * 0.85f
                        val absNx = abs(nx)
                        val absNy = abs(ny)

                        val boxD = max(absNx, absNy)
                        val sq3 = cbrtApprox(absNx * absNx * absNx + absNy * absNy * absNy)
                        val dist: Float
                        val inside: Boolean
                        when {
                            adj == 4 -> {
                                dist = 0.82f * boxD + 0.18f * sq3
                                inside = boxD <= 1.07f
                            }
                            adj >= 2 -> {
                                dist = 0.44f * boxD + 0.56f * sq3
                                inside = dist <= 1.02f
                            }
                            else -> {
                                dist = sq3
                                inside = dist <= 0.99f
                            }
                        }
                        if (!inside) continue

                        val pIdx = rowOff + px
                        if (pieceMask[pIdx] && dist >= 0.95f) continue

                        val seamWeight = if (absNy >= absNx) {
                            if (ny < 0f) diffTop else diffBot
                        } else {
                            if (nx < 0f) diffLeft else diffRight
                        }

                        val radial = sqrt(nxRaw * nxRaw + nyRaw * nyRaw)
                        val d2 = dist * dist
                        val d4 = d2 * d2
                        var dome = (1f - 0.10f * d4 * (0.35f + 0.65f * seamWeight)).coerceIn(0.48f, 1f)
                        var hShade = 0f
                        if (holeR > 0f && radial < holeR * 1.5f) {
                            val t = (1f - radial / (holeR * 1.5f)).coerceIn(0f, 1f)
                            dome *= (1f - 0.22f * t * t)
                            if (radial < holeR) {
                                // 浅色豆微孔仅轻微变暖变深（半透塑料内壁），避免白豆变黑洞
                                hShade = ((1f - radial / holeR).coerceIn(0f, 1f)) * 0.20f
                            }
                        }
                        val groove = ((dist - 0.84f) / 0.22f).coerceIn(0f, 1f) * seamWeight

                        pieceMask[pIdx] = true
                        colR[pIdx] = br
                        colG[pIdx] = bg
                        colB[pIdx] = bb
                        heightMap[pIdx] = dome
                        seamMap[pIdx] = max(seamMap[pIdx], groove)
                        holeShade[pIdx] = max(holeShade[pIdx], hShade)
                    }
                }
            }
        }

        // 1. 细腻手工纸/桌垫背景（与画布底色无缝融接，不再有僵硬正方形边缘线）
        val bgR = FloatArray(nPix)
        val bgG = FloatArray(nPix)
        val bgB = FloatArray(nPix)
        val halfW = cw * 0.5f
        val halfH = ch * 0.5f
        for (y in 0 until ch) {
            val dy = (y - halfH) / halfH
            val rowOff = y * cw
            for (x in 0 until cw) {
                val dx = (x - halfW) / halfW
                // 仅在画面中心略提亮补光，边缘平稳过渡至纯画布底色 (229, 221, 208)
                val spot = (1f - (dx * dx + dy * dy)).coerceIn(0f, 1f)
                val fiber = (hashUnit((y * 4999) xor (x * 7919), 11) - 0.5f) * 3.8f * spot
                val p = rowOff + x
                bgR[p] = (229f + spot * 8f + fiber).coerceIn(0f, 255f)
                bgG[p] = (221f + spot * 8f + fiber * 0.96f).coerceIn(0f, 255f)
                bgB[p] = (208f + spot * 8f + fiber * 0.92f).coerceIn(0f, 255f)
            }
        }

        val pieceF = FloatArray(nPix) { i -> if (pieceMask[i]) 1f else 0f }
        val smoothAlpha = boxBlurSeparable(pieceF, cw, ch, 1)
        val shadowBlur = boxBlurSeparable(smoothAlpha, cw, ch, max(3, (cellPx * 0.30f).roundToInt()))
        val heightBlur = boxBlurSeparable(heightMap, cw, ch, 1)

        val blurR = boxBlurMasked(colR, pieceMask, cw, ch, radius = 2)
        val blurG = boxBlurMasked(colG, pieceMask, cw, ch, radius = 2)
        val blurB = boxBlurMasked(colB, pieceMask, cw, ch, radius = 2)

        val outPixels = IntArray(nPix)
        val shOffX = max(3, (cellPx * 0.24f).roundToInt())
        val shOffY = max(3, (cellPx * 0.28f).roundToInt())
        val rimOffY = max(1, (cellPx * 0.13f).roundToInt())
        val nz = 0.28f

        for (y in 0 until ch) {
            val rowOff = y * cw
            val yUp = max(0, y - 1)
            val yDn = min(ch - 1, y + 1)
            val sy = y - shOffY
            val ry = y - rimOffY
            val nyNorm = y.toFloat() / ch
            for (x in 0 until cw) {
                val p = rowOff + x
                val alpha = ((smoothAlpha[p] - 0.14f) / 0.70f).coerceIn(0f, 1f)

                val sx = x - shOffX
                val shiftedShadow = if (sy in 0 until ch && sx in 0 until cw) shadowBlur[sy * cw + sx] else 0f
                val ao = ((shiftedShadow * 0.38f + shadowBlur[p] * 0.16f).coerceIn(0f, 0.50f)) * (1f - alpha)

                // 外轮廓底缘 3D 塑料侧壁厚度
                val isRim = alpha < 0.45f && ry in 0 until ch && pieceMask[ry * cw + x]
                val litBgR = bgR[p] * (1f - ao)
                val litBgG = bgG[p] * (1f - ao)
                val litBgB = bgB[p] * (1f - ao)

                if (isRim) {
                    val rp = ry * cw + x
                    val rimR = (colR[rp] * 0.68f).roundToInt().coerceIn(0, 255)
                    val rimG = (colG[rp] * 0.68f).roundToInt().coerceIn(0, 255)
                    val rimB = (colB[rp] * 0.68f).roundToInt().coerceIn(0, 255)
                    outPixels[p] = Color.rgb(rimR, rimG, rimB)
                    continue
                }

                if (alpha <= 0.005f) {
                    outPixels[p] = Color.rgb(litBgR.roundToInt(), litBgG.roundToInt(), litBgB.roundToInt())
                    continue
                }

                val xLt = max(0, x - 1)
                val xRt = min(cw - 1, x + 1)
                val gx = (heightBlur[rowOff + xRt] - heightBlur[rowOff + xLt]) * 0.78f
                val gy = (heightBlur[yDn * cw + x] - heightBlur[yUp * cw + x]) * 0.78f
                val norm = sqrt(gx * gx + gy * gy + nz * nz) + 1e-5f
                val rawDiff = (-(gx * -0.45f + gy * -0.58f) + nz * 0.66f) / norm
                val diffuse = 0.94f + 0.13f * rawDiff.coerceIn(-0.5f, 1.0f)

                // 烘焙油纸斜向柔和反光 + 塑料微颗粒质感
                val sheenPos = abs((x.toFloat() / cw - 0.35f) + (nyNorm - 0.30f))
                val sheen = (1f - sheenPos * 2.2f).coerceIn(0f, 1f) * 8f
                val spec = ((rawDiff - 0.96f) * 4.5f).coerceIn(0f, 1f) * 14f + sheen
                val ironTex = (hashUnit((y * 2311) xor (x * 4721), 17) - 0.5f) * 2.4f

                // 较大邻域次表面融色，使色块交界呈现真实的加热熔合柔和过渡
                val baseR = 0.58f * colR[p] + 0.42f * blurR[p]
                val baseG = 0.58f * colG[p] + 0.42f * blurG[p]
                val baseB = 0.58f * colB[p] + 0.42f * blurB[p]

                val mod = (1f - 0.055f * seamMap[p]) * (1f - holeShade[p])
                val shR = (baseR * diffuse + spec + ironTex) * mod
                val shG = (baseG * diffuse + spec + ironTex) * mod
                val shB = (baseB * diffuse + spec + ironTex) * mod

                val finalR = (shR * alpha + litBgR * (1f - alpha)).roundToInt().coerceIn(0, 255)
                val finalG = (shG * alpha + litBgG * (1f - alpha)).roundToInt().coerceIn(0, 255)
                val finalB = (shB * alpha + litBgB * (1f - alpha)).roundToInt().coerceIn(0, 255)
                outPixels[p] = Color.rgb(finalR, finalG, finalB)
            }
        }

        val bmp = Bitmap.createBitmap(cw, ch, Bitmap.Config.ARGB_8888)
        bmp.setPixels(outPixels, 0, cw, 0, 0, cw, ch)
        return bmp
    }

    private fun cbrtApprox(v: Float): Float =
        if (v <= 0f) 0f else kotlin.math.cbrt(v.toDouble()).toFloat()

    private fun hashUnit(seed: Int, salt: Int): Float {
        var x = seed xor (salt * 0x27d4eb2d)
        x = (x xor (x ushr 15)) * -2048144789
        x = (x xor (x ushr 13)) * -1028477387
        x = x xor (x ushr 16)
        return ((x ushr 1) and 0xFFFF) / 65535.0f
    }

    private fun boxBlurSeparable(src: FloatArray, w: Int, h: Int, radius: Int): FloatArray {
        if (radius <= 0) return src
        val tmp = FloatArray(w * h)
        val dst = FloatArray(w * h)
        val diam = (2 * radius + 1).toFloat()
        for (y in 0 until h) {
            val rowOff = y * w
            var acc = 0f
            for (dx in -radius..radius) acc += src[rowOff + dx.coerceIn(0, w - 1)]
            tmp[rowOff] = acc / diam
            for (x in 1 until w) {
                acc += src[rowOff + (x + radius).coerceIn(0, w - 1)]
                acc -= src[rowOff + (x - radius - 1).coerceIn(0, w - 1)]
                tmp[rowOff + x] = acc / diam
            }
        }
        for (x in 0 until w) {
            var acc = 0f
            for (dy in -radius..radius) acc += tmp[dy.coerceIn(0, h - 1) * w + x]
            dst[x] = acc / diam
            for (y in 1 until h) {
                acc += tmp[(y + radius).coerceIn(0, h - 1) * w + x]
                acc -= tmp[(y - radius - 1).coerceIn(0, h - 1) * w + x]
                dst[y * w + x] = acc / diam
            }
        }
        return dst
    }

    private fun boxBlurMasked(src: FloatArray, mask: BooleanArray, w: Int, h: Int, radius: Int = 1): FloatArray {
        val dst = FloatArray(w * h)
        for (y in 0 until h) {
            val rowOff = y * w
            for (x in 0 until w) {
                val p = rowOff + x
                if (!mask[p]) continue
                var sum = 0f
                var cnt = 0
                for (dy in -radius..radius) {
                    val ny = y + dy
                    if (ny !in 0 until h) continue
                    val nOff = ny * w
                    for (dx in -radius..radius) {
                        val nx = x + dx
                        if (nx in 0 until w && mask[nOff + nx]) {
                            sum += src[nOff + nx]
                            cnt++
                        }
                    }
                }
                dst[p] = if (cnt > 0) sum / cnt else src[p]
            }
        }
        return dst
    }
}
