  function beginWait(key, label, priority) { state.feedback.waits[key] = { label: label, start: new Date().getTime(), priority: priority || 0 }; paintWait(); }
  function endWait(key) { delete state.feedback.waits[key]; paintWait(); }
  function notice(message) { state.feedback.notice = message; paintWait(); }
  function paintWait() {
    var best = null, k, now = new Date().getTime();
    for (k in state.feedback.waits) { if (state.feedback.waits.hasOwnProperty(k) && (!best || state.feedback.waits[k].priority > best.priority)) { best = state.feedback.waits[k]; } }
    var seconds = best ? Math.floor((now - best.start) / 1000) : 0;
    var visible = best && now - best.start >= 800;
    var message = visible ? best.label + (seconds >= 8 ? " · 已等待 " + seconds + " 秒，请稍候" : "…") : state.feedback.notice;
    el("workstate").style.display = visible ? "" : "none";
    el("statusbar").className = visible ? "working" : "";
    if (el("msg").getAttribute("data-message") !== message) { text(el("msg"), message); el("msg").title = message; el("msg").setAttribute("data-message", message); }
    if (state.feedback.waits.search) { text(el("searchwaittext"), "正在查询元件 · 已等待 " + Math.floor((now - state.feedback.waits.search.start) / 1000) + " 秒"); }
  }
