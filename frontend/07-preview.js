  var previewLane = String(new Date().getTime()) + "-" + String(Math.random()).slice(2), previewRevision = 0;
  function view() { return el(state.preview.full ? "largeport" : "previewport"); }
  function cancelImage(id) {
    var request = state.preview.images[id]; if (request) { window.clearTimeout(request.timer); request.pending = false; request.next = null; }
    endWait("image:" + id);
  }
  function showEmpty(message) { cancelImage("previewimg"); el("previewimg").setAttribute("data-preview", ""); el("previewimg").setAttribute("data-loaded", ""); el("previewimg").style.display = "none"; el("previewempty").style.display = ""; text(el("previewempty"), message); }
  function loadImage(img, url, label) {
    var id = img.id, empty = el(id === "largeimg" ? "largeempty" : "previewempty"), current = state.preview.images[id];
    if (img.getAttribute("data-preview") === url && current && (current.pending || current.loaded)) { current.next = null; return; }
    if (current && current.pending) { current.next = { url: url, label: label }; return; }
    cancelImage(id); var request = { pending: true, loaded: false, timer: null }; state.preview.images[id] = request;
    empty.className = img.getAttribute("data-loaded") ? "previewempty updating" : "previewempty";
    img.setAttribute("data-preview", url); img.style.visibility = img.getAttribute("data-loaded") ? "visible" : "hidden"; empty.style.display = ""; text(empty, label + "，请稍候…"); beginWait("image:" + id, label, 70);
    function finish(ok, message) {
      if (state.preview.images[id] !== request || !request.pending) { return; }
      request.pending = false; request.loaded = ok; window.clearTimeout(request.timer); endWait("image:" + id);
      if (request.next) { var next = request.next; loadImage(img, next.url, next.label); return; }
      if (ok) { img.setAttribute("data-loaded", url); img.style.visibility = "visible"; empty.style.display = "none"; }
      else { img.style.visibility = "hidden"; img.setAttribute("data-preview", ""); text(empty, message); empty.style.display = ""; }
    }
    img.onload = function () { if (img.complete) { finish(true); } };
    img.onerror = function () { finish(false, "预览加载失败，请点击“适应窗口”重试或查看服务日志"); };
    request.timer = window.setTimeout(function () { finish(false, "预览等待超时，请点击“适应窗口”重试"); }, 45000);
    img.src = url + "&lane=" + encodeURIComponent(previewLane + ":" + id) + "&revision=" + (++previewRevision);
  }
  function layerControl() {
    var select = el("previewlayers");
    if (!select) {
      select = document.createElement("select"); select.id = "previewlayers";
      select.title = "封装预览图层（不修改导出内容）"; select.style.fontSize = "11px";
      var values = ["all", "pads", "silk", "assembly"], labels = ["全部图层", "焊盘与钻孔", "丝印", "装配外形"];
      for (var i = 0; i < values.length; i++) { var option = document.createElement("option"); option.value = values[i]; text(option, labels[i]); select.appendChild(option); }
      select.onchange = function () { renderPreview(false); };
      el("zoomtools").appendChild(select);
    }
    select.style.display = state.preview.kind === "footprint" ? "" : "none";
    return select.value || "all";
  }
  function renderPreview(reset) {
    if (!state.selection.detail) { return; }
    el("tabfootprint").className = "tab" + (state.preview.kind === "footprint" ? " active" : ""); el("tabsymbol").className = "tab" + (state.preview.kind === "symbol" ? " active" : ""); el("tab3d").className = "tab" + (state.preview.kind === "model3d" ? " active" : "");
    var layers = layerControl();
    var is3d = state.preview.kind === "model3d", has = is3d ? state.selection.detail.model3d : state.preview.kind === "footprint" ? state.selection.detail.hasFootprint : state.selection.detail.hasSymbol;
    el("orbittools").style.display = el("largeorbit").style.display = is3d ? "" : "none";
    text(el("previewhint"), is3d ? "拖动后更新旋转视角 · 滚轮缩放 · 双击打开大图" : "滚轮缩放 · 按住鼠标拖动 · 双击预览打开大图");
    text(el("largehint"), is3d ? "拖动后更新旋转视角 · 滚轮缩放" : "滚轮缩放 · 按住鼠标拖动");
    text(el("geometry"), is3d ? "真实模型" : state.preview.kind === "footprint" ? (state.selection.detail.padCount || 0) + " 焊盘" : (state.selection.detail.pinCount || 0) + " 引脚");
    if (!has) { showEmpty(state.preview.kind === "footprint" ? "该元件没有封装数据" : "该元件没有符号数据"); return; }
    if (reset) { state.preview.zoom = 1; }
    var port = view(), size = Math.max(80, Math.floor(Math.min(port.clientWidth - 30, port.clientHeight - 30) * state.preview.zoom));
    var pixels = size * Math.min(2, window.devicePixelRatio || 1);
    var resolution = pixels > 2048 ? 4096 : pixels > 1024 ? 2048 : pixels > 512 ? 1024 : 512;
    if (is3d) { resolution = Math.min(1024, resolution); }
    var url = "/api/png/" + state.preview.kind + "/" + encodeURIComponent(state.selection.sel.cid) + ".png?token=" + encodeURIComponent(window.__edakitToken || "") + "&size=" + resolution;
    if (state.preview.kind === "footprint") { url += "&layers=" + encodeURIComponent(layers); }
    if (is3d) { url += "&yaw=" + state.preview.yaw + "&pitch=" + state.preview.pitch; }
    var img = el(state.preview.full ? "largeimg" : "previewimg"), canvas = el(state.preview.full ? "largecanvas" : "previewcanvas");
    var cw = Math.max(port.clientWidth - 2, size + 30), ch = Math.max(port.clientHeight - 2, size + 30);
    canvas.style.width = cw + "px"; canvas.style.height = ch + "px";
    img.style.width = size + "px"; img.style.height = size + "px"; img.style.left = Math.floor((cw - size) / 2) + "px"; img.style.top = Math.floor((ch - size) / 2) + "px"; img.style.display = "";
    loadImage(img, url, is3d ? "正在生成3D视角预览" : "正在生成" + (state.preview.kind === "footprint" ? "封装" : "符号") + "预览");
    text(el(state.preview.full ? "largezoomlabel" : "zoomlabel"), Math.round(state.preview.zoom * 100) + "%");
    if (reset) { port.scrollLeft = Math.max(0, (cw - port.clientWidth) / 2); port.scrollTop = Math.max(0, (ch - port.clientHeight) / 2); }
  }
  function zoom(factor, ev) {
    if (!state.selection.detail) { return; } var port = view(), before = state.preview.zoom;
    var px = port.clientWidth / 2, py = port.clientHeight / 2;
    if (ev && port.getBoundingClientRect) { var rect = port.getBoundingClientRect(); px = ev.clientX - rect.left; py = ev.clientY - rect.top; }
    var x = port.scrollLeft + px, y = port.scrollTop + py;
    state.preview.zoom = Math.max(0.5, Math.min(8, state.preview.zoom * factor)); renderPreview(false);
    var ratio = state.preview.zoom / before; port.scrollLeft = x * ratio - px; port.scrollTop = y * ratio - py;
  }
  function full(open) { if (open && !state.selection.detail) { return; } cancelImage(open ? "previewimg" : "largeimg"); state.preview.full = open; state.preview.zoom = 1; el("largeview").style.display = open ? "" : "none"; text(el("largetitle"), (state.selection.sel ? state.selection.sel.model + " · " : "") + (state.preview.kind === "model3d" ? "3D 模型" : state.preview.kind === "footprint" ? "PCB 封装" : "原理图符号")); layout(); renderPreview(true); }
