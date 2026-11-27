package com.pindoustudio.app.ui

import android.app.Application
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pindoustudio.app.data.PaletteRepository
import com.pindoustudio.app.data.PindouJsonCodec
import com.pindoustudio.app.data.PortfolioRepository
import com.pindoustudio.app.data.PortfolioStats
import com.pindoustudio.app.data.PortfolioWork
import com.pindoustudio.app.engine.DetectedSourceType
import com.pindoustudio.app.engine.ExternalBeadRecognizer
import com.pindoustudio.app.engine.ExternalImportHint
import com.pindoustudio.app.engine.NativeBeadConverter
import com.pindoustudio.app.engine.RecognitionResult
import com.pindoustudio.app.export.AndroidSheetExporter
import com.pindoustudio.app.model.BeadBrand
import com.pindoustudio.app.model.BeadDiameter
import com.pindoustudio.app.model.BeadPattern
import com.pindoustudio.app.model.BomSummary
import com.pindoustudio.app.model.ConvertMode
import com.pindoustudio.app.model.DrawTool
import com.pindoustudio.app.model.MainTab
import com.pindoustudio.app.model.PaletteColor
import com.pindoustudio.app.model.PhotoSlot
import com.pindoustudio.app.model.SampleEntry
import com.pindoustudio.app.model.ViewMode
import com.pindoustudio.app.update.AppUpdater
import com.pindoustudio.app.update.UpdateManifest
import kotlinx.coroutines.Dispatchers
import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class PindouUiState(
    val activeTab: MainTab = MainTab.CANVAS,
    val brand: BeadBrand = BeadBrand.MARD,
    val diameter: BeadDiameter = BeadDiameter.MM_26,
    val viewMode: ViewMode = ViewMode.GRID,
    val drawTool: DrawTool = DrawTool.BRUSH,
    val brushCode: String = "H1",
    val highlightCode: String? = null,
    val showCodes: Boolean = true,
    val showGrid: Boolean = true,
    val pattern: BeadPattern,
    val bom: BomSummary,
    val samples: List<SampleEntry> = emptyList(),
    val canUndo: Boolean = false,
    val canRedo: Boolean = false,
    val lastTappedCoord: String = "轻点网格涂色 · 双指缩放拖拽",
    val isConverting: Boolean = false,
    val convertOriginalBmp: Bitmap? = null,
    val convertPreviewBmp: Bitmap? = null,
    val isConvertCropped: Boolean = false,
    val showConvertCropDialog: Boolean = false,
    val convertSourceName: String = "内置猫咪示例照片",
    val convertWorkTitle: String = "",
    val convertMode: ConvertMode = ConvertMode.CUTOUT_OUTLINE,
    val targetWidth: Int = 40,
    val targetHeight: Int = 40,
    val maxColors: Int = 14,
    val suppressGreenCast: Boolean = true,
    val smoothEyes: Boolean = true,
    val addOutline: Boolean = true,
    val appVersionName: String = "1.0",
    val appVersionCode: Long = 1L,
    val isCheckingUpdate: Boolean = false,
    val updateManifest: UpdateManifest? = null,
    val updateProgress: Float? = null,
    val downloadedApk: File? = null,
    val updateError: String? = null,
    val showUpdateDialog: Boolean = false,
    val portfolioWorks: List<PortfolioWork> = emptyList(),
    val portfolioStats: PortfolioStats,
    val showExternalImportDialog: Boolean = false,
    val externalImportOriginalBmp: Bitmap? = null,
    val externalImportSourceBmp: Bitmap? = null,
    val isExternalCropped: Boolean = false,
    val showExternalCropDialog: Boolean = false,
    val externalImportTitle: String = "",
    val externalImportHint: ExternalImportHint = ExternalImportHint.AUTO,
    val externalImportCustomW: Int? = null,
    val externalImportCustomH: Int? = null,
    val externalImportCraftColors: Int = 14,
    val externalImportMarkCompleted: Boolean = false,
    val externalImportResult: RecognitionResult? = null,
    val externalImportPreviewBmp: Bitmap? = null,
    val isRecognizingExternal: Boolean = false,
    val toastMessage: String? = null
)

class PindouViewModel(application: Application) : AndroidViewModel(application) {

    val paletteRepo = PaletteRepository(application)
    private val portfolioRepo = PortfolioRepository(application)
    private var lastConvertedPatternName: String? = null
    private var lastConvertedRefBmp: Bitmap? = null
    private val undoStack = ArrayDeque<List<String?>>()
    private val redoStack = ArrayDeque<List<String?>>()

    private val _uiState: MutableStateFlow<PindouUiState>
    val uiState: StateFlow<PindouUiState>

    init {
        val samples = PindouJsonCodec.loadSamplesIndex(application)
        val firstPattern = if (samples.isNotEmpty()) {
            PindouJsonCodec.loadFromAsset(application, samples.first().file)
                .copy(name = samples.first().title.substringBefore(" · "))
        } else {
            BeadPattern("空白拼板", 40, 40, List(1600) { null })
        }
        val demoPhoto = runCatching {
            application.assets.open("samples/demo_cat.jpg").use { BitmapFactory.decodeStream(it) }
        }.getOrNull()

        val initialBom = paletteRepo.computeBom(firstPattern, BeadBrand.MARD, BeadDiameter.MM_26)
        val ver = AppUpdater.getCurrentVersion(application)
        val initialWorks = portfolioRepo.loadAll()
        val initialStats = portfolioRepo.computeStats(initialWorks)
        _uiState = MutableStateFlow(
            PindouUiState(
                pattern = firstPattern,
                bom = initialBom,
                samples = samples,
                convertOriginalBmp = demoPhoto,
                convertPreviewBmp = demoPhoto,
                appVersionName = ver.versionName,
                appVersionCode = ver.versionCode,
                portfolioWorks = initialWorks,
                portfolioStats = initialStats
            )
        )
        uiState = _uiState.asStateFlow()
        if (AppUpdater.isManifestConfigured()) {
            checkForUpdate(manual = false)
        }
    }

    fun selectTab(tab: MainTab) {
        _uiState.update { it.copy(activeTab = tab) }
    }

    fun selectBrand(brand: BeadBrand) {
        _uiState.update { st ->
            st.copy(
                brand = brand,
                bom = paletteRepo.computeBom(st.pattern, brand, st.diameter)
            )
        }
    }

    fun selectDiameter(diameter: BeadDiameter) {
        _uiState.update { st ->
            st.copy(
                diameter = diameter,
                bom = paletteRepo.computeBom(st.pattern, st.brand, diameter)
            )
        }
    }

    fun selectViewMode(mode: ViewMode) {
        _uiState.update { it.copy(viewMode = mode) }
    }

    fun selectDrawTool(tool: DrawTool) {
        _uiState.update { it.copy(drawTool = tool) }
    }

    fun selectBrushCode(code: String) {
        _uiState.update { it.copy(brushCode = code, drawTool = DrawTool.BRUSH) }
    }

    fun toggleHighlightColor(mardCode: String) {
        _uiState.update { st ->
            val next = if (st.highlightCode == mardCode) null else mardCode
            st.copy(highlightCode = next, brushCode = mardCode)
        }
    }

    fun clearHighlight() {
        _uiState.update { it.copy(highlightCode = null) }
    }

    fun toggleShowCodes() {
        _uiState.update { it.copy(showCodes = !it.showCodes) }
    }

    fun toggleShowGrid() {
        _uiState.update { it.copy(showGrid = !it.showGrid) }
    }

    fun loadSample(sample: SampleEntry) {
        val ctx = getApplication<Application>()
        val loaded = PindouJsonCodec.loadFromAsset(ctx, sample.file)
            .copy(name = sample.title.substringBefore(" · "))
        applyNewPattern(loaded, "已切换作品：${sample.title}")
    }

    fun createBlankPattern(w: Int, h: Int) {
        val blank = BeadPattern("新建空白板_${w}x${h}", w, h, List(w * h) { null })
        applyNewPattern(blank, "已新建 ${w}×${h} 空白拼板")
    }

    private fun applyNewPattern(pattern: BeadPattern, toast: String) {
        undoStack.clear()
        redoStack.clear()
        _uiState.update { st ->
            st.copy(
                pattern = pattern,
                bom = paletteRepo.computeBom(pattern, st.brand, st.diameter),
                highlightCode = null,
                canUndo = false,
                canRedo = false,
                activeTab = MainTab.CANVAS,
                viewMode = ViewMode.GRID,
                toastMessage = toast
            )
        }
    }

    fun onCellTap(r: Int, c: Int) {
        val st = _uiState.value
        val pat = st.pattern
        if (r !in 0 until pat.height || c !in 0 until pat.width) return

        val currentCode = pat.get(r, c)
        val entry = paletteRepo.findByMardCode(currentCode)
        val coordLabel = if (entry != null) {
            "R${r + 1} C${c + 1} · ${st.brand.label} ${entry.codeFor(st.brand)} (${entry.nameZh})"
        } else {
            "R${r + 1} C${c + 1} · 空孔位"
        }

        when (st.drawTool) {
            DrawTool.EYEDROPPER -> {
                if (currentCode != null) {
                    val disp = paletteRepo.translateCode(currentCode, st.brand)
                    _uiState.update {
                        it.copy(
                            brushCode = currentCode,
                            drawTool = DrawTool.BRUSH,
                            lastTappedCoord = coordLabel,
                            toastMessage = "已吸取 ${st.brand.label} $disp"
                        )
                    }
                } else {
                    _uiState.update { it.copy(lastTappedCoord = coordLabel) }
                }
            }
            DrawTool.BRUSH -> applyCellMutation(r, c, st.brushCode, coordLabel)
            DrawTool.ERASER -> applyCellMutation(r, c, null, coordLabel)
            DrawTool.FILL -> applyFloodFill(r, c, st.brushCode, coordLabel)
        }
    }

    private fun applyCellMutation(r: Int, c: Int, nextCode: String?, coordLabel: String) {
        val st = _uiState.value
        val idx = r * st.pattern.width + c
        if (st.pattern.cells[idx] == nextCode) {
            _uiState.update { it.copy(lastTappedCoord = coordLabel) }
            return
        }
        pushUndo(st.pattern.cells)
        val nextCells = st.pattern.cells.toMutableList()
        nextCells[idx] = nextCode
        val updated = st.pattern.withUpdatedCells(nextCells)
        _uiState.update {
            it.copy(
                pattern = updated,
                bom = paletteRepo.computeBom(updated, it.brand, it.diameter),
                canUndo = undoStack.isNotEmpty(),
                canRedo = redoStack.isNotEmpty(),
                lastTappedCoord = coordLabel
            )
        }
    }

    private fun applyFloodFill(startR: Int, startC: Int, replacement: String?, coordLabel: String) {
        val st = _uiState.value
        val w = st.pattern.width
        val h = st.pattern.height
        val target = st.pattern.get(startR, startC)
        if (target == replacement) return

        pushUndo(st.pattern.cells)
        val nextCells = st.pattern.cells.toMutableList()
        val visited = BooleanArray(w * h)
        val queue = ArrayDeque<Int>()
        val startIdx = startR * w + startC
        visited[startIdx] = true
        queue.addLast(startIdx)
        while (queue.isNotEmpty()) {
            val cur = queue.removeFirst()
            nextCells[cur] = replacement
            val r = cur / w
            val c = cur % w
            val nbrs = intArrayOf(
                if (r > 0) cur - w else -1,
                if (r + 1 < h) cur + w else -1,
                if (c > 0) cur - 1 else -1,
                if (c + 1 < w) cur + 1 else -1
            )
            for (n in nbrs) {
                if (n >= 0 && !visited[n] && nextCells[n] == target) {
                    visited[n] = true
                    queue.addLast(n)
                }
            }
        }
        val updated = st.pattern.withUpdatedCells(nextCells)
        _uiState.update {
            it.copy(
                pattern = updated,
                bom = paletteRepo.computeBom(updated, it.brand, it.diameter),
                canUndo = undoStack.isNotEmpty(),
                canRedo = redoStack.isNotEmpty(),
                lastTappedCoord = coordLabel
            )
        }
    }

    private fun pushUndo(cells: List<String?>) {
        if (undoStack.size >= 40) undoStack.removeFirst()
        undoStack.addLast(cells)
        redoStack.clear()
    }

    fun undo() {
        val prev = undoStack.removeLastOrNull() ?: return
        val cur = _uiState.value
        redoStack.addLast(cur.pattern.cells)
        val updated = cur.pattern.withUpdatedCells(prev)
        _uiState.update {
            it.copy(
                pattern = updated,
                bom = paletteRepo.computeBom(updated, it.brand, it.diameter),
                canUndo = undoStack.isNotEmpty(),
                canRedo = redoStack.isNotEmpty()
            )
        }
    }

    fun redo() {
        val next = redoStack.removeLastOrNull() ?: return
        val cur = _uiState.value
        undoStack.addLast(cur.pattern.cells)
        val updated = cur.pattern.withUpdatedCells(next)
        _uiState.update {
            it.copy(
                pattern = updated,
                bom = paletteRepo.computeBom(updated, it.brand, it.diameter),
                canUndo = undoStack.isNotEmpty(),
                canRedo = redoStack.isNotEmpty()
            )
        }
    }

    fun setConvertSourceUri(uri: Uri) {
        viewModelScope.launch {
            val ctx = getApplication<Application>()
            val (bmp, name) = withContext(Dispatchers.IO) {
                val decoded = ExternalBeadRecognizer.decodeBoundedBitmap(ctx, uri, maxSide = 2048)
                val cleanName = resolveCleanTitleFromUri(ctx, uri).ifBlank { "相册图片" }
                decoded to cleanName
            }
            if (bmp != null) {
                _uiState.update {
                    it.copy(
                        convertOriginalBmp = bmp,
                        convertPreviewBmp = bmp,
                        isConvertCropped = false,
                        showConvertCropDialog = true,
                        convertSourceName = name
                    )
                }
            } else {
                showToast("读取相册图片失败")
            }
        }
    }

    fun openConvertCropDialog() {
        val st = _uiState.value
        if (st.convertOriginalBmp == null && st.convertPreviewBmp == null) {
            showToast("请先选择一张图片")
            return
        }
        _uiState.update { it.copy(showConvertCropDialog = true) }
    }

    fun dismissConvertCropDialog() {
        _uiState.update { it.copy(showConvertCropDialog = false) }
    }

    fun applyConvertCrop(cropped: Bitmap) {
        _uiState.update {
            it.copy(
                convertPreviewBmp = cropped,
                isConvertCropped = true,
                showConvertCropDialog = false,
                toastMessage = "已框选区域（${cropped.width}×${cropped.height} px）"
            )
        }
    }

    fun resetConvertCropToOriginal() {
        _uiState.update { st ->
            val orig = st.convertOriginalBmp ?: st.convertPreviewBmp
            st.copy(
                convertPreviewBmp = orig,
                isConvertCropped = false,
                showConvertCropDialog = false,
                toastMessage = "已恢复原图范围"
            )
        }
    }

    fun updateConvertWorkTitle(title: String) {
        _uiState.update { it.copy(convertWorkTitle = title) }
    }

    fun updateConvertSettings(
        mode: ConvertMode = _uiState.value.convertMode,
        width: Int = _uiState.value.targetWidth,
        height: Int = _uiState.value.targetHeight,
        maxColors: Int = _uiState.value.maxColors,
        suppressGreenCast: Boolean = _uiState.value.suppressGreenCast,
        smoothEyes: Boolean = _uiState.value.smoothEyes,
        addOutline: Boolean = _uiState.value.addOutline
    ) {
        _uiState.update {
            it.copy(
                convertMode = mode,
                targetWidth = width.coerceIn(12, 96),
                targetHeight = height.coerceIn(12, 96),
                maxColors = maxColors.coerceIn(4, 32),
                suppressGreenCast = suppressGreenCast,
                smoothEyes = smoothEyes,
                addOutline = addOutline
            )
        }
    }

    fun runOfflineConversion() {
        val st = _uiState.value
        val src = st.convertPreviewBmp ?: run {
            showToast("请先选择一张图片")
            return
        }
        val outTitle = st.convertWorkTitle.trim().ifBlank { "我的拼豆画_${st.targetWidth}x${st.targetHeight}" }
        _uiState.update { it.copy(isConverting = true) }
        viewModelScope.launch {
            val converted = withContext(Dispatchers.Default) {
                NativeBeadConverter.convert(
                    bitmap = src,
                    paletteRepo = paletteRepo,
                    name = outTitle,
                    mode = st.convertMode,
                    targetW = st.targetWidth,
                    targetH = st.targetHeight,
                    maxColors = st.maxColors,
                    suppressGreenCast = st.suppressGreenCast,
                    smoothEyes = st.smoothEyes,
                    addOutline = st.addOutline
                )
            }
            _uiState.update { it.copy(isConverting = false) }
            lastConvertedPatternName = converted.name
            lastConvertedRefBmp = src
            applyNewPattern(converted, "已离线生成 ${converted.width}×${converted.height} 拼豆图纸")
        }
    }

    fun exportSheetPng() {
        val st = _uiState.value
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    AndroidSheetExporter.exportPngToGallery(getApplication(), st.pattern, paletteRepo, st.brand, st.diameter)
                }
            }.onSuccess { path ->
                showToast("已保存到系统相册：$path")
            }.onFailure { err ->
                showToast("保存失败：${err.message ?: "未知错误"}")
            }
        }
    }

    fun exportBakedJpg() {
        val st = _uiState.value
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    AndroidSheetExporter.exportBakedJpgToGallery(
                        getApplication(),
                        st.pattern,
                        paletteRepo,
                        st.diameter
                    )
                }
            }.onSuccess { path ->
                showToast("已保存成品效果图到相册：$path")
            }.onFailure { err ->
                showToast("保存失败：${err.message ?: "未知错误"}")
            }
        }
    }

    fun shareSheetPng() {
        val st = _uiState.value
        AndroidSheetExporter.sharePng(getApplication(), st.pattern, paletteRepo, st.brand, st.diameter)
    }

    fun exportCsv() {
        val st = _uiState.value
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    AndroidSheetExporter.exportCsvToDownloads(getApplication(), st.pattern, paletteRepo, st.brand, st.diameter)
                }
            }.onSuccess { path ->
                showToast("已保存到文件下载：$path")
            }.onFailure { err ->
                showToast("导出失败：${err.message ?: "未知错误"}")
            }
        }
    }

    fun exportPindouJson() {
        val st = _uiState.value
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    AndroidSheetExporter.exportPindouJsonToDownloads(getApplication(), st.pattern, paletteRepo)
                }
            }.onSuccess { path ->
                showToast("已保存工程到下载：$path")
            }.onFailure { err ->
                showToast("保存失败：${err.message ?: "未知错误"}")
            }
        }
    }

    fun copyBomToClipboard() {
        val st = _uiState.value
        val phys = st.bom.physical
        val lines = buildList {
            add("【${st.pattern.name}】${st.pattern.width}×${st.pattern.height}格 · ${phys.beadMm}mm 成品约 ${phys.widthCm}×${phys.heightCm}cm · 共 ${st.bom.totalBeads} 颗（${st.bom.colorCount} 色）")
            add("主选品牌：${st.brand.label}")
            st.bom.items.forEach { item ->
                val b = item.color.brands
                add("${item.displayCode} (${item.color.nameZh}) ×${item.count}颗 [备${item.spareCount}] | MARD:${item.mardCode} COCO:${b["COCO"]} 漫漫:${b["漫漫"]} 盼盼:${b["盼盼"]} 咪小窝:${b["咪小窝"]}")
            }
        }
        val cm = getApplication<Application>().getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("豆绘工坊用豆清单", lines.joinToString("\n")))
        showToast("已复制 ${st.brand.label} 采购清单（含五品牌对照）")
    }

    fun checkForUpdate(manual: Boolean = true, overrideManifestUrl: String? = null) {
        val st = _uiState.value
        if (st.isCheckingUpdate) return
        val urls = if (!overrideManifestUrl.isNullOrBlank()) {
            listOf(overrideManifestUrl)
        } else {
            AppUpdater.DEFAULT_MANIFEST_URLS
        }
        if (overrideManifestUrl.isNullOrBlank() && !AppUpdater.isManifestConfigured(urls)) {
            if (manual) {
                showToast("当前 v${st.appVersionName} · 请先配置 AppUpdater 云端仓库地址即可启用自动推送更新")
            }
            return
        }
        _uiState.update { it.copy(isCheckingUpdate = true, updateError = null) }
        viewModelScope.launch {
            val res = withContext(Dispatchers.IO) { AppUpdater.fetchManifest(urls) }
            res.onSuccess { manifest ->
                val curVer = AppUpdater.getCurrentVersion(getApplication()).versionCode
                if (manifest.versionCode > curVer) {
                    _uiState.update {
                        it.copy(
                            isCheckingUpdate = false,
                            updateManifest = manifest,
                            downloadedApk = null,
                            updateProgress = null,
                            updateError = null,
                            showUpdateDialog = true
                        )
                    }
                } else {
                    _uiState.update { it.copy(isCheckingUpdate = false) }
                    if (manual) showToast("当前已是最新版本 v${st.appVersionName}")
                }
            }.onFailure { err ->
                _uiState.update { it.copy(isCheckingUpdate = false) }
                if (manual) showToast("检查更新失败：${err.message ?: "请检查网络"}")
            }
        }
    }

    fun startUpdateDownload() {
        val st = _uiState.value
        val manifest = st.updateManifest ?: return
        if (st.updateProgress != null && st.downloadedApk == null) return
        _uiState.update { it.copy(updateProgress = 0f, updateError = null, downloadedApk = null) }
        viewModelScope.launch {
            val res = withContext(Dispatchers.IO) {
                AppUpdater.downloadAndVerifyApk(getApplication(), manifest) { p ->
                    _uiState.update { cur -> cur.copy(updateProgress = p) }
                }
            }
            res.onSuccess { apkFile ->
                _uiState.update { it.copy(updateProgress = 1f, downloadedApk = apkFile, updateError = null) }
                installDownloadedApk()
            }.onFailure { err ->
                _uiState.update {
                    it.copy(
                        updateProgress = null,
                        updateError = err.message ?: "镜像下载失败，建议使用下方浏览器备用下载"
                    )
                }
            }
        }
    }

    fun installDownloadedApk() {
        val apk = _uiState.value.downloadedApk ?: return
        val started = AppUpdater.installApk(getApplication(), apk)
        if (!started) {
            showToast("请先开启「允许安装未知应用」权限后返回点击「立即安装」")
        }
    }

    fun openFallbackUpdatePage() {
        val url = _uiState.value.updateManifest?.fallbackPageUrl ?: return
        AppUpdater.openFallbackDownloadPage(getApplication(), url)
    }

    fun dismissUpdateDialog() {
        val st = _uiState.value
        if (st.updateManifest?.forceUpdate == true) return
        _uiState.update { it.copy(showUpdateDialog = false) }
    }

    fun saveCurrentWorkToPortfolio() {
        val st = _uiState.value
        val refBmp = if (st.pattern.name == lastConvertedPatternName) lastConvertedRefBmp else null
        viewModelScope.launch {
            val updated = withContext(Dispatchers.IO) {
                portfolioRepo.saveNewWork(st.pattern, st.diameter, paletteRepo, refBmp)
            }
            val stats = withContext(Dispatchers.Default) { portfolioRepo.computeStats(updated) }
            _uiState.update {
                it.copy(
                    portfolioWorks = updated,
                    portfolioStats = stats,
                    activeTab = MainTab.ARCHIVE,
                    toastMessage = "已收录《${st.pattern.name}》到作品馆（可随时补传参考图或实物照）"
                )
            }
        }
    }

    fun attachPortfolioPhoto(workId: String, slot: PhotoSlot, uri: Uri) {
        viewModelScope.launch {
            val updated = withContext(Dispatchers.IO) {
                portfolioRepo.attachPhotoFromUri(workId, slot, uri)
            }
            val stats = withContext(Dispatchers.Default) { portfolioRepo.computeStats(updated) }
            _uiState.update {
                it.copy(
                    portfolioWorks = updated,
                    portfolioStats = stats,
                    toastMessage = "已更新「${slot.label}」照片"
                )
            }
        }
    }

    fun removePortfolioPhoto(workId: String, slot: PhotoSlot) {
        viewModelScope.launch {
            val updated = withContext(Dispatchers.IO) {
                portfolioRepo.removePhotoSlot(workId, slot)
            }
            val stats = withContext(Dispatchers.Default) { portfolioRepo.computeStats(updated) }
            _uiState.update { it.copy(portfolioWorks = updated, portfolioStats = stats) }
        }
    }

    fun renameCurrentPattern(newTitle: String) {
        val clean = newTitle.trim()
        if (clean.isEmpty()) return
        _uiState.update { st ->
            if (st.pattern.name == lastConvertedPatternName) {
                lastConvertedPatternName = clean
            }
            st.copy(
                pattern = st.pattern.copy(name = clean),
                toastMessage = "已重命名为《$clean》"
            )
        }
    }

    fun renamePortfolioWork(workId: String, newTitle: String) {
        val clean = newTitle.trim()
        if (clean.isEmpty()) return
        viewModelScope.launch {
            val updated = withContext(Dispatchers.IO) {
                portfolioRepo.renameWork(workId, clean)
            }
            val stats = withContext(Dispatchers.Default) { portfolioRepo.computeStats(updated) }
            _uiState.update {
                it.copy(
                    portfolioWorks = updated,
                    portfolioStats = stats,
                    toastMessage = "已重命名为《$clean》"
                )
            }
        }
    }

    fun togglePortfolioCompleted(workId: String) {
        viewModelScope.launch {
            val updated = withContext(Dispatchers.IO) {
                portfolioRepo.toggleCompleted(workId)
            }
            val stats = withContext(Dispatchers.Default) { portfolioRepo.computeStats(updated) }
            _uiState.update { it.copy(portfolioWorks = updated, portfolioStats = stats) }
        }
    }

    fun deletePortfolioWork(workId: String) {
        viewModelScope.launch {
            val updated = withContext(Dispatchers.IO) {
                portfolioRepo.deleteWork(workId)
            }
            val stats = withContext(Dispatchers.Default) { portfolioRepo.computeStats(updated) }
            _uiState.update {
                it.copy(portfolioWorks = updated, portfolioStats = stats, toastMessage = "已从作品馆移除")
            }
        }
    }

    fun loadPortfolioWorkToCanvas(work: PortfolioWork) {
        viewModelScope.launch {
            val loaded = withContext(Dispatchers.IO) { portfolioRepo.loadPattern(work) }
            if (loaded != null) {
                applyNewPattern(loaded, "已从作品馆载入《${work.title}》")
            } else {
                showToast("载入图纸文件失败")
            }
        }
    }

    fun openExternalImportDialog() {
        _uiState.update { it.copy(showExternalImportDialog = true) }
    }

    fun dismissExternalImportDialog() {
        _uiState.update { it.copy(showExternalImportDialog = false) }
    }

    fun pickExternalImportUri(uri: Uri) {
        viewModelScope.launch {
            val ctx = getApplication<Application>()
            val (bmp, fileName) = withContext(Dispatchers.IO) {
                val decoded = ExternalBeadRecognizer.decodeBoundedBitmap(ctx, uri, maxSide = 2048)
                val name = resolveCleanTitleFromUri(ctx, uri)
                decoded to name
            }
            if (bmp == null) {
                showToast("读取图片失败")
                return@launch
            }
            _uiState.update {
                it.copy(
                    externalImportOriginalBmp = bmp,
                    externalImportSourceBmp = bmp,
                    isExternalCropped = false,
                    showExternalCropDialog = false,
                    externalImportTitle = fileName,
                    externalImportCustomW = null,
                    externalImportCustomH = null,
                    externalImportResult = null,
                    externalImportPreviewBmp = null,
                    isRecognizingExternal = true
                )
            }
            runExternalRecognition()
        }
    }

    fun openExternalCropDialog() {
        val st = _uiState.value
        if (st.externalImportOriginalBmp == null && st.externalImportSourceBmp == null) {
            showToast("请先从相册选图")
            return
        }
        _uiState.update { it.copy(showExternalCropDialog = true) }
    }

    fun dismissExternalCropDialog() {
        _uiState.update { it.copy(showExternalCropDialog = false) }
    }

    fun applyExternalCrop(cropped: Bitmap) {
        _uiState.update {
            it.copy(
                externalImportSourceBmp = cropped,
                isExternalCropped = true,
                showExternalCropDialog = false,
                externalImportCustomW = null,
                externalImportCustomH = null,
                isRecognizingExternal = true
            )
        }
        runExternalRecognition()
    }

    fun resetExternalCropToOriginal() {
        val st = _uiState.value
        val orig = st.externalImportOriginalBmp ?: st.externalImportSourceBmp ?: return
        _uiState.update {
            it.copy(
                externalImportSourceBmp = orig,
                isExternalCropped = false,
                showExternalCropDialog = false,
                externalImportCustomW = null,
                externalImportCustomH = null,
                isRecognizingExternal = true
            )
        }
        runExternalRecognition()
    }

    fun updateExternalImportOptions(
        title: String? = null,
        hint: ExternalImportHint? = null,
        customW: Int? = null,
        customH: Int? = null,
        clearCustomSize: Boolean = false,
        craftColors: Int? = null,
        markCompleted: Boolean? = null
    ) {
        val prev = _uiState.value
        val nextW = if (clearCustomSize) null else (customW ?: prev.externalImportCustomW)
        val nextH = if (clearCustomSize) null else (customH ?: prev.externalImportCustomH)
        val nextHint = hint ?: prev.externalImportHint
        val nextCap = craftColors ?: prev.externalImportCraftColors
        val nextTitle = title ?: prev.externalImportTitle
        val nextDone = markCompleted ?: prev.externalImportMarkCompleted
        val needReRun = (nextHint != prev.externalImportHint ||
            nextW != prev.externalImportCustomW ||
            nextH != prev.externalImportCustomH ||
            nextCap != prev.externalImportCraftColors) && prev.externalImportSourceBmp != null

        _uiState.update {
            it.copy(
                externalImportTitle = nextTitle,
                externalImportHint = nextHint,
                externalImportCustomW = nextW,
                externalImportCustomH = nextH,
                externalImportCraftColors = nextCap,
                externalImportMarkCompleted = nextDone,
                isRecognizingExternal = if (needReRun) true else it.isRecognizingExternal
            )
        }
        if (needReRun) {
            runExternalRecognition()
        } else if (title != null && prev.externalImportResult != null) {
            val r = prev.externalImportResult
            _uiState.update {
                it.copy(externalImportResult = r.copy(pattern = r.pattern.copy(name = nextTitle)))
            }
        }
    }

    private fun runExternalRecognition() {
        val st = _uiState.value
        val bmp = st.externalImportSourceBmp ?: return
        viewModelScope.launch {
            val (result, prevBmp) = withContext(Dispatchers.Default) {
                val r = ExternalBeadRecognizer.recognize(
                    bitmap = bmp,
                    paletteRepo = paletteRepo,
                    title = st.externalImportTitle.ifBlank { "导入拼豆作品" },
                    hint = st.externalImportHint,
                    overrideWidth = st.externalImportCustomW,
                    overrideHeight = st.externalImportCustomH,
                    craftMaxColors = st.externalImportCraftColors
                )
                val p = portfolioRepo.renderPatternPreviewBitmap(r.pattern, paletteRepo, maxSide = 520)
                r to p
            }
            val friendlyTitle = st.externalImportTitle.ifBlank {
                val tag = if (result.detectedType == DetectedSourceType.EXTERNAL_CHART) "导入图纸" else "实拍成品"
                "$tag ${result.pattern.width}×${result.pattern.height}"
            }
            val finalRes = if (result.pattern.name != friendlyTitle) {
                result.copy(pattern = result.pattern.copy(name = friendlyTitle))
            } else result
            _uiState.update {
                it.copy(
                    externalImportTitle = friendlyTitle,
                    externalImportResult = finalRes,
                    externalImportPreviewBmp = prevBmp,
                    externalImportMarkCompleted = result.markCompletedByDefault,
                    isRecognizingExternal = false
                )
            }
        }
    }

    fun saveRecognizedWorkToPortfolio() {
        val st = _uiState.value
        val res = st.externalImportResult ?: return
        val srcBmp = st.externalImportSourceBmp ?: return
        val finalTitle = st.externalImportTitle.ifBlank { res.pattern.name }
        val finalPattern = res.pattern.copy(name = finalTitle)
        val isChart = res.detectedType == DetectedSourceType.EXTERNAL_CHART
        val markDone = st.externalImportMarkCompleted

        viewModelScope.launch {
            val updated = withContext(Dispatchers.IO) {
                portfolioRepo.saveNewWork(
                    pattern = finalPattern,
                    diameter = st.diameter,
                    paletteRepo = paletteRepo,
                    refBitmap = if (isChart) srcBmp else null,
                    ironedBitmap = if (!isChart) srcBmp else null,
                    markCompleted = markDone
                )
            }
            val stats = withContext(Dispatchers.Default) { portfolioRepo.computeStats(updated) }
            _uiState.update {
                it.copy(
                    portfolioWorks = updated,
                    portfolioStats = stats,
                    showExternalImportDialog = false,
                    activeTab = MainTab.ARCHIVE,
                    toastMessage = "已智能识别并收录《$finalTitle》(${finalPattern.width}×${finalPattern.height})"
                )
            }
        }
    }

    fun loadRecognizedWorkToCanvas() {
        val st = _uiState.value
        val res = st.externalImportResult ?: return
        val finalTitle = st.externalImportTitle.ifBlank { res.pattern.name }
        val finalPattern = res.pattern.copy(name = finalTitle)
        lastConvertedPatternName = finalPattern.name
        lastConvertedRefBmp = st.externalImportSourceBmp
        _uiState.update { it.copy(showExternalImportDialog = false) }
        applyNewPattern(finalPattern, "已载入识别图纸《$finalTitle》(${finalPattern.width}×${finalPattern.height})")
    }

    private fun resolveCleanTitleFromUri(context: Context, uri: Uri): String {
        val rawName = runCatching {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        }.getOrNull()
        val clean = rawName?.substringBeforeLast('.')?.trim().orEmpty()
        val isJunkId = clean.isEmpty() ||
            clean.matches(Regex("^\\d+$")) ||
            clean.startsWith("image:", ignoreCase = true) ||
            clean.startsWith("IMG_", ignoreCase = true) ||
            clean.startsWith("Screenshot_", ignoreCase = true) ||
            clean.startsWith("mmexport", ignoreCase = true)
        return if (isJunkId) "" else clean
    }

    fun clearToast() {
        _uiState.update { it.copy(toastMessage = null) }
    }

    private fun showToast(msg: String) {
        _uiState.update { it.copy(toastMessage = msg) }
    }

    fun searchPalette(series: String, query: String): List<PaletteColor> {
        val q = query.trim().uppercase()
        return paletteRepo.palette.filter { entry ->
            (series == "ALL" || entry.series == series) &&
                (q.isEmpty() ||
                    entry.code.contains(q) ||
                    entry.nameZh.uppercase().contains(q) ||
                    entry.brands.values.any { it.uppercase().contains(q) })
        }
    }
}
