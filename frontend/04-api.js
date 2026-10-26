  var sessionMatch = /(?:[?&])session=([^&]*)/.exec(window.location.search);
  var hostSession = sessionMatch ? decodeURIComponent(sessionMatch[1]) : "";
  function jsonp(path, params, ok, fail) {
    if (path === "/api/es/place" && (!window.JSON || !window.JSON.parse || !window.JSON.stringify)) { if (fail) { fail("当前旧版浏览器不支持安全放置，请使用 EdaKit CEF 工作台"); } return; }
    params.token = window.__edakitToken || "";
    if (hostSession) { params.session = hostSession; }
    var name = "edakitCb" + (++sequence), parts = [], k, values, i, finished = false;
    var script = document.createElement("script"), timer;
    function removeCallback() { try { delete window[name]; } catch (e) { window[name] = undefined; } }
    function clean(late) { window.clearTimeout(timer); if (late) { window[name] = function () { removeCallback(); }; window.setTimeout(removeCallback, 300000); } else { removeCallback(); } if (script.parentNode) { script.parentNode.removeChild(script); } }
    function reject() { if (finished) { return; } finished = true; clean(true); if (fail) { fail("请求失败或等待超时，请检查网络与服务后重试"); } }
    for (k in params) { if (params.hasOwnProperty(k)) { values = typeof params[k] === "object" ? params[k] : [params[k]]; for (i = 0; i < values.length; i++) { parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(values[i])); } } }
    // CEF supports XHR+JSON; retain JSONP for the legacy OpenURL host.
    if (path === "/api/es/place" || (!document.documentMode && window.XMLHttpRequest && window.JSON && window.JSON.parse)) {
      var xhr = new XMLHttpRequest();
      var placing = path === "/api/es/place";
      xhr.open(placing ? "POST" : "GET", path + "?" + parts.join("&"), true);
      if (placing) { xhr.setRequestHeader("Content-Type", "application/json"); }
      timer = window.setTimeout(function () { xhr.abort(); reject(); }, 25000);
      xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4 || finished) { return; }
        var data;
        try { data = window.JSON.parse(xhr.responseText); } catch (error) { reject(); return; }
        if (!data || typeof data !== 'object' || Object.prototype.toString.call(data) === '[object Array]') { reject(); return; }
        if ((xhr.status < 200 || xhr.status >= 300) && !data.error) { reject(); return; }
        finished = true; clean();
        if (data.error) { if (fail) { fail(data.message || data.error); } } else { ok(data); }
      };
      xhr.send(placing ? JSON.stringify(params) : null);
      return { abort: function () { if (!finished) { finished = true; clean(); xhr.abort(); } } };
    }
    window[name] = function (data) { if (finished) { return; } if (!data || typeof data !== 'object') { reject(); return; } finished = true; clean(); if (data.error) { if (fail) { fail(data.message || data.error); } return; } ok(data); };
    script.onerror = reject; script.src = path + "?" + parts.join("&") + "&cb=" + name + "&t=" + new Date().getTime(); timer = window.setTimeout(reject, 25000); document.body.appendChild(script);
    return { abort: function () { if (!finished) { finished = true; clean(true); } } };
  }
  var statusPending = false, detailPending = false;
  function status() { if (statusPending) { return; } statusPending = true; jsonp("/api/es/status", {}, function (d) { statusPending = false; text(el("st"), d.capture_online ? "● Capture 已连接" : "○ Capture 未连接"); el("st").style.color = d.capture_online ? "#34866a" : "#ad6a56"; }, function () { statusPending = false; text(el("st"), "○ 连接状态暂不可用"); }); }
