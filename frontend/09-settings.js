  var librarySaving = false;
  function closeLibrarySettings() {
    if (librarySaving) { return; }
    el("librarymask").style.display = el("librarydialog").style.display = "none";
    el("librarysettings").focus();
  }
  bind("librarysettings", "click", function () {
    if (librarySaving) { return; }
    el("librarymask").style.display = el("librarydialog").style.display = "";
    el("librarysave").disabled = true; text(el("librarymessage"), "正在读取…");
    jsonp("/api/es/library/settings", {}, function (d) {
      el("symbolpath").value = d.symbol_lib; el("footprintpath").value = d.footprint_lib; el("cadencepath").value = d.cadence_root;
      el("librarysave").disabled = false; text(el("librarymessage"), ""); el("symbolpath").focus();
    }, function (message) { text(el("librarymessage"), message); });
  });
  bind("libraryclose", "click", closeLibrarySettings);
  bind("librarysave", "click", function () {
    if (librarySaving) { return; }
    librarySaving = true; el("librarysave").disabled = true; text(el("librarymessage"), "正在保存…");
    jsonp("/api/es/library/settings/save", { symbol_lib: el("symbolpath").value, footprint_lib: el("footprintpath").value, cadence_root: el("cadencepath").value }, function (d) {
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
