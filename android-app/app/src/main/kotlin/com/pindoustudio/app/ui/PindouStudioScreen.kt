package com.pindoustudio.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pindoustudio.app.R
import com.pindoustudio.app.model.BeadBrand
import com.pindoustudio.app.model.BeadDiameter
import com.pindoustudio.app.model.ConvertMode
import com.pindoustudio.app.model.DOMESTIC_BOARD_PRESETS
import com.pindoustudio.app.model.DrawTool
import com.pindoustudio.app.model.MainTab
import com.pindoustudio.app.model.ViewMode
import com.pindoustudio.app.model.calcPhysicalSpec
import com.pindoustudio.app.ui.theme.CraftSurface
import com.pindoustudio.app.ui.theme.HairlineBorder
import com.pindoustudio.app.ui.theme.InkCharcoal
import com.pindoustudio.app.ui.theme.InkMuted
import com.pindoustudio.app.ui.theme.ParchmentBg
import com.pindoustudio.app.ui.theme.SageCompletion
import com.pindoustudio.app.ui.theme.SageSoft
import com.pindoustudio.app.ui.theme.TerracottaAccent
import com.pindoustudio.app.ui.theme.TerracottaSoft
import kotlin.math.max
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PindouStudioScreen(viewModel: PindouViewModel) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    var showSamplesDialog by remember { mutableStateOf(false) }
    var showExportMenu by remember { mutableStateOf(false) }
    var showPaletteSheet by remember { mutableStateOf(false) }
    var showRenameCurrentDialog by remember { mutableStateOf(false) }
    var fitTrigger by remember { mutableIntStateOf(0) }

    LaunchedEffect(state.toastMessage) {
        val msg = state.toastMessage
        if (msg != null) {
            snackbarHostState.showSnackbar(msg)
            viewModel.clearToast()
        }
    }

    Scaffold(
        containerColor = ParchmentBg,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = CraftSurface),
                title = {
                    Column(modifier = Modifier.clickable { viewModel.openAboutUpdateDialog() }) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                            Image(
                                painter = painterResource(R.drawable.ic_brand_logo),
                                contentDescription = "豆绘工坊 Logo",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier
                                    .size(26.dp)
                                    .clip(RoundedCornerShape(7.dp))
                                    .border(1.dp, HairlineBorder, RoundedCornerShape(7.dp))
                            )
                            Text("豆绘工坊", fontWeight = FontWeight.Bold, fontSize = 18.sp, color = InkCharcoal)
                            Surface(color = TerracottaSoft, shape = RoundedCornerShape(99.dp)) {
                                Text(
                                    "${state.diameter.shortLabel} · ${state.brand.label}",
                                    color = TerracottaAccent,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    modifier = Modifier.padding(horizontal = 7.dp, vertical = 2.dp)
                                )
                            }
                        }
                        Text(
                            "✎ ${state.pattern.name} · ${state.pattern.width}×${state.pattern.height}格 · ${state.bom.totalBeads}颗 (${state.bom.physical.widthCm}×${state.bom.physical.heightCm}cm)",
                            fontSize = 11.sp,
                            color = InkMuted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.clickable { showRenameCurrentDialog = true }
                        )
                    }
                },
                actions = {
                    TextButton(
                        onClick = viewModel::openAboutUpdateDialog,
                        contentPadding = PaddingValues(horizontal = 6.dp, vertical = 4.dp)
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(3.dp)
                        ) {
                            Text("更新", fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                            if (state.hasAvailableUpdate) {
                                Box(
                                    modifier = Modifier
                                        .size(7.dp)
                                        .clip(CircleShape)
                                        .background(TerracottaAccent)
                                )
                            }
                        }
                    }
                    TextButton(
                        onClick = { showSamplesDialog = true },
                        contentPadding = PaddingValues(horizontal = 6.dp, vertical = 4.dp)
                    ) {
                        Text("作品库", fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    }
                    Box {
                        TextButton(
                            onClick = { showExportMenu = true },
                            contentPadding = PaddingValues(horizontal = 6.dp, vertical = 4.dp)
                        ) {
                            Text("导出", fontWeight = FontWeight.Bold, fontSize = 13.sp, color = TerracottaAccent)
                        }
                        DropdownMenu(expanded = showExportMenu, onDismissRequest = { showExportMenu = false }) {
                            DropdownMenuItem(
                                text = { Text("重命名当前作品", fontWeight = FontWeight.SemiBold, color = InkCharcoal) },
                                onClick = { showExportMenu = false; showRenameCurrentDialog = true }
                            )
                            DropdownMenuItem(
                                text = { Text("收录到作品馆（存图纸/实物对照）", fontWeight = FontWeight.SemiBold, color = TerracottaAccent) },
                                onClick = { showExportMenu = false; viewModel.saveCurrentWorkToPortfolio() }
                            )
                            HorizontalDivider(color = HairlineBorder)
                            DropdownMenuItem(
                                text = { Text("保存 ${state.brand.label} 施工图到相册 (PNG)") },
                                onClick = { showExportMenu = false; viewModel.exportSheetPng() }
                            )
                            DropdownMenuItem(
                                text = { Text("保存 2.6mm 熨烫图到相册 (JPG)") },
                                onClick = { showExportMenu = false; viewModel.exportBakedJpg() }
                            )
                            DropdownMenuItem(
                                text = { Text("保存五品牌清单到下载 (CSV)") },
                                onClick = { showExportMenu = false; viewModel.exportCsv() }
                            )
                            DropdownMenuItem(
                                text = { Text("保存 .pindou.json 工程到下载") },
                                onClick = { showExportMenu = false; viewModel.exportPindouJson() }
                            )
                            DropdownMenuItem(
                                text = { Text("分享施工图给其他应用…") },
                                onClick = { showExportMenu = false; viewModel.shareSheetPng() }
                            )
                        }
                    }
                }
            )
        },
        bottomBar = {
            NavigationBar(containerColor = CraftSurface) {
                MainTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = state.activeTab == tab,
                        onClick = { viewModel.selectTab(tab) },
                        icon = {
                            val badge = when (tab) {
                                MainTab.CANVAS -> "拼"
                                MainTab.BOM -> "${state.bom.colorCount}"
                                MainTab.CONVERT -> "图"
                                MainTab.ARCHIVE -> "${state.portfolioWorks.size}"
                            }
                            Box(
                                modifier = Modifier
                                    .size(26.dp)
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(if (state.activeTab == tab) TerracottaSoft else ParchmentBg),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    badge,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = if (state.activeTab == tab) TerracottaAccent else InkMuted
                                )
                            }
                        },
                        label = { Text(tab.label, fontSize = 11.sp, maxLines = 1, fontWeight = FontWeight.SemiBold) }
                    )
                }
            }
        }
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            when (state.activeTab) {
                MainTab.CANVAS -> CanvasWorkspaceTab(
                    state = state,
                    viewModel = viewModel,
                    fitTrigger = fitTrigger,
                    onFitClick = { fitTrigger++ },
                    onOpenPalette = { showPaletteSheet = true }
                )
                MainTab.BOM -> BomChecklistTab(
                    state = state,
                    onSelectBrand = viewModel::selectBrand,
                    onSelectDiameter = viewModel::selectDiameter,
                    onColorClick = { code ->
                        viewModel.toggleHighlightColor(code)
                        viewModel.selectTab(MainTab.CANVAS)
                    },
                    onClearHighlight = viewModel::clearHighlight,
                    onCopyBom = viewModel::copyBomToClipboard,
                    onOpenPalette = { showPaletteSheet = true }
                )
                MainTab.CONVERT -> PhotoConvertTab(
                    state = state,
                    viewModel = viewModel
                )
                MainTab.ARCHIVE -> ArchivePortfolioTab(
                    state = state,
                    viewModel = viewModel
                )
            }
        }
    }

    if (showSamplesDialog) {
        AlertDialog(
            onDismissRequest = { showSamplesDialog = false },
            containerColor = CraftSurface,
            title = { Text("内置猫咪作品库 & 空白拼板", fontWeight = FontWeight.Bold) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    state.samples.forEach { sample ->
                        Card(
                            onClick = { showSamplesDialog = false; viewModel.loadSample(sample) },
                            colors = CardDefaults.cardColors(containerColor = ParchmentBg),
                            border = BorderStroke(1.dp, HairlineBorder)
                        ) {
                            Column(modifier = Modifier.fillMaxWidth().padding(12.dp)) {
                                Text(sample.title, fontWeight = FontWeight.Bold, color = InkCharcoal)
                                Text(sample.subtitle, fontSize = 12.sp, color = InkMuted)
                            }
                        }
                    }
                    HorizontalDivider(color = HairlineBorder)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = { showSamplesDialog = false; viewModel.createBlankPattern(29, 29) },
                            modifier = Modifier.weight(1f)
                        ) { Text("空白 29×29") }
                        OutlinedButton(
                            onClick = { showSamplesDialog = false; viewModel.createBlankPattern(52, 52) },
                            modifier = Modifier.weight(1f)
                        ) { Text("空白 52×52") }
                    }
                }
            },
            dismissButton = {
                TextButton(
                    onClick = { showSamplesDialog = false; viewModel.checkForUpdate(manual = true) },
                    enabled = !state.isCheckingUpdate
                ) {
                    Text(if (state.isCheckingUpdate) "检查更新中…" else "检查更新 v${state.appVersionName}")
                }
            },
            confirmButton = {
                TextButton(onClick = { showSamplesDialog = false }) { Text("关闭") }
            }
        )
    }

    if (state.showAboutUpdateDialog) {
        AlertDialog(
            onDismissRequest = viewModel::dismissAboutUpdateDialog,
            containerColor = CraftSurface,
            title = {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Image(
                        painter = painterResource(R.drawable.ic_brand_logo),
                        contentDescription = "豆绘工坊 Logo",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .size(34.dp)
                            .clip(RoundedCornerShape(9.dp))
                            .border(1.dp, HairlineBorder, RoundedCornerShape(9.dp))
                    )
                    Column {
                        Text("豆绘工坊 v${state.appVersionName}", fontWeight = FontWeight.Bold, fontSize = 16.sp, color = InkCharcoal)
                        Text("免费开源 · 纯离线 · 零广告（Build ${state.appVersionCode}）", fontSize = 11.sp, color = InkMuted)
                    }
                }
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = ParchmentBg),
                        border = BorderStroke(1.dp, HairlineBorder)
                    ) {
                        Column(
                            modifier = Modifier.fillMaxWidth().padding(10.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Text("GitHub 开源仓库地址", fontWeight = FontWeight.Bold, fontSize = 12.sp, color = InkCharcoal)
                            Text(
                                com.pindoustudio.app.update.AppUpdater.GITHUB_REPO_URL,
                                fontSize = 11.5.sp,
                                fontFamily = FontFamily.Monospace,
                                color = TerracottaAccent,
                                modifier = Modifier.clickable { viewModel.openGitHubRepo() }
                            )
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedButton(
                                    onClick = viewModel::copyGitHubRepoUrl,
                                    modifier = Modifier.weight(1f),
                                    contentPadding = PaddingValues(vertical = 6.dp)
                                ) { Text("复制地址", fontSize = 12.sp) }
                                OutlinedButton(
                                    onClick = viewModel::openGitHubRepo,
                                    modifier = Modifier.weight(1f),
                                    border = BorderStroke(1.dp, TerracottaAccent),
                                    contentPadding = PaddingValues(vertical = 6.dp)
                                ) { Text("打开 GitHub", fontSize = 12.sp, color = TerracottaAccent) }
                            }
                        }
                    }

                    Card(
                        colors = CardDefaults.cardColors(containerColor = ParchmentBg),
                        border = BorderStroke(1.dp, if (state.hasAvailableUpdate) TerracottaAccent else HairlineBorder)
                    ) {
                        Column(
                            modifier = Modifier.fillMaxWidth().padding(10.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Text("云端版本检测（跨版本合并直达）", fontWeight = FontWeight.Bold, fontSize = 12.sp, color = InkCharcoal)
                            Text(
                                "即使隔了多个版本才打开，点击检查更新也会一次性拉取最新版直装并保留全部本地作品。",
                                fontSize = 11.5.sp,
                                color = InkMuted
                            )
                            val statusText = state.updateCheckStatusText
                            if (!statusText.isNullOrBlank()) {
                                Text(
                                    statusText,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = if (state.hasAvailableUpdate) TerracottaAccent else SageCompletion
                                )
                            }
                        }
                    }
                }
            },
            dismissButton = {
                TextButton(onClick = viewModel::dismissAboutUpdateDialog) { Text("关闭", color = InkMuted) }
            },
            confirmButton = {
                Button(
                    onClick = { viewModel.checkForUpdate(manual = true) },
                    enabled = !state.isCheckingUpdate,
                    colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent)
                ) {
                    if (state.isCheckingUpdate) {
                        CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp, color = CraftSurface)
                        Spacer(Modifier.width(6.dp))
                        Text("正在检测…")
                    } else {
                        Text(if (state.hasAvailableUpdate) "立即更新到最新版" else "检查更新", fontWeight = FontWeight.Bold)
                    }
                }
            }
        )
    }

    val updManifest = state.updateManifest
    if (state.showUpdateDialog && updManifest != null) {
        val mergedSummary = remember(updManifest, state.appVersionCode) {
            updManifest.buildMergedSummary(state.appVersionCode)
        }
        AlertDialog(
            onDismissRequest = viewModel::dismissUpdateDialog,
            containerColor = CraftSurface,
            title = { Text("发现新版本 v${updManifest.versionName}", fontWeight = FontWeight.Bold, color = InkCharcoal) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (mergedSummary.skippedCount > 1) {
                        Surface(
                            color = TerracottaSoft,
                            shape = RoundedCornerShape(8.dp),
                            border = BorderStroke(1.dp, TerracottaAccent.copy(alpha = 0.45f))
                        ) {
                            Text(
                                "已为您合并跳过期间的 ${mergedSummary.skippedCount} 个版本，一次更新直达 v${updManifest.versionName}（保留作品数据）",
                                fontSize = 11.5.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = TerracottaAccent,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                            )
                        }
                    }
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 220.dp)
                            .verticalScroll(rememberScrollState())
                    ) {
                        Text(mergedSummary.mergedChangelog, fontSize = 13.sp, color = InkCharcoal)
                    }
                    Text(
                        "开源主页：${updManifest.repoUrl}",
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        color = InkMuted,
                        modifier = Modifier.clickable { viewModel.openGitHubRepo() }
                    )
                    val prog = state.updateProgress
                    if (prog != null) {
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            LinearProgressIndicator(
                                progress = { prog.coerceIn(0f, 1f) },
                                modifier = Modifier.fillMaxWidth(),
                                color = TerracottaAccent
                            )
                            Text(
                                if (state.downloadedApk != null) "校验通过，准备安装 (SHA-256 已验证)"
                                else "正在从国内高速节点下载… ${(prog * 100).roundToInt()}%",
                                fontSize = 11.5.sp,
                                color = InkMuted
                            )
                        }
                    }
                    if (!state.updateError.isNullOrBlank()) {
                        Text(state.updateError!!, fontSize = 12.sp, color = TerracottaAccent)
                    }
                }
            },
            dismissButton = {
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (updManifest.fallbackPageUrl.isNotBlank()) {
                        TextButton(onClick = viewModel::openFallbackUpdatePage) {
                            Text("浏览器备用下载")
                        }
                    }
                    if (!updManifest.forceUpdate) {
                        TextButton(onClick = viewModel::dismissUpdateDialog) { Text("稍后") }
                    }
                }
            },
            confirmButton = {
                when {
                    state.downloadedApk != null -> {
                        Button(
                            onClick = viewModel::installDownloadedApk,
                            colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent)
                        ) { Text("立即安装") }
                    }
                    state.updateProgress != null -> {
                        Button(onClick = {}, enabled = false) { Text("下载中…") }
                    }
                    else -> {
                        Button(
                            onClick = viewModel::startUpdateDownload,
                            colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent)
                        ) { Text("立即更新") }
                    }
                }
            }
        )
    }

    if (showPaletteSheet) {
        PalettePickerSheet(
            state = state,
            viewModel = viewModel,
            onDismiss = { showPaletteSheet = false }
        )
    }

    ExternalImportDialog(
        state = state,
        viewModel = viewModel
    )

    if (showRenameCurrentDialog) {
        var draftTitle by remember(state.pattern.name) { mutableStateOf(state.pattern.name) }
        AlertDialog(
            onDismissRequest = { showRenameCurrentDialog = false },
            containerColor = CraftSurface,
            title = { Text("重命名当前作品", fontWeight = FontWeight.Bold, color = InkCharcoal) },
            text = {
                OutlinedTextField(
                    value = draftTitle,
                    onValueChange = { draftTitle = it },
                    label = { Text("作品名称") },
                    placeholder = { Text("例如：蓝床单小白猫") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            },
            dismissButton = {
                TextButton(onClick = { showRenameCurrentDialog = false }) { Text("取消", color = InkMuted) }
            },
            confirmButton = {
                Button(
                    onClick = {
                        viewModel.renameCurrentPattern(draftTitle)
                        showRenameCurrentDialog = false
                    },
                    enabled = draftTitle.trim().isNotEmpty(),
                    colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent)
                ) { Text("保存") }
            }
        )
    }
}

@Composable
private fun DomesticStandardStrip(
    selectedBrand: BeadBrand,
    selectedDiameter: BeadDiameter,
    bomSummaryText: String,
    onSelectBrand: (BeadBrand) -> Unit,
    onSelectDiameter: (BeadDiameter) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(CraftSurface)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            BeadBrand.entries.forEach { b ->
                FilterChip(
                    selected = selectedBrand == b,
                    onClick = { onSelectBrand(b) },
                    label = { Text(b.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = TerracottaSoft,
                        selectedLabelColor = TerracottaAccent
                    )
                )
            }
            Spacer(Modifier.width(4.dp))
            BeadDiameter.entries.forEach { d ->
                FilterChip(
                    selected = selectedDiameter == d,
                    onClick = { onSelectDiameter(d) },
                    label = { Text(d.shortLabel, fontSize = 12.sp, fontFamily = FontFamily.Monospace) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = SageSoft,
                        selectedLabelColor = SageCompletion
                    )
                )
            }
        }
        Text(
            bomSummaryText,
            fontSize = 11.5.sp,
            fontFamily = FontFamily.Monospace,
            color = InkMuted
        )
    }
}

@Composable
private fun CanvasWorkspaceTab(
    state: PindouUiState,
    viewModel: PindouViewModel,
    fitTrigger: Int,
    onFitClick: () -> Unit,
    onOpenPalette: () -> Unit
) {
    var showBrandMenu by remember { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxSize()) {
        // 简洁顶部控制条：色号图 / 成品预览 + 品牌切换 + 显隐号 / 居中
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(CraftSurface)
                .padding(horizontal = 10.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                ViewMode.entries.forEach { vm ->
                    val selected = state.viewMode == vm
                    Surface(
                        onClick = { viewModel.selectViewMode(vm) },
                        shape = RoundedCornerShape(8.dp),
                        color = if (selected) InkCharcoal else ParchmentBg,
                        border = BorderStroke(1.dp, if (selected) InkCharcoal else HairlineBorder)
                    ) {
                        Text(
                            vm.label,
                            color = if (selected) CraftSurface else InkCharcoal,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.padding(horizontal = 11.dp, vertical = 6.dp)
                        )
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.CenterVertically) {
                Box {
                    TextButton(onClick = { showBrandMenu = true }, contentPadding = PaddingValues(horizontal = 6.dp)) {
                        Text("${state.brand.label} ▾", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = TerracottaAccent)
                    }
                    DropdownMenu(expanded = showBrandMenu, onDismissRequest = { showBrandMenu = false }) {
                        BeadBrand.entries.forEach { b ->
                            DropdownMenuItem(
                                text = { Text(b.label, fontWeight = if (b == state.brand) FontWeight.Bold else FontWeight.Normal) },
                                onClick = { showBrandMenu = false; viewModel.selectBrand(b) }
                            )
                        }
                    }
                }
                if (state.viewMode == ViewMode.GRID) {
                    TextButton(onClick = viewModel::toggleShowCodes, contentPadding = PaddingValues(horizontal = 6.dp)) {
                        Text(if (state.showCodes) "隐号" else "显号", fontSize = 12.sp)
                    }
                }
                TextButton(onClick = onFitClick, contentPadding = PaddingValues(horizontal = 6.dp)) {
                    Text("居中", fontSize = 12.sp)
                }
            }
        }
        HorizontalDivider(color = HairlineBorder)

        if (state.highlightCode != null && state.viewMode == ViewMode.GRID) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(TerracottaSoft)
                    .padding(horizontal = 12.dp, vertical = 5.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    "正在单独高亮：${state.brand.label} ${viewModel.paletteRepo.translateCode(state.highlightCode, state.brand)}",
                    color = TerracottaAccent,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 12.sp
                )
                TextButton(onClick = viewModel::clearHighlight, contentPadding = PaddingValues(horizontal = 8.dp)) {
                    Text("取消高亮", fontSize = 12.sp)
                }
            }
        }

        // 交互式高精拼豆画布（成品预览下独占全屏视野，无冗余干扰条）
        BeadCanvasView(
            pattern = state.pattern,
            paletteRepo = viewModel.paletteRepo,
            brand = state.brand,
            viewMode = state.viewMode,
            highlightCode = state.highlightCode,
            showCodes = state.showCodes,
            showGrid = state.showGrid,
            fitTrigger = fitTrigger,
            onCellTap = viewModel::onCellTap,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
        )

        // 底部绘制工具与当前画笔条（仅在色号图编辑模式显示）
        if (state.viewMode == ViewMode.GRID) {
            HorizontalDivider(color = HairlineBorder)
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(CraftSurface)
                    .padding(horizontal = 10.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                Text(state.lastTappedCoord, fontSize = 11.sp, fontFamily = FontFamily.Monospace, color = InkMuted)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        DrawTool.entries.forEach { tool ->
                            val active = state.drawTool == tool
                            Surface(
                                onClick = { viewModel.selectDrawTool(tool) },
                                shape = RoundedCornerShape(7.dp),
                                color = if (active) TerracottaAccent else ParchmentBg
                            ) {
                                Text(
                                    tool.label,
                                    color = if (active) CraftSurface else InkCharcoal,
                                    fontSize = 11.5.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp)
                                )
                            }
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                        TextButton(onClick = viewModel::undo, enabled = state.canUndo, contentPadding = PaddingValues(horizontal = 6.dp)) {
                            Text("撤销", fontSize = 12.sp)
                        }
                        TextButton(onClick = viewModel::redo, enabled = state.canRedo, contentPadding = PaddingValues(horizontal = 6.dp)) {
                            Text("重做", fontSize = 12.sp)
                        }
                        val brushEntry = viewModel.paletteRepo.findByMardCode(state.brushCode)
                        Surface(
                            onClick = onOpenPalette,
                            shape = RoundedCornerShape(8.dp),
                            color = ParchmentBg,
                            border = BorderStroke(1.dp, HairlineBorder)
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(5.dp)
                            ) {
                                Box(
                                    modifier = Modifier
                                        .size(14.dp)
                                        .clip(CircleShape)
                                        .background(Color(brushEntry?.argb ?: android.graphics.Color.WHITE))
                                        .border(1.dp, HairlineBorder, CircleShape)
                                )
                                Text(
                                    viewModel.paletteRepo.translateCode(state.brushCode, state.brand),
                                    fontSize = 12.sp,
                                    fontFamily = FontFamily.Monospace,
                                    fontWeight = FontWeight.Bold
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun BomChecklistTab(
    state: PindouUiState,
    onSelectBrand: (BeadBrand) -> Unit,
    onSelectDiameter: (BeadDiameter) -> Unit,
    onColorClick: (String) -> Unit,
    onClearHighlight: () -> Unit,
    onCopyBom: () -> Unit,
    onOpenPalette: () -> Unit
) {
    val phys = state.bom.physical
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item {
            DomesticStandardStrip(
                selectedBrand = state.brand,
                selectedDiameter = state.diameter,
                bomSummaryText = "国内 5 品牌色号实时转换 · ${phys.width}×${phys.height}格",
                onSelectBrand = onSelectBrand,
                onSelectDiameter = onSelectDiameter
            )
            Spacer(Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                KpiCard("网格尺寸", "${phys.width}×${phys.height} 格", Modifier.weight(1f))
                KpiCard("实拼 / 备豆", "${state.bom.totalBeads} / ${state.bom.totalSpareBeads}", Modifier.weight(1f))
            }
            Spacer(Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                KpiCard("${phys.beadMm}mm 成品", "${phys.widthCm}×${phys.heightCm} cm", Modifier.weight(1f))
                KpiCard("${phys.boardSize}×${phys.boardSize} 拼板", "${phys.boardsX}×${phys.boardsY} (${phys.totalBoards}块)", Modifier.weight(1f))
            }
            Spacer(Modifier.height(10.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text("共 ${state.bom.colorCount} 色 · 点击色号定位", fontSize = 12.sp, color = InkMuted)
                Row(horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (state.highlightCode != null) {
                        TextButton(onClick = onClearHighlight, contentPadding = PaddingValues(horizontal = 6.dp)) { Text("取消高亮", fontSize = 12.sp) }
                    }
                    TextButton(onClick = onCopyBom, contentPadding = PaddingValues(horizontal = 6.dp)) { Text("复制清单", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = TerracottaAccent) }
                    TextButton(onClick = onOpenPalette, contentPadding = PaddingValues(horizontal = 6.dp)) { Text("全色卡", fontSize = 12.sp) }
                }
            }
        }

        items(state.bom.items, key = { it.mardCode }) { item ->
            val isolated = state.highlightCode == item.mardCode
            Card(
                onClick = { onColorClick(item.mardCode) },
                colors = CardDefaults.cardColors(containerColor = if (isolated) TerracottaSoft else CraftSurface),
                border = BorderStroke(1.dp, if (isolated) TerracottaAccent else HairlineBorder)
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(28.dp)
                            .clip(RoundedCornerShape(7.dp))
                            .background(Color(item.color.argb))
                            .border(1.dp, HairlineBorder, RoundedCornerShape(7.dp))
                    )
                    Column(modifier = Modifier.weight(1f)) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(item.displayCode, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                            if (state.brand != BeadBrand.MARD) {
                                Text("MARD ${item.mardCode}", fontFamily = FontFamily.Monospace, fontSize = 11.sp, color = InkMuted)
                            }
                        }
                        Text(
                            "${item.color.nameZh} · COCO:${item.color.brands["COCO"]} · 漫漫:${item.color.brands["漫漫"]} · 盼盼:${item.color.brands["盼盼"]}",
                            fontSize = 11.sp,
                            color = InkMuted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        Text("${item.count} 颗", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                        Text("备 ${item.spareCount}", fontFamily = FontFamily.Monospace, fontSize = 11.sp, color = InkMuted)
                    }
                }
            }
        }
    }
}

@Composable
private fun KpiCard(label: String, value: String, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = CraftSurface),
        border = BorderStroke(1.dp, HairlineBorder)
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Text(label, fontSize = 11.sp, color = InkMuted)
            Text(value, fontSize = 14.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace, color = InkCharcoal)
        }
    }
}

@Composable
private fun PhotoConvertTab(
    state: PindouUiState,
    viewModel: PindouViewModel
) {
    val photoPicker = rememberLauncherForActivityResult(
        contract = GalleryImagePickerContract()
    ) { uri ->
        if (uri != null) viewModel.setConvertSourceUri(uri)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Card(
            onClick = viewModel::openExternalImportDialog,
            colors = CardDefaults.cardColors(containerColor = SageSoft),
            border = BorderStroke(1.dp, SageCompletion.copy(alpha = 0.45f))
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "已有历史拼豆图纸 / 实拍成品照？",
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp,
                        color = SageCompletion
                    )
                    Text(
                        "直接智能识别网格周期、色号与豆量 →",
                        fontSize = 11.5.sp,
                        color = InkCharcoal
                    )
                }
                Text("去识别", fontWeight = FontWeight.Bold, fontSize = 12.5.sp, color = SageCompletion)
            }
        }

        Card(
            colors = CardDefaults.cardColors(containerColor = CraftSurface),
            border = BorderStroke(1.dp, HairlineBorder)
        ) {
            Column(
                modifier = Modifier.fillMaxWidth().padding(12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                val bmp = state.convertPreviewBmp
                if (bmp != null) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(172.dp)
                            .clip(RoundedCornerShape(10.dp))
                            .background(ParchmentBg)
                            .clickable { viewModel.openConvertCropDialog() }
                    ) {
                        Image(
                            bitmap = bmp.asImageBitmap(),
                            contentDescription = "待转换原图",
                            contentScale = ContentScale.Fit,
                            modifier = Modifier.fillMaxSize()
                        )
                        Surface(
                            modifier = Modifier
                                .align(Alignment.BottomEnd)
                                .padding(8.dp),
                            shape = RoundedCornerShape(999.dp),
                            color = InkCharcoal.copy(alpha = 0.78f)
                        ) {
                            Text(
                                if (state.isConvertCropped) "已框选 ${bmp.width}×${bmp.height} · 调整" else "点击放大框选区域",
                                color = Color.White,
                                fontSize = 10.5.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(horizontal = 9.dp, vertical = 4.dp)
                            )
                        }
                    }
                }
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            "当前图片：${state.convertSourceName}",
                            fontSize = 12.sp,
                            color = InkMuted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f)
                        )
                        if (state.isConvertCropped) {
                            TextButton(
                                onClick = viewModel::resetConvertCropToOriginal,
                                contentPadding = PaddingValues(horizontal = 6.dp, vertical = 2.dp)
                            ) {
                                Text("恢复原图", fontSize = 11.5.sp, color = TerracottaAccent)
                            }
                        }
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OutlinedButton(
                            onClick = { viewModel.openConvertCropDialog() },
                            modifier = Modifier.weight(1f),
                            border = BorderStroke(1.dp, TerracottaAccent)
                        ) {
                            Text("放大框选", color = TerracottaAccent, fontWeight = FontWeight.SemiBold)
                        }
                        OutlinedButton(
                            onClick = { photoPicker.launch(Unit) },
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("从相册换图")
                        }
                    }
                }
                OutlinedTextField(
                    value = state.convertWorkTitle,
                    onValueChange = viewModel::updateConvertWorkTitle,
                    label = { Text("作品名称（选填）") },
                    placeholder = { Text("例如：蓝床单小白猫") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }

        Text("转换算法模式", fontWeight = FontWeight.Bold, fontSize = 13.sp)
        ConvertMode.entries.forEach { mode ->
            val active = state.convertMode == mode
            Card(
                onClick = {
                    viewModel.updateConvertSettings(
                        mode = mode,
                        addOutline = mode == ConvertMode.CUTOUT_OUTLINE
                    )
                },
                colors = CardDefaults.cardColors(containerColor = if (active) TerracottaSoft else CraftSurface),
                border = BorderStroke(1.dp, if (active) TerracottaAccent else HairlineBorder)
            ) {
                Column(modifier = Modifier.fillMaxWidth().padding(12.dp)) {
                    Text(mode.label, fontWeight = FontWeight.Bold, color = if (active) TerracottaAccent else InkCharcoal)
                    Text(mode.desc, fontSize = 12.sp, color = InkMuted)
                }
            }
        }

        val targetSpec = calcPhysicalSpec(state.targetWidth, state.targetHeight, state.diameter)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("目标拼豆尺寸", fontWeight = FontWeight.Bold, fontSize = 13.sp)
            Text(
                "${state.targetWidth}×${state.targetHeight}格 · 约 ${targetSpec.widthCm}×${targetSpec.heightCm}cm",
                fontSize = 11.5.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                color = TerracottaAccent
            )
        }
        val longestEdgeNow = max(state.targetWidth, state.targetHeight)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            DOMESTIC_BOARD_PRESETS.forEach { p ->
                FilterChip(
                    selected = longestEdgeNow == p.width,
                    onClick = { viewModel.selectLongestEdgePreset(p.width) },
                    label = {
                        Text(
                            if (state.lockConvertAspect) "最长边 ${p.width}格" else "${p.width}×${p.height}",
                            fontFamily = FontFamily.Monospace
                        )
                    }
                )
            }
        }

        Card(
            colors = CardDefaults.cardColors(containerColor = CraftSurface),
            border = BorderStroke(1.dp, HairlineBorder)
        ) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text("按裁剪比例自适应长方形格数", fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold)
                    Switch(
                        checked = state.lockConvertAspect,
                        onCheckedChange = viewModel::toggleLockConvertAspect
                    )
                }
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("宽度格数", fontSize = 12.sp, color = InkMuted)
                    Text("${state.targetWidth} 格", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, color = InkCharcoal)
                }
                Slider(
                    value = state.targetWidth.toFloat(),
                    onValueChange = { viewModel.updateConvertSettings(width = it.roundToInt(), lockAspect = false) },
                    valueRange = 12f..96f
                )
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("高度格数", fontSize = 12.sp, color = InkMuted)
                    Text("${state.targetHeight} 格", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, color = InkCharcoal)
                }
                Slider(
                    value = state.targetHeight.toFloat(),
                    onValueChange = { viewModel.updateConvertSettings(height = it.roundToInt(), lockAspect = false) },
                    valueRange = 12f..96f
                )
                HorizontalDivider(color = HairlineBorder)
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("最大用色上限", fontWeight = FontWeight.SemiBold)
                    Text("${state.maxColors} 色", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, color = TerracottaAccent)
                }
                Slider(
                    value = state.maxColors.toFloat(),
                    onValueChange = { viewModel.updateConvertSettings(maxColors = it.roundToInt()) },
                    valueRange = 6f..28f
                )
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("抑制白毛偏绿 (排除 G15/H18/M1-7)", fontSize = 12.5.sp)
                    Switch(
                        checked = state.suppressGreenCast,
                        onCheckedChange = { viewModel.updateConvertSettings(suppressGreenCast = it) }
                    )
                }
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("圆眼柔和抗锯齿（告别棱角）", fontSize = 12.5.sp)
                    Switch(
                        checked = state.smoothEyes,
                        onCheckedChange = { viewModel.updateConvertSettings(smoothEyes = it) }
                    )
                }
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("外圈加 1 格 H5 炭灰描边", fontSize = 12.5.sp)
                    Switch(
                        checked = state.addOutline,
                        onCheckedChange = { viewModel.updateConvertSettings(addOutline = it) }
                    )
                }
            }
        }

        Button(
            onClick = viewModel::runOfflineConversion,
            enabled = !state.isConverting,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
            colors = ButtonDefaults.buttonColors(containerColor = TerracottaAccent)
        ) {
            if (state.isConverting) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), color = CraftSurface, strokeWidth = 2.dp)
                Spacer(Modifier.width(8.dp))
                Text("正在离线量化生成…")
            } else {
                Text("开始离线生成拼豆图纸", fontWeight = FontWeight.Bold)
            }
        }
    }

    val cropSrc = state.convertOriginalBmp ?: state.convertPreviewBmp
    if (state.showConvertCropDialog && cropSrc != null) {
        ImageCropDialog(
            sourceBitmap = cropSrc,
            title = "放大框选目标区域",
            onConfirmCrop = viewModel::applyConvertCrop,
            onUseOriginal = viewModel::resetConvertCropToOriginal,
            onDismiss = viewModel::dismissConvertCropDialog
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PalettePickerSheet(
    state: PindouUiState,
    viewModel: PindouViewModel,
    onDismiss: () -> Unit
) {
    var query by remember { mutableStateOf("") }
    var series by remember { mutableStateOf("ALL") }
    val filtered = remember(query, series) { viewModel.searchPalette(series, query) }

    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = CraftSurface) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .height(520.dp)
                .padding(horizontal = 14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("MARD 221 基准全色卡（当前品牌：${state.brand.label}）", fontWeight = FontWeight.Bold, fontSize = 15.sp)
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                placeholder = { Text("输入任意品牌色号或中文色名（如 H1 / 橙棕）") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Row(
                modifier = Modifier.horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                listOf("ALL" to "全部", "A" to "A黄橙", "B" to "B绿", "C" to "C蓝", "D" to "D紫", "E" to "E粉", "F" to "F红", "G" to "G棕肤", "H" to "H黑白灰", "M" to "M灰阶").forEach { (sKey, sLabel) ->
                    FilterChip(
                        selected = series == sKey,
                        onClick = { series = sKey },
                        label = { Text(sLabel, fontSize = 12.sp) }
                    )
                }
            }
            LazyVerticalGrid(
                columns = GridCells.Adaptive(minSize = 96.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f)
            ) {
                items(filtered, key = { it.code }) { entry ->
                    val disp = entry.codeFor(state.brand)
                    Card(
                        onClick = { viewModel.selectBrushCode(entry.code); onDismiss() },
                        colors = CardDefaults.cardColors(containerColor = ParchmentBg),
                        border = BorderStroke(1.dp, if (state.brushCode == entry.code) TerracottaAccent else HairlineBorder)
                    ) {
                        Column(modifier = Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(24.dp)
                                    .clip(RoundedCornerShape(6.dp))
                                    .background(Color(entry.argb))
                                    .border(1.dp, HairlineBorder, RoundedCornerShape(6.dp))
                            )
                            Text(
                                if (state.brand == BeadBrand.MARD) disp else "$disp (${entry.code})",
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                fontSize = 12.sp,
                                maxLines = 1
                            )
                            Text(entry.nameZh, fontSize = 11.sp, color = InkMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }
    }
}
