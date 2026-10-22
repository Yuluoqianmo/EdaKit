  function beginWait(key, label, priority) { state.feedback.waits[key] = { label: label, start: new Date().getTime(), priority: priority || 0 }; paintWait(); }
  function endWait(key) { delete state.feedback.waits[key]; paintWait(); }
  var activityRecords = [];
  function notice(message) {
    if (!message) { return; }
    state.feedback.notice = String(message);
    if (!activityRecords.length || activityRecords[activityRecords.length - 1].message !== String(message)) {
      var now = new Date(), stamp = ("0" + now.getHours()).slice(-2) + ":" + ("0" + now.getMinutes()).slice(-2) + ":" + ("0" + now.getSeconds()).slice(-2);
      activityRecords.push({ message: String(message), stamp: stamp });
      if (activityRecords.length > 80) { activityRecords.shift(); }
      var row = document.createElement("div"); row.className = "activityentry";
      text(row, stamp + "  " + message); el("activitylog").insertBefore(row, el("activitylog").firstChild);
      if (el("activitylog").childNodes.length > 80) { el("activitylog").removeChild(el("activitylog").lastChild); }
      el("activitylog").scrollTop = 0;
    }
    paintWait();
  }
  bind("activitycopy", "click", function () {
    var lines = [], i, field = el("activityclipboard"), copied = false;
    for (i = 0; i < activityRecords.length; i++) { lines.push(activityRecords[i].stamp + "  " + activityRecords[i].message); }
    field.value = lines.join("\n\n"); field.focus(); field.select();
    try { copied = document.execCommand("copy"); } catch (ignore) {}
    text(el("activitycopy"), copied ? "已复制" : "请按 Ctrl+C");
    window.setTimeout(function () { text(el("activitycopy"), "复制记录"); }, 2000);
  });
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
