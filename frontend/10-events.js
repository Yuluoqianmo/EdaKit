  bind("btnsearch", "click", search); bind("btnclear", "click", resetFilters);
  function keywordChanged() { packages(450); markDirty(); }
  bind("kw", "keyup", function (ev) { ev = ev || window.event; if (ev.keyCode !== 13) { keywordChanged(); } }); bind("kw", "change", keywordChanged); bind("kw", "input", keywordChanged);
  bind("kw", "keydown", function (ev) { ev = ev || window.event; if (ev.keyCode === 13) { search(); } });
  bind("cat", "change", function () { categoryChanged(1); }); bind("cat2", "change", function () { categoryChanged(2); }); bind("cat3", "change", function () { categoryChanged(3); });
  bind("prev", "click", function () { if (state.catalog.page > 1) { query(state.catalog.applied, state.catalog.page - 1, state.catalog.size); } }); bind("next", "click", function () { if (state.catalog.page < Math.ceil(state.catalog.total / state.catalog.size)) { query(state.catalog.applied, state.catalog.page + 1, state.catalog.size); } });
  bind("pagesize", "change", function () { query(state.catalog.applied, 1, parseInt(el("pagesize").value, 10)); });
  bind("cancelquery", "click", cancelQuery); bind("queryretry", "click", function () { if (state.catalog.failed) { query(state.catalog.failed.criteria, state.catalog.failed.page, state.catalog.failed.size); } });
  bind("facetretry", "click", function () { state.catalog.facetContext = null; packages(0); });
  bind("morefilters", "click", function () { allParams(true); });
  bind("allparamclose", "click", function () { allParams(false); }); bind("allparamdone", "click", function () { allParams(false); }); bind("allparammask", "click", function () { allParams(false); });
  bind("allparamquery", "click", function () { allParams(false); search(); });
  bind("facetarea", "scroll", closePicker);
  bind("clearparams", "click", function () { state.catalog.chosen = {}; updateButtons(); closePicker(); markDirty(); });
  function toggleRail() { el("categorychooser").style.display = el("categorychooser").style.display === "none" ? "" : "none"; closePicker(); }
  bind("railtoggle", "click", toggleRail); bind("categorypath", "click", toggleRail); bind("backresults", "click", function () { state.layout.phoneDetail = false; layout(); }); bind("railclose", "click", toggleRail);
  bind("pickersearch", "keyup", drawPicker); bind("pickersearch", "input", drawPicker); bind("pickerclose", "click", closePicker);
  bind("pickerclear", "click", function () { if (!state.catalog.picker) { return; } delete state.catalog.chosen[state.catalog.picker.key]; updateButtons(); markDirty(); drawPicker(); });
  bind(document, "click", function (ev) { ev = ev || window.event; var target = ev.target || ev.srcElement; while (target) { if (target.id === "facetpopup" || (target.className && String(target.className).indexOf("facetbutton") >= 0)) { return; } target = target.parentNode; } closePicker(); });
  bind(document, "click", function (ev) { ev = ev || window.event; var target = ev.target || ev.srcElement; while (target) { if (target.id === "categorychooser" || target.id === "railtoggle" || target.id === "categorypath") { return; } target = target.parentNode; } el("categorychooser").style.display = "none"; });
  bind(document, "keydown", function (ev) { ev = ev || window.event; if (ev.keyCode === 27) { el("categorychooser").style.display = "none"; if (state.catalog.picker) { closePicker(); } else if (state.catalog.more) { allParams(false); } } });
  bind("datasheet", "click", function (ev) {
    ev = ev || window.event; if (ev.preventDefault) { ev.preventDefault(); } ev.returnValue = false;
    if (!state.selection.sel || state.selection.openingDoc) { return false; } var cid = state.selection.sel.cid;
    state.selection.openingDoc = true; el("datasheet").className = "datalink opening"; text(el("datasheet"), "正在打开手册…"); beginWait("doc", "正在打开数据手册", 80);
    notice("正在打开数据手册，请稍候…");
    function done() { state.selection.openingDoc = false; el("datasheet").className = "datalink"; text(el("datasheet"), "数据手册 ↗"); endWait("doc"); }
    jsonp("/api/es/datasheet/open", { cid: cid }, function (d) { done(); if (state.selection.sel && state.selection.sel.cid === cid) { notice(d.message); } }, function (msg) { done(); if (state.selection.sel && state.selection.sel.cid === cid) { notice(msg || "数据手册打开失败，请重试"); } });
    return false;
  });
  bind("btnplace", "click", place); bind("tabsymbol", "click", function () { state.preview.kind = "symbol"; renderPreview(true); }); bind("tabfootprint", "click", function () { state.preview.kind = "footprint"; renderPreview(true); });
  bind("tab3d", "click", function () { state.preview.kind = "model3d"; renderPreview(true); });
  function rotate(yaw, pitch) { state.preview.yaw = (state.preview.yaw + yaw + 360) % 360; state.preview.pitch = Math.max(-85, Math.min(85, state.preview.pitch + pitch)); renderPreview(false); }
  bind("rotateleft", "click", function () { rotate(-30, 0); }); bind("rotateright", "click", function () { rotate(30, 0); }); bind("rotatetop", "click", function () { rotate(0, state.preview.pitch >= 75 ? -60 : 20); });
  bind("largeleft", "click", function () { rotate(-30, 0); }); bind("largeright", "click", function () { rotate(30, 0); }); bind("largetop", "click", function () { rotate(0, state.preview.pitch >= 75 ? -60 : 20); });
  bind("zoomin", "click", function () { zoom(1.4); }); bind("zoomout", "click", function () { zoom(1 / 1.4); }); bind("zoomfit", "click", function () { renderPreview(true); }); bind("zoomfull", "click", function () { full(true); });
  bind("largein", "click", function () { zoom(1.4); }); bind("largeout", "click", function () { zoom(1 / 1.4); }); bind("largefit", "click", function () { renderPreview(true); }); bind("largeclose", "click", function () { full(false); });
  bind("previewport", "dblclick", function () { full(true); }); bind(document, "keydown", function (ev) { ev = ev || window.event; if (ev.keyCode === 27 && state.preview.full) { full(false); } });
  function wheel(ev) { ev = ev || window.event; var d = ev.wheelDelta || -ev.detail || -ev.deltaY; zoom(d > 0 ? 1.2 : 1 / 1.2, ev); if (ev.preventDefault) { ev.preventDefault(); } ev.returnValue = false; return false; }
  function pan(ev) { ev = ev || window.event; if (ev.button !== 0 && ev.button !== 1) { return; } var port = this.id === "largeport" ? el("largeport") : view(); state.preview.drag = { port: port, x: ev.clientX, y: ev.clientY, left: port.scrollLeft, top: port.scrollTop }; if (ev.preventDefault) { ev.preventDefault(); } ev.returnValue = false; }
  function bindPort(id) { var port = el(id); port.onmousedown = pan; if (port.addEventListener) { port.addEventListener("wheel", wheel, false); } else { port.onmousewheel = wheel; } }
  bindPort("previewport"); bindPort("largeport");
  el("previewimg").ondragstart = el("largeimg").ondragstart = function () { return false; };
  bind(document, "mousemove", function (ev) { if (!state.preview.drag) { return; } ev = ev || window.event; var d = state.preview.drag; if (state.preview.kind === "model3d") { d.dx = ev.clientX - d.x; d.dy = ev.clientY - d.y; } else { d.port.scrollLeft = d.left + d.x - ev.clientX; d.port.scrollTop = d.top + d.y - ev.clientY; } }); bind(document, "mouseup", function () { var d = state.preview.drag; state.preview.drag = null; if (d && state.preview.kind === "model3d" && (d.dx || d.dy)) { rotate(Math.round((d.dx || 0) / 3), Math.round((d.dy || 0) / 3)); } });
  bind(window, "resize", function () { closePicker(); scheduleLayout(); });
  applyColumns(); layout(); status(); resetDetail(); drawRows(); window.setInterval(status, 10000); window.setInterval(paintWait, 1000);
  beginWait("categories", "正在加载电子分类", 30);
  jsonp("/api/es/categories", {}, function (d) { endWait("categories"); state.catalog.cats = d.categories || []; options("cat", state.catalog.cats, "全部分类"); navigation(); }, function () { endWait("categories"); options("cat", [], "分类加载失败"); notice("分类加载失败，仍可输入型号查询；重新打开商城可重试"); });
