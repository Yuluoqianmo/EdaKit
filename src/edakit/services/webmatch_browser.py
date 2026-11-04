"""Visible default-browser DOM reader. No cookies, network interception or exports.

Uses only a dedicated browser profile and public DevTools input/DOM operations.
Controls are discovered from visible toolbar elements; no editor model is read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit


class WebMatchError(ValueError):
    pass


def document_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise WebMatchError('请填写有效的钉钉表格链接')
    try:
        p = urlsplit(value.strip())
        valid = (p.scheme == 'https' and p.hostname == 'alidocs.dingtalk.com'
                 and p.port in (None, 443) and not p.username and not p.password
                 and re.fullmatch(r'/i/nodes/[A-Za-z0-9_-]{5,128}/?', p.path))
    except ValueError:
        valid = False
    if not valid:
        raise WebMatchError('测试版仅支持 alidocs.dingtalk.com 的知识库文档链接')
    return 'https://alidocs.dingtalk.com' + p.path.rstrip('/')


def loopback_ws(value, port):
    p = urlsplit(value)
    if (p.scheme != 'ws' or p.hostname != '127.0.0.1' or p.port != port
            or p.username or p.password or not p.path.startswith('/devtools/')):
        raise WebMatchError('测试浏览器连接地址无效')
    return value


def default_browser_path():
    """Resolve the user's HTTPS association, without changing their preference."""
    import ctypes
    from ctypes import wintypes
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
            progid = winreg.QueryValueEx(key, 'ProgId')[0]
        query = ctypes.windll.shlwapi.AssocQueryStringW
        query.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                          wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        query.restype = ctypes.c_long
        size = wintypes.DWORD(32768)
        result = ctypes.create_unicode_buffer(size.value)
        # ASSOCSTR_EXECUTABLE returns the executable, not an untrusted shell command.
        if query(0, 2, progid, 'open', result, ctypes.byref(size)) != 0:
            raise OSError('association lookup failed')
        path = Path(result.value)
        if not path.is_absolute() or not path.is_file():
            raise OSError('browser executable unavailable')
        return path
    except (OSError, ValueError):
        raise WebMatchError('无法读取系统默认浏览器，请检查 Windows 默认应用设置') from None


def supported_browser(path):
    names = {'chrome.exe': 'Chrome', 'msedge.exe': 'Edge', 'chromium.exe': 'Chromium',
             'brave.exe': 'Brave', 'vivaldi.exe': 'Vivaldi'}
    name = names.get(Path(path).name.lower())
    if not name:
        raise WebMatchError('当前系统默认浏览器尚未适配自动匹配；不会擅自改用其他浏览器')
    return name


def clipboard_sequence():
    """Observe a new normal Windows copy, without changing clipboard permissions."""
    import ctypes
    if os.name != 'nt':
        raise WebMatchError('当前环境不支持 Windows 区域复制')
    return ctypes.windll.user32.GetClipboardSequenceNumber()


def clipboard_text():
    import ctypes
    from ctypes import wintypes
    user, kernel = ctypes.windll.user32, ctypes.windll.kernel32
    user.GetClipboardData.argtypes, user.GetClipboardData.restype = [wintypes.UINT], wintypes.HANDLE
    kernel.GlobalLock.argtypes, kernel.GlobalLock.restype = [wintypes.HGLOBAL], ctypes.c_void_p
    kernel.GlobalSize.argtypes, kernel.GlobalSize.restype = [wintypes.HGLOBAL], ctypes.c_size_t
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not user.OpenClipboard(None):
        return None
    try:
        handle = user.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return None
        size = kernel.GlobalSize(handle)
        if size > 4_000_000:
            raise WebMatchError('复制区域过大，已停止读取')
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer, size // 2).split('\0', 1)[0]
        finally:
            kernel.GlobalUnlock(handle)
    finally:
        user.CloseClipboard()


# Traverse ordinary same-origin documents only. No private application state.
DOM = r"""function docs(d){var out=[d];for(var f of d.querySelectorAll('iframe')){
try{if(f.contentDocument)out=out.concat(docs(f.contentDocument));}catch(e){}}return out;}
function marked(k){for(var d of docs(document)){var e=d.querySelector('[data-edakit-webtest="'+k+'"]');if(e)return e;}return null;}
function active(d){var e=d.activeElement;try{if(e&&e.tagName==='IFRAME'&&e.contentDocument)return active(e.contentDocument);}catch(x){}return e;}
function text(e){return !e?'':('value' in e?String(e.value):String(e.innerText||e.textContent||''));}
"""


class CDP:
    def __init__(self, endpoint, port):
        import websocket
        self.ws = websocket.create_connection(loopback_ws(endpoint, port), timeout=4,
                                              suppress_origin=True,
                                              http_no_proxy=['127.0.0.1', 'localhost'])
        self.seq = 0
        self.structure_requests = set()
        self.structure_ready = []

    def call(self, method, params=None, max_size=2_000_000):
        self.seq += 1
        seq, deadline = self.seq, time.monotonic() + 6
        self.ws.send(json.dumps({'id': seq, 'method': method, 'params': params or {}}))
        while time.monotonic() < deadline:
            raw = self.ws.recv()
            if len(raw) > max_size:
                raise WebMatchError('测试浏览器响应过大，已停止读取')
            data = json.loads(raw)
            event = data.get('method')
            event_params = data.get('params', {})
            if event == 'Network.responseReceived':
                response = event_params.get('response', {})
                parsed = urlsplit(response.get('url', ''))
                if (parsed.scheme == 'https' and parsed.hostname == 'alidocs.dingtalk.com'
                        and parsed.path == '/api/document/data' and response.get('status') == 200
                        and len(self.structure_requests) < 10):
                    self.structure_requests.add(event_params.get('requestId'))
            elif event == 'Network.loadingFinished' and event_params.get('requestId') in self.structure_requests:
                self.structure_ready.append(event_params['requestId'])
                self.structure_requests.discard(event_params['requestId'])
            if data.get('id') != seq:
                continue
            if 'error' in data:
                raise WebMatchError('测试浏览器操作失败，请重新校准控件')
            return data.get('result', {})
        raise WebMatchError('测试浏览器响应超时')

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
        if result.get('exceptionDetails'):
            raise WebMatchError('网页控件读取失败，请重新校准')
        return result.get('result', {}).get('value')

    def close(self):
        self.ws.close()


class BrowserReader:
    def structure_probe(self, cancel, progress):
        from .webmatch_structure import inspect_checkpoint
        return self._checkpoint(cancel, progress, inspect_checkpoint, diagnostic=True)

    def read_table(self, cancel, progress):
        from .webmatch_structure import read_checkpoint
        return self._checkpoint(cancel, progress, read_checkpoint)

    def _checkpoint(self, cancel, progress, decode, diagnostic=False):
        import base64
        wait = self.prepare(cancel, progress)
        started = time.perf_counter()
        self.connect()
        self.cdp.structure_requests.clear()
        self.cdp.structure_ready.clear()
        self.cdp.call('Network.enable', {'maxTotalBufferSize': 12000000, 'maxResourceBufferSize': 10000000})
        try:
            background = False
            try:
                window = self.cdp.call('Browser.getWindowForTarget', {'targetId': self.target})
                self.cdp.call('Browser.setWindowBounds', {'windowId': window['windowId'], 'bounds': {'windowState': 'minimized'}})
                background = True
            except (WebMatchError, KeyError):
                pass
            # Reload the actual document normally; never replay private requests.
            progress('已登录，正在后台读取文档快照…')
            self.cdp.call('Page.reload')
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if cancel.wait(.25):
                    raise WebMatchError('已取消结构诊断')
                self.connect()  # Recheck target document before every inspection.
                self.cdp.call('Runtime.evaluate', {'expression': 'document.readyState'})
                if not self.cdp.structure_ready:
                    continue
                request = self.cdp.structure_ready.pop(0)
                body = self.cdp.call('Network.getResponseBody', {'requestId': request}, max_size=14000000)
                raw = body.get('body', '')
                if body.get('base64Encoded'):
                    raw = base64.b64decode(raw, validate=True).decode('utf-8')
                if len(raw) > 8000000:
                    raise WebMatchError('文档响应超过诊断上限，已停止')
                received = time.perf_counter()
                try:
                    result = decode(raw)
                except WebMatchError as error:
                    from .webmatch_structure import CheckpointError
                    if isinstance(error, CheckpointError):
                        error.diagnostics.update(wait or {})
                        error.diagnostics.update(backgroundWindow=background,
                            response_ms=round((received-started)*1000, 2),
                            parsing_ms=round((time.perf_counter()-received)*1000, 2))
                    raise
                parsed = time.perf_counter()
                if cancel.is_set():
                    raise WebMatchError('已取消；未应用不完整结果')
                if diagnostic:
                    if result.get('ok'):
                        result['backgroundWindow'] = background
                        return result
                else:
                    table, metadata = result
                    metadata.update(wait or {})
                    metadata.update(backgroundWindow=background,
                        response_ms=round((received-started)*1000, 2),
                        parsing_ms=round((parsed-received)*1000, 2),
                        reader_ms=round((parsed-started)*1000, 2))
                    return table, metadata
            raise WebMatchError('未取得可解析的文档快照响应；请保留窗口并复制诊断报告')
        finally:
            try:
                self.cdp.call('Network.disable')
            finally:
                self.cdp.structure_requests.clear()
                self.cdp.structure_ready.clear()

    def __init__(self, profile, factory=CDP):
        self.profile, self.factory = Path(profile), factory
        self.process = None
        self.cdp = None
        self.port = 0
        self.url = ''
        self.target = ''
        self.header_row = 1
        self.anchors = {}
        self.product = ''
        self.calibration = {}
        self.browser_name = ''
        self.navigation = 'input'
        self.range_end = None

    def discover(self):
        """Recognize toolbar controls; return value-free structure on failure."""
        probe = self.evaluate(r"""
function visible(e){var r=e.getBoundingClientRect();return r.width>12&&r.height>8&&r.right>0&&r.bottom>0&&getComputedStyle(e).visibility!=='hidden';}
function semantics(e){var s='';for(var i=0;e&&i<3;i++,e=e.parentElement)s+=' '+[e.id,e.className,e.getAttribute('aria-label'),e.getAttribute('title'),e.getAttribute('placeholder')].join(' ');return s;}
function address(e){return /^\$?[A-Z]{1,3}\$?[1-9]\d*(?::\$?[A-Z]{1,3}\$?[1-9]\d*)?$/i.test(text(e).trim());}
function nameSemantic(e){return /name.?box|name.?input|coordinate|address.?input|名称框|地址框|坐标框/i.test(semantics(e));}
function formulaSemantic(e){return /formula|fx.?input|公式/i.test(semantics(e));}
function rect(e){var r=e.getBoundingClientRect();return {x:Math.round(r.left),y:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)};}
var choices=[],probe={ok:false,canvasCount:0,addressCandidates:0,formulaCandidates:0,documents:0,frames:0,inaccessibleFrames:0,controls:[],displayAddressCount:0};
for(var d of docs(document)){
 probe.documents++;
 for(var frame of d.querySelectorAll('iframe')){probe.frames++;try{if(!frame.contentDocument)probe.inaccessibleFrames++;}catch(e){probe.inaccessibleFrames++;}}
 var canvases=Array.from(d.querySelectorAll('canvas')).filter(visible);
 probe.canvasCount+=canvases.length;
 var inputs=Array.from(d.querySelectorAll('input,textarea,[contenteditable]:not([contenteditable="false"]),[role="textbox"]')).filter(visible);
 var gridTop=canvases.length?Math.min.apply(null,canvases.map(function(e){return e.getBoundingClientRect().top;})):null;
 for(var e of inputs){if(probe.controls.length>=40)break;
  probe.controls.push({tag:e.tagName,editable:!!(e.tagName==='INPUT'||e.tagName==='TEXTAREA'||e.isContentEditable),readOnly:!!e.readOnly,disabled:!!e.disabled,password:e.type==='password',addressLike:e.type!=='password'&&address(e),nameSemantic:nameSemantic(e),formulaSemantic:formulaSemantic(e),rect:rect(e),aboveCanvas:gridTop!==null&&e.getBoundingClientRect().bottom<=gridTop+6});
 }
 // A1 may be rendered as a display node instead of an editable input. Report
 // this explicitly, but never type into that node or an arbitrary cell editor.
 for(var e of d.querySelectorAll('div,span,button')){if(e.children.length===0&&nameSemantic(e)&&visible(e)&&address(e))probe.displayAddressCount++;}
 if(!canvases.length)continue;
 // Confirmed DingTalk structure: read-only selection display and custom
 // Cangjie formula DOM, scoped to the public, focusable table wrapper.
 var wrappers=Array.from(d.querySelectorAll('#FlexTableWrapper[tabindex]')).filter(visible);
 for(var grid of wrappers){
  for(var bar of grid.querySelectorAll('.m-formular-bar')){
   var displays=Array.from(bar.querySelectorAll('[data-testid]')).filter(function(e){return /^SelectionDisplay/i.test(e.getAttribute('data-testid')||'')&&visible(e)&&address(e);});
   var editors=Array.from(bar.querySelectorAll('.m-rich-text-editor-content')).filter(visible);
   if(displays.length===1&&editors.length===1){
    var nr=displays[0].getBoundingClientRect(),fr=editors[0].getBoundingClientRect();
    if(fr.left>=nr.right-4&&Math.abs(fr.top-nr.top)<32){
     probe.addressCandidates++;probe.formulaCandidates++;
     choices.push({name:displays[0],formula:editors[0],grid:grid,navigation:'keyboard'});
    }
   }
  }
 }
 if(choices.some(function(c){return c.grid&&c.grid.ownerDocument===d;}))continue;
 var names=inputs.filter(function(e){var r=e.getBoundingClientRect();return e.type!=='password'&&!e.readOnly&&!e.disabled&&(e.tagName==='INPUT'||e.tagName==='TEXTAREA'||e.isContentEditable)&&r.width<240&&address(e)&&(r.bottom<=gridTop+6||nameSemantic(e));});
 probe.addressCandidates+=names.length;
 if(names.length!==1)continue;var n=names[0],nr=n.getBoundingClientRect();
 var formula=inputs.filter(function(e){if(e===n||e.type==='password')return false;var r=e.getBoundingClientRect();return r.left>=nr.right-4&&Math.abs(r.top-nr.top)<24&&(r.bottom<=gridTop+6||formulaSemantic(e));});
 var semantic=formula.filter(formulaSemantic);
 if(semantic.length===1)formula=semantic;
 probe.formulaCandidates+=formula.length;
 if(formula.length===1&&!choices.some(function(c){return c.name===n;}))choices.push({name:n,formula:formula[0],navigation:'input'});
}
if(choices.length!==1)return probe;
for(var k of ['name','formula','grid']){for(var d of docs(document))for(var old of d.querySelectorAll('[data-edakit-webtest="'+k+'"]'))old.removeAttribute('data-edakit-webtest');if(choices[0][k])choices[0][k].setAttribute('data-edakit-webtest',k);}
probe.ok=true;probe.navigation=choices[0].navigation;return probe;
""")
        self.calibration = dict(probe or {}, automatic=True)
        if probe and probe.get('ok'):
            self.navigation = probe.get('navigation', 'input')
        return bool(probe and probe.get('ok'))

    def prepare(self, cancel, progress):
        started = time.perf_counter()
        deadline = time.monotonic() + 600
        page_ready_at = None
        while time.monotonic() < deadline:
            if cancel.is_set():
                raise WebMatchError('已取消')
            if not self.process or self.process.poll() is not None:
                raise WebMatchError('钉钉窗口已关闭，请重新匹配')
            try:
                if self.discover():
                    return {'login_and_page_wait_ms': round((time.perf_counter()-started)*1000, 2)}
                if page_ready_at is None and self.calibration.get('canvasCount', 0):
                    page_ready_at = time.monotonic()
            except WebMatchError:
                pass  # The official login redirect is expected until the user logs in.
            if page_ready_at is not None and time.monotonic()-page_ready_at > 35:
                raise WebMatchError('已打开文档，但未能自动识别表格控件；请复制诊断报告，无需手动校准')
            progress('请在弹出的钉钉窗口登录；登录完成后会自动开始，无需校准')
            if cancel.wait(.6):
                raise WebMatchError('已取消')
        raise WebMatchError('等待登录或识别表格超时；没有修改表格，可复制诊断报告')

    def used_range(self, cancel):
        self._select_address('A1', 250, cancel)
        if self.evaluate("return active(document)===marked('name');"):
            raise WebMatchError('网页未进入表格选择状态，已停止自动读取')
        self._key('End', 'End', 35, 2)
        if cancel.wait(.3):
            raise WebMatchError('已取消')
        end = self.evaluate("return text(marked('name')).replace(/\\$/g,'').trim().toUpperCase();")
        match = re.fullmatch(r'([A-Z]{1,3})([1-9]\d{0,5})', end or '')
        if not match:
            raise WebMatchError('无法自动确认表格末行，已停止，未应用结果')
        col = 0
        for c in match[1]:
            col = col * 26 + ord(c) - 64
        rows = int(match[2])
        if not 2 <= rows <= 2000 or not 3 <= col <= 52 or rows * col > 50000:
            raise WebMatchError('自动识别的表格范围异常或过大，已停止，未应用结果')
        self.range_end = (col, rows)
        return rows, col, end

    def copy_range(self, address, cancel):
        started = time.perf_counter()
        self._select_address(address, 250, cancel)
        if self.evaluate("return active(document)===marked('name');"):
            raise WebMatchError('网页未确认区域选择，已停止复制')
        before = clipboard_sequence()
        self._key('c', 'KeyC', 67, 2)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if cancel.wait(.08):
                raise WebMatchError('已取消')
            current = clipboard_sequence()
            if current == before:
                continue
            value = clipboard_text()
            if value is not None and clipboard_sequence() == current:
                return value, {'total_ms': round((time.perf_counter()-started)*1000, 2)}
        raise WebMatchError('网页未提供可读取的区域复制结果，将使用自动逐行读取')

    def open(self, url):
        self.url = document_url(url)
        browser = default_browser_path()
        self.browser_name = supported_browser(browser)
        # Keep different browser products' profiles separate. Never use the
        # user's ordinary profile or change their default-browser registration.
        if browser.stem.lower() != 'msedge':
            self.profile = self.profile.parent / ('browser-profile-' + browser.stem.lower())
        self.profile.mkdir(parents=True, exist_ok=True)
        active = self.profile / 'DevToolsActivePort'
        # Only this object's explicitly launched process may be connected to.
        if self.process is not None:
            raise WebMatchError('测试窗口已打开，请先关闭测试连接')
        try:
            active.unlink(missing_ok=True)
        except OSError:
            raise WebMatchError('测试浏览器目录被占用，请关闭旧测试窗口') from None
        self.process = subprocess.Popen([
            str(browser), '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
            '--user-data-dir=' + str(self.profile), '--no-first-run', '--no-default-browser-check',
            '--disable-background-mode', '--new-window', self.url,
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise WebMatchError('系统默认浏览器未启动自动匹配连接，可能受到企业策略限制')
            try:
                port = int(active.read_text(encoding='utf-8').splitlines()[0])
                if 1 <= port <= 65535:
                    self.port = port
                    return
            except (OSError, ValueError, IndexError):
                pass
            time.sleep(.1)
        raise WebMatchError('未建立默认浏览器连接，请检查企业浏览器策略')

    def connect(self):
        if not self.process or self.process.poll() is not None or not self.port:
            raise WebMatchError('测试浏览器已关闭，请重新打开')
        if self.cdp:
            # Do not switch silently to a different tab or document.
            if self.cdp.evaluate('location.origin+location.pathname').rstrip('/') != self.url:
                raise WebMatchError('请完成扫码并保持原物料表打开；不要切换到其他文档')
            return
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{self.port}/json/list', timeout=4) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise WebMatchError('浏览器标签列表过大')
        pages = json.loads(raw)
        selected = [p for p in pages if p.get('type') == 'page'
                    and p.get('url', '').split('?', 1)[0].rstrip('/') == self.url]
        if len(selected) != 1:
            raise WebMatchError('请先扫码打开目标物料表，并且只保留一个该文档标签')
        page = selected[0]
        self.target = page['id']
        self.cdp = self.factory(page['webSocketDebuggerUrl'], self.port)
        try:
            self.cdp.call('Page.setDownloadBehavior', {'behavior': 'deny'})
            self.product = self.cdp.call('Browser.getVersion').get('product', '')[:80]
        except Exception:
            self.cdp.close()
            self.cdp = None
            raise WebMatchError('无法禁用测试窗口下载，已停止连接') from None

    def evaluate(self, code):
        self.connect()
        return self.cdp.evaluate('(function(){' + DOM + code + '})()')

    def calibrate(self, kind):
        if kind not in ('name', 'formula'):
            raise WebMatchError('校准类型无效')
        code = r"""
var k=KIND,e=active(document);if(!e||e===e.ownerDocument.body)return {ok:false,reason:'no_focused_control'};
var semantic=[e.id,e.className,e.getAttribute('aria-label'),e.getAttribute('title'),e.getAttribute('placeholder')].join(' ');
var probe={ok:false,tag:e.tagName,type:e.type||'',addressLike:/^\$?[A-Z]{1,3}\$?[1-9]\d*(?::\$?[A-Z]{1,3}\$?[1-9]\d*)?$/i.test(text(e).trim()),nameSemantic:/name.?box|name.?input|range|coordinate|address|名称|区域|地址|坐标|位置/i.test(semantic)};
if(k==='name'){
if(e.tagName!=='INPUT'||!probe.addressLike||!probe.nameSemantic)return probe;
}else{if(!(e.tagName==='INPUT'||e.tagName==='TEXTAREA'||e.isContentEditable||e.getAttribute('role')==='textbox'))return probe;
if(e.type==='password'||e.getAttribute('data-edakit-webtest')==='name')return probe;}
for(var d of docs(document))for(var old of d.querySelectorAll('[data-edakit-webtest="'+k+'"]'))old.removeAttribute('data-edakit-webtest');
e.setAttribute('data-edakit-webtest',k);probe.ok=true;return probe;
""".replace('KIND', json.dumps(kind))
        result = self.evaluate(code)
        self.calibration[kind] = result
        if not result.get('ok'):
            message = ('请先在 Edge 中点击左上角显示 A1 的名称框，再记录；无法确认名称框时不会输入任何内容'
                       if kind == 'name' else '请先在 Edge 中点击 fx 右侧的公式栏输入区域，再记录')
            raise WebMatchError(message)

    def _focus_name(self):
        result = self.evaluate("var e=marked('name');if(!e||!(e.tagName==='INPUT'||e.tagName==='TEXTAREA'||e.isContentEditable))return false;e.focus();return active(document)===e;")
        if not result:
            raise WebMatchError('名称框失效，请重新校准；没有向表格单元格输入')

    def _key(self, key, code, vk, modifiers=0):
        for kind in ('keyDown', 'keyUp'):
            self.cdp.call('Input.dispatchKeyEvent', {'type': kind, 'key': key, 'code': code,
                                                    'windowsVirtualKeyCode': vk, 'modifiers': modifiers})

    def _read_selected(self, address, settle_ms, cancel):
        return self._select_address(address, settle_ms, cancel)

    def _select_address(self, address, settle_ms, cancel):
        if not re.fullmatch(r'[A-Z]{1,3}[1-9]\d{0,5}(?::[A-Z]{1,3}[1-9]\d{0,5})?', address):
            raise WebMatchError('单元格地址无效')
        if cancel.is_set():
            raise WebMatchError('已取消')
        started = time.perf_counter()
        if self.navigation == 'keyboard':
            self._select_keyboard(address, cancel)
        else:
            self._select_input(address)
        selected = time.perf_counter()
        if cancel.wait(settle_ms / 1000):
            raise WebMatchError('已取消')
        settled = time.perf_counter()
        def snapshot():
            return self.evaluate("var n=marked('name'),f=marked('formula');return !n||!f?null:{address:text(n).replace(/\\$/g,'').trim().toUpperCase(),value:text(f)};")
        first = snapshot()
        confirm_start = time.perf_counter()
        if cancel.wait(.06):
            raise WebMatchError('已取消')
        confirm_end = time.perf_counter()
        second = snapshot()
        ended = time.perf_counter()
        if not first or not second or first['address'] != address or second['address'] != address:
            raise WebMatchError('网页选中地址与请求不一致，可能有筛选、隐藏行或控件变化，已停止')
        if first['value'] != second['value']:
            raise WebMatchError('公式栏内容尚未稳定，请重试')
        if len(second['value']) > 32768:
            raise WebMatchError('单元格内容超过测试版限制')
        return second['value'], {'select_ms': round((selected - started) * 1000, 2),
                                 'settle_read_ms': round((ended - selected) * 1000, 2),
                                 'wait_ms': round(((settled - selected) + (confirm_end - confirm_start)) * 1000, 2),
                                 'read_ms': round(((ended - settled) - (confirm_end - confirm_start)) * 1000, 2),
                                 'total_ms': round((ended - started) * 1000, 2)}

    def _focus_grid(self):
        if not self.evaluate("var g=marked('grid');if(!g||g.id!=='FlexTableWrapper'||!g.contains(marked('name'))||!g.contains(marked('formula')))return false;g.focus();return active(document)===g;"):
            raise WebMatchError('表格键盘焦点无法确认，已停止；没有输入单元格内容')

    def _grid_focused(self):
        if not self.evaluate("return !!marked('grid')&&active(document)===marked('grid');"):
            raise WebMatchError('表格失去焦点，已停止自动读取')

    def _selection(self):
        return self.evaluate("return text(marked('name')).replace(/\\$/g,'').trim().toUpperCase();")

    @staticmethod
    def _point(address):
        m = re.fullmatch(r'([A-Z]{1,3})([1-9]\d{0,5})', address or '')
        if not m:
            raise WebMatchError('无法确认当前选区地址，已停止读取')
        column = 0
        for c in m[1]:
            column = column * 26 + ord(c) - 64
        row = int(m[2])
        if not 1 <= column <= 52 or not 1 <= row <= 2000:
            raise WebMatchError('选区地址超出自动读取上限，已停止')
        return column, row

    def _move_keyboard(self, target, cancel):
        goal = self._point(target)
        self._focus_grid()
        # Home/End are native selection commands. Only use End after its
        # endpoint was independently measured, and verify every shortcut.
        current_text = self._selection()
        current = self._point(current_text) if ':' not in (current_text or '') else None
        distance = lambda p: abs(goal[0]-p[0]) + abs(goal[1]-p[1])
        shortcuts = [((1, 1), 'A1', 'Home', 36)]
        if self.range_end:
            col, row = self.range_end
            name = ''
            while col:
                col, digit = divmod(col-1, 26)
                name = chr(65+digit) + name
            shortcuts.append((self.range_end, name+str(row), 'End', 35))
        best = min(shortcuts, key=lambda item: distance(item[0]))
        if current is None or distance(best[0])+1 < distance(current):
            self._grid_focused()
            self._key(best[2], best[2], best[3], 2)
            if cancel.wait(.08):
                raise WebMatchError('已取消')
            if self._selection() != best[1]:
                raise WebMatchError('表格未响应首尾定位命令，已停止读取')
            current = best[0]
        for delta, positive, negative, pos_vk, neg_vk in (
                (goal[1]-current[1], 'ArrowDown', 'ArrowUp', 40, 38),
                (goal[0]-current[0], 'ArrowRight', 'ArrowLeft', 39, 37)):
            key, vk = (positive, pos_vk) if delta > 0 else (negative, neg_vk)
            for step in range(abs(delta)):
                if cancel.is_set():
                    raise WebMatchError('已取消')
                if step % 20 == 0:
                    self._grid_focused()
                self._key(key, key, vk)
        if cancel.wait(.08):
            raise WebMatchError('已取消')
        self._grid_focused()
        if self._selection() != target:
            raise WebMatchError('键盘移动后的选区与目标不一致，可能存在筛选或隐藏行，未应用结果')

    def _select_keyboard(self, address, cancel):
        if ':' not in address:
            self._move_keyboard(address, cancel)
            return
        start, end = address.split(':')
        if start != 'A1' or self._point(end) != self.range_end:
            raise WebMatchError('仅支持已验证的完整区域复制')
        self._move_keyboard('A1', cancel)
        self._grid_focused()
        self._key('End', 'End', 35, 2 | 8)  # Ctrl+Shift+End; select, never edit.
        if cancel.wait(.15):
            raise WebMatchError('已取消')
        self._grid_focused()
        if self._selection() != address:
            raise WebMatchError('表格没有显示预期完整选区，不能复制可疑区域')

    def _select_input(self, address):
        self._focus_name()
        self._key('a', 'KeyA', 65, 2)
        if not self.evaluate("return marked('name')===active(document);"):
            raise WebMatchError('名称框失去焦点，已停止，未输入查询地址')
        self.cdp.call('Input.insertText', {'text': address})
        if not self.evaluate("return marked('name')===active(document);"):
            raise WebMatchError('名称框失去焦点，已停止')
        self._key('Enter', 'Enter', 13)

    def read_cell(self, address, settle_ms, cancel):
        match = re.fullmatch(r'([A-Z]{1,3})([1-9]\d{0,5})', address)
        if not match:
            raise WebMatchError('单元格地址无效')
        column, number = match.groups()
        anchor_ms = 0
        # Starting from a verified, nonempty header prevents a delayed formula
        # update from silently reusing the previous material's value.
        if int(number) != self.header_row and column in self.anchors:
            before = time.perf_counter()
            header, _ = self._read_selected(column + str(self.header_row), settle_ms, cancel)
            if header.strip() != self.anchors[column]:
                raise WebMatchError('表头锚点未更新，已停止以防读取上一次的内容')
            anchor_ms = (time.perf_counter() - before) * 1000
        value, timing = self._read_selected(address, settle_ms, cancel)
        if int(number) == self.header_row:
            self.anchors[column] = value.strip()
        elif column in self.anchors and value.strip() == self.anchors[column]:
            raise WebMatchError('公式栏仍是表头，未取得目标格新内容；请增加等待时间')
        timing['anchor_ms'] = round(anchor_ms, 2)
        timing['total_ms'] = round(timing['total_ms'] + anchor_ms, 2)
        return value, timing

    def close(self):
        if self.cdp:
            try:
                self.cdp.close()
            except Exception:
                pass
            self.cdp = None
        if self.process and self.process.poll() is None:
            # The explicitly launched dedicated browser only; never ordinary windows.
            self.process.terminate()
        self.process = None


# Compatibility for existing callers/tests; browser selection is always automatic.
EdgeReader = BrowserReader
