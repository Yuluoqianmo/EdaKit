  var visibleColumns = [true, true, true, true, true, false];
  function applyColumns() {
    var weights = [33, 23, 24, 10, 10, 32], total = 0, classes = "panel", i, j, cols;
    for (i = 0; i < weights.length; i++) { if (visibleColumns[i]) { total += weights[i]; } else { classes += " hide-column-" + i; } }
    el("results").className = classes;
    var tables = [el("list"), el("listheadtable")];
    for (j = 0; j < tables.length; j++) { cols = tables[j].getElementsByTagName("col"); for (i = 0; i < cols.length; i++) { cols[i].style.display = visibleColumns[i] ? "" : "none"; cols[i].style.width = visibleColumns[i] ? (weights[i] * 100 / total) + "%" : "0"; } }
    syncListHead();
  }
  bind("columnbutton", "click", function () { el("columnmenu").style.display = el("columnmenu").style.display === "none" ? "" : "none"; });
  var columnInputs = el("columnmenu").getElementsByTagName("input");
  for (var ci = 0; ci < columnInputs.length; ci++) { bind(columnInputs[ci], "change", function () { visibleColumns[parseInt(this.getAttribute("data-column"), 10)] = this.checked; applyColumns(); }); }
  bind(document, "click", function (ev) { ev = ev || window.event; var target = ev.target || ev.srcElement; while (target) { if (target.id === "columnbutton" || target.id === "columnmenu") { return; } target = target.parentNode; } el("columnmenu").style.display = "none"; });
  function syncListHead() { el("listheadtable").style.width = el("listbox").clientWidth + "px"; }
  var layoutQueued = false;
  function scheduleLayout() { if (layoutQueued) { return; } layoutQueued = true; (window.requestAnimationFrame || function (fn) { window.setTimeout(fn, 16); })(function () { layoutQueued = false; layout(); }); }
  function layout() {
    var w = document.documentElement.clientWidth || document.body.clientWidth, h = document.documentElement.clientHeight || document.body.clientHeight;
    var dock = w < 1050, phone = w < 640, short = h < 650, margin = 12, content = w - margin * 2, top = 158, available = Math.max(220, h - top - 132), detailH, listH;
    document.body.className = phone ? "phone" : dock ? "dock" : "wide";
    el("sidebar").style.display = "none";
    el("filters").style.left = el("workspace").style.left = margin + "px";
    el("filters").style.top = "80px"; el("filters").style.height = "66px";
    el("workspace").style.top = top + "px";
    el("largeview").style.width = w + "px"; el("largeview").style.height = h + "px";
    var sw = Math.max(130, w - 196); el("kw").style.width = sw + "px";
    el("btnsearch").style.left = (sw + 34) + "px"; el("btnclear").style.left = (sw + 112) + "px";
    el("searchhelp").style.display = "none";
    var pathW = Math.max(110, Math.floor(content * .28)), commonLeft = 80 + pathW, areaW = Math.max(180, content - commonLeft - 112);
    el("categorypath").style.width = pathW + "px";
    var names = [], ids = ["cat", "cat2", "cat3"], i, node;
    for (i = 0; i < ids.length; i++) { node = el(ids[i]); if (node.value !== "0" && node.selectedIndex >= 0) { names.push(node.options[node.selectedIndex].text); } }
    text(el("categorypath"), names.length ? names.join(" › ") : "全部分类"); el("categorypath").title = names.join(" / ") || "选择分类";
    el("facetplaceholder").style.display = "none";
    var panelW = Math.max(300, Math.min(1060, w - 32)), columns = panelW >= 900 ? 4 : panelW >= 650 ? 3 : 2;
    var panelH = Math.min(h - 32, Math.max(270, 142 + Math.ceil(state.catalog.facets.length / columns) * 82));
    el("allparammask").style.width = w + "px"; el("allparammask").style.height = h + "px";
    el("allparams").style.width = panelW + "px"; el("allparams").style.height = panelH + "px";
    el("allparams").style.left = Math.floor((w - panelW) / 2) + "px"; el("allparams").style.top = Math.floor((h - panelH) / 2) + "px";
    var fieldsW = state.catalog.more ? panelW - 44 : areaW, fieldColumns = state.catalog.more ? columns : 2, fieldW = Math.floor((fieldsW - (fieldColumns - 1) * 10) / fieldColumns), count = 0, groups = [el("facetfields").childNodes, el("facetextra").childNodes], j;
    for (j = 0; j < groups.length; j++) { for (i = 0; i < groups[j].length; i++) { node = groups[j][i]; if (node.nodeType !== 1) { continue; } node.style.left = ((count % fieldColumns) * (fieldW + 10)) + "px"; node.style.top = (state.catalog.more ? Math.floor(count / fieldColumns) * 82 : 0) + "px"; node.style.width = fieldW + "px"; node.getElementsByTagName("button")[0].style.width = fieldW + "px"; count++; } }
    el("facetarea").style.position = state.catalog.more ? "relative" : "absolute";
    el("facetarea").style.left = state.catalog.more ? "0px" : commonLeft + "px";
    el("facetarea").style.top = state.catalog.more ? "0px" : "2px";
    el("facetarea").style.width = fieldsW + "px"; el("facetarea").style.height = state.catalog.more ? (panelH - 142) + "px" : "32px";
    el("facetarea").style.display = !state.catalog.more && phone ? "none" : "";
    el("facetfields").style.height = (state.catalog.more ? Math.ceil(count / fieldColumns) * 82 : 32) + "px";
    el("facetextra").style.display = state.catalog.more ? "" : "none";
    el("facetextra").style.position = "absolute"; el("facetextra").style.top = "0px";
    text(el("morefilters"), "全部参数 (" + state.catalog.facets.length + ")"); parameterCount();
    if (dock) {
      listH = Math.max(170, Math.min(available - (short ? 185 : 235), Math.floor(available * state.layout.split)));
      detailH = available - listH - 10;
      el("results").style.cssText = "left:0;right:0;top:0;width:auto;height:" + listH + "px;bottom:auto";
      el("detail").style.cssText = "left:0;right:0;top:" + (listH + 10) + "px;width:auto;bottom:0";
      el("splitter").style.cssText = "left:0;right:0;top:" + listH + "px;height:10px;display:block";
      if (phone) { el("results").style.display = state.layout.phoneDetail ? "none" : ""; el("detail").style.display = state.layout.phoneDetail ? "" : "none"; el("detail").style.top = "0px"; el("results").style.height = "auto"; el("results").style.bottom = "0px"; el("splitter").style.display = "none"; }
    } else {
      var dw = Math.max(360, Math.floor(content * .36));
      el("results").style.cssText = "left:0;top:0;bottom:0;width:" + (content - dw - 10) + "px";
      el("detail").style.cssText = "right:0;top:0;bottom:0;width:" + dw + "px"; el("splitter").style.display = "none";
    }
    el("searchwait").className = short ? "compactwait" : "";
    syncListHead(); if (state.selection.detail) { renderPreview(false); }
  }
  var splitDrag = null;
  bind("splitter", "mousedown", function (ev) { ev = ev || window.event; splitDrag = { y: ev.clientY, value: state.layout.split }; if (ev.preventDefault) { ev.preventDefault(); } });
  bind("splitter", "keydown", function (ev) { ev = ev || window.event; if (ev.keyCode === 38 || ev.keyCode === 40) { state.layout.split = Math.max(.3, Math.min(.72, state.layout.split + (ev.keyCode === 38 ? -.03 : .03))); layout(); if (ev.preventDefault) { ev.preventDefault(); } } });
  bind(document, "mousemove", function (ev) { if (!splitDrag) { return; } ev = ev || window.event; state.layout.split = Math.max(.3, Math.min(.72, splitDrag.value + (ev.clientY - splitDrag.y) / Math.max(250, document.documentElement.clientHeight - 196))); scheduleLayout(); });
  bind(document, "mouseup", function () { splitDrag = null; });
