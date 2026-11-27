package com.pindoustudio.app.ui

import android.graphics.Bitmap
import android.graphics.Matrix
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.pindoustudio.app.ui.theme.SageCompletion
import com.pindoustudio.app.ui.theme.TerracottaAccent
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

private enum class CropAspectRatio(val label: String, val ratio: Float?) {
    FREE("自由", null),
    SQUARE("1:1", 1f),
    PORTRAIT_3_4("3:4", 3f / 4f),
    LANDSCAPE_4_3("4:3", 4f / 3f)
}

private enum class CropDragTarget {
    NONE,
    TOP_LEFT,
    TOP_RIGHT,
    BOTTOM_LEFT,
    BOTTOM_RIGHT,
    LEFT,
    RIGHT,
    TOP,
    BOTTOM,
    MOVE_BOX,
    PAN_IMAGE
}

/**
 * 全屏交互式图片放大框选裁剪弹窗：
 * - 支持双指捏合缩放（1×..6×）、底部快捷倍率按钮（− / 1× / 2× / 3× / +）及 90° 旋转
 * - 支持拖动裁剪框四角、四边与整体框移动，或在放大状态下拖拽底层照片微调构图
 * - 实时保证裁剪框严格落在已显示图像范围内部，确认后输出所见即所得的高清裁剪 Bitmap
 */
@Composable
fun ImageCropDialog(
    sourceBitmap: Bitmap,
    title: String = "放大框选区域",
    onConfirmCrop: (Bitmap) -> Unit,
    onUseOriginal: () -> Unit,
    onDismiss: () -> Unit
) {
    var rotationDeg by remember(sourceBitmap) { mutableIntStateOf(0) }
    var aspectRatio by remember(sourceBitmap) { mutableStateOf(CropAspectRatio.FREE) }

    val workingBmp = remember(sourceBitmap, rotationDeg) {
        if (rotationDeg == 0) {
            sourceBitmap
        } else {
            val matrix = Matrix().apply { postRotate(rotationDeg.toFloat()) }
            Bitmap.createBitmap(sourceBitmap, 0, 0, sourceBitmap.width, sourceBitmap.height, matrix, true)
        }
    }
    val workingImageBmp = remember(workingBmp) { workingBmp.asImageBitmap() }

    val density = LocalDensity.current
    val padPx = with(density) { 20.dp.toPx() }
    val hitRadiusPx = with(density) { 28.dp.toPx() }
    val minCropFloorPx = with(density) { 64.dp.toPx() }

    var viewSize by remember { mutableStateOf(IntSize.Zero) }
    var zoom by remember(workingBmp) { mutableFloatStateOf(1f) }
    var panX by remember(workingBmp) { mutableFloatStateOf(0f) }
    var panY by remember(workingBmp) { mutableFloatStateOf(0f) }
    var cropL by remember(workingBmp) { mutableFloatStateOf(0f) }
    var cropT by remember(workingBmp) { mutableFloatStateOf(0f) }
    var cropR by remember(workingBmp) { mutableFloatStateOf(0f) }
    var cropB by remember(workingBmp) { mutableFloatStateOf(0f) }
    var initializedForKey by remember { mutableStateOf<Pair<Bitmap, IntSize>?>(null) }

    fun baseScaleOf(bmp: Bitmap, vs: IntSize): Float {
        if (vs.width <= 0 || vs.height <= 0) return 1f
        val availW = max(16f, vs.width - 2f * padPx)
        val availH = max(16f, vs.height - 2f * padPx)
        return min(availW / bmp.width.coerceAtLeast(1), availH / bmp.height.coerceAtLeast(1))
    }

    fun dispScaleOf(bmp: Bitmap, vs: IntSize, z: Float): Float = baseScaleOf(bmp, vs) * z

    fun imageBounds(bmp: Bitmap, vs: IntSize, z: Float, px: Float, py: Float): FloatArray {
        val ds = dispScaleOf(bmp, vs, z)
        val dw = bmp.width * ds
        val dh = bmp.height * ds
        val left = (vs.width - dw) * 0.5f + px
        val top = (vs.height - dh) * 0.5f + py
        return floatArrayOf(left, top, left + dw, top + dh, ds)
    }

    fun clampPanToCrop(bmp: Bitmap, vs: IntSize, z: Float) {
        if (vs.width <= 0 || vs.height <= 0 || cropR <= cropL || cropB <= cropT) return
        val ds = dispScaleOf(bmp, vs, z)
        val dw = bmp.width * ds
        val dh = bmp.height * ds
        val halfW = (vs.width - dw) * 0.5f
        val halfH = (vs.height - dh) * 0.5f
        // 保证 imgLeft <= cropL 且 imgRight >= cropR
        val minPanX = cropR - halfW - dw
        val maxPanX = cropL - halfW
        val minPanY = cropB - halfH - dh
        val maxPanY = cropT - halfH
        panX = if (minPanX <= maxPanX) panX.coerceIn(minPanX, maxPanX) else 0.5f * (minPanX + maxPanX)
        panY = if (minPanY <= maxPanY) panY.coerceIn(minPanY, maxPanY) else 0.5f * (minPanY + maxPanY)
    }

    fun fitInitialCrop(bmp: Bitmap, vs: IntSize, z: Float, px: Float, py: Float, ratio: Float?) {
        if (vs.width <= 0 || vs.height <= 0) return
        val b = imageBounds(bmp, vs, z, px, py)
        val safeL = max(padPx, b[0])
        val safeT = max(padPx, b[1])
        val safeR = min(vs.width - padPx, b[2])
        val safeB = min(vs.height - padPx, b[3])
        val safeW = max(32f, safeR - safeL)
        val safeH = max(32f, safeB - safeT)
        val cx = (safeL + safeR) * 0.5f
        val cy = (safeT + safeB) * 0.5f
        val targetW: Float
        val targetH: Float
        if (ratio == null) {
            targetW = safeW * 0.86f
            targetH = safeH * 0.86f
        } else {
            val maxW = safeW * 0.88f
            val maxH = safeH * 0.88f
            if (maxW / maxH > ratio) {
                targetH = maxH
                targetW = targetH * ratio
            } else {
                targetW = maxW
                targetH = targetW / ratio
            }
        }
        cropL = cx - targetW * 0.5f
        cropT = cy - targetH * 0.5f
        cropR = cx + targetW * 0.5f
        cropB = cy + targetH * 0.5f
    }

    fun applyZoomAnchored(targetZoom: Float, anchorX: Float, anchorY: Float) {
        if (viewSize.width <= 0 || viewSize.height <= 0) return
        val bs = baseScaleOf(workingBmp, viewSize)
        val minZoomForCrop = if (cropR > cropL && cropB > cropT) {
            max(1f, max((cropR - cropL) / (workingBmp.width * bs), (cropB - cropT) / (workingBmp.height * bs)))
        } else 1f
        val clampedZoom = targetZoom.coerceIn(minZoomForCrop, 6f)
        val oldScale = bs * zoom
        val newScale = bs * clampedZoom
        val oldLeft = (viewSize.width - workingBmp.width * oldScale) * 0.5f + panX
        val oldTop = (viewSize.height - workingBmp.height * oldScale) * 0.5f + panY
        val bmpX = (anchorX - oldLeft) / oldScale
        val bmpY = (anchorY - oldTop) / oldScale
        val newLeft = anchorX - bmpX * newScale
        val newTop = anchorY - bmpY * newScale
        zoom = clampedZoom
        panX = newLeft - (viewSize.width - workingBmp.width * newScale) * 0.5f
        panY = newTop - (viewSize.height - workingBmp.height * newScale) * 0.5f
        clampPanToCrop(workingBmp, viewSize, zoom)
    }

    LaunchedEffect(workingBmp, viewSize) {
        val key = workingBmp to viewSize
        if (viewSize.width > 0 && viewSize.height > 0 && initializedForKey != key) {
            zoom = 1f
            panX = 0f
            panY = 0f
            fitInitialCrop(workingBmp, viewSize, 1f, 0f, 0f, aspectRatio.ratio)
            initializedForKey = key
        }
    }

    val currentRatio by rememberUpdatedState(aspectRatio.ratio)
    val currentBmp by rememberUpdatedState(workingBmp)

    // 实时计算框选像素尺寸
    val curBounds = imageBounds(workingBmp, viewSize, zoom, panX, panY)
    val dsNow = curBounds[4].coerceAtLeast(1e-4f)
    val selPxW = if (cropR > cropL) ((cropR - cropL) / dsNow).roundToInt().coerceIn(1, workingBmp.width) else workingBmp.width
    val selPxH = if (cropB > cropT) ((cropB - cropT) / dsNow).roundToInt().coerceIn(1, workingBmp.height) else workingBmp.height

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = Color(0xFF141312)
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // 顶部栏
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFF1F1D1B))
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    TextButton(onClick = onDismiss) {
                        Text("取消", color = Color(0xFFD6CFC7), fontSize = 14.sp)
                    }
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            title,
                            color = Color.White,
                            fontWeight = FontWeight.Bold,
                            fontSize = 15.sp
                        )
                        Text(
                            "框选 ${selPxW}×${selPxH} px · ${"%.1f".format(zoom)}×",
                            color = Color(0xFFE0B49F),
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace
                        )
                    }
                    TextButton(onClick = {
                        rotationDeg = 0
                        aspectRatio = CropAspectRatio.FREE
                        zoom = 1f
                        panX = 0f
                        panY = 0f
                        fitInitialCrop(sourceBitmap, viewSize, 1f, 0f, 0f, null)
                    }) {
                        Text("重置", color = TerracottaAccent, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    }
                }

                // 中央交互画布
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .onSizeChanged { viewSize = it }
                        .pointerInput(workingBmp, aspectRatio) {
                            awaitEachGesture {
                                val firstDown = awaitFirstDown(requireUnconsumed = false)
                                val downPos = firstDown.position
                                var target = CropDragTarget.NONE

                                val dTL = hypot(downPos.x - cropL, downPos.y - cropT)
                                val dTR = hypot(downPos.x - cropR, downPos.y - cropT)
                                val dBL = hypot(downPos.x - cropL, downPos.y - cropB)
                                val dBR = hypot(downPos.x - cropR, downPos.y - cropB)
                                val minCorner = min(min(dTL, dTR), min(dBL, dBR))

                                if (minCorner <= hitRadiusPx) {
                                    target = when (minCorner) {
                                        dTL -> CropDragTarget.TOP_LEFT
                                        dTR -> CropDragTarget.TOP_RIGHT
                                        dBL -> CropDragTarget.BOTTOM_LEFT
                                        else -> CropDragTarget.BOTTOM_RIGHT
                                    }
                                } else {
                                    val onL = abs(downPos.x - cropL) <= hitRadiusPx && downPos.y in (cropT - hitRadiusPx)..(cropB + hitRadiusPx)
                                    val onR = abs(downPos.x - cropR) <= hitRadiusPx && downPos.y in (cropT - hitRadiusPx)..(cropB + hitRadiusPx)
                                    val onT = abs(downPos.y - cropT) <= hitRadiusPx && downPos.x in (cropL - hitRadiusPx)..(cropR + hitRadiusPx)
                                    val onB = abs(downPos.y - cropB) <= hitRadiusPx && downPos.x in (cropL - hitRadiusPx)..(cropR + hitRadiusPx)
                                    target = when {
                                        onL -> CropDragTarget.LEFT
                                        onR -> CropDragTarget.RIGHT
                                        onT -> CropDragTarget.TOP
                                        onB -> CropDragTarget.BOTTOM
                                        downPos.x in cropL..cropR && downPos.y in cropT..cropB ->
                                            if (zoom > 1.03f) CropDragTarget.PAN_IMAGE else CropDragTarget.MOVE_BOX
                                        else -> CropDragTarget.PAN_IMAGE
                                    }
                                }

                                while (true) {
                                    val event = awaitPointerEvent()
                                    val pressed = event.changes.filter { it.pressed }
                                    if (pressed.isEmpty()) break

                                    if (pressed.size >= 2) {
                                        val p0 = pressed[0]
                                        val p1 = pressed[1]
                                        val prevDist = hypot(p0.previousPosition.x - p1.previousPosition.x, p0.previousPosition.y - p1.previousPosition.y)
                                        val curDist = hypot(p0.position.x - p1.position.x, p0.position.y - p1.position.y)
                                        val prevCx = (p0.previousPosition.x + p1.previousPosition.x) * 0.5f
                                        val prevCy = (p0.previousPosition.y + p1.previousPosition.y) * 0.5f
                                        val curCx = (p0.position.x + p1.position.x) * 0.5f
                                        val curCy = (p0.position.y + p1.position.y) * 0.5f

                                        val zoomFactor = if (prevDist > 6f) curDist / prevDist else 1f
                                        panX += curCx - prevCx
                                        panY += curCy - prevCy
                                        applyZoomAnchored(zoom * zoomFactor, curCx, curCy)
                                        pressed.forEach { if (it.positionChanged()) it.consume() }
                                        target = CropDragTarget.PAN_IMAGE
                                    } else {
                                        val ch = pressed.first()
                                        val dx = ch.position.x - ch.previousPosition.x
                                        val dy = ch.position.y - ch.previousPosition.y
                                        if (abs(dx) > 0.01f || abs(dy) > 0.01f) {
                                            val bmp = currentBmp
                                            val ib = imageBounds(bmp, viewSize, zoom, panX, panY)
                                            val minX = max(padPx, ib[0])
                                            val minY = max(padPx, ib[1])
                                            val maxX = min(viewSize.width - padPx, ib[2])
                                            val maxY = min(viewSize.height - padPx, ib[3])
                                            val minCrop = min(minCropFloorPx, min(maxX - minX, maxY - minY) * 0.5f)
                                            val ar = currentRatio

                                            when (target) {
                                                CropDragTarget.PAN_IMAGE -> {
                                                    panX += dx
                                                    panY += dy
                                                    clampPanToCrop(bmp, viewSize, zoom)
                                                }
                                                CropDragTarget.MOVE_BOX -> {
                                                    val boxW = cropR - cropL
                                                    val boxH = cropB - cropT
                                                    val nl = (cropL + dx).coerceIn(minX, max(minX, maxX - boxW))
                                                    val nt = (cropT + dy).coerceIn(minY, max(minY, maxY - boxH))
                                                    cropL = nl
                                                    cropT = nt
                                                    cropR = nl + boxW
                                                    cropB = nt + boxH
                                                }
                                                CropDragTarget.TOP_LEFT -> {
                                                    var nl = (cropL + dx).coerceIn(minX, cropR - minCrop)
                                                    var nt = (cropT + dy).coerceIn(minY, cropB - minCrop)
                                                    if (ar != null) {
                                                        val w = cropR - nl
                                                        val h = w / ar
                                                        nt = cropB - h
                                                        if (nt < minY) {
                                                            nt = minY
                                                            nl = cropR - (cropB - nt) * ar
                                                        }
                                                        if (cropB - nt < minCrop || cropR - nl < minCrop) {
                                                            nl = cropL; nt = cropT
                                                        }
                                                    }
                                                    cropL = nl; cropT = nt
                                                }
                                                CropDragTarget.TOP_RIGHT -> {
                                                    var nr = (cropR + dx).coerceIn(cropL + minCrop, maxX)
                                                    var nt = (cropT + dy).coerceIn(minY, cropB - minCrop)
                                                    if (ar != null) {
                                                        val w = nr - cropL
                                                        val h = w / ar
                                                        nt = cropB - h
                                                        if (nt < minY) {
                                                            nt = minY
                                                            nr = cropL + (cropB - nt) * ar
                                                        }
                                                        if (cropB - nt < minCrop || nr - cropL < minCrop) {
                                                            nr = cropR; nt = cropT
                                                        }
                                                    }
                                                    cropR = nr; cropT = nt
                                                }
                                                CropDragTarget.BOTTOM_LEFT -> {
                                                    var nl = (cropL + dx).coerceIn(minX, cropR - minCrop)
                                                    var nb = (cropB + dy).coerceIn(cropT + minCrop, maxY)
                                                    if (ar != null) {
                                                        val w = cropR - nl
                                                        val h = w / ar
                                                        nb = cropT + h
                                                        if (nb > maxY) {
                                                            nb = maxY
                                                            nl = cropR - (nb - cropT) * ar
                                                        }
                                                        if (nb - cropT < minCrop || cropR - nl < minCrop) {
                                                            nl = cropL; nb = cropB
                                                        }
                                                    }
                                                    cropL = nl; cropB = nb
                                                }
                                                CropDragTarget.BOTTOM_RIGHT -> {
                                                    var nr = (cropR + dx).coerceIn(cropL + minCrop, maxX)
                                                    var nb = (cropB + dy).coerceIn(cropT + minCrop, maxY)
                                                    if (ar != null) {
                                                        val w = nr - cropL
                                                        val h = w / ar
                                                        nb = cropT + h
                                                        if (nb > maxY) {
                                                            nb = maxY
                                                            nr = cropL + (nb - cropT) * ar
                                                        }
                                                        if (nb - cropT < minCrop || nr - cropL < minCrop) {
                                                            nr = cropR; nb = cropB
                                                        }
                                                    }
                                                    cropR = nr; cropB = nb
                                                }
                                                CropDragTarget.LEFT -> {
                                                    val nl = (cropL + dx).coerceIn(minX, cropR - minCrop)
                                                    if (ar == null) {
                                                        cropL = nl
                                                    } else {
                                                        val newW = cropR - nl
                                                        val newH = newW / ar
                                                        val cy = (cropT + cropB) * 0.5f
                                                        val nt = cy - newH * 0.5f
                                                        val nb = cy + newH * 0.5f
                                                        if (nt >= minY && nb <= maxY && newH >= minCrop) {
                                                            cropL = nl; cropT = nt; cropB = nb
                                                        }
                                                    }
                                                }
                                                CropDragTarget.RIGHT -> {
                                                    val nr = (cropR + dx).coerceIn(cropL + minCrop, maxX)
                                                    if (ar == null) {
                                                        cropR = nr
                                                    } else {
                                                        val newW = nr - cropL
                                                        val newH = newW / ar
                                                        val cy = (cropT + cropB) * 0.5f
                                                        val nt = cy - newH * 0.5f
                                                        val nb = cy + newH * 0.5f
                                                        if (nt >= minY && nb <= maxY && newH >= minCrop) {
                                                            cropR = nr; cropT = nt; cropB = nb
                                                        }
                                                    }
                                                }
                                                CropDragTarget.TOP -> {
                                                    val nt = (cropT + dy).coerceIn(minY, cropB - minCrop)
                                                    if (ar == null) {
                                                        cropT = nt
                                                    } else {
                                                        val newH = cropB - nt
                                                        val newW = newH * ar
                                                        val cx = (cropL + cropR) * 0.5f
                                                        val nl = cx - newW * 0.5f
                                                        val nr = cx + newW * 0.5f
                                                        if (nl >= minX && nr <= maxX && newW >= minCrop) {
                                                            cropT = nt; cropL = nl; cropR = nr
                                                        }
                                                    }
                                                }
                                                CropDragTarget.BOTTOM -> {
                                                    val nb = (cropB + dy).coerceIn(cropT + minCrop, maxY)
                                                    if (ar == null) {
                                                        cropB = nb
                                                    } else {
                                                        val newH = nb - cropT
                                                        val newW = newH * ar
                                                        val cx = (cropL + cropR) * 0.5f
                                                        val nl = cx - newW * 0.5f
                                                        val nr = cx + newW * 0.5f
                                                        if (nl >= minX && nr <= maxX && newW >= minCrop) {
                                                            cropB = nb; cropL = nl; cropR = nr
                                                        }
                                                    }
                                                }
                                                CropDragTarget.NONE -> Unit
                                            }
                                            ch.consume()
                                        }
                                    }
                                }
                            }
                        }
                ) {
                    Canvas(modifier = Modifier.fillMaxSize()) {
                        if (viewSize.width <= 0 || viewSize.height <= 0 || cropR <= cropL || cropB <= cropT) return@Canvas
                        val b = imageBounds(workingBmp, viewSize, zoom, panX, panY)
                        val imgL = b[0]
                        val imgT = b[1]
                        val imgW = (b[2] - b[0]).roundToInt().coerceAtLeast(1)
                        val imgH = (b[3] - b[1]).roundToInt().coerceAtLeast(1)

                        drawImage(
                            image = workingImageBmp,
                            dstOffset = IntOffset(imgL.roundToInt(), imgT.roundToInt()),
                            dstSize = IntSize(imgW, imgH)
                        )

                        // 四周半透明遮罩
                        val scrim = Color.Black.copy(alpha = 0.62f)
                        drawRect(scrim, topLeft = Offset.Zero, size = Size(size.width, cropT.coerceAtLeast(0f)))
                        drawRect(
                            scrim,
                            topLeft = Offset(0f, cropB),
                            size = Size(size.width, (size.height - cropB).coerceAtLeast(0f))
                        )
                        drawRect(
                            scrim,
                            topLeft = Offset(0f, cropT),
                            size = Size(cropL.coerceAtLeast(0f), (cropB - cropT).coerceAtLeast(0f))
                        )
                        drawRect(
                            scrim,
                            topLeft = Offset(cropR, cropT),
                            size = Size((size.width - cropR).coerceAtLeast(0f), (cropB - cropT).coerceAtLeast(0f))
                        )

                        val cw = cropR - cropL
                        val ch = cropB - cropT

                        // 三分线网格
                        val gridStroke = 1.dp.toPx()
                        val gridColor = Color.White.copy(alpha = 0.34f)
                        for (k in 1..2) {
                            val gx = cropL + cw * k / 3f
                            val gy = cropT + ch * k / 3f
                            drawLine(gridColor, Offset(gx, cropT), Offset(gx, cropB), strokeWidth = gridStroke)
                            drawLine(gridColor, Offset(cropL, gy), Offset(cropR, gy), strokeWidth = gridStroke)
                        }

                        // 外框细线
                        drawRect(
                            color = Color.White,
                            topLeft = Offset(cropL, cropT),
                            size = Size(cw, ch),
                            style = androidx.compose.ui.graphics.drawscope.Stroke(width = 1.5.dp.toPx())
                        )

                        // 四角加粗 L 型手柄
                        val cornerArm = min(22.dp.toPx(), min(cw, ch) * 0.32f)
                        val cornerStroke = 3.8.dp.toPx()
                        val cornerColor = TerracottaAccent
                        drawLine(cornerColor, Offset(cropL, cropT), Offset(cropL + cornerArm, cropT), cornerStroke, StrokeCap.Round)
                        drawLine(cornerColor, Offset(cropL, cropT), Offset(cropL, cropT + cornerArm), cornerStroke, StrokeCap.Round)
                        drawLine(cornerColor, Offset(cropR, cropT), Offset(cropR - cornerArm, cropT), cornerStroke, StrokeCap.Round)
                        drawLine(cornerColor, Offset(cropR, cropT), Offset(cropR, cropT + cornerArm), cornerStroke, StrokeCap.Round)
                        drawLine(cornerColor, Offset(cropL, cropB), Offset(cropL + cornerArm, cropB), cornerStroke, StrokeCap.Round)
                        drawLine(cornerColor, Offset(cropL, cropB), Offset(cropL, cropB - cornerArm), cornerStroke, StrokeCap.Round)
                        drawLine(cornerColor, Offset(cropR, cropB), Offset(cropR - cornerArm, cropB), cornerStroke, StrokeCap.Round)
                        drawLine(cornerColor, Offset(cropR, cropB), Offset(cropR, cropB - cornerArm), cornerStroke, StrokeCap.Round)

                        // 四边中点把手条
                        val barHalf = min(14.dp.toPx(), min(cw, ch) * 0.22f)
                        val midX = (cropL + cropR) * 0.5f
                        val midY = (cropT + cropB) * 0.5f
                        drawLine(Color.White, Offset(midX - barHalf, cropT), Offset(midX + barHalf, cropT), cornerStroke, StrokeCap.Round)
                        drawLine(Color.White, Offset(midX - barHalf, cropB), Offset(midX + barHalf, cropB), cornerStroke, StrokeCap.Round)
                        drawLine(Color.White, Offset(cropL, midY - barHalf), Offset(cropL, midY + barHalf), cornerStroke, StrokeCap.Round)
                        drawLine(Color.White, Offset(cropR, midY - barHalf), Offset(cropR, midY + barHalf), cornerStroke, StrokeCap.Round)
                    }
                }

                // 底部操控台
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFF1F1D1B))
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    // 放大倍率 + 旋转控制栏
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        val anchorX = if (cropR > cropL) (cropL + cropR) * 0.5f else viewSize.width * 0.5f
                        val anchorY = if (cropB > cropT) (cropT + cropB) * 0.5f else viewSize.height * 0.5f

                        CropControlPill("缩小 -") {
                            applyZoomAnchored(zoom / 1.35f, anchorX, anchorY)
                        }
                        listOf(1f to "1×", 2f to "2×", 3f to "3×", 4f to "4×").forEach { (zTarget, lbl) ->
                            val active = abs(zoom - zTarget) < 0.15f
                            CropControlPill(lbl, highlighted = active) {
                                applyZoomAnchored(zTarget, anchorX, anchorY)
                            }
                        }
                        CropControlPill("放大 +") {
                            applyZoomAnchored(zoom * 1.35f, anchorX, anchorY)
                        }
                        CropControlPill("旋转90°") {
                            rotationDeg = (rotationDeg + 90) % 360
                        }
                    }

                    // 比例预设 + 手势提示
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            CropAspectRatio.entries.forEach { rOpt ->
                                CropControlPill(rOpt.label, highlighted = aspectRatio == rOpt) {
                                    aspectRatio = rOpt
                                    fitInitialCrop(workingBmp, viewSize, zoom, panX, panY, rOpt.ratio)
                                }
                            }
                        }
                        Text(
                            "双指放大 · 拖角框选",
                            color = Color(0xFFB5ACA4),
                            fontSize = 10.5.sp
                        )
                    }

                    // 底部确认按钮栏
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        OutlinedButton(
                            onClick = onUseOriginal,
                            modifier = Modifier.weight(1f),
                            border = BorderStroke(1.dp, Color(0xFF5A544E)),
                            contentPadding = PaddingValues(vertical = 10.dp)
                        ) {
                            Text("直接用原图", color = Color(0xFFEDE6DF), fontWeight = FontWeight.SemiBold)
                        }
                        Button(
                            onClick = {
                                if (viewSize.width <= 0 || viewSize.height <= 0 || cropR <= cropL || cropB <= cropT) {
                                    onConfirmCrop(workingBmp)
                                    return@Button
                                }
                                val b = imageBounds(workingBmp, viewSize, zoom, panX, panY)
                                val dw = max(1f, b[2] - b[0])
                                val dh = max(1f, b[3] - b[1])
                                val u0 = ((cropL - b[0]) / dw).coerceIn(0f, 1f)
                                val v0 = ((cropT - b[1]) / dh).coerceIn(0f, 1f)
                                val u1 = ((cropR - b[0]) / dw).coerceIn(u0, 1f)
                                val v1 = ((cropB - b[1]) / dh).coerceIn(v0, 1f)
                                val pxX = (u0 * workingBmp.width).roundToInt().coerceIn(0, workingBmp.width - 1)
                                val pxY = (v0 * workingBmp.height).roundToInt().coerceIn(0, workingBmp.height - 1)
                                val pxW = ((u1 - u0) * workingBmp.width).roundToInt().coerceIn(1, workingBmp.width - pxX)
                                val pxH = ((v1 - v0) * workingBmp.height).roundToInt().coerceIn(1, workingBmp.height - pxY)
                                val cropped = Bitmap.createBitmap(workingBmp, pxX, pxY, pxW, pxH)
                                onConfirmCrop(cropped)
                            },
                            modifier = Modifier.weight(1.3f),
                            colors = ButtonDefaults.buttonColors(containerColor = SageCompletion),
                            contentPadding = PaddingValues(vertical = 10.dp)
                        ) {
                            Spacer(Modifier.width(2.dp))
                            Text("确认框选 (${selPxW}×${selPxH})", fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun CropControlPill(
    label: String,
    highlighted: Boolean = false,
    onClick: () -> Unit
) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(8.dp),
        color = if (highlighted) TerracottaAccent else Color(0xFF2D2A26),
        border = BorderStroke(1.dp, if (highlighted) TerracottaAccent else Color(0xFF44403B))
    ) {
        Text(
            label,
            color = if (highlighted) Color.White else Color(0xFFE6DFD8),
            fontSize = 11.5.sp,
            fontWeight = if (highlighted) FontWeight.Bold else FontWeight.Medium,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp)
        )
    }
}
