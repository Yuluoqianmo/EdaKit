  var librarySaving = false;
  function closeLibrarySettings() {
    if (librarySaving || directoryPicking) { return; }
    el("librarymask").style.display = el("librarydialog").style.display = "none";
    el("librarysettings").focus();
  }
  bind("librarysettings", "click", function () {
    if (librarySaving || directoryPicking) { return; }
    el("librarymask").style.display = el("librarydialog").style.display = "";
    el("librarysave").disabled = true; text(el("librarymessage"), "正在读取…");
    jsonp("/api/es/library/settings", {}, function (d) {
      el("symbolpath").value = d.symbol_lib; el("footprintpath").value = d.footprint_lib; el("cadencepath").value = d.cadence_root;
      el("steppath").value = d.step_lib || "";
      el("librarysave").disabled = false; text(el("librarymessage"), d.cadence_detected ? "已检测到有效的 Cadence 安装目录" : "未检测到有效的 Cadence 安装目录，请选择安装根目录"); el("symbolpath").focus();
    }, function (message) { text(el("librarymessage"), message); });
  });
  bind("libraryclose", "click", closeLibrarySettings);
  bind("librarysave", "click", function () {
    if (librarySaving || directoryPicking) { return; }
    librarySaving = true; el("librarysave").disabled = true; text(el("librarymessage"), "正在保存…");
    jsonp("/api/es/library/settings/save", { symbol_lib: el("symbolpath").value, footprint_lib: el("footprintpath").value, step_lib: el("steppath").value, cadence_root: el("cadencepath").value }, function (d) {
      librarySaving = false; el("librarysave").disabled = false; text(el("librarymessage"), d.message);
    }, function (message) { librarySaving = false; el("librarysave").disabled = false; text(el("librarymessage"), message); });
  });
  bind(document, "keydown", function (ev) {
    ev = ev || window.event;
    if (el("librarydialog").style.display === "none") { return; }
    if (ev.keyCode === 27) { closeLibrarySettings(); }
    if (ev.keyCode === 9) {
      var first = el("libraryclose"), last = el("librarysave");
      if (ev.shiftKey && document.activeElement === first) { last.focus(); if (ev.preventDefault) { ev.preventDefault(); } ev.returnValue = false; }
      else if (!ev.shiftKey && document.activeElement === last) { first.focus(); if (ev.preventDefault) { ev.preventDefault(); } ev.returnValue = false; }
    }
  });

  var directoryPicking = false;
  function pickerControls(busy, active) {
    var ids = ["symbolpathbrowse", "footprintpathbrowse", "steppathbrowse", "cadencepathbrowse", "librarysave", "libraryclose"], i;
    for (i = 0; i < ids.length; i++) { el(ids[i]).disabled = busy; }
    if (active) { text(el(active + "browse"), busy ? "选择中…" : "选择目录…"); }
  }
  function browseLibraryPath(id) {
    if (directoryPicking || librarySaving) { return; }
    directoryPicking = true;
    pickerControls(true, id);
    text(el("librarymessage"), "正在打开系统目录窗口，请稍候…");
    function finish(message) { directoryPicking = false; pickerControls(false, id); text(el("librarymessage"), message); notice(message); }
    jsonp("/api/es/library/browse", {initial: el(id).value}, function (job) {
      text(el("librarymessage"), "目录窗口已请求打开，请在系统窗口完成选择");
      function poll() {
        jsonp("/api/es/library/browse/status", {job: job.job}, function (result) {
          if (!result.done) { window.setTimeout(poll, 600); return; }
          if (result.path) { el(id).value = result.path; }
          finish(result.message || (result.path ? "目录已选择，请点击保存" : result.cancelled ? "已取消选择，原路径保持不变" : "目录窗口未返回有效路径，请重试"));
        }, function () { text(el("librarymessage"), "正在重新连接目录窗口，请先完成系统窗口中的选择…"); window.setTimeout(poll, 1200); });
      }
      poll();
    }, finish);
  }
  bind("symbolpathbrowse", "click", function () { browseLibraryPath("symbolpath"); });
  bind("footprintpathbrowse", "click", function () { browseLibraryPath("footprintpath"); });
  bind("steppathbrowse", "click", function () { browseLibraryPath("steppath"); });
  bind("cadencepathbrowse", "click", function () { browseLibraryPath("cadencepath"); });
