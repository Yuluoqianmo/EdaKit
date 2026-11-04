"""Synthetic tests; no real document, credentials or company material values."""
import json
import threading

import pytest

from edakit.services import bom, webmatch
from edakit.services.webmatch_browser import EdgeReader, WebMatchError, document_url, loopback_ws


URL = 'https://alidocs.dingtalk.com/i/nodes/SYNTHETIC_TEST'
CONFIG = {'mapping': dict(bom.FIELDS), 'typeProperty': 'Type'}


class Reader:
    def __init__(self):
        self.cells = {'D1': 'Manufacturer_PN', 'F1': '新物料编码', 'B1': 'Part_Type',
                      'D2': 'TEST-A', 'F2': '00001', 'B2': '电阻',
                      'D3': ' test-a ', 'F3': '00001', 'B3': '电阻',
                      'D4': 'TEST-B', 'F4': '00002', 'B4': '电阻',
                      'D5': 'test-b', 'F5': '00003', 'B5': '电阻',
                      'D6': 'TEST-C', 'F6': '', 'B6': '电阻'}
        self.reads = []
        self.cancel_on = ''
        self.closed = False

    def open(self, url):
        assert url == URL

    def calibrate(self, kind):
        assert kind in ('name', 'formula')

    def read_cell(self, address, settle, cancel):
        self.reads.append(address)
        if address == self.cancel_on:
            cancel.set()
        if cancel.is_set():
            raise WebMatchError('已取消')
        return self.cells.get(address, ''), {'select_ms': 1, 'settle_read_ms': 2, 'total_ms': 3}

    def close(self):
        self.closed = True


def wait(manager):
    manager.thread.join(2)
    assert not manager.thread.is_alive()
    return manager.status('owner')


def opened():
    reader = Reader()
    manager = webmatch.WebMatch(lambda: reader)
    manager.command({'session': 'owner', 'action': 'open', 'url': URL})
    assert wait(manager)['state'] == 'waiting'
    return manager, reader


def start(manager, **extra):
    manager.command(dict({'session': 'owner', 'action': 'start', 'snapshot': 'snapshot1',
                          '_models': ['TEST-A', 'TEST-B', 'TEST-C', 'TEST-NOT-FOUND', 'TEST'],
                          'lastRow': 6}, **extra))
    return wait(manager)


@pytest.mark.parametrize('value', ['http://alidocs.dingtalk.com/i/nodes/ABCDE',
    'https://alidocs.dingtalk.com.evil.test/i/nodes/ABCDE', 'https://user@alidocs.dingtalk.com/i/nodes/ABCDE',
    'https://alidocs.dingtalk.com:123/i/nodes/ABCDE', 'file:///E:/test.html',
    'https://alidocs.dingtalk.com/other/ABCDE', None, 123])
def test_document_allowlist(value):
    with pytest.raises(WebMatchError):
        document_url(value)


def test_url_strips_query_without_passing_plugin_credentials():
    assert document_url(URL + '?utm_scene=team_space#private') == URL


@pytest.mark.parametrize('value', ['ws://evil.test:9222/devtools/page/1',
    'ws://127.0.0.1:9223/devtools/page/1', 'wss://127.0.0.1:9222/devtools/page/1',
    'ws://user@127.0.0.1:9222/devtools/page/1', 'ws://127.0.0.1:9222/other'])
def test_cdp_cannot_connect_to_nonowned_endpoint(value):
    with pytest.raises(WebMatchError):
        loopback_ws(value, 9222)


def test_duplicate_empty_and_unmatched_in_range_no_persistence(monkeypatch):
    monkeypatch.setattr(bom, 'atomic_write', lambda *a: pytest.fail('unexpected table persistence'))
    manager, reader = opened()
    state = start(manager)
    assert state['state'] == 'done'
    s = state['summary']
    assert (s['matched'], s['conflicts'], s['emptyCodes'], s['unmatchedInRange']) == (1, 1, 1, 2)
    assert s['duplicateModels'] == 2 and s['rowsScanned'] == 5
    records = manager.result('owner', state['run'], 'snapshot1')
    assert records['records']['test-a'] == [('00001', '电阻')]
    assert len(records['records']['test-b']) == 2
    assert 'test' not in records['records']
    assert 'F7' not in reader.reads
    assert reader.reads.count('D2') == 2  # verified again after code/type read


def test_timing_report_does_not_contain_values_url_or_snapshot():
    manager, _ = opened()
    start(manager)
    report = manager.command({'session': 'owner', 'action': 'report'})
    serialized = json.dumps(report)
    for value in ('TEST-A', 'test-a', '00001', '00002', URL, 'snapshot1', 'owner'):
        assert value not in serialized
    assert report['loginExcluded'] is True
    assert report['containsMaterialValues'] is False
    assert report['cells'] and all('total_ms' in x for x in report['cells'])
    assert report['summary']['login_and_calibration_wait_ms'] >= 0


def test_result_is_bound_to_owner_run_and_snapshot():
    manager, _ = opened()
    state = start(manager)
    for args in [('other', state['run'], 'snapshot1'), ('owner', 'old-run', 'snapshot1'),
                 ('owner', state['run'], 'other-snapshot')]:
        with pytest.raises(WebMatchError):
            manager.result(*args)


def test_cancel_never_applies_partial_records():
    manager, reader = opened()
    reader.cancel_on = 'D4'
    state = start(manager)
    assert state['state'] == 'cancelled'
    assert manager.records == {}
    with pytest.raises(WebMatchError):
        manager.result('owner', state['run'], 'snapshot1')
    assert state['summary']['outcome'] == 'cancelled'


def test_header_mismatch_stops_before_reading_data():
    manager, reader = opened()
    reader.cells['F1'] = 'wrong header'
    state = start(manager)
    assert state['state'] == 'error'
    assert 'D2' not in reader.reads and not manager.records


def test_rechecks_model_and_rejects_changed_row():
    manager, reader = opened()
    original = reader.read_cell
    def changed(address, settle, cancel):
        value, timing = original(address, settle, cancel)
        if address == 'D2' and reader.reads.count(address) > 1:
            return 'OTHER', timing
        return value, timing
    reader.read_cell = changed
    state = start(manager)
    assert state['state'] == 'error' and not manager.records


def test_close_discards_memory_and_does_not_touch_main_browser():
    manager, reader = opened()
    state = start(manager)
    manager.command({'session': 'owner', 'action': 'close'})
    assert reader.closed and not manager.records
    with pytest.raises(WebMatchError):
        manager.result('owner', state['run'], 'snapshot1')


@pytest.mark.parametrize('bad', [{'lastRow': 3000}, {'firstRow': True}, {'lastRow': 1},
    {'settleMs': 0}, {'modelColumn': 'D;evil'}, {'codeColumn': 'D'}, {'headerRow': 2}])
def test_scope_bounds(bad):
    with pytest.raises(WebMatchError):
        webmatch.scan_options(bad)


def test_preview_uses_ephemeral_records_without_codes_file(monkeypatch):
    manager, _ = opened()
    state = start(manager)
    monkeypatch.setattr(webmatch, 'manager', lambda: manager)
    monkeypatch.setattr(bom, 'config', lambda: CONFIG)
    snap = {'design': 'synthetic', 'root': 'root', 'rows': [
        {'id': '0/1', 'reference': 'R1', 'path': '0/1',
         'props': {'Manufacturer_PN': 'TEST-A', 'Value': '1K', 'PCB Footprint': 'R0805'}}]}
    monkeypatch.setattr(bom, 'status', lambda *a: {'state': 'done', 'snapshot': snap})
    monkeypatch.setattr(bom, 'directory', lambda: pytest.fail('must not read or write code cache'))
    result = bom.from_request({'session': 'owner', 'snapshot': 'snapshot1', 'webMatch': state['run']})
    assert result['rows'][0]['物料编码'] == '00001'


def test_start_rejects_bad_models_and_concurrent_actions():
    manager, reader = opened()
    with pytest.raises(WebMatchError):
        start(manager, _models=[])
    entered, release = threading.Event(), threading.Event()
    original = reader.read_cell
    def blocked(*a):
        entered.set()
        assert release.wait(2)
        return original(*a)
    reader.read_cell = blocked
    manager.command({'session': 'owner', 'action': 'check'})
    assert entered.wait(1)
    with pytest.raises(WebMatchError):
        manager.command({'session': 'owner', 'action': 'calibrate', 'kind': 'name'})
    release.set()
    wait(manager)


def test_anchor_rejects_stale_previous_value_and_accounts_for_anchor_time(tmp_path):
    reader = EdgeReader(tmp_path)
    reader.anchors = {'D': 'Manufacturer_PN'}
    calls = []
    def select(address, *args):
        calls.append(address)
        return 'Manufacturer_PN', {'total_ms': 1, 'select_ms': 0, 'settle_read_ms': 1}
    reader._read_selected = select
    with pytest.raises(WebMatchError, match='公式栏仍是表头'):
        reader.read_cell('D2', 250, threading.Event())
    assert calls == ['D1', 'D2']
    def fresh(address, *args):
        return ('Manufacturer_PN' if address == 'D1' else 'TEST-A'), {'total_ms': 1}
    reader._read_selected = fresh
    value, timing = reader.read_cell('D2', 250, threading.Event())
    assert value == 'TEST-A' and 'anchor_ms' in timing


def test_webmatch_js_is_compatible_with_old_cef():
    from pathlib import Path
    import esprima
    text = (Path(__file__).resolve().parents[1] / 'frontend/bom/webmatch.js').read_text(encoding='utf-8')
    esprima.parseScript(text)
    assert not any(word in text for word in ('async ', '=>', 'const ', 'let '))


class AutoReader(Reader):
    def __init__(self):
        super().__init__()
        self.fail_copy = False
        self.bad_copy = False
        self.cancel_copy = False
        self.ready = False

    def prepare(self, cancel, progress):
        self.ready = True
        progress('请登录')
        return {'login_and_page_wait_ms': 1234}

    def used_range(self, cancel):
        return 6, 6, 'F6'

    def copy_range(self, address, cancel):
        assert self.ready and address == 'A1:F6'
        if self.cancel_copy:
            cancel.set()
            raise WebMatchError('已取消')
        if self.fail_copy:
            raise WebMatchError('复制不可用')
        value = '\r\n'.join('\t'.join(self.cells.get(f'{col}{row}', '') for col in 'ABCDEF') for row in range(1, 7))
        if self.bad_copy:
            value = value.replace('00001', 'BAD-COPY')
        return value, {'total_ms': 12}


def auto_started(reader=None):
    reader = reader or AutoReader()
    manager = webmatch.WebMatch(lambda: reader)
    manager._automatic = manager._automatic_copy  # Legacy copy regression tests.
    manager.command({'session': 'owner', 'action': 'auto', 'snapshot': 'snapshot1',
                     'url': URL, '_models': ['TEST-A', 'TEST-B', 'TEST-C', 'NOT-FOUND']})
    return manager, reader, wait(manager)


def test_auto_login_discovery_bulk_read_and_result_without_manual_steps():
    manager, reader, state = auto_started()
    assert state['state'] == 'done'
    assert state['summary']['mode'] == 'automatic_bulk_copy'
    assert state['summary']['login_and_page_wait_ms'] == 1234
    assert (state['summary']['matched'], state['summary']['conflicts'],
            state['summary']['emptyCodes'], state['summary']['unmatchedInRange']) == (1, 1, 1, 1)
    assert manager.result('owner', state['run'], 'snapshot1')['records']['test-a'] == [('00001', '电阻')]
    report = json.dumps(manager.command({'session': 'owner', 'action': 'report'}))
    for private in (URL, 'TEST-A', 'BAD-COPY', '00001', 'snapshot1'):
        assert private not in report
    assert len(reader.reads) < 40


def test_auto_copy_unavailable_falls_back_without_user_calibration():
    reader = AutoReader()
    reader.fail_copy = True
    manager, _, state = auto_started(reader)
    assert state['state'] == 'done'
    assert state['summary']['mode'] == 'automatic_row_fallback'
    assert manager.result('owner', state['run'], 'snapshot1')['records']['test-a'] == [('00001', '电阻')]


def test_auto_stale_copy_is_rejected_and_never_applied():
    reader = AutoReader()
    reader.bad_copy = True
    manager, _, state = auto_started(reader)
    assert state['state'] == 'error' and not manager.records
    with pytest.raises(WebMatchError):
        manager.result('owner', state['run'], 'snapshot1')
    assert 'BAD-COPY' not in json.dumps(manager.command({'session': 'owner', 'action': 'report'}))


def test_auto_cancelled_copy_does_not_fall_back_or_publish():
    reader = AutoReader()
    reader.cancel_copy = True
    manager, _, state = auto_started(reader)
    assert state['state'] == 'cancelled' and not manager.records
    assert 'D2' not in reader.reads


@pytest.mark.parametrize('value,rows,cols', [('a\tb', 2, 2), ('a\tb\tc', 1, 2), ('"unfinished', 1, 1)])
def test_truncated_or_malformed_copy_is_not_accepted(value, rows, cols):
    with pytest.raises(WebMatchError):
        webmatch.copied_table(value, rows, cols)


def test_tsv_preserves_quoted_newlines_blanks_and_leading_zero_codes():
    assert webmatch.copied_table('"line1\nline2"\t00001\r\n\t\r\n', 2, 2) == [
        ['line1\nline2', '00001'], ['', '']]


@pytest.mark.parametrize('exe,name', [('chrome.exe','Chrome'), ('msedge.exe','Edge'),
    ('brave.exe','Brave'), ('vivaldi.exe','Vivaldi'), ('chromium.exe','Chromium')])
def test_system_default_browser_support(exe, name):
    from edakit.services.webmatch_browser import supported_browser
    assert supported_browser(exe) == name


def test_unsupported_default_does_not_silently_use_edge():
    from edakit.services.webmatch_browser import supported_browser
    with pytest.raises(WebMatchError, match='不会擅自改用'):
        supported_browser('firefox.exe')


@pytest.mark.parametrize('mode,ok', [('standard', True), ('overlay', True),
    ('plaintext', True), ('grid', False), ('readonly', False), ('ambiguous', False),
    ('display', False), ('dingtalk', True), ('dingtalk-ambiguous', False)])
def test_discovery_toolbar_variants_and_safe_diagnostics(mode, ok):
    """Execute shipped JS against structural fixtures, never a real document."""
    import shutil
    import subprocess
    from edakit.services.webmatch_browser import DOM
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for DOM fixture tests')
    reader = EdgeReader('unused')
    scripts = []
    reader.evaluate = lambda script: scripts.append(script) or {}
    reader.discover()
    fixture = r"""
const vm=require('vm'),fs=require('fs');
const data=JSON.parse(fs.readFileSync(0,'utf8')),mode=data.mode;
const doc={},all=[];
function el(value,left,top,width=80){return {value,type:'text',tagName:'INPUT',children:[],
 readOnly:false,disabled:false,id:'',className:'',ownerDocument:doc,parentElement:null,
 getAttribute:()=>null,setAttribute:()=>{},removeAttribute:()=>{},
 getBoundingClientRect:()=>({left,top,right:left+width,bottom:top+24,width,height:24})};}
let name=el('A1',10,40),formula=el('PRIVATE-MATERIAL-DO-NOT-REPORT',120,40,480);
let cell=el('B2',20,150),canvas=el('',0,90,600);
if(mode==='overlay'){canvas.getBoundingClientRect=()=>({left:0,top:0,right:600,bottom:400,width:600,height:400});name.className='name-box';formula.className='formula-input';}
if(mode==='plaintext'){name.tagName='DIV';name.isContentEditable=true;name.getAttribute=k=>k==='contenteditable'?'plaintext-only':null;}
if(mode==='grid'){name=cell;}
if(mode==='readonly')name.readOnly=true;
all.push(name,formula);if(mode!=='grid')all.push(cell);
if(mode==='ambiguous')all.push(el('C3',300,40));
if(mode==='display'){all.splice(0,1);name.tagName='SPAN';name.className='name-box';name.innerText='A1';}
doc.querySelectorAll=s=>s==='canvas'?[canvas]:s.startsWith('input,textarea')?all:s==='div,span,button'&&mode==='display'?[name]:[];
if(mode.startsWith('dingtalk')){
 name.tagName='DIV';name.value='A1';name.getAttribute=k=>k==='data-testid'?'SelectionDisplayBar':null;
 formula.tagName='DIV';formula.className='m-rich-text-editor-content';
 const bar={querySelectorAll:s=>s==='[data-testid]'?(mode==='dingtalk-ambiguous'?[name,name]:[name]):s==='.m-rich-text-editor-content'?[formula]:[]};
 const grid=el('',0,0,600);grid.ownerDocument=doc;grid.querySelectorAll=s=>s==='.m-formular-bar'?[bar]:[];
 const query=doc.querySelectorAll;
 doc.querySelectorAll=s=>s==='#FlexTableWrapper[tabindex]'?[grid]:s.startsWith('input,textarea')?[]:query(s);
}
const context={document:doc,getComputedStyle:()=>({visibility:'visible'})};
process.stdout.write(JSON.stringify(vm.runInNewContext('(function(){'+data.script+'})()',context)));
"""
    result = subprocess.run([node, '-e', fixture], input=json.dumps({'mode': mode, 'script': DOM + scripts[0]}),
                            capture_output=True, text=True, encoding='utf-8', timeout=10, check=True)
    probe = json.loads(result.stdout)
    assert probe['ok'] is ok
    assert 'PRIVATE-MATERIAL' not in result.stdout
    assert all('value' not in c and 'id' not in c and 'className' not in c for c in probe['controls'])
    if mode == 'dingtalk':
        assert probe['navigation'] == 'keyboard'
    if mode == 'display':
        assert probe['displayAddressCount'] == 1


class NoWait:
    def __init__(self):
        self.cancelled = False

    def is_set(self):
        return self.cancelled

    def wait(self, seconds):
        return self.cancelled


class KeyboardReader(EdgeReader):
    def __init__(self):
        super().__init__('unused')
        self.navigation = 'keyboard'
        self.range_end = (6, 12)
        self.selection = 'A1'
        self.focused = True
        self.keys = []
        self.cancel_after = None
        self.skip_rows = False
        self.cdp = None  # Any accidental Input.insertText would fail the test.

    def evaluate(self, script):
        if 'address:text' in script:
            return {'address': self.selection, 'value': 'synthetic-'+self.selection}
        if 'return text(marked' in script:
            return self.selection
        return self.focused

    def _key(self, key, code, vk, modifiers=0):
        self.keys.append((key, modifiers))
        if self.cancel_after and len(self.keys) == self.cancel_after[0]:
            self.cancel_after[1].cancelled = True
        if key == 'Home' and modifiers == 2:
            self.selection = 'A1'
        elif key == 'End' and modifiers == 2:
            self.selection = 'F12'
        elif key == 'End' and modifiers == 10:
            self.selection = 'A1:F12'
        else:
            col, row = self._point(self.selection)
            if key == 'ArrowDown':
                row += 2 if self.skip_rows else 1
            elif key == 'ArrowUp':
                row -= 1
            elif key == 'ArrowRight':
                col += 1
            elif key == 'ArrowLeft':
                col -= 1
            self.selection = webmatch.column_name(col)+str(row)


def test_readonly_selection_navigation_never_inserts_text():
    reader = KeyboardReader()
    reader.selection = 'F12'
    value, _ = reader._select_address('D3', 250, NoWait())
    assert value == 'synthetic-D3' and reader.selection == 'D3'
    assert reader.keys[0] == ('Home', 2)
    assert all(k in ('Home', 'End', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight') for k, _ in reader.keys)
    reader._select_keyboard('A1:F12', NoWait())
    assert reader.selection == 'A1:F12' and reader.keys[-1] == ('End', 10)


def test_keyboard_navigation_uses_verified_end_for_nearby_rows():
    reader = KeyboardReader()
    reader._move_keyboard('D11', NoWait())
    assert reader.selection == 'D11' and reader.keys[0] == ('End', 2)
    assert len(reader.keys) == 4


def test_keyboard_focus_loss_and_filtered_row_mismatch_stop():
    reader = KeyboardReader()
    reader.focused = False
    with pytest.raises(WebMatchError, match='焦点'):
        reader._move_keyboard('D3', NoWait())
    assert not reader.keys
    reader.focused, reader.skip_rows = True, True
    with pytest.raises(WebMatchError, match='目标不一致'):
        reader._move_keyboard('A3', NoWait())


def test_keyboard_cancellation_stops_navigation_before_target():
    reader, cancel = KeyboardReader(), NoWait()
    reader.range_end = None
    reader.cancel_after = (3, cancel)
    with pytest.raises(WebMatchError, match='已取消'):
        reader._move_keyboard('D50', cancel)
    assert len(reader.keys) == 3


@pytest.mark.parametrize('address', ['A0', 'A2001', 'BA1', 'A1:F12', '', 'not-an-address'])
def test_keyboard_address_bounds(address):
    with pytest.raises(WebMatchError):
        EdgeReader._point(address)


def test_keyboard_copy_failure_does_not_start_quadratic_row_scan():
    reader = AutoReader()
    reader.navigation, reader.fail_copy = 'keyboard', True
    manager, _, state = auto_started(reader)
    assert state['state'] == 'error' and not manager.records
    assert '逐格扫描' in state['message']
    assert 'D2' not in reader.reads
