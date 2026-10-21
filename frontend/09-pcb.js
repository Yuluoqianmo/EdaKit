  var pcbBusy = false;
  function pcbButton() {
    el("btnpcb").disabled = pcbBusy || !state.selection.detail || !state.selection.detail.hasFootprint || !state.selection.detail.hasSymbol;
    text(el("btnpcb"), pcbBusy ? "生成中…" : "生成 PCB 封装");
  }
  bind("btnpcb", "click", function () {
    if (pcbBusy || !state.selection.sel || !state.selection.detail || !state.selection.detail.hasFootprint) { return; }
    var cid = state.selection.sel.cid;
    pcbBusy = true; pcbButton(); beginWait("pcb", "正在生成 PCB 封装", 90);
    jsonp("/api/es/footprint", { cid: cid }, function (d) {
      pcbBusy = false; pcbButton(); endWait("pcb");
      if (state.selection.sel && state.selection.sel.cid === cid) { text(el("pmsg"), "候选封装已生成，目录已打开。" + d.footprint); }
      window.alert(d.message + "\n\n候选文件已生成，需在 Allegro 中编译验证。\n完整指令见目录内 BUILD.txt。");
    }, function (message) {
      pcbBusy = false; pcbButton(); endWait("pcb");
      if (state.selection.sel && state.selection.sel.cid === cid) { text(el("pmsg"), message || "封装生成失败"); }
      notice(message || "封装生成失败");
    });
  });
