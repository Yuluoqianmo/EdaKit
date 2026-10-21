  function resetDetail() {
    detailPending = false;
    ++state.selection.detailQuery; state.layout.phoneDetail = false; state.preview.full = false; el("largeview").style.display = "none"; state.selection.sel = null; state.selection.detail = null; endWait("cad"); endWait("product"); cancelImage("previewimg"); cancelImage("largeimg");
    el("btnplace").disabled = el("tabfootprint").disabled = el("tabsymbol").disabled = el("tab3d").disabled = true;
    text(el("dname"), "请选择一个元件"); text(el("selectedcid"), ""); text(el("prop"), "从查询结果中选择元件，查看符号与封装。"); text(el("pmsg"), ""); datasheet("", "选择元件后查看手册"); showEmpty("选择元件后显示预览");
  }
  function datasheet(url, message) {
    var valid = /^https?:\/\//i.test(url || ""); el("datasheet").style.display = valid ? "" : "none"; el("nodatasheet").style.display = valid ? "none" : "";
    if (valid) { el("datasheet").href = url; el("datasheet").title = "在系统默认浏览器打开当前器件的数据手册"; }
    else { el("datasheet").removeAttribute("href"); text(el("nodatasheet"), message || "暂无数据手册"); }
  }
  function properties(p) {
    var summary = [], key, count = 0, rows = p.paramDisplay || [], i, item;
    for (i = 0; i < rows.length && i < 3; i++) { item = rows[i]; summary.push('<span title="' + esc(item.key + "：" + item.value + (item.note ? "\n" + item.note : "")) + '">' + esc(item.label) + " " + esc(item.displayValue) + (item.needsReview ? "（待核对）" : "") + '</span>'); }
    if (!rows.length) { for (key in p.params) { if (p.params.hasOwnProperty(key) && count < 3) { summary.push(esc(key) + " " + esc(p.params[key])); count++; } } }
    el("prop").innerHTML = "封装：" + esc(p.package && p.package !== "-" ? p.package : "商城未提供") + "<br>" + esc(p.brand || "—") + " · 库存 " + esc(p.stock) + " · " + esc(p.price) + (summary.length ? '<br><span class="paramsummary">' + summary.join("") + '</span>' : "");
  }
  function select(tr, p) {
    var rows = el("rows").rows; for (var i = 0; i < rows.length; i++) { rows[i].className = ""; } tr.className = "sel";
    state.layout.phoneDetail = true; layout();
    if (state.selection.sel && state.selection.sel.cid === p.cid && (state.selection.detail || detailPending)) { return; }
    detailPending = true;
    cancelImage("largeimg");
    state.selection.sel = p; state.selection.detail = null; state.preview.zoom = 1; state.preview.yaw = 35; state.preview.pitch = 55; state.preview.png = ""; el("btnplace").disabled = el("tab3d").disabled = el("tabfootprint").disabled = el("tabsymbol").disabled = true;
    text(el("dname"), p.model); text(el("selectedcid"), p.cid);
    properties(p); datasheet(p.datasheet, "正在查询手册…");
    text(el("pmsg"), "正在加载元件详情…"); showEmpty("正在加载预览…");
    var token = ++state.selection.detailQuery; beginWait("product", "正在查询商品资料和数据手册", 40); beginWait("cad", "正在加载符号与封装详情", 60);
    jsonp("/api/es/product/" + encodeURIComponent(p.cid), {}, function (metadata) {
      if (token !== state.selection.detailQuery) { return; } endWait("product");
      if (metadata.package && metadata.package !== "-") { p.package = metadata.package; }
      if (metadata.brand) { p.brand = metadata.brand; }
      if (metadata.datasheet) { p.datasheet = metadata.datasheet; }
      if (metadata.params) { p.params = metadata.params; p.paramDisplay = metadata.paramDisplay || []; } properties(p); datasheet(p.datasheet || (state.selection.detail ? state.selection.detail.datasheet : ""));
    }, function () { if (token === state.selection.detailQuery) { endWait("product"); if (!p.datasheet) { datasheet(state.selection.detail ? state.selection.detail.datasheet : "", "手册查询失败，可重新选择重试"); } } });
    jsonp("/api/es/part/" + encodeURIComponent(p.cid), {}, function (d) {
      if (token !== state.selection.detailQuery) { return; } detailPending = false; endWait("cad"); state.selection.detail = d; el("btnplace").disabled = !d.hasSymbol || state.placement.placing; el("tabsymbol").disabled = !d.hasSymbol; el("tabfootprint").disabled = !d.hasFootprint; el("tab3d").disabled = !d.model3d; el("tab3d").title = d.model3d ? "查看真实3D模型" : "该元件暂无3D模型";
      if (!p.datasheet && d.datasheet) { datasheet(d.datasheet); }
      if (state.preview.kind === "model3d" && !d.model3d) { state.preview.kind = "footprint"; }
      text(el("pmsg"), d.hasSymbol ? "单击按钮后切回原理图，单击落位；Esc 退出。" : "该元件没有原理图符号");
      if (!d.hasFootprint && d.hasSymbol) { state.preview.kind = "symbol"; } renderPreview(true);
    }, function (msg) { if (token === state.selection.detailQuery) { detailPending = false; endWait("cad"); text(el("pmsg"), msg || "详情加载失败，请重新选择"); showEmpty("预览加载失败"); } });
  }
