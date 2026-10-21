/* ES3 syntax: the probe must also explain failure in older hosts. */
(function () {
    var errors = [], busy = false;
    window.onerror = function (message, source, line) {
        errors.push({message: String(message), source: String(source), line: line});
        document.getElementById("state").innerHTML = "发生脚本错误，请保留页面和日志。";
        return false;
    };
    function context(name) {
        try { return !!document.createElement("canvas").getContext(name); }
        catch (e) { return false; }
    }
    function run() {
        if (busy) { return; }
        busy = true;
        var out = document.getElementById("results"), state = document.getElementById("state");
        var css = window.getComputedStyle ? window.getComputedStyle(document.getElementById("stylecheck"), null) : document.getElementById("stylecheck").currentStyle;
        var flex = window.getComputedStyle ? window.getComputedStyle(document.getElementById("flexcheck"), null) : document.getElementById("flexcheck").currentStyle;
        var img = document.getElementById("svgcheck");
        var report = {url: location.href, userAgent: navigator.userAgent,
            documentMode: document.documentMode || null, json: !!window.JSON,
            xhr: !!window.XMLHttpRequest, requestAnimationFrame: !!window.requestAnimationFrame,
            canvas2d: context("2d"), webgl1: context("webgl") || context("experimental-webgl"),
            webgl2: context("webgl2"), cssBorder: css ? css.borderLeftWidth : null,
            flexDisplay: flex ? flex.display : null,
            svgLoaded: !!(img.complete && img.naturalWidth > 0),
            viewport: {width: document.documentElement.clientWidth, height: document.documentElement.clientHeight},
            devicePixelRatio: window.devicePixelRatio || null, errors: errors};
        function text(value) {
            if (window.JSON) { return JSON.stringify(value, null, 2); }
            return "当前宿主缺少 JSON；无法自动保存。UA: " + navigator.userAgent;
        }
        function display() {
            if (typeof out.textContent !== "undefined") { out.textContent = text(report); }
            else { out.innerText = text(report); }
        }
        display();
        if (!report.xhr || !report.json) {
            state.innerHTML = "基础能力不足，自动保存未执行。请截取检测结果。";
            busy = false; return;
        }
        state.innerHTML = "正在验证同源请求并保存检测结果……";
        var xhr = new XMLHttpRequest(), timer = window.setTimeout(function () {
            xhr.abort(); busy = false; state.innerHTML = "同源请求超时，请检查探针服务窗口。";
        }, 8000);
        xhr.open("GET", "/ping", true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) { return; }
            window.clearTimeout(timer);
            report.sameOriginXHR = xhr.status === 200 && xhr.responseText.indexOf('"ok":true') >= 0;
            display();
            var save = new XMLHttpRequest();
            var saveTimer = window.setTimeout(function () {
                save.abort(); busy = false; state.innerHTML = "保存超时，请截图保留结果。";
            }, 8000);
            save.open("POST", "/report", true);
            save.setRequestHeader("Content-Type", "application/json");
            save.onreadystatechange = function () {
                if (save.readyState !== 4) { return; }
                window.clearTimeout(saveTimer); busy = false;
                state.innerHTML = save.status === 200 ? "检测完成，日志已保存到 events.jsonl。请继续检查中文输入和焦点。" : "保存失败，请截图保留结果。";
            };
            save.send(JSON.stringify(report));
        };
        xhr.send(null);
    }
    document.getElementById("run").onclick = run;
    window.onload = run;
}());
