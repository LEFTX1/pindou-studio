package com.pindoustudio.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.pindoustudio.app.engine.DetectedSourceType
import com.pindoustudio.app.engine.ExternalImportHint
import com.pindoustudio.app.ui.theme.CraftSurface
import com.pindoustudio.app.ui.theme.HairlineBorder
import com.pindoustudio.app.ui.theme.InkCharcoal
import com.pindoustudio.app.ui.theme.InkMuted
import com.pindoustudio.app.ui.theme.ParchmentBg
import com.pindoustudio.app.ui.theme.SageCompletion
import com.pindoustudio.app.ui.theme.SageSoft
import com.pindoustudio.app.ui.theme.TerracottaAccent
import com.pindoustudio.app.ui.theme.TerracottaSoft
import kotlin.math.roundToInt

@Composable
fun ExternalImportDialog(
    state: PindouUiState,
    viewModel: PindouViewModel
) {
    if (!state.showExternalImportDialog) return

    val picker = rememberLauncherForActivityResult(
        contract = GalleryImagePickerContract()
    ) { uri ->
        if (uri != null) viewModel.pickExternalImportUri(uri)
    }

    Dialog(
        onDismissRequest = viewModel::dismissExternalImportDialog,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 20.dp),
            shape = RoundedCornerShape(18.dp),
            color = CraftSurface
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
                    .padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            "智能识别导入历史作品",
                            fontWeight = FontWeight.Bold,
                            fontSize = 16.sp,
                            color = InkCharcoal
                        )
                        Text(
                            "支持小红书/其他软件图纸、或实拍拼好/烫好成品照",
                            fontSize = 11.5.sp,
                            color = InkMuted
                        )
                    }
                    TextButton(onClick = viewModel::dismissExternalImportDialog) {
                        Text("关闭", color = TerracottaAccent, fontWeight = FontWeight.Bold)
                    }
                }

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    ExternalImportHint.entries.forEach { hint ->
                        FilterChip(
                            selected = state.externalImportHint == hint,
                            onClick = { viewModel.updateExternalImportOptions(hint = hint) },
                            label = { Text(hint.label, fontSize = 12.sp) }
                        )
                    }
                }

                Button(
                    onClick = {
                        picker.launch(Unit)
                    },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent)
                ) {
                    Text(
                        if (state.externalImportSourceBmp == null) "从相册选图纸 / 成品照" else "重新从相册换图",
                        fontWeight = FontWeight.Bold
                    )
                }

                if (state.isRecognizingExternal) {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = ParchmentBg),
                        border = BorderStroke(1.dp, HairlineBorder)
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                strokeWidth = 2.5.dp,
                                color = TerracottaAccent
                            )
                            Text("正在离线识别网格周期与色号…", fontSize = 12.5.sp, color = InkCharcoal)
                        }
                    }
                }

                val res = state.externalImportResult
                val srcBmp = state.externalImportSourceBmp
                val prevBmp = state.externalImportPreviewBmp
                if (!state.isRecognizingExternal && res != null && srcBmp != null) {
                    val pat = res.pattern
                    val beads = pat.cells.count { !it.isNullOrBlank() }
                    val colors = pat.cells.asSequence().filterNotNull().distinct().count()

                    Card(
                        colors = CardDefaults.cardColors(containerColor = ParchmentBg),
                        border = BorderStroke(1.dp, HairlineBorder)
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(10.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                Column(
                                    modifier = Modifier.weight(1f),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    verticalArrangement = Arrangement.spacedBy(4.dp)
                                ) {
                                    Image(
                                        bitmap = srcBmp.asImageBitmap(),
                                        contentDescription = "待识别原图",
                                        contentScale = ContentScale.Fit,
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .height(130.dp)
                                            .clip(RoundedCornerShape(8.dp))
                                            .background(CraftSurface)
                                    )
                                    Text("原图", fontSize = 11.sp, color = InkMuted)
                                }
                                Column(
                                    modifier = Modifier.weight(1f),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    verticalArrangement = Arrangement.spacedBy(4.dp)
                                ) {
                                    if (prevBmp != null) {
                                        Image(
                                            bitmap = prevBmp.asImageBitmap(),
                                            contentDescription = "识别还原图",
                                            contentScale = ContentScale.Fit,
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .height(130.dp)
                                                .clip(RoundedCornerShape(8.dp))
                                                .background(CraftSurface)
                                        )
                                    } else {
                                        Box(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .height(130.dp)
                                                .clip(RoundedCornerShape(8.dp))
                                                .background(CraftSurface)
                                        )
                                    }
                                    Text("识别还原图", fontSize = 11.sp, color = SageCompletion, fontWeight = FontWeight.SemiBold)
                                }
                            }

                            Surface(
                                color = if (res.detectedType == DetectedSourceType.EXTERNAL_CHART) SageSoft else TerracottaSoft,
                                shape = RoundedCornerShape(8.dp)
                            ) {
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(horizontal = 10.dp, vertical = 7.dp),
                                    verticalArrangement = Arrangement.spacedBy(2.dp)
                                ) {
                                    Text(
                                        "${res.detectedType.label} · ${pat.width}×${pat.height}格 · ${beads}颗 · ${colors}色",
                                        fontWeight = FontWeight.Bold,
                                        fontFamily = FontFamily.Monospace,
                                        fontSize = 12.sp,
                                        color = if (res.detectedType == DetectedSourceType.EXTERNAL_CHART) SageCompletion else TerracottaAccent
                                    )
                                    Text(
                                        res.confidenceLabel,
                                        fontSize = 11.sp,
                                        color = InkMuted,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis
                                    )
                                }
                            }
                        }
                    }

                    OutlinedTextField(
                        value = state.externalImportTitle,
                        onValueChange = { viewModel.updateExternalImportOptions(title = it) },
                        label = { Text("作品名称") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )

                    if (res.detectedType != DetectedSourceType.EXTERNAL_CHART || state.externalImportCustomW != null) {
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text("格数宽度微调 / 实物用色上限", fontSize = 11.5.sp, color = InkMuted, fontWeight = FontWeight.SemiBold)
                            Row(
                                modifier = Modifier.horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                listOf<Int?>(null, 29, 36, 48, 52).forEach { wOpt ->
                                    FilterChip(
                                        selected = state.externalImportCustomW == wOpt,
                                        onClick = {
                                            if (wOpt == null) {
                                                viewModel.updateExternalImportOptions(customW = null, customH = null, clearCustomSize = true)
                                            } else {
                                                val aspect = srcBmp.height.toFloat() / srcBmp.width.coerceAtLeast(1)
                                                val hOpt = (wOpt * aspect).roundToInt().coerceIn(12, 96)
                                                viewModel.updateExternalImportOptions(customW = wOpt, customH = hOpt)
                                            }
                                        },
                                        label = { Text(if (wOpt == null) "自动" else "${wOpt}格", fontSize = 11.5.sp) }
                                    )
                                }
                                listOf(10, 14, 20).forEach { capOpt ->
                                    FilterChip(
                                        selected = state.externalImportCraftColors == capOpt,
                                        onClick = { viewModel.updateExternalImportOptions(craftColors = capOpt) },
                                        label = { Text("${capOpt}色", fontSize = 11.5.sp) }
                                    )
                                }
                            }
                        }
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            "标记为已完工（计入成品战绩）",
                            fontSize = 12.5.sp,
                            color = InkCharcoal
                        )
                        Switch(
                            checked = state.externalImportMarkCompleted,
                            onCheckedChange = { viewModel.updateExternalImportOptions(markCompleted = it) }
                        )
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OutlinedButton(
                            onClick = viewModel::loadRecognizedWorkToCanvas,
                            modifier = Modifier.weight(1f),
                            contentPadding = PaddingValues(vertical = 10.dp)
                        ) {
                            Text("载入画布精修", fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold)
                        }
                        Button(
                            onClick = viewModel::saveRecognizedWorkToPortfolio,
                            modifier = Modifier.weight(1f),
                            colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent),
                            contentPadding = PaddingValues(vertical = 10.dp)
                        ) {
                            Text("收录进作品馆", fontSize = 12.5.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                } else if (!state.isRecognizingExternal && srcBmp == null) {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = ParchmentBg),
                        border = BorderStroke(1.dp, HairlineBorder)
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            Text("支持导入的图源示例：", fontWeight = FontWeight.Bold, fontSize = 12.5.sp, color = InkCharcoal)
                            Text("• 小红书 / 其他拼豆生成器导出的 MARD 网格图纸（自动剥离标尺并避让字码提取纯色与格数）", fontSize = 11.5.sp, color = InkMuted)
                            Text("• 以前拼好或烫好的实物豆画照片（自动抠除桌面与豆孔反光，换算成可编辑图纸与用豆统计）", fontSize = 11.5.sp, color = InkMuted)
                        }
                    }
                }
            }
        }
    }
}
