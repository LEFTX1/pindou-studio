package com.pindoustudio.app.ui

import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.pindoustudio.app.data.CraftAchievement
import com.pindoustudio.app.data.PortfolioStats
import com.pindoustudio.app.data.PortfolioWork
import com.pindoustudio.app.model.BeadBrand
import com.pindoustudio.app.model.PhotoSlot
import com.pindoustudio.app.ui.theme.CraftSurface
import com.pindoustudio.app.ui.theme.HairlineBorder
import com.pindoustudio.app.ui.theme.InkCharcoal
import com.pindoustudio.app.ui.theme.InkMuted
import com.pindoustudio.app.ui.theme.ParchmentBg
import com.pindoustudio.app.ui.theme.SageCompletion
import com.pindoustudio.app.ui.theme.SageSoft
import com.pindoustudio.app.ui.theme.TerracottaAccent
import com.pindoustudio.app.ui.theme.TerracottaSoft
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.max
import kotlin.math.roundToInt

@Composable
fun ArchivePortfolioTab(
    state: PindouUiState,
    viewModel: PindouViewModel
) {
    var pendingPickTarget by remember { mutableStateOf<Pair<String, PhotoSlot>?>(null) }
    var lightboxTarget by remember { mutableStateOf<Pair<PortfolioWork, PhotoSlot>?>(null) }
    var renameTarget by remember { mutableStateOf<PortfolioWork?>(null) }

    val slotPhotoPicker = rememberLauncherForActivityResult(
        contract = GalleryImagePickerContract()
    ) { uri ->
        val target = pendingPickTarget
        pendingPickTarget = null
        if (uri != null && target != null) {
            viewModel.attachPortfolioPhoto(target.first, target.second, uri)
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        item {
            CraftStatsDashboardCard(
                stats = state.portfolioStats,
                brand = state.brand,
                viewModel = viewModel
            )
        }

        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = CraftSurface),
                border = BorderStroke(1.dp, TerracottaAccent.copy(alpha = 0.45f))
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                "收录当前图纸到作品馆",
                                fontWeight = FontWeight.Bold,
                                fontSize = 13.5.sp,
                                color = InkCharcoal
                            )
                            Text(
                                "《${state.pattern.name}》· ${state.bom.totalBeads}颗 (${state.bom.colorCount}色) · 自动记入统计盘",
                                fontSize = 11.5.sp,
                                color = InkMuted,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        }
                        Spacer(Modifier.width(8.dp))
                        Button(
                            onClick = viewModel::saveCurrentWorkToPortfolio,
                            colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent),
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp)
                        ) {
                            Text("+ 收录", fontWeight = FontWeight.Bold, fontSize = 12.5.sp)
                        }
                    }

                    HorizontalDivider(color = HairlineBorder)

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                "导入历史外部图纸 / 成品照",
                                fontWeight = FontWeight.Bold,
                                fontSize = 13.sp,
                                color = InkCharcoal
                            )
                            Text(
                                "小红书图纸 / 实拍成品自动识别格数与色号",
                                fontSize = 11.sp,
                                color = InkMuted,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        }
                        Spacer(Modifier.width(8.dp))
                        OutlinedButton(
                            onClick = viewModel::openExternalImportDialog,
                            border = BorderStroke(1.dp, SageCompletion),
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp)
                        ) {
                            Text("智能识别", fontWeight = FontWeight.Bold, fontSize = 12.5.sp, color = SageCompletion)
                        }
                    }
                }
            }
        }

        if (state.portfolioWorks.isEmpty()) {
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = CraftSurface),
                    border = BorderStroke(1.dp, HairlineBorder)
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(20.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        Text("还没有收录的拼豆作品", fontWeight = FontWeight.Bold, color = InkCharcoal)
                        Text(
                            "点击上方「+ 收录」，即可把当前图纸连同【参考图 / 拼豆图纸 / 拼好的图 / 烫好的图】存成组合档案（4张图均为选填），点亮你的专属拼豆成就统计盘。",
                            fontSize = 12.sp,
                            color = InkMuted
                        )
                    }
                }
            }
        } else {
            items(state.portfolioWorks, key = { it.id }) { work ->
                PortfolioWorkCard(
                    work = work,
                    onSlotClick = { slot ->
                        val existing = work.photoPathFor(slot)
                        if (existing != null) {
                            lightboxTarget = work to slot
                        } else {
                            pendingPickTarget = work.id to slot
                            slotPhotoPicker.launch(Unit)
                        }
                    },
                    onToggleCompleted = { viewModel.togglePortfolioCompleted(work.id) },
                    onRename = { renameTarget = work },
                    onLoadToCanvas = { viewModel.loadPortfolioWorkToCanvas(work) },
                    onDelete = { viewModel.deletePortfolioWork(work.id) }
                )
            }
        }
    }

    val lb = lightboxTarget
    if (lb != null) {
        val (work, slot) = lb
        val latestWork = state.portfolioWorks.find { it.id == work.id } ?: work
        val photoPath = latestWork.photoPathFor(slot)
        if (photoPath == null) {
            lightboxTarget = null
        } else {
            PhotoSlotLightboxDialog(
                workTitle = latestWork.title,
                slot = slot,
                photoPath = photoPath,
                onReplace = {
                    lightboxTarget = null
                    pendingPickTarget = latestWork.id to slot
                    slotPhotoPicker.launch(Unit)
                },
                onRemove = {
                    lightboxTarget = null
                    viewModel.removePortfolioPhoto(latestWork.id, slot)
                },
                onDismiss = { lightboxTarget = null }
            )
        }
    }

    val rt = renameTarget
    if (rt != null) {
        RenameWorkDialog(
            initialTitle = rt.title,
            onConfirm = { newTitle ->
                viewModel.renamePortfolioWork(rt.id, newTitle)
                renameTarget = null
            },
            onDismiss = { renameTarget = null }
        )
    }
}

@Composable
private fun CraftStatsDashboardCard(
    stats: PortfolioStats,
    brand: BeadBrand,
    viewModel: PindouViewModel
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = CraftSurface),
        border = BorderStroke(1.dp, HairlineBorder)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("我的拼豆战绩统计盘", fontWeight = FontWeight.Bold, fontSize = 15.5.sp, color = InkCharcoal)
                    Text(
                        if (stats.totalBeads < stats.rankNextGoal) {
                            "距下一称号还差 ${stats.rankNextGoal - stats.totalBeads} 颗豆"
                        } else {
                            "已登顶最高手作里程碑！"
                        },
                        fontSize = 11.5.sp,
                        color = InkMuted
                    )
                }
                Surface(color = TerracottaSoft, shape = RoundedCornerShape(99.dp)) {
                    Text(
                        "★ ${stats.rankTitle}",
                        color = TerracottaAccent,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                    )
                }
            }

            LinearProgressIndicator(
                progress = { stats.rankProgress },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(8.dp)
                    .clip(RoundedCornerShape(99.dp)),
                color = TerracottaAccent,
                trackColor = ParchmentBg
            )

            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatKpiBox(
                    label = "总规划 / 已完工拼豆",
                    value = "${stats.totalBeads} / ${stats.completedBeads} 颗",
                    modifier = Modifier.weight(1f)
                )
                StatKpiBox(
                    label = "收录作品 / 已完工",
                    value = "${stats.totalWorks} / ${stats.completedWorks} 件",
                    modifier = Modifier.weight(1f)
                )
            }
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatKpiBox(
                    label = "累计面积 / 豆链总长",
                    value = "${stats.totalAreaCm2}cm² · ${stats.chainMeters}米",
                    modifier = Modifier.weight(1f)
                )
                StatKpiBox(
                    label = "驾驭色号 / 过程图集",
                    value = "${stats.uniqueColorsUsed} 色 · ${stats.documentedPhotos} 张",
                    modifier = Modifier.weight(1f)
                )
            }

            if (stats.totalBeads > 0L) {
                Surface(
                    color = SageSoft,
                    shape = RoundedCornerShape(9.dp),
                    border = BorderStroke(1.dp, SageCompletion.copy(alpha = 0.28f))
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 10.dp, vertical = 7.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            "排成一排长达 ${stats.chainMeters} 米 · 约占 ${stats.equivalentBoards52} 块 52×52 标准拼板",
                            fontSize = 11.5.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = SageCompletion
                        )
                    }
                }
            }

            // 手作勋章墙 (3x2 里程碑)
            HorizontalDivider(color = HairlineBorder)
            val unlockedCount = stats.achievements.count { it.unlocked }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text("拼豆成就勋章墙", fontWeight = FontWeight.Bold, fontSize = 12.5.sp, color = InkCharcoal)
                Text("已点亮 $unlockedCount / ${stats.achievements.size}", fontSize = 11.sp, fontFamily = FontFamily.Monospace, color = TerracottaAccent, fontWeight = FontWeight.Bold)
            }
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                stats.achievements.chunked(3).forEach { rowBadges ->
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        rowBadges.forEach { badge ->
                            AchievementBadgeTile(badge = badge, modifier = Modifier.weight(1f))
                        }
                    }
                }
            }

            // 个人配色指纹环形图
            if (stats.seriesStats.isNotEmpty() && stats.totalBeads > 0L) {
                HorizontalDivider(color = HairlineBorder)
                Text("个人配色指纹环形图", fontWeight = FontWeight.Bold, fontSize = 12.5.sp, color = InkCharcoal)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    Box(
                        modifier = Modifier.size(110.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Canvas(modifier = Modifier.fillMaxSize()) {
                            val strokeW = 22.dp.toPx()
                            val pad = strokeW / 2f + 2f
                            val arcSize = Size(size.width - pad * 2f, size.height - pad * 2f)
                            var startAngle = -90f
                            val totalSeries = stats.seriesStats.sumOf { it.count }.coerceAtLeast(1L)
                            stats.seriesStats.forEach { s ->
                                val sweep = (s.count.toFloat() / totalSeries) * 360f
                                val rawColor = if (s.sampleArgb == android.graphics.Color.WHITE) Color(0xFFD6CDC0) else Color(s.sampleArgb)
                                drawArc(
                                    color = rawColor,
                                    startAngle = startAngle,
                                    sweepAngle = (sweep - 2.2f).coerceAtLeast(2f),
                                    useCenter = false,
                                    topLeft = Offset(pad, pad),
                                    size = arcSize,
                                    style = Stroke(width = strokeW, cap = StrokeCap.Butt)
                                )
                                startAngle += sweep
                            }
                        }
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("${stats.uniqueColorsUsed}色", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 14.sp, color = InkCharcoal)
                            Text("配色指纹", fontSize = 9.5.sp, color = InkMuted)
                        }
                    }

                    Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        val totalSeries = stats.seriesStats.sumOf { it.count }.coerceAtLeast(1L)
                        stats.seriesStats.forEach { s ->
                            val pct = ((s.count * 100.0) / totalSeries).roundToInt()
                            val dotCol = if (s.sampleArgb == android.graphics.Color.WHITE) Color(0xFFD6CDC0) else Color(s.sampleArgb)
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Box(
                                        modifier = Modifier
                                            .size(9.dp)
                                            .clip(CircleShape)
                                            .background(dotCol)
                                    )
                                    Text(s.label, fontSize = 11.5.sp, color = InkCharcoal)
                                }
                                Text(
                                    "$pct% (${s.count})",
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = InkMuted
                                )
                            }
                        }
                    }
                }
            }

            // 作品肝度对比柱状图
            if (stats.workBars.isNotEmpty()) {
                HorizontalDivider(color = HairlineBorder)
                Text("作品用豆量排行对比（绿=已完工 · 橙=待拼豆）", fontWeight = FontWeight.Bold, fontSize = 12.5.sp, color = InkCharcoal)
                val maxWorkBeads = max(1, stats.workBars.maxOf { it.beads })
                Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    stats.workBars.forEach { wb ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Text(
                                wb.title,
                                fontSize = 11.sp,
                                color = InkCharcoal,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.width(108.dp)
                            )
                            Box(
                                modifier = Modifier
                                    .weight(1f)
                                    .height(10.dp)
                                    .clip(RoundedCornerShape(99.dp))
                                    .background(ParchmentBg)
                            ) {
                                val frac = (wb.beads.toFloat() / maxWorkBeads).coerceIn(0.08f, 1f)
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth(frac)
                                        .height(10.dp)
                                        .clip(RoundedCornerShape(99.dp))
                                        .background(if (wb.completed) SageCompletion else TerracottaAccent)
                                )
                            }
                            Text(
                                "${wb.beads}颗",
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                fontSize = 11.sp,
                                color = if (wb.completed) SageCompletion else InkCharcoal
                            )
                        }
                    }
                }
            }

            // 最爱神仙色号排行 Top 6
            if (stats.topColors.isNotEmpty()) {
                HorizontalDivider(color = HairlineBorder)
                Text("最爱神仙色号排行（${brand.label} 对照）", fontWeight = FontWeight.Bold, fontSize = 12.5.sp, color = InkCharcoal)
                val maxCnt = max(1, stats.topColors.first().count)
                Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    stats.topColors.take(6).forEach { c ->
                        val dispCode = viewModel.paletteRepo.translateCode(c.mardCode, brand)
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(15.dp)
                                    .clip(RoundedCornerShape(4.dp))
                                    .background(Color(c.argb))
                                    .border(1.dp, HairlineBorder, RoundedCornerShape(4.dp))
                            )
                            Text(
                                dispCode,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                fontSize = 11.5.sp,
                                modifier = Modifier.width(46.dp),
                                maxLines = 1
                            )
                            Text(
                                c.nameZh,
                                fontSize = 11.sp,
                                color = InkMuted,
                                modifier = Modifier.width(54.dp),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                            Box(
                                modifier = Modifier
                                    .weight(1f)
                                    .height(9.dp)
                                    .clip(RoundedCornerShape(99.dp))
                                    .background(ParchmentBg)
                            ) {
                                val frac = (c.count.toFloat() / maxCnt).coerceIn(0.08f, 1f)
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth(frac)
                                        .height(9.dp)
                                        .clip(RoundedCornerShape(99.dp))
                                        .background(if (c.argb == android.graphics.Color.WHITE) Color(0xFFD2C8BC) else Color(c.argb))
                                )
                            }
                            Text(
                                "${c.count}",
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 11.sp,
                                color = InkCharcoal
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AchievementBadgeTile(badge: CraftAchievement, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(10.dp),
        color = if (badge.unlocked) TerracottaSoft else ParchmentBg,
        border = BorderStroke(1.dp, if (badge.unlocked) TerracottaAccent.copy(alpha = 0.65f) else HairlineBorder)
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 7.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.dp)
        ) {
            Text(
                if (badge.unlocked) "★ ${badge.title}" else badge.title,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
                color = if (badge.unlocked) TerracottaAccent else InkMuted,
                maxLines = 1
            )
            Text(badge.desc, fontSize = 9.5.sp, color = InkMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                if (badge.unlocked) "已解锁" else badge.progressText,
                fontSize = 9.5.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
                color = if (badge.unlocked) SageCompletion else InkMuted
            )
        }
    }
}

@Composable
private fun StatKpiBox(label: String, value: String, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        color = ParchmentBg,
        shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, HairlineBorder)
    ) {
        Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
            Text(label, fontSize = 10.5.sp, color = InkMuted, maxLines = 1)
            Text(value, fontSize = 12.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, color = InkCharcoal, maxLines = 1)
        }
    }
}

@Composable
private fun PortfolioWorkCard(
    work: PortfolioWork,
    onSlotClick: (PhotoSlot) -> Unit,
    onToggleCompleted: () -> Unit,
    onRename: () -> Unit,
    onLoadToCanvas: () -> Unit,
    onDelete: () -> Unit
) {
    val dateStr = remember(work.createdAt) {
        SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(work.createdAt))
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = CraftSurface),
        border = BorderStroke(1.dp, HairlineBorder)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .clickable { onRename() }
                ) {
                    Text(
                        "${work.title} ✎",
                        fontWeight = FontWeight.Bold,
                        fontSize = 14.sp,
                        color = InkCharcoal,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                    Text(
                        "$dateStr · ${work.width}×${work.height}格 · ${work.totalBeads}颗 (${work.colorCount}色)",
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        color = InkMuted
                    )
                }
                Surface(
                    onClick = onToggleCompleted,
                    shape = RoundedCornerShape(99.dp),
                    color = if (work.isCompleted) SageSoft else ParchmentBg,
                    border = BorderStroke(1.dp, if (work.isCompleted) SageCompletion else HairlineBorder)
                ) {
                    Text(
                        if (work.isCompleted) "✓ 已完工" else "待拼豆",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = if (work.isCompleted) SageCompletion else InkMuted,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp)
                    )
                }
            }

            // 4 个完全可选的组合图槽位：参考图 | 拼豆图纸 | 拼好的图 | 烫好的图
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                PhotoSlot.entries.forEach { slot ->
                    PhotoSlotThumbnail(
                        slot = slot,
                        path = work.photoPathFor(slot),
                        onClick = { onSlotClick(slot) },
                        modifier = Modifier.weight(1f)
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text("点击槽位看图 / 补传", fontSize = 10.5.sp, color = InkMuted)
                Row(horizontalArrangement = Arrangement.spacedBy(0.dp)) {
                    TextButton(onClick = onRename, contentPadding = PaddingValues(horizontal = 6.dp, vertical = 2.dp)) {
                        Text("重命名", fontSize = 12.sp, color = InkCharcoal)
                    }
                    TextButton(onClick = onLoadToCanvas, contentPadding = PaddingValues(horizontal = 6.dp, vertical = 2.dp)) {
                        Text("载入画布", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = TerracottaAccent)
                    }
                    TextButton(onClick = onDelete, contentPadding = PaddingValues(horizontal = 6.dp, vertical = 2.dp)) {
                        Text("删除", fontSize = 12.sp, color = InkMuted)
                    }
                }
            }
        }
    }
}

@Composable
private fun PhotoSlotThumbnail(
    slot: PhotoSlot,
    path: String?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val bmp by produceState<ImageBitmap?>(initialValue = null, key1 = path) {
        value = if (path.isNullOrBlank()) null else withContext(Dispatchers.IO) {
            runCatching { BitmapFactory.decodeFile(path)?.asImageBitmap() }.getOrNull()
        }
    }

    Surface(
        onClick = onClick,
        modifier = modifier.aspectRatio(1f),
        shape = RoundedCornerShape(8.dp),
        color = ParchmentBg,
        border = BorderStroke(1.dp, if (bmp != null) TerracottaAccent.copy(alpha = 0.35f) else HairlineBorder)
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            if (bmp != null) {
                Image(
                    bitmap = bmp!!,
                    contentDescription = slot.label,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize()
                )
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .background(Color(0x99231F1D))
                        .padding(vertical = 2.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(slot.label, fontSize = 9.5.sp, color = Color.White, fontWeight = FontWeight.SemiBold)
                }
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(4.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center
                ) {
                    Box(
                        modifier = Modifier
                            .size(18.dp)
                            .clip(CircleShape)
                            .background(CraftSurface)
                            .border(1.dp, HairlineBorder, CircleShape),
                        contentAlignment = Alignment.Center
                    ) {
                        Text("+", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = TerracottaAccent)
                    }
                    Spacer(Modifier.height(3.dp))
                    Text(slot.label, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = InkCharcoal, maxLines = 1)
                    Text(slot.optionalHint, fontSize = 9.sp, color = InkMuted)
                }
            }
        }
    }
}

@Composable
private fun PhotoSlotLightboxDialog(
    workTitle: String,
    slot: PhotoSlot,
    photoPath: String,
    onReplace: () -> Unit,
    onRemove: () -> Unit,
    onDismiss: () -> Unit
) {
    val bmp by produceState<ImageBitmap?>(initialValue = null, key1 = photoPath) {
        value = withContext(Dispatchers.IO) {
            runCatching { BitmapFactory.decodeFile(photoPath)?.asImageBitmap() }.getOrNull()
        }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Card(
            modifier = Modifier
                .fillMaxWidth(0.92f)
                .padding(8.dp),
            colors = CardDefaults.cardColors(containerColor = CraftSurface),
            shape = RoundedCornerShape(16.dp)
        ) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("${slot.label} · $workTitle", fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    TextButton(onClick = onDismiss) { Text("关闭") }
                }
                if (bmp != null) {
                    Image(
                        bitmap = bmp!!,
                        contentDescription = slot.label,
                        contentScale = ContentScale.Fit,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(340.dp)
                            .clip(RoundedCornerShape(10.dp))
                            .background(ParchmentBg)
                    )
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    OutlinedButton(onClick = onRemove, modifier = Modifier.weight(1f)) {
                        Text("清除此图")
                    }
                    Button(
                        onClick = onReplace,
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent)
                    ) {
                        Text("从相册替换")
                    }
                }
            }
        }
    }
}

@Composable
private fun RenameWorkDialog(
    initialTitle: String,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit
) {
    var draft by remember(initialTitle) { mutableStateOf(initialTitle) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = CraftSurface,
        title = { Text("重命名作品", fontWeight = FontWeight.Bold, color = InkCharcoal) },
        text = {
            OutlinedTextField(
                value = draft,
                onValueChange = { draft = it },
                label = { Text("作品名称") },
                placeholder = { Text("输入容易辨认的名字") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消", color = InkMuted) }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(draft) },
                enabled = draft.trim().isNotEmpty(),
                colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent)
            ) { Text("保存") }
        }
    )
}
