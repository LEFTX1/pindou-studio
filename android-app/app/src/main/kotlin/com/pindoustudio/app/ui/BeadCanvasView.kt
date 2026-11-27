package com.pindoustudio.app.ui

import android.graphics.Bitmap
import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import com.pindoustudio.app.data.PaletteRepository
import com.pindoustudio.app.engine.BakedPhysicsRenderer
import com.pindoustudio.app.model.BeadBrand
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.ViewMode
import com.pindoustudio.app.ui.theme.LinenTray
import com.pindoustudio.app.ui.theme.TerracottaAccent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.floor
import kotlin.math.min
import kotlin.math.roundToInt

@Composable
fun BeadCanvasView(
    pattern: BeadPattern,
    paletteRepo: PaletteRepository,
    brand: BeadBrand,
    viewMode: ViewMode,
    highlightCode: String?,
    showCodes: Boolean,
    showGrid: Boolean,
    fitTrigger: Int,
    onCellTap: (Int, Int) -> Unit,
    modifier: Modifier = Modifier
) {
    var boxSize by remember { mutableStateOf(IntSize.Zero) }
    var scale by remember { mutableFloatStateOf(1f) }
    var panX by remember { mutableFloatStateOf(0f) }
    var panY by remember { mutableFloatStateOf(0f) }

    val baseCellPx = 24f

    // 在成品预览模式下异步渲染真实像素级物理高度场 + 光学材质图并缓存
    val bakedBitmap by produceState<Bitmap?>(
        initialValue = null,
        key1 = viewMode,
        key2 = pattern
    ) {
        if (viewMode != ViewMode.BAKED) {
            value = null
            return@produceState
        }
        value = withContext(Dispatchers.Default) {
            BakedPhysicsRenderer.render(
                pattern = pattern,
                paletteRepo = paletteRepo,
                maxCanvasPx = 680
            )
        }
    }

    fun resetFit(sz: IntSize) {
        if (sz.width <= 0 || sz.height <= 0 || pattern.width <= 0 || pattern.height <= 0) return
        val margin = 56f
        val availW = (sz.width - margin).coerceAtLeast(100f)
        val availH = (sz.height - margin).coerceAtLeast(100f)
        val fit = min(availW / pattern.width, availH / pattern.height)
        scale = (fit / baseCellPx).coerceIn(0.22f, 4.5f)
        val gw = pattern.width * baseCellPx * scale
        val gh = pattern.height * baseCellPx * scale
        panX = (sz.width - gw) / 2f
        panY = (sz.height - gh) / 2f
    }

    LaunchedEffect(pattern.name, pattern.width, pattern.height, fitTrigger, boxSize) {
        if (boxSize.width > 0 && boxSize.height > 0) {
            resetFit(boxSize)
        }
    }

    val codeTextPaint = remember {
        Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textAlign = Paint.Align.CENTER
            typeface = Typeface.MONOSPACE
            isFakeBoldText = true
        }
    }
    val axisTextPaint = remember {
        Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize = 22f
            typeface = Typeface.MONOSPACE
            textAlign = Paint.Align.CENTER
        }
    }

    Box(
        modifier = modifier
            .background(if (viewMode == ViewMode.BAKED) Color(0xFFE5DDD0) else LinenTray)
            .onSizeChanged { newSize ->
                val needFit = boxSize == IntSize.Zero
                boxSize = newSize
                if (needFit) resetFit(newSize)
            }
            .pointerInput(Unit) {
                detectTransformGestures { centroid, pan, zoom, _ ->
                    val oldScale = scale
                    val newScale = (oldScale * zoom).coerceIn(0.45f, 5.0f)
                    val factor = newScale / oldScale
                    panX = centroid.x - (centroid.x - panX) * factor + pan.x
                    panY = centroid.y - (centroid.y - panY) * factor + pan.y
                    scale = newScale
                }
            }
            .pointerInput(pattern.width, pattern.height, viewMode) {
                detectTapGestures { offset ->
                    if (viewMode == ViewMode.BAKED) return@detectTapGestures
                    val cellPx = baseCellPx * scale
                    val c = floor((offset.x - panX) / cellPx).toInt()
                    val r = floor((offset.y - panY) / cellPx).toInt()
                    if (r in 0 until pattern.height && c in 0 until pattern.width) {
                        onCellTap(r, c)
                    }
                }
            }
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            if (viewMode == ViewMode.BAKED) {
                val bmp = bakedBitmap ?: return@Canvas
                val imgBmp = bmp.asImageBitmap()
                // 按画布缩放比例自适应平铺/缩放显示真实物理渲染位图
                val fitScale = min(
                    (size.width * 0.94f) / bmp.width,
                    (size.height * 0.94f) / bmp.height
                ) * (scale / (min((size.width - 56f) / pattern.width, (size.height - 56f) / pattern.height) / baseCellPx).coerceAtLeast(0.1f))
                val drawW = (bmp.width * fitScale).roundToInt().coerceAtLeast(1)
                val drawH = (bmp.height * fitScale).roundToInt().coerceAtLeast(1)
                val cx = (panX + (pattern.width * baseCellPx * scale) / 2f - drawW / 2f).roundToInt()
                val cy = (panY + (pattern.height * baseCellPx * scale) / 2f - drawH / 2f).roundToInt()
                drawImage(
                    image = imgBmp,
                    dstOffset = IntOffset(cx, cy),
                    dstSize = IntSize(drawW, drawH)
                )
                return@Canvas
            }

            val cellPx = baseCellPx * scale
            val gridW = pattern.width * cellPx
            val gridH = pattern.height * cellPx

            drawRect(
                color = Color(0xFFFFFDF9),
                topLeft = Offset(panX, panY),
                size = Size(gridW, gridH)
            )

            val drawCodes = showCodes && cellPx >= 24f

            for (r in 0 until pattern.height) {
                val cy = panY + r * cellPx
                if (cy + cellPx < 0f || cy > size.height) continue

                for (c in 0 until pattern.width) {
                    val cx = panX + c * cellPx
                    if (cx + cellPx < 0f || cx > size.width) continue

                    val code = pattern.get(r, c)
                    if (code == null) {
                        drawRect(
                            color = if ((r + c) % 2 == 0) Color(0xFFFAF7F1) else Color(0xFFF0EAE0),
                            topLeft = Offset(cx, cy),
                            size = Size(cellPx + 0.5f, cellPx + 0.5f)
                        )
                        continue
                    }

                    val entry = paletteRepo.findByMardCode(code) ?: continue
                    val alpha = if (highlightCode != null && highlightCode != entry.code) 0.14f else 1f
                    val beadCol = Color(entry.argb).copy(alpha = alpha)

                    drawRect(
                        color = beadCol,
                        topLeft = Offset(cx, cy),
                        size = Size(cellPx + 0.5f, cellPx + 0.5f)
                    )
                    if (highlightCode != null && highlightCode == entry.code) {
                        drawRect(
                            color = TerracottaAccent,
                            topLeft = Offset(cx + 1f, cy + 1f),
                            size = Size(cellPx - 2f, cellPx - 2f),
                            style = Stroke(width = (cellPx * 0.1f).coerceAtLeast(2f))
                        )
                    }
                    if (drawCodes) {
                        val disp = entry.codeFor(brand)
                        codeTextPaint.color = if (entry.luminance > 145) {
                            android.graphics.Color.argb((alpha * 255).toInt(), 25, 22, 20)
                        } else {
                            android.graphics.Color.argb((alpha * 255).toInt(), 255, 255, 255)
                        }
                        codeTextPaint.textSize = (cellPx * if (disp.length > 3) 0.27f else 0.34f).coerceAtLeast(10f)
                        val fm = codeTextPaint.fontMetrics
                        val ty = cy + cellPx / 2f - (fm.ascent + fm.descent) / 2f
                        drawContext.canvas.nativeCanvas.drawText(disp, cx + cellPx / 2f, ty, codeTextPaint)
                    }
                }
            }

            if (showGrid) {
                for (c in 0..pattern.width) {
                    val x = panX + c * cellPx
                    val (col, sw) = when {
                        c % 10 == 0 -> Color(0xFF231F1D).copy(alpha = 0.60f) to 2.2f
                        c % 5 == 0 -> Color(0xFF231F1D).copy(alpha = 0.34f) to 1.4f
                        else -> Color(0xFF231F1D).copy(alpha = 0.14f) to 0.8f
                    }
                    drawLine(col, Offset(x, panY), Offset(x, panY + gridH), strokeWidth = sw)
                }
                for (r in 0..pattern.height) {
                    val y = panY + r * cellPx
                    val (col, sw) = when {
                        r % 10 == 0 -> Color(0xFF231F1D).copy(alpha = 0.60f) to 2.2f
                        r % 5 == 0 -> Color(0xFF231F1D).copy(alpha = 0.34f) to 1.4f
                        else -> Color(0xFF231F1D).copy(alpha = 0.14f) to 0.8f
                    }
                    drawLine(col, Offset(panX, y), Offset(panX + gridW, y), strokeWidth = sw)
                }
            }

            if (cellPx >= 12f) {
                axisTextPaint.textSize = (cellPx * 0.36f).coerceIn(14f, 24f)
                val step = if (cellPx >= 24f) 1 else 5
                axisTextPaint.textAlign = Paint.Align.CENTER
                axisTextPaint.color = android.graphics.Color.rgb(107, 98, 91)
                for (c in 0 until pattern.width) {
                    if (step > 1 && (c + 1) % 5 != 0 && c != 0) continue
                    drawContext.canvas.nativeCanvas.drawText(
                        "${c + 1}",
                        panX + (c + 0.5f) * cellPx,
                        panY - 10f,
                        axisTextPaint
                    )
                }
                axisTextPaint.textAlign = Paint.Align.RIGHT
                axisTextPaint.color = android.graphics.Color.rgb(107, 98, 91)
                for (r in 0 until pattern.height) {
                    if (step > 1 && (r + 1) % 5 != 0 && r != 0) continue
                    drawContext.canvas.nativeCanvas.drawText(
                        "${r + 1}",
                        panX - 8f,
                        panY + (r + 0.62f) * cellPx,
                        axisTextPaint
                    )
                }
            }
        }

        if (viewMode == ViewMode.BAKED && bakedBitmap == null) {
            Column(
                modifier = Modifier.align(Alignment.Center),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                CircularProgressIndicator(modifier = Modifier.size(28.dp), color = TerracottaAccent, strokeWidth = 2.5.dp)
                Spacer(Modifier.height(8.dp))
                Text("正在渲染实物物理光影…", fontSize = 12.sp, color = Color(0xFF6B625B))
            }
        }
    }
}
