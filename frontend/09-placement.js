  function placeBusy(busy) {
    state.placement.placing = busy; el("btnplace").disabled = busy || !state.selection.detail || !state.selection.detail.hasSymbol; text(el("btnplace"), busy ? "准备中…" : "放置到原理图");
    if (!busy) { endWait("place"); }
  }
  function place() {
    if (!state.selection.sel || state.placement.placing) { return; } var p = state.selection.sel;
    if (state.selection.detail && !state.selection.detail.hasSymbol) { return; }
    placeBusy(true); beginWait("place", "正在准备 " + p.model + " 的放置数据", 90); text(el("pmsg"), "正在准备放置，请稍候，不要重复点击…");
    jsonp("/api/es/place", { cid: p.cid, force_cursor: "1" }, function (d) {
      if (state.selection.sel && state.selection.sel.cid === p.cid && !d.captureOnline) { text(el("pmsg"), "Capture 未连接，请检查插件。请求可能稍后执行。"); }
      pollPlace(d.seq, p.cid, 0);
    }, function (msg) { placeBusy(false); if (state.selection.sel && state.selection.sel.cid === p.cid) { text(el("pmsg"), (msg || "准备失败") + "；请查看原理图或服务日志确认放置状态。"); } });
  }
  function pollPlace(seq, cid, attempt) {
    if (attempt > 120) { placeBusy(false); notice("等待 Capture 超时，请检查原理图与服务日志"); if (state.selection.sel && state.selection.sel.cid === cid) { text(el("pmsg"), "等待 Capture 超时，请检查原理图与服务日志。"); } return; }
    jsonp("/api/es/place/status", { seq: seq }, function (d) {
      var r = d.result, same = state.selection.sel && state.selection.sel.cid === cid;
      if (!r || r.stage === "waiting-schematic") { if (r && same) { text(el("pmsg"), "请点击原理图，继续放置。"); } window.setTimeout(function () { pollPlace(seq, cid, attempt + 1); }, 700); return; }
      placeBusy(false);
      if (same) { text(el("pmsg"), !r.ok ? "放置失败：" + r.message : (r.message || "").indexOf("armed:") === 0 ? "单击原理图落位，Esc 退出。" : r.message); }
    }, function () { placeBusy(false); if (state.selection.sel && state.selection.sel.cid === cid) { text(el("pmsg"), "放置状态查询失败，请查看原理图或服务日志确认状态。"); } });
  }
