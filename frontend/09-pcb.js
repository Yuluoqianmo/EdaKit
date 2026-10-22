  var pcbBusy = false;
  function showPcbResult(d) {
    var elapsed = typeof d.elapsedSeconds === "number" ? " · " + d.elapsedSeconds.toFixed(2) + " 秒" : "";
    notice("PCB 封装生成完成" + elapsed + "\n" + d.footprint + "\n封装库：" + d.directory + "\n" + d.message + "\n文件：" + d.footprint.toLowerCase() + ".dra / " + d.footprint.toLowerCase() + ".psm");
  }
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
      notice(message || "封装生成失败");
    });
  });
  function pollPcb(job, cid, failures) {
    jsonp("/api/es/footprint/status", { job: job }, function (d) {
      if (d.status === "building") {
        if (state.feedback.waits.pcb && d.message) { state.feedback.waits.pcb.label = d.message; paintWait(); }
        window.setTimeout(function () { pollPcb(job, cid, 0); }, 400); return;
      }
      pcbBusy = false; pcbButton(); endWait("pcb");
      if (d.status === "compiled") {

        showPcbResult(d);
      } else {
        notice(d.message || "构建失败");
      }
    }, function (message) {
      if (failures < 3) { window.setTimeout(function () { pollPcb(job, cid, failures + 1); }, 1500); return; }
      pcbBusy = false; pcbButton(); endWait("pcb"); notice(message || "构建状态查询失败");
    });
  }
