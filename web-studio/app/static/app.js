/* 豆绘工坊 · 国内 2.6mm + MARD 221 五大品牌交互工作台 */
(() => {
  "use strict";

  const state = {
    brands: ["MARD", "COCO", "漫漫", "盼盼", "咪小窝"],
    brand: "MARD",
    beadMm: 2.6,
    boardSize: 52,
    palette: [],
    paletteByCode: new Map(),
    gallery: [],

    projectName: "豆绘工坊",
    projectId: "",
    grid: [],
    width: 0,
    height: 0,

    viewMode: "grid", // grid | baked
    bakedCacheKey: "",
    bakedImg: null,
    bakedFetchingKey: "",
    tool: "brush", // brush | eraser | eyedropper | fill
    brushCode: "H1",
    highlightCode: null,
    showCodes: true,
    showGrid: true,

    undoStack: [],
    redoStack: [],

    zoom: 1.0,
    panX: 0,
    panY: 0,
    cellBasePx: 22,

    isPainting: false,
    strokeChanged: false,
    isPanning: false,
    spaceHeld: false,
    panStartX: 0,
    panStartY: 0,
    panOriginX: 0,
    panOriginY: 0,
    hoverCell: null,

    selectedFile: null,
    convertMode: "photo_fusion",
    paletteSeriesFilter: "ALL",
  };

  const els = {
    projectNameDisplay: document.getElementById("projectNameDisplay"),
    gallerySelect: document.getElementById("gallerySelect"),
    brandSwitcher: document.getElementById("brandSwitcher"),
    beadSpecSwitcher: document.getElementById("beadSpecSwitcher"),
    btnExportSheet: document.getElementById("btnExportSheet"),
    btnExportBaked: document.getElementById("btnExportBaked"),
    btnExportCsv: document.getElementById("btnExportCsv"),
    btnExportPindou: document.getElementById("btnExportPindou"),

    uploadDropzone: document.getElementById("uploadDropzone"),
    imageFileInput: document.getElementById("imageFileInput"),
    uploadPreviewImg: document.getElementById("uploadPreviewImg"),
    uploadPlaceholder: document.getElementById("uploadPlaceholder"),
    convertModeGroup: document.getElementById("convertModeGroup"),
    boardPresetChips: document.getElementById("boardPresetChips"),
    inputWidth: document.getElementById("inputWidth"),
    inputHeight: document.getElementById("inputHeight"),
    inputMaxColors: document.getElementById("inputMaxColors"),
    maxColorsLabel: document.getElementById("maxColorsLabel"),
    chkSuppressGreen: document.getElementById("chkSuppressGreen"),
    chkSmoothEyes: document.getElementById("chkSmoothEyes"),
    chkRemoveBg: document.getElementById("chkRemoveBg"),
    chkOutline: document.getElementById("chkOutline"),
    btnConvert: document.getElementById("btnConvert"),
    btnImportPindou: document.getElementById("btnImportPindou"),
    pindouImportInput: document.getElementById("pindouImportInput"),
    btnNewBlank: document.getElementById("btnNewBlank"),

    viewModeTabs: document.getElementById("viewModeTabs"),
    drawToolGroup: document.getElementById("drawToolGroup"),
    btnUndo: document.getElementById("btnUndo"),
    btnRedo: document.getElementById("btnRedo"),
    chkShowCodes: document.getElementById("chkShowCodes"),
    chkShowGrid: document.getElementById("chkShowGrid"),
    btnZoomOut: document.getElementById("btnZoomOut"),
    btnZoomIn: document.getElementById("btnZoomIn"),
    btnFitView: document.getElementById("btnFitView"),
    zoomPercent: document.getElementById("zoomPercent"),

    canvasTray: document.getElementById("canvasTray"),
    canvas: document.getElementById("beadCanvas"),
    hoverTooltip: document.getElementById("hoverTooltip"),
    statusCoords: document.getElementById("statusCoords"),
    statusBrush: document.getElementById("statusBrush"),

    bomBrandBadge: document.getElementById("bomBrandBadge"),
    kpiGridSize: document.getElementById("kpiGridSize"),
    kpiBeadCount: document.getElementById("kpiBeadCount"),
    kpiPhysicalCm: document.getElementById("kpiPhysicalCm"),
    kpiBoardLabel: document.getElementById("kpiBoardLabel"),
    kpiBoardCount: document.getElementById("kpiBoardCount"),
    activeBrushSwatch: document.getElementById("activeBrushSwatch"),
    activeBrushCode: document.getElementById("activeBrushCode"),
    activeBrushMard: document.getElementById("activeBrushMard"),
    activeBrushName: document.getElementById("activeBrushName"),
    btnOpenPalette: document.getElementById("btnOpenPalette"),
    bomCountTitle: document.getElementById("bomCountTitle"),
    btnClearHighlight: document.getElementById("btnClearHighlight"),
    bomList: document.getElementById("bomList"),
    btnCopyBom: document.getElementById("btnCopyBom"),

    paletteModal: document.getElementById("paletteModal"),
    btnClosePalette: document.getElementById("btnClosePalette"),
    paletteSearchInput: document.getElementById("paletteSearchInput"),
    paletteSeriesTabs: document.getElementById("paletteSeriesTabs"),
    paletteGrid: document.getElementById("paletteGrid"),
    toastEl: document.getElementById("toastEl"),
  };

  const ctx = els.canvas.getContext("2d");
  let toastTimer = null;

  function showToast(msg) {
    els.toastEl.textContent = msg;
    els.toastEl.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toastEl.classList.add("hidden"), 2400);
  }

  function translateCode(mardCode, brand = state.brand) {
    const entry = state.paletteByCode.get(mardCode);
    if (!entry) return mardCode || "";
    return (entry.brands && entry.brands[brand]) || mardCode;
  }

  function cloneGrid(grid) {
    return grid.map((row) => row.slice());
  }

  function pushUndoSnapshot() {
    state.undoStack.push(cloneGrid(state.grid));
    if (state.undoStack.length > 60) state.undoStack.shift();
    state.redoStack = [];
    syncUndoButtons();
  }

  function syncUndoButtons() {
    els.btnUndo.disabled = state.undoStack.length === 0;
    els.btnRedo.disabled = state.redoStack.length === 0;
  }

  function doUndo() {
    if (!state.undoStack.length) return;
    state.redoStack.push(cloneGrid(state.grid));
    state.grid = state.undoStack.pop();
    syncUndoButtons();
    refreshUI();
  }

  function doRedo() {
    if (!state.redoStack.length) return;
    state.undoStack.push(cloneGrid(state.grid));
    state.grid = state.redoStack.pop();
    syncUndoButtons();
    refreshUI();
  }

  function computeLocalBom() {
    const counts = new Map();
    for (let r = 0; r < state.height; r++) {
      const row = state.grid[r];
      for (let c = 0; c < state.width; c++) {
        const code = row[c];
        if (code) counts.set(code, (counts.get(code) || 0) + 1);
      }
    }
    const items = [];
    let totalBeads = 0;
    let totalSpare = 0;
    for (const [mardCode, count] of counts.entries()) {
      const entry = state.paletteByCode.get(mardCode);
      if (!entry) continue;
      const spare = count + Math.max(2, Math.ceil(count * 0.1));
      totalBeads += count;
      totalSpare += spare;
      items.push({
        mardCode,
        displayCode: translateCode(mardCode, state.brand),
        hex: entry.hex,
        rgb: entry.rgb,
        nameZh: entry.name_zh,
        series: entry.series,
        count,
        spareCount: spare,
        brands: entry.brands,
      });
    }
    items.sort((a, b) => b.count - a.count);

    const wCm = ((state.width * state.beadMm) / 10).toFixed(1);
    const hCm = ((state.height * state.beadMm) / 10).toFixed(1);
    const board = state.beadMm > 4.0 ? 29 : 52;
    const bx = Math.ceil(state.width / board);
    const by = Math.ceil(state.height / board);

    return {
      items,
      totalBeads,
      totalSpare,
      colorCount: items.length,
      wCm,
      hCm,
      board,
      bx,
      by,
    };
  }

  function refreshBrushCard() {
    const entry = state.paletteByCode.get(state.brushCode);
    if (!entry) return;
    const disp = translateCode(entry.code, state.brand);
    els.activeBrushSwatch.style.backgroundColor = entry.hex;
    els.activeBrushCode.textContent = disp;
    els.activeBrushMard.textContent = state.brand !== "MARD" ? `(MARD ${entry.code})` : "";
    els.activeBrushName.textContent = `${entry.name_zh} · ${entry.hex}`;
    els.statusBrush.textContent = `当前画笔：${state.brand} ${disp}${state.brand !== "MARD" ? ` / MARD ${entry.code}` : ""} (${entry.name_zh})`;
  }

  function refreshBomPanel() {
    const bom = computeLocalBom();
    els.bomBrandBadge.textContent = state.brand;
    els.kpiGridSize.textContent = `${state.width}×${state.height} 格`;
    els.kpiBeadCount.textContent = `${bom.totalBeads} / ${bom.totalSpare}`;
    els.kpiPhysicalCm.textContent = `${bom.wCm}×${bom.hCm} cm`;
    els.kpiBoardLabel.textContent = `${bom.board}×${bom.board} 拼板`;
    els.kpiBoardCount.textContent = `${bom.bx}×${bom.by} 块 (${bom.bx * bom.by}块)`;
    els.bomCountTitle.textContent = `当前用色清单 (${bom.colorCount} 色)`;
    els.btnClearHighlight.classList.toggle("hidden", !state.highlightCode);

    els.bomList.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const item of bom.items) {
      const row = document.createElement("div");
      row.className = "bom-row" + (state.highlightCode === item.mardCode ? " isolated" : "");
      row.dataset.mard = item.mardCode;
      row.innerHTML = `
        <span class="bom-swatch" style="background:${item.hex}"></span>
        <div class="bom-meta">
          <div class="bom-code-line">
            <strong>${item.displayCode}</strong>
            ${state.brand !== "MARD" ? `<span class="bom-mard-ref">MARD ${item.mardCode}</span>` : ""}
          </div>
          <div class="bom-zh">${item.nameZh}</div>
        </div>
        <div class="bom-counts">
          <strong>${item.count} 颗</strong>
          <span>备 ${item.spareCount}</span>
        </div>
      `;
      row.addEventListener("click", () => {
        state.brushCode = item.mardCode;
        state.highlightCode = state.highlightCode === item.mardCode ? null : item.mardCode;
        refreshUI();
      });
      frag.appendChild(row);
    }
    els.bomList.appendChild(frag);
  }

  function fitCanvasToTray() {
    if (!state.width || !state.height) return;
    const rect = els.canvasTray.getBoundingClientRect();
    const pad = 64;
    const availW = Math.max(200, rect.width - pad);
    const availH = Math.max(200, rect.height - pad);
    const fitPx = Math.min(availW / state.width, availH / state.height);
    state.zoom = Math.max(0.25, Math.min(4.0, fitPx / state.cellBasePx));
    const gridW = state.width * state.cellBasePx * state.zoom;
    const gridH = state.height * state.cellBasePx * state.zoom;
    state.panX = Math.round((rect.width - gridW) / 2);
    state.panY = Math.round((rect.height - gridH) / 2);
    els.zoomPercent.textContent = `${Math.round(state.zoom * 100)}%`;
    renderCanvas();
  }

  function renderCanvas() {
    const rect = els.canvasTray.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const cw = Math.max(1, Math.floor(rect.width));
    const ch = Math.max(1, Math.floor(rect.height));
    if (els.canvas.width !== Math.floor(cw * dpr) || els.canvas.height !== Math.floor(ch * dpr)) {
      els.canvas.width = Math.floor(cw * dpr);
      els.canvas.height = Math.floor(ch * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);

    if (!state.width || !state.height) return;
    const cellPx = state.cellBasePx * state.zoom;
    const gridW = state.width * cellPx;
    const gridH = state.height * cellPx;
    const x0 = state.panX;
    const y0 = state.panY;

    const isBaked = state.viewMode === "baked";
    const showCodes = state.showCodes && !isBaked && cellPx >= 15;

    // 满焊平融实拍物理高度场渲染图
    if (isBaked) {
      const key = `${state.projectName}:${state.width}x${state.height}:${state.undoStack.length}`;
      if (state.bakedCacheKey === key && state.bakedImg && state.bakedImg.complete) {
        const aspect = state.bakedImg.width / Math.max(1, state.bakedImg.height);
        const targetW = gridW * 1.24;
        const targetH = targetW / aspect;
        const dx = x0 + (gridW - targetW) / 2;
        const dy = y0 + (gridH - targetH) / 2;
        ctx.drawImage(state.bakedImg, dx, dy, targetW, targetH);
      } else {
        if (state.bakedFetchingKey !== key) {
          state.bakedFetchingKey = key;
          fetch("/api/export/baked", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ grid: state.grid, title: state.projectName }),
          })
            .then((r) => (r.ok ? r.blob() : null))
            .then((blob) => {
              if (!blob) return;
              const url = URL.createObjectURL(blob);
              const img = new Image();
              img.onload = () => {
                state.bakedCacheKey = key;
                state.bakedImg = img;
                if (state.viewMode === "baked") renderCanvas();
                setTimeout(() => URL.revokeObjectURL(url), 5000);
              };
              img.src = url;
            })
            .catch(() => {});
        }
        ctx.save();
        ctx.fillStyle = "#E5DDD0";
        ctx.beginPath();
        ctx.roundRect(x0, y0, gridW, gridH, 14);
        ctx.fill();
        ctx.fillStyle = "#6B625B";
        ctx.font = '600 13px "Noto Sans SC", sans-serif';
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("正在渲染实物成品效果…", x0 + gridW / 2, y0 + gridH / 2);
        ctx.restore();
      }
      return;
    }

    // 纸张底座阴影（网格色号图模式）
    ctx.save();
    ctx.fillStyle = "#FFFDF9";
    ctx.shadowColor = "rgba(35, 31, 29, 0.14)";
    ctx.shadowBlur = 18;
    ctx.shadowOffsetY = 5;
    ctx.fillRect(x0, y0, gridW, gridH);
    ctx.restore();

    for (let r = 0; r < state.height; r++) {
      const cy = y0 + r * cellPx;
      if (cy + cellPx < 0 || cy > ch) continue;

      for (let c = 0; c < state.width; c++) {
        const cx = x0 + c * cellPx;
        if (cx + cellPx < 0 || cx > cw) continue;

        const code = state.grid[r][c];
        if (!code) {
          ctx.fillStyle = (r + c) % 2 === 0 ? "#FAF7F1" : "#F1EBE0";
          ctx.fillRect(cx, cy, cellPx + 0.3, cellPx + 0.3);
          continue;
        }

        const entry = state.paletteByCode.get(code);
        if (!entry) continue;

        const alpha = state.highlightCode && state.highlightCode !== code ? 0.14 : 1.0;

        ctx.globalAlpha = alpha;
        ctx.fillStyle = entry.hex;
        ctx.fillRect(cx, cy, cellPx + 0.35, cellPx + 0.35);

        if (showCodes) {
          const lum = 0.299 * entry.r + 0.587 * entry.g + 0.114 * entry.b;
          ctx.fillStyle = lum > 145 ? "#1F1C1A" : "#FFFFFF";
          const disp = translateCode(code, state.brand);
          const fSize = Math.max(7, Math.floor(cellPx * (disp.length > 3 ? 0.28 : 0.36)));
          ctx.font = `700 ${fSize}px "JetBrains Mono", Consolas, monospace`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(disp, cx + cellPx / 2, cy + cellPx / 2);
        }

        if (state.highlightCode && state.highlightCode === code) {
          ctx.strokeStyle = "#C95B3C";
          ctx.lineWidth = Math.max(1.2, cellPx * 0.09);
          ctx.strokeRect(cx + 0.5, cy + 0.5, cellPx - 1, cellPx - 1);
        }
        ctx.globalAlpha = 1.0;
      }
    }

    // 网格线与每5/10格加粗参考线
    if (state.showGrid) {
      for (let c = 0; c <= state.width; c++) {
        const x = Math.round(x0 + c * cellPx) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x, y0);
        ctx.lineTo(x, y0 + gridH);
        if (c % 10 === 0) {
          ctx.strokeStyle = "rgba(35, 31, 29, 0.58)";
          ctx.lineWidth = 1.4;
        } else if (c % 5 === 0) {
          ctx.strokeStyle = "rgba(35, 31, 29, 0.32)";
          ctx.lineWidth = 1.0;
        } else {
          ctx.strokeStyle = "rgba(35, 31, 29, 0.14)";
          ctx.lineWidth = 0.7;
        }
        ctx.stroke();
      }
      for (let r = 0; r <= state.height; r++) {
        const y = Math.round(y0 + r * cellPx) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x0, y);
        ctx.lineTo(x0 + gridW, y);
        if (r % 10 === 0) {
          ctx.strokeStyle = "rgba(35, 31, 29, 0.58)";
          ctx.lineWidth = 1.4;
        } else if (r % 5 === 0) {
          ctx.strokeStyle = "rgba(35, 31, 29, 0.32)";
          ctx.lineWidth = 1.0;
        } else {
          ctx.strokeStyle = "rgba(35, 31, 29, 0.14)";
          ctx.lineWidth = 0.7;
        }
        ctx.stroke();
      }
    }

    // 标尺坐标（顶/左）
    if (!isBaked && cellPx >= 9) {
      ctx.save();
      ctx.font = '600 10px "JetBrains Mono", Consolas, monospace';
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const step = cellPx >= 15 ? 1 : 5;
      for (let c = 0; c < state.width; c++) {
        if (step > 1 && (c + 1) % 5 !== 0 && c !== 0) continue;
        ctx.fillStyle = "#6B625B";
        ctx.fillText(String(c + 1), x0 + (c + 0.5) * cellPx, y0 - 10);
      }
      ctx.textAlign = "right";
      ctx.fillStyle = "#6B625B";
      for (let r = 0; r < state.height; r++) {
        if (step > 1 && (r + 1) % 5 !== 0 && r !== 0) continue;
        ctx.fillText(String(r + 1), x0 - 6, y0 + (r + 0.5) * cellPx);
      }
      ctx.restore();
    }

    // 悬停高亮十字准星
    if (state.hoverCell && !isBaked) {
      const { r, c } = state.hoverCell;
      ctx.save();
      ctx.strokeStyle = "#C95B3C";
      ctx.lineWidth = 2;
      ctx.strokeRect(x0 + c * cellPx, y0 + r * cellPx, cellPx, cellPx);
      ctx.restore();
    }
  }

  function refreshUI() {
    els.projectNameDisplay.textContent = `${state.projectName} · ${state.width}×${state.height} 格`;
    refreshBrushCard();
    refreshBomPanel();
    renderCanvas();
  }

  function applyLoadedPattern(data) {
    state.projectName = data.name || "拼豆作品";
    state.width = data.width;
    state.height = data.height;
    state.grid = cloneGrid(data.grid);
    state.undoStack = [];
    state.redoStack = [];
    state.highlightCode = null;
    syncUndoButtons();
    refreshUI();
    fitCanvasToTray();
  }

  function cellAtClientPos(clientX, clientY) {
    const rect = els.canvasTray.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const cellPx = state.cellBasePx * state.zoom;
    const c = Math.floor((x - state.panX) / cellPx);
    const r = Math.floor((y - state.panY) / cellPx);
    if (r < 0 || r >= state.height || c < 0 || c >= state.width) return null;
    return { r, c, x, y, trayW: rect.width, trayH: rect.height };
  }

  function applyToolAtCell(r, c, isFirstClick) {
    if (state.tool === "eyedropper") {
      const code = state.grid[r][c];
      if (code) {
        state.brushCode = code;
        state.tool = "brush";
        syncToolButtons();
        refreshBrushCard();
        showToast(`已吸取 ${state.brand} ${translateCode(code)}`);
      }
      return;
    }

    if (state.tool === "fill") {
      if (!isFirstClick) return;
      const target = state.grid[r][c];
      const replacement = state.brushCode;
      if (target === replacement) return;
      pushUndoSnapshot();
      const q = [[r, c]];
      const visited = new Set([`${r},${c}`]);
      while (q.length) {
        const [cr, cc] = q.shift();
        state.grid[cr][cc] = replacement;
        for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
          const nr = cr + dr;
          const nc = cc + dc;
          const key = `${nr},${nc}`;
          if (nr >= 0 && nr < state.height && nc >= 0 && nc < state.width && !visited.has(key) && state.grid[nr][nc] === target) {
            visited.add(key);
            q.push([nr, nc]);
          }
        }
      }
      refreshUI();
      return;
    }

    const nextVal = state.tool === "eraser" ? null : state.brushCode;
    if (state.grid[r][c] === nextVal) return;
    if (!state.strokeChanged) {
      pushUndoSnapshot();
      state.strokeChanged = true;
    }
    state.grid[r][c] = nextVal;
    refreshUI();
  }

  function syncToolButtons() {
    for (const btn of els.drawToolGroup.querySelectorAll(".tool-btn[data-tool]")) {
      btn.classList.toggle("active", btn.dataset.tool === state.tool);
    }
  }

  function renderPaletteModal() {
    const query = els.paletteSearchInput.value.trim().toUpperCase();
    const series = state.paletteSeriesFilter;
    els.paletteGrid.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const entry of state.palette) {
      if (series !== "ALL" && entry.series !== series) continue;
      if (query) {
        const matchFields = [
          entry.code,
          entry.name_zh,
          ...Object.values(entry.brands || {}),
        ].join(" ").toUpperCase();
        if (!matchFields.includes(query)) continue;
      }
      const disp = translateCode(entry.code, state.brand);
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "pal-tile";
      tile.innerHTML = `
        <span class="pal-tile-swatch" style="background:${entry.hex}"></span>
        <strong>${disp}${state.brand !== "MARD" ? ` · ${entry.code}` : ""}</strong>
        <span>${entry.name_zh}</span>
      `;
      tile.addEventListener("click", () => {
        state.brushCode = entry.code;
        state.tool = "brush";
        syncToolButtons();
        refreshBrushCard();
        els.paletteModal.classList.add("hidden");
        showToast(`画笔已设为 ${state.brand} ${disp} (${entry.name_zh})`);
      });
      frag.appendChild(tile);
    }
    els.paletteGrid.appendChild(frag);
  }

  async function loadGalleryProject(projectId) {
    try {
      const resp = await fetch(`/api/gallery/${encodeURIComponent(projectId)}`);
      if (!resp.ok) throw new Error("作品加载失败");
      const data = await resp.json();
      state.projectId = projectId;
      applyLoadedPattern(data);
    } catch (err) {
      showToast(err.message || "加载作品失败");
    }
  }

  async function triggerExport(endpoint, filename) {
    if (!state.grid.length) return;
    try {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grid: state.grid,
          title: state.projectName,
          name: state.projectName,
          brand: state.brand,
          bead_mm: state.beadMm,
          board_size: state.beadMm > 4.0 ? 29 : 52,
        }),
      });
      if (!resp.ok) throw new Error("导出请求失败");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      showToast(`已导出：${filename}`);
    } catch (err) {
      showToast(err.message || "导出失败");
    }
  }

  function handleSelectedImageFile(file) {
    if (!file) return;
    state.selectedFile = file;
    const reader = new FileReader();
    reader.onload = () => {
      els.uploadPreviewImg.src = reader.result;
      els.uploadPreviewImg.classList.remove("hidden");
      els.uploadPlaceholder.classList.add("hidden");
    };
    reader.readAsDataURL(file);
  }

  function bindEvents() {
    // 品牌切换（0ms 实时刷新全图、清单与提示）
    els.brandSwitcher.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn[data-brand]");
      if (!btn) return;
      state.brand = btn.dataset.brand;
      for (const b of els.brandSwitcher.querySelectorAll(".seg-btn")) {
        b.classList.toggle("active", b === btn);
      }
      refreshUI();
      showToast(`已切换为 ${state.brand} 色号标准`);
    });

    // 豆径切换
    els.beadSpecSwitcher.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn[data-mm]");
      if (!btn) return;
      state.beadMm = parseFloat(btn.dataset.mm);
      for (const b of els.beadSpecSwitcher.querySelectorAll(".seg-btn")) {
        b.classList.toggle("active", b === btn);
      }
      refreshBomPanel();
    });

    // 内置作品选择
    els.gallerySelect.addEventListener("change", () => {
      if (els.gallerySelect.value) loadGalleryProject(els.gallerySelect.value);
    });

    // 导出按钮组
    els.btnExportSheet.addEventListener("click", () =>
      triggerExport("/api/export/sheet", `${state.projectName}_${state.brand}版_施工图.png`)
    );
    els.btnExportBaked.addEventListener("click", () =>
      triggerExport("/api/export/baked", `${state.projectName}_2.6mm熨烫平融预览.jpg`)
    );
    els.btnExportCsv.addEventListener("click", () =>
      triggerExport("/api/export/csv", `${state.projectName}_${state.brand}版_五品牌采购清单.csv`)
    );
    els.btnExportPindou.addEventListener("click", () =>
      triggerExport("/api/export/pindou", `${state.projectName}.pindou.json`)
    );

    // 上传区
    els.uploadDropzone.addEventListener("click", () => els.imageFileInput.click());
    els.imageFileInput.addEventListener("change", (e) => handleSelectedImageFile(e.target.files[0]));
    els.uploadDropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      els.uploadDropzone.classList.add("drag-over");
    });
    els.uploadDropzone.addEventListener("dragleave", () => els.uploadDropzone.classList.remove("drag-over"));
    els.uploadDropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      els.uploadDropzone.classList.remove("drag-over");
      if (e.dataTransfer.files[0]) handleSelectedImageFile(e.dataTransfer.files[0]);
    });

    // 转换模式
    els.convertModeGroup.addEventListener("click", (e) => {
      const card = e.target.closest(".mode-card[data-mode]");
      if (!card) return;
      state.convertMode = card.dataset.mode;
      for (const c of els.convertModeGroup.querySelectorAll(".mode-card")) {
        c.classList.toggle("active", c === card);
      }
      if (state.convertMode === "cutout_outline") {
        els.chkRemoveBg.checked = true;
        els.chkOutline.checked = true;
      }
    });

    els.inputMaxColors.addEventListener("input", () => {
      els.maxColorsLabel.textContent = `${els.inputMaxColors.value} 色`;
    });

    // 生成图纸
    els.btnConvert.addEventListener("click", async () => {
      if (!state.selectedFile) {
        showToast("请先上传或拖拽一张照片 / 参考图");
        return;
      }
      els.btnConvert.disabled = true;
      els.btnConvert.textContent = "正在按国内标准计算…";
      try {
        const fd = new FormData();
        fd.append("file", state.selectedFile);
        fd.append("mode", state.convertMode);
        fd.append("width", els.inputWidth.value);
        fd.append("height", els.inputHeight.value);
        fd.append("max_colors", els.inputMaxColors.value);
        fd.append("suppress_green_cast", els.chkSuppressGreen.checked ? "true" : "false");
        fd.append("smooth_eyes", els.chkSmoothEyes.checked ? "true" : "false");
        fd.append("remove_bg", els.chkRemoveBg.checked ? "true" : "false");
        fd.append("add_outline", els.chkOutline.checked ? "true" : "false");
        fd.append("brand", state.brand);
        fd.append("bead_mm", String(state.beadMm));
        fd.append("board_size", String(state.beadMm > 4 ? 29 : 52));

        const resp = await fetch("/api/convert", { method: "POST", body: fd });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || "转换失败");
        }
        const data = await resp.json();
        applyLoadedPattern(data);
        showToast(`转换完成：${data.width}×${data.height} · ${data.bom.color_count} 色`);
      } catch (err) {
        showToast(err.message || "转换出错");
      } finally {
        els.btnConvert.disabled = false;
        els.btnConvert.textContent = "生成拼豆图纸";
      }
    });

    // 导入 .pindou.json / 新建空白板
    els.btnImportPindou.addEventListener("click", () => els.pindouImportInput.click());
    els.pindouImportInput.addEventListener("change", async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append("file", f);
      try {
        const resp = await fetch("/api/import-pindou", { method: "POST", body: fd });
        if (!resp.ok) throw new Error("工程文件格式无效");
        const data = await resp.json();
        applyLoadedPattern(data);
        showToast(`已导入工程：${data.name}`);
      } catch (err) {
        showToast(err.message);
      }
      e.target.value = "";
    });

    els.btnNewBlank.addEventListener("click", () => {
      const w = Math.max(12, Math.min(128, parseInt(els.inputWidth.value, 10) || 52));
      const h = Math.max(12, Math.min(128, parseInt(els.inputHeight.value, 10) || 52));
      const blank = Array.from({ length: h }, () => Array(w).fill(null));
      applyLoadedPattern({ name: `新建空白拼板_${w}x${h}`, width: w, height: h, grid: blank });
      showToast(`已创建 ${w}×${h} 空白拼板`);
    });

    // 视图模式 & 画笔工具
    els.viewModeTabs.addEventListener("click", (e) => {
      const tab = e.target.closest(".view-tab[data-view]");
      if (!tab) return;
      state.viewMode = tab.dataset.view;
      for (const t of els.viewModeTabs.querySelectorAll(".view-tab")) {
        t.classList.toggle("active", t === tab);
      }
      renderCanvas();
    });

    els.drawToolGroup.addEventListener("click", (e) => {
      const btn = e.target.closest(".tool-btn[data-tool]");
      if (!btn) return;
      state.tool = btn.dataset.tool;
      syncToolButtons();
    });

    els.btnUndo.addEventListener("click", doUndo);
    els.btnRedo.addEventListener("click", doRedo);
    els.chkShowCodes.addEventListener("change", () => {
      state.showCodes = els.chkShowCodes.checked;
      renderCanvas();
    });
    els.chkShowGrid.addEventListener("change", () => {
      state.showGrid = els.chkShowGrid.checked;
      renderCanvas();
    });

    els.btnZoomIn.addEventListener("click", () => {
      state.zoom = Math.min(4.0, state.zoom * 1.2);
      els.zoomPercent.textContent = `${Math.round(state.zoom * 100)}%`;
      renderCanvas();
    });
    els.btnZoomOut.addEventListener("click", () => {
      state.zoom = Math.max(0.25, state.zoom / 1.2);
      els.zoomPercent.textContent = `${Math.round(state.zoom * 100)}%`;
      renderCanvas();
    });
    els.btnFitView.addEventListener("click", fitCanvasToTray);

    // 高亮清除与复制采购文本
    els.btnClearHighlight.addEventListener("click", () => {
      state.highlightCode = null;
      refreshUI();
    });

    els.btnCopyBom.addEventListener("click", async () => {
      const bom = computeLocalBom();
      const lines = [
        `【${state.projectName}】${state.width}×${state.height}格 · ${state.beadMm}mm成品约${bom.wCm}×${bom.hCm}cm · ${bom.totalBeads}颗(${bom.colorCount}色)`,
        `当前视图品牌: ${state.brand}`,
        ...bom.items.map(
          (i) =>
            `${i.displayCode} (MARD:${i.mardCode} | COCO:${i.brands.COCO} | 漫漫:${i.brands["漫漫"]} | 盼盼:${i.brands["盼盼"]} | 咪小窝:${i.brands["咪小窝"]}) ${i.nameZh} ×${i.count}颗 (备豆:${i.spareCount})`
        ),
      ];
      try {
        await navigator.clipboard.writeText(lines.join("\n"));
        showToast("已复制 5 品牌采购清单到剪贴板");
      } catch {
        showToast("剪贴板不可用，请直接使用顶部『清单 CSV』导出");
      }
    });

    // 全色卡弹窗
    els.btnOpenPalette.addEventListener("click", () => {
      els.paletteModal.classList.remove("hidden");
      renderPaletteModal();
      els.paletteSearchInput.focus();
    });
    els.btnClosePalette.addEventListener("click", () => els.paletteModal.classList.add("hidden"));
    els.paletteModal.addEventListener("click", (e) => {
      if (e.target === els.paletteModal) els.paletteModal.classList.add("hidden");
    });
    els.paletteSearchInput.addEventListener("input", renderPaletteModal);
    els.paletteSeriesTabs.addEventListener("click", (e) => {
      const btn = e.target.closest(".series-btn[data-series]");
      if (!btn) return;
      state.paletteSeriesFilter = btn.dataset.series;
      for (const b of els.paletteSeriesTabs.querySelectorAll(".series-btn")) {
        b.classList.toggle("active", b === btn);
      }
      renderPaletteModal();
    });

    // 画布鼠标/滚轮交互
    els.canvas.addEventListener("mousedown", (e) => {
      if (e.button === 1 || state.spaceHeld) {
        state.isPanning = true;
        state.panStartX = e.clientX;
        state.panStartY = e.clientY;
        state.panOriginX = state.panX;
        state.panOriginY = state.panY;
        return;
      }
      if (e.button !== 0) return;
      const cell = cellAtClientPos(e.clientX, e.clientY);
      if (!cell) return;
      state.isPainting = true;
      state.strokeChanged = false;
      applyToolAtCell(cell.r, cell.c, true);
    });

    window.addEventListener("mousemove", (e) => {
      if (state.isPanning) {
        state.panX = state.panOriginX + (e.clientX - state.panStartX);
        state.panY = state.panOriginY + (e.clientY - state.panStartY);
        renderCanvas();
        return;
      }
      const cell = cellAtClientPos(e.clientX, e.clientY);
      if (state.isPainting && cell) {
        applyToolAtCell(cell.r, cell.c, false);
      }
      state.hoverCell = cell ? { r: cell.r, c: cell.c } : null;
      if (!cell) {
        els.hoverTooltip.classList.add("hidden");
        els.statusCoords.textContent = "坐标：移入网格查看行列与 5 品牌色号";
        renderCanvas();
        return;
      }
      const code = state.grid[cell.r][cell.c];
      const entry = code ? state.paletteByCode.get(code) : null;
      if (entry) {
        const b = entry.brands || {};
        els.statusCoords.textContent = `坐标：第 ${cell.r + 1} 行, 第 ${cell.c + 1} 列 | ${state.brand} ${translateCode(code)} (${entry.name_zh})`;
        els.hoverTooltip.innerHTML = `
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
            <span style="width:12px;height:12px;border-radius:3px;background:${entry.hex};border:1px solid rgba(255,255,255,0.4);"></span>
            <strong>R${cell.r + 1} C${cell.c + 1} · ${entry.name_zh}</strong>
          </div>
          <div style="font-family:var(--font-mono);font-size:11px;line-height:1.45;opacity:0.92;">
            MARD:${b.MARD} · COCO:${b.COCO}<br/>
            漫漫:${b["漫漫"]} · 盼盼:${b["盼盼"]} · 咪小窝:${b["咪小窝"]}
          </div>
        `;
      } else {
        els.statusCoords.textContent = `坐标：第 ${cell.r + 1} 行, 第 ${cell.c + 1} 列 | 空孔位`;
        els.hoverTooltip.innerHTML = `<strong>R${cell.r + 1} C${cell.c + 1}</strong> · 空孔位（未放豆）`;
      }
      const tx = Math.min(cell.trayW - 210, Math.max(8, cell.x + 16));
      const ty = Math.min(cell.trayH - 76, Math.max(8, cell.y + 16));
      els.hoverTooltip.style.left = `${tx}px`;
      els.hoverTooltip.style.top = `${ty}px`;
      els.hoverTooltip.classList.remove("hidden");
      renderCanvas();
    });

    window.addEventListener("mouseup", () => {
      state.isPainting = false;
      state.strokeChanged = false;
      state.isPanning = false;
    });

    els.canvas.addEventListener("mouseleave", () => {
      state.hoverCell = null;
      els.hoverTooltip.classList.add("hidden");
      renderCanvas();
    });

    els.canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const rect = els.canvasTray.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const oldZoom = state.zoom;
        const factor = e.deltaY < 0 ? 1.12 : 0.89;
        const newZoom = Math.max(0.25, Math.min(4.5, oldZoom * factor));
        state.panX = mx - ((mx - state.panX) * newZoom) / oldZoom;
        state.panY = my - ((my - state.panY) * newZoom) / oldZoom;
        state.zoom = newZoom;
        els.zoomPercent.textContent = `${Math.round(state.zoom * 100)}%`;
        renderCanvas();
      },
      { passive: false }
    );

    // 快捷键
    window.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      if (e.code === "Space") {
        state.spaceHeld = true;
        els.canvasTray.style.cursor = "grab";
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        doUndo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault();
        doRedo();
      } else if (e.key.toLowerCase() === "b") {
        state.tool = "brush";
        syncToolButtons();
      } else if (e.key.toLowerCase() === "e") {
        state.tool = "eraser";
        syncToolButtons();
      } else if (e.key.toLowerCase() === "i") {
        state.tool = "eyedropper";
        syncToolButtons();
      } else if (e.key.toLowerCase() === "g") {
        state.tool = "fill";
        syncToolButtons();
      }
    });

    window.addEventListener("keyup", (e) => {
      if (e.code === "Space") {
        state.spaceHeld = false;
        els.canvasTray.style.cursor = "crosshair";
      }
    });

    window.addEventListener("resize", renderCanvas);
  }

  async function init() {
    bindEvents();
    try {
      const [stdResp, galResp] = await Promise.all([fetch("/api/standards"), fetch("/api/gallery")]);
      const stdData = await stdResp.json();
      const galData = await galResp.json();

      state.palette = stdData.palette || [];
      state.paletteByCode = new Map(state.palette.map((e) => [e.code, e]));
      state.gallery = galData.items || [];

      // 渲染尺寸预设按钮
      els.boardPresetChips.innerHTML = "";
      for (const p of stdData.board_presets || []) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "preset-chip" + (p.id === "cutout_40" ? " active" : "");
        chip.textContent = `${p.w}×${p.h}`;
        chip.title = `${p.label} · ${p.desc}`;
        chip.addEventListener("click", () => {
          els.inputWidth.value = p.w;
          els.inputHeight.value = p.h;
          for (const c of els.boardPresetChips.querySelectorAll(".preset-chip")) {
            c.classList.toggle("active", c === chip);
          }
        });
        els.boardPresetChips.appendChild(chip);
      }

      // 填充内置作品库下拉
      els.gallerySelect.innerHTML = "";
      for (const item of state.gallery) {
        const opt = document.createElement("option");
        opt.value = item.id;
        opt.textContent = `${item.name} (${item.width}×${item.height} · ${item.bead_count}颗)`;
        els.gallerySelect.appendChild(opt);
      }

      if (state.gallery.length > 0) {
        // 默认优先打开 40×38 异形描边猫脸作品，没有则加载第一项
        const preferred =
          state.gallery.find((x) => x.name.includes("图二_异形描边像素款")) ||
          state.gallery[state.gallery.length - 1];
        els.gallerySelect.value = preferred.id;
        await loadGalleryProject(preferred.id);
      }
    } catch (err) {
      showToast("初始化数据失败：" + (err.message || err));
    }
  }

  init();
})();
