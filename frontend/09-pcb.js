  var pcbBusy = false;
  var pcbResultFocus = null;
  function closePcbResult() {
    el("pcbresult").style.display = el("pcbresultmask").style.display = "none";
    if (pcbResultFocus && pcbResultFocus.focus) { pcbResultFocus.focus(); }
  }
  function showPcbResult(d) {
    pcbResultFocus = document.activeElement;
    text(el("pcbresultname"), d.footprint);
    el("pcbdrawing").value = d.directory;
    el("pcbcommand").value = d.message + "\n" + d.footprint + ".dra\n" + d.footprint + ".psm";
    text(el("pcbcopymsg"), "");
    el("pcbresult").style.display = el("pcbresultmask").style.display = "";
    el("pcbdrawing").focus();
  }
  function copyPcbField(id) {
    var field = el(id), copied = false;
    field.focus(); field.select();
    try { copied = document.execCommand("copy"); } catch (error) { copied = false; }
    text(el("pcbcopymsg"), copied ? "已复制" : "已选中完整内容，请按 Ctrl+C 复制");
  }
  bind("pcbresultclose", "click", closePcbResult);
  bind("pcbdrawingcopy", "click", function () { copyPcbField("pcbdrawing"); });
  bind("pcbcommandcopy", "click", function () { copyPcbField("pcbcommand"); });
  bind(document, "keydown", function (ev) {
    ev = ev || window.event;
    if (el("pcbresult").style.display === "none") { return; }
    if (ev.keyCode === 27) { closePcbResult(); }
    if (ev.keyCode === 9) {
      var first = el("pcbresultclose"), last = el("pcbcommandcopy");
      if (ev.shiftKey && document.activeElement === first) { last.focus(); if (ev.preventDefault) { ev.preventDefault(); } ev.returnValue = false; }
      else if (!ev.shiftKey && document.activeElement === last) { first.focus(); if (ev.preventDefault) { ev.preventDefault(); } ev.returnValue = false; }
    }
  });
  function pcbButton() {
    el("btnpcb").disabled = pcbBusy || !state.selection.detail || !state.selection.detail.hasFootprint || !state.selection.detail.hasSymbol;
    text(el("btnpcb"), pcbBusy ? "生成中…" : "生成 PCB 封装");
  }
  bind("btnpcb", "click", function () {
    if (pcbBusy || !state.selection.sel || !state.selection.detail || !state.selection.detail.hasFootprint) { return; }
    var cid = state.selection.sel.cid;
    pcbBusy = true; pcbButton(); beginWait("pcb", "正在生成 PCB 封装", 90);
    jsonp("/api/es/footprint", { cid: cid }, function (d) {
      pollPcb(d.job, cid, 0);
    }, function (message) {
      pcbBusy = false; pcbButton(); endWait("pcb");
      if (state.selection.sel && state.selection.sel.cid === cid) { text(el("pmsg"), message || "封装生成失败"); }
      notice(message || "封装生成失败");
    });
  });
  function pollPcb(job, cid, failures) {
    jsonp("/api/es/footprint/status", { job: job }, function (d) {
      if (d.status === "building") { window.setTimeout(function () { pollPcb(job, cid, 0); }, 900); return; }
      pcbBusy = false; pcbButton(); endWait("pcb");
      if (d.status === "compiled") {
        if (state.selection.sel && state.selection.sel.cid === cid) { text(el("pmsg"), "PCB 封装已保存：" + d.footprint); }
        showPcbResult(d);
      } else {
        if (state.selection.sel && state.selection.sel.cid === cid) { text(el("pmsg"), d.message || "构建失败"); }
        notice(d.message || "构建失败");
      }
    }, function (message) {
      if (failures < 3) { window.setTimeout(function () { pollPcb(job, cid, failures + 1); }, 1500); return; }
      pcbBusy = false; pcbButton(); endWait("pcb"); notice(message || "构建状态查询失败");
    });
  }
