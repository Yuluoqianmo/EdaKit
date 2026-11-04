"""Experimental range reader with in-memory results and data-free timing reports.

This first test build scans an explicitly selected row range, rather than taking
the first website Find hit. That permits duplicate detection within that range.
"""
from __future__ import annotations

import copy
import csv
import io
from pathlib import Path
import re
import threading
import time
import uuid

from .webmatch_browser import BrowserReader, WebMatchError, document_url

BUILD = '0.1.8'


def column_name(number):
    result = ''
    while number:
        number, digit = divmod(number - 1, 26)
        result = chr(65 + digit) + result
    return result


def copied_table(value, rows, columns):
    if not isinstance(value, str) or len(value) > 2_000_000:
        raise WebMatchError('区域复制内容无效或过大')
    try:
        table = list(csv.reader(io.StringIO(value), delimiter='\t', strict=True))
    except csv.Error:
        raise WebMatchError('区域复制格式无法确认，未应用结果') from None
    if len(table) != rows or any(len(row) > columns for row in table):
        raise WebMatchError('区域复制行列数不一致，可能被截断，未应用结果')
    return [row + [''] * (columns-len(row)) for row in table]


def scan_options(body):
    out = {}
    for key, default in (('modelColumn', 'D'), ('codeColumn', 'F'), ('typeColumn', 'B')):
        value = body.get(key, default)
        if not isinstance(value, str) or not re.fullmatch(r'[A-Z]{1,3}', value):
            raise WebMatchError('列名请使用大写字母，例如 D、F、B')
        out[key] = value
    if len(set(out.values())) != 3:
        raise WebMatchError('型号、编码和类型必须选择不同的列')
    for key, default, low, high in (('headerRow', 1, 1, 100), ('firstRow', 2, 2, 100000),
                                   ('lastRow', 30, 2, 100000), ('settleMs', 250, 150, 2000)):
        value = body.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise WebMatchError('行号或等待时间超出测试范围')
        out[key] = value
    if not out['headerRow'] < out['firstRow'] <= out['lastRow'] or out['lastRow'] - out['firstRow'] >= 2000:
        raise WebMatchError('一次测试最多扫描 2000 行，并且数据行必须位于表头之后')
    return out


class WebMatch:
    def __init__(self, reader_factory=None):
        self.reader_factory = reader_factory or self._reader
        self.reader = None
        self.owner = ''
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread = None
        self.records = {}
        self.snapshot = ''
        self.run = ''
        self.state = {'state': 'closed', 'message': '尚未打开测试浏览器', 'build': BUILD}
        self.metrics = []
        self.summary = {}
        self.options = {}
        self.opened_at = None

    @staticmethod
    def _reader():
        from ..config import app_dir
        return BrowserReader(Path(app_dir()) / 'webmatch-test' / 'browser-profile')

    def _update(self, **values):
        with self.lock:
            self.state.update(values)

    def status(self, owner):
        with self.lock:
            self._owner(owner)
            return copy.deepcopy(dict(self.state, run=self.run, summary=self.summary,
                                      busy=bool(self.thread and self.thread.is_alive())))

    def _owner(self, owner):
        if not isinstance(owner, str) or not owner or len(owner) > 160:
            raise WebMatchError('请从 Capture 的 BOM 页面打开测试功能')
        if self.owner and owner != self.owner:
            raise WebMatchError('测试窗口正在由另一个 Capture 会话使用，请先关闭该测试连接')

    def _spawn(self, fn):
        if self.thread and self.thread.is_alive():
            raise WebMatchError('测试任务仍在运行，请等待或取消')
        self.cancel.clear()
        def work():
            try:
                fn()
            except Exception as exc:
                from .webmatch_structure import CheckpointError
                # Never pass upstream DOM/material strings to HTTP logs or reports.
                message = str(exc) if isinstance(exc, WebMatchError) else '测试操作失败；请检查窗口是否关闭、网络和控件校准状态'
                self.records = {}
                if isinstance(exc, CheckpointError):
                    with self.lock:
                        self.summary['parser'] = copy.deepcopy(exc.diagnostics)
                self._update(state='cancelled' if self.cancel.is_set() else 'error', message=message)
                if self.summary:
                    self.summary['outcome'] = 'cancelled' if self.cancel.is_set() else 'error'
        self.thread = threading.Thread(target=work, name='edakit-webmatch-test', daemon=True)
        self.thread.start()

    def command(self, body):
        if not isinstance(body, dict):
            raise WebMatchError('测试请求无效')
        owner, action = body.get('session', ''), body.get('action', '')
        with self.lock:
            self._owner(owner)
            if action not in ('status', 'report', 'cancel') and self.thread and self.thread.is_alive():
                raise WebMatchError('测试任务仍在运行，请等待或取消')
            if action == 'status':
                return self.status(owner)
            if action == 'report':
                return {'build': BUILD, 'mode': self.summary.get('mode', 'explicit_range_scan'), 'loginExcluded': True,
                        'containsMaterialValues': False, 'scope': dict(self.options),
                        'state': self.state['state'], 'summary': copy.deepcopy(self.summary),
                        'stage': self.state.get('stage', ''), 'message': self.state.get('message', ''),
                        'browser': getattr(self.reader, 'product', ''),
                        'browserOpenMs': self.state.get('browserOpenMs'),
                        'calibration': copy.deepcopy(getattr(self.reader, 'calibration', {})),
                        'cells': copy.deepcopy(self.metrics)}
            if action == 'cancel':
                self.cancel.set()
                return self.status(owner)
            if action == 'probe':
                url = document_url(body.get('url'))
                self.owner = owner
                self.records, self.metrics, self.summary = {}, [], {}
                self.run = ''
                def probe():
                    if self.reader:
                        self.reader.close()
                    self.reader = self.reader_factory()
                    self.reader.open(url)
                    self._update(state='waiting', stage='structure_probe', message='请登录钉钉，登录后自动检查结构')
                    result = self.reader.structure_probe(self.cancel, lambda msg: self._update(message=msg))
                    self.summary = {'mode': 'structure_probe', 'structure': result}
                    self._update(state='done', stage='structure_completed', message='结构诊断完成，请复制诊断报告；尚未应用物料匹配')
                self._spawn(probe)
            elif action == 'auto':
                url = document_url(body.get('url'))
                models, snapshot = body.get('_models'), body.get('snapshot', '')
                if (not isinstance(models, list) or not 0 < len(models) <= 2000
                        or not all(isinstance(x, str) and 0 < len(x) <= 32768 for x in models)
                        or not isinstance(snapshot, str) or not snapshot):
                    raise WebMatchError('请先读取工程，且需有 1～2000 个非空厂家型号')
                self.owner = owner
                self.records, self.metrics, self.summary = {}, [], {}
                self.run, self.snapshot = '', snapshot
                self._update(state='opening', stage='opening', done=0, total=1,
                             message='正在打开钉钉；你只需登录，其余步骤自动完成')
                self._spawn(lambda: self._automatic(url, snapshot, models))
            elif action == 'open':
                url = document_url(body.get('url'))
                if self.reader:
                    raise WebMatchError('测试窗口已存在，请先关闭测试连接')
                self.owner, self.opened_at = owner, time.perf_counter()
                self._update(state='opening', message='正在打开默认浏览器匹配窗口…')
                def start_browser():
                    before = time.perf_counter()
                    self.reader = self.reader_factory()
                    self.reader.open(url)
                    self._update(state='waiting', stage='login_and_calibration', browserOpenMs=round((time.perf_counter() - before) * 1000, 2), message='请在默认浏览器扫码打开表格')
                self._spawn(start_browser)
            elif action == 'close':
                if self.thread and self.thread.is_alive():
                    raise WebMatchError('请先取消任务，等待停止后关闭连接')
                if self.reader:
                    self.reader.close()
                self.reader = None
                self.records, self.metrics, self.summary = {}, [], {}
                self.run, self.snapshot, self.owner = '', '', ''
                self._update(state='closed', message='测试连接已关闭，内存匹配结果已释放')
            elif action == 'calibrate':
                if not self.reader:
                    raise WebMatchError('请先打开测试浏览器')
                kind = body.get('kind')
                if kind not in ('name', 'formula'):
                    raise WebMatchError('校准类型无效')
                def calibrate():
                    self._update(stage='calibrate_' + kind)
                    self.reader.calibrate(kind)
                    self._update(state='calibrating', message=('名称框' if kind == 'name' else '公式栏') + '已记录；两项完成后校验表头')
                self._spawn(calibrate)
            elif action in ('check', 'start'):
                if not self.reader:
                    raise WebMatchError('请先打开测试浏览器')
                options = scan_options(body)
                if action == 'start':
                    snapshot = body.get('snapshot', '')
                    models = body.get('_models')
                    if (not isinstance(models, list) or not 0 < len(models) <= 2000
                            or not all(isinstance(x, str) and 0 < len(x) <= 32768 for x in models)
                            or not isinstance(snapshot, str) or not snapshot):
                        raise WebMatchError('请先读取工程，且需有 1～2000 个非空厂家型号')
                    self._spawn(lambda: self._scan(snapshot, models, options))
                else:
                    self._spawn(lambda: self._headers(options))
            else:
                raise WebMatchError('未知测试操作')
            return self.status(owner)

    def _automatic(self, url, snapshot, models):
        from .bom import normalized
        opened = time.perf_counter()
        self.options = {}
        self.summary = {'mode': 'automatic_checkpoint', 'outcome': 'waiting_for_login'}
        if self.reader:
            self.reader.close()
        self.reader = self.reader_factory()
        self.reader.open(url)
        self._update(browserOpenMs=round((time.perf_counter()-opened)*1000, 2))
        table, metadata = self.reader.read_table(self.cancel, lambda msg: self._update(
            state='waiting', stage='read_snapshot', message=msg))
        self.summary.update(metadata, outcome='running')
        self._update(state='running', stage='matching', done=0, total=len(table),
                     message='快照校验通过，正在匹配型号和物料编码…')
        started = time.perf_counter()
        wanted = {normalized(value) for value in models if normalized(value)}
        records, hits = {key: set() for key in wanted}, {key: 0 for key in wanted}
        for model, code, typ in table:
            if self.cancel.is_set():
                raise WebMatchError('已取消；未应用不完整结果')
            key = normalized(model)
            if key in wanted:
                records[key].add((code, typ))
                hits[key] += 1
        if self.cancel.is_set():
            raise WebMatchError('已取消；未应用不完整结果')
        elapsed = round((time.perf_counter()-started)*1000, 2)
        result = {'name': '钉钉网页 · 快照匹配 · 仅内存',
                  'records': {key: sorted(values) for key, values in records.items() if values}}
        with self.lock:
            if self.cancel.is_set():
                raise WebMatchError('已取消；未应用不完整结果')
            self.records, self.snapshot = result, snapshot
            self.run = uuid.uuid4().hex
            self.summary.update(outcome='done', models=len(wanted),
                matched=sum(len(v) == 1 and bool(next(iter(v))[0]) for v in records.values()),
                unmatchedInRange=sum(not v for v in records.values()),
                conflicts=sum(len(v) > 1 for v in records.values()),
                emptyCodes=sum(len(v) == 1 and not next(iter(v))[0] for v in records.values()),
                duplicateModels=sum(count > 1 for count in hits.values()),
                matching_ms=elapsed, batch_ms=round(metadata.get('reader_ms', 0)+elapsed, 2))
            self._update(state='done', stage='completed', done=len(table), total=len(table),
                         message='后台匹配完成，正在更新本次 BOM；未命中及冲突项保留待处理')

    def _automatic_copy(self, url, snapshot, models):
        """Legacy copy implementation retained for regression comparison only."""
        from .bom import normalized
        opened = time.perf_counter()
        self.summary = {'mode': 'automatic', 'outcome': 'waiting_for_login'}
        if self.reader and getattr(self.reader, 'url', url) != url:
            self.reader.close()
            self.reader = None
        if self.reader is None or (getattr(self.reader, 'process', None) is not None
                                   and self.reader.process.poll() is not None):
            if self.reader:
                self.reader.close()
            self.reader = self.reader_factory()
            self.reader.open(url)
        self._update(browserOpenMs=round((time.perf_counter()-opened)*1000, 2))
        wait = self.reader.prepare(self.cancel, lambda msg: self._update(
            state='waiting', stage='login', message=msg))
        started = time.perf_counter()
        self.opened_at = started
        self.summary.update(wait, outcome='running')
        self._update(state='running', stage='identify', message='已登录，正在自动识别表头和表格范围…')
        try:
            row_count, col_count, end = self.reader.used_range(self.cancel)
            options = {'headerRow': 1, 'firstRow': 2, 'lastRow': row_count, 'settleMs': 250}
            required = {'Manufacturer_PN': 'modelColumn', '新物料编码': 'codeColumn', 'Part_Type': 'typeColumn'}
            self.reader.header_row, self.reader.anchors = 1, {}
            for number in range(1, min(col_count, 26)+1):
                col = column_name(number)
                value = self._read(col+'1', 'header', 1, options, self.metrics)
                if value in required:
                    key = required[value]
                    if key in options:
                        raise WebMatchError('存在同名表头，无法自动确定列，未应用结果')
                    options[key] = col
            if not all(key in options for key in required.values()):
                raise WebMatchError('未识别到型号、物料编码和类型表头，请确认打开的是物料总表')
            self.options = options
            self._update(stage='bulk_copy', message='正在批量读取表格，随后自动匹配整个 BOM…')
            try:
                raw, timing = self.reader.copy_range('A1:'+end, self.cancel)
            except WebMatchError:
                if self.cancel.is_set():
                    raise
                if getattr(self.reader, 'navigation', '') == 'keyboard':
                    raise WebMatchError('当前表格未提供可确认的完整区域复制；已停止，未应用结果。键盘模式不进行可能长时间阻塞的逐格扫描') from None
                before = list(self.metrics)
                self._update(message='网页暂不支持批量复制，正在自动逐行读取，无需操作')
                self._scan(snapshot, models, options)
                self.metrics = before + self.metrics
                self.summary.update(wait, mode='automatic_row_fallback',
                                    batch_ms=round((time.perf_counter()-started)*1000, 2))
                self._update(message='自动匹配完成，正在更新 BOM；筛选隐藏项覆盖未确认')
                return
            table = copied_table(raw, row_count, col_count)
            self.metrics.append(dict(timing, kind='bulk_copy', sourceRow=0, success=True))
            # The copied data must agree with freshly read headers and spaced rows.
            for expected, key in required.items():
                idx = 0
                for c in options[key]:
                    idx = idx*26 + ord(c)-64
                if table[0][idx-1].strip() != expected:
                    raise WebMatchError('复制的表头与当前表格不一致，未应用结果')
            indices = {}
            for key in required.values():
                idx = 0
                for c in options[key]:
                    idx = idx*26 + ord(c)-64
                indices[key] = idx-1
            self._update(stage='verify', message='正在自动核对复制结果，防止缺行或旧内容…')
            for row in sorted({2, max(2, row_count//2), row_count}):
                for key in required.values():
                    actual = self._read(options[key]+str(row), 'bulk_verify', row, options, self.metrics)
                    if actual != table[row-1][indices[key]].strip():
                        raise WebMatchError('批量数据与表格抽查不一致，未应用结果')
            match_start = time.perf_counter()
            wanted = {normalized(x) for x in models if normalized(x)}
            records, hits = {key: set() for key in wanted}, {key: 0 for key in wanted}
            for row in table[1:]:
                if self.cancel.is_set():
                    raise WebMatchError('已取消；未应用不完整结果')
                key = normalized(row[indices['modelColumn']])
                if key in wanted:
                    records[key].add((row[indices['codeColumn']].strip(), row[indices['typeColumn']].strip()))
                    hits[key] += 1
            if self.cancel.is_set():
                raise WebMatchError('已取消；未应用不完整结果')
            self.records = {'name': '钉钉网页 · 自动匹配 · 仅内存',
                            'records': {key: sorted(v) for key, v in records.items() if v}}
            self.run = uuid.uuid4().hex
            self.summary.update(mode='automatic_bulk_copy', outcome='done', models=len(wanted),
                rowsScanned=row_count-1, matched=sum(len(v)==1 and bool(next(iter(v))[0]) for v in records.values()),
                unmatchedInRange=sum(not v for v in records.values()), conflicts=sum(len(v)>1 for v in records.values()),
                emptyCodes=sum(len(v)==1 and not next(iter(v))[0] for v in records.values()),
                duplicateModels=sum(v>1 for v in hits.values()),
                matching_ms=round((time.perf_counter()-match_start)*1000, 2),
                coverage='当前工作表自动识别区域；筛选、隐藏项及其他工作表覆盖未确认')
            self._update(state='done', stage='completed', done=row_count-1, total=row_count-1,
                         message='自动匹配完成，正在更新 BOM；筛选隐藏项覆盖未确认')
        finally:
            self.summary['batch_ms'] = round((time.perf_counter()-started)*1000, 2)

    def _read(self, address, kind, source_row, options, metrics):
        self._update(stage='read_' + kind)
        before = time.perf_counter()
        try:
            value, timing = self.reader.read_cell(address, options['settleMs'], self.cancel)
        except Exception:
            with self.lock:
                metrics.append({'kind': kind, 'sourceRow': source_row, 'success': False,
                                'total_ms': round((time.perf_counter() - before) * 1000, 2)})
            raise
        with self.lock:
            metrics.append(dict(timing, kind=kind, sourceRow=source_row, success=True))
        return value.strip()

    def _headers(self, options, metrics=None):
        metrics = metrics if metrics is not None else []
        self.reader.header_row = options['headerRow']
        self.reader.anchors = {}
        expected = [('modelColumn', 'Manufacturer_PN'), ('codeColumn', '新物料编码'), ('typeColumn', 'Part_Type')]
        for column, header in expected:
            value = self._read(options[column] + str(options['headerRow']), 'header', options['headerRow'], options, metrics)
            if value != header:
                raise WebMatchError('表头校验失败：请核对工作表、列名和公式栏校准；没有写入任何单元格')
        self._update(state='ready', message='三个表头校验通过。先扫描小范围并人工核对，再扩大行范围')

    def _scan(self, snapshot, models, options):
        from .bom import normalized
        started = time.perf_counter()
        self.records, self.metrics, self.summary = {}, [], {}
        self.options, self.snapshot, self.run = options, snapshot, uuid.uuid4().hex
        self._update(state='running', message='正在校验表头…', done=0,
                     total=options['lastRow'] - options['firstRow'] + 1, models=len(models))
        self.summary = {'outcome': 'running', 'batch_ms': 0, 'rowsScanned': 0,
                        'models': 0, 'matched': 0, 'unmatchedInRange': 0, 'conflicts': 0,
                        'emptyCodes': 0, 'normalization_ms': 0, 'matching_ms': 0,
                        'result_build_ms': 0, 'coverage': '用户指定范围，未证明覆盖整表',
                        'login_and_calibration_wait_ms': round((started - self.opened_at) * 1000, 2) if self.opened_at else None}
        try:
            self._headers(options, self.metrics)
            self._update(state='running')
            prep = time.perf_counter()
            wanted = set(normalized(x) for x in models if normalized(x))
            self.summary['normalization_ms'] = round((time.perf_counter() - prep) * 1000, 2)
            self.summary['models'] = len(wanted)
            records = {key: set() for key in wanted}
            hits = {key: 0 for key in wanted}
            matching = 0.0
            for ordinal, number in enumerate(range(options['firstRow'], options['lastRow'] + 1), 1):
                if self.cancel.is_set():
                    raise WebMatchError('已取消；不应用不完整结果')
                if time.perf_counter() - started > 3600:
                    raise WebMatchError('测试超过一小时上限，已停止；请缩小范围')
                raw = self._read(options['modelColumn'] + str(number), 'model', number, options, self.metrics)
                mark = time.perf_counter()
                key = normalized(raw)
                hit = key in wanted
                matching += time.perf_counter() - mark
                if hit:
                    code = self._read(options['codeColumn'] + str(number), 'code', number, options, self.metrics)
                    typ = self._read(options['typeColumn'] + str(number), 'type', number, options, self.metrics)
                    # Re-read model after reading its code/type to reject shifted/stale selection.
                    verify = self._read(options['modelColumn'] + str(number), 'verify', number, options, self.metrics)
                    if normalized(verify) != key:
                        raise WebMatchError('读取期间型号发生变化，已停止；请勿操作测试窗口')
                    records[key].add((code, typ))
                    hits[key] += 1
                with self.lock:
                    self.summary['rowsScanned'] = ordinal
                    self.summary['batch_ms'] = round((time.perf_counter() - started) * 1000, 2)
                self._update(done=ordinal, state='running', message='正在读取指定范围，请勿操作钉钉窗口；可随时取消')
            if self.cancel.is_set():
                raise WebMatchError('已取消；不应用不完整结果')
            finish = time.perf_counter()
            result = {key: sorted(values) for key, values in records.items() if values}
            matched = sum(len(v) == 1 and bool(next(iter(v))[0]) for v in records.values())
            self.records = {'name': '钉钉网页测试 · 仅内存 · 指定行范围', 'records': result}
            self.summary.update(matched=matched, unmatchedInRange=sum(not v for v in records.values()),
                                conflicts=sum(len(v) > 1 for v in records.values()),
                                emptyCodes=sum(len(v) == 1 and not next(iter(v))[0] for v in records.values()),
                                duplicateModels=sum(count > 1 for count in hits.values()),
                                header_ms=round(sum(x['total_ms'] for x in self.metrics if x['kind'] == 'header'), 2),
                                reader_ms=round(sum(x['total_ms'] for x in self.metrics if x['kind'] != 'header'), 2),
                                anchor_ms=round(sum(x.get('anchor_ms', 0) for x in self.metrics), 2),
                                matching_ms=round(matching * 1000, 2), outcome='done',
                                result_build_ms=round((time.perf_counter() - finish) * 1000, 2),
                                batch_ms=round((time.perf_counter() - started) * 1000, 2))
            self._update(state='done', stage='completed', message='指定范围读取完成；请人工核对后应用。范围外重复项仍未知')
        finally:
            self.summary['batch_ms'] = round((time.perf_counter() - started) * 1000, 2)

    def result(self, owner, run, snapshot):
        with self.lock:
            self._owner(owner)
            if (self.state['state'] != 'done' or not run or run != self.run
                    or snapshot != self.snapshot or not self.records):
                raise WebMatchError('网页测试结果已失效或尚未完成；请重新测试或切回 Excel 编码表')
            return copy.deepcopy(self.records)

    def close(self):
        self.cancel.set()
        thread = self.thread
        if thread:
            thread.join(timeout=7)
        if not thread or not thread.is_alive():
            if self.reader:
                self.reader.close()
            self.reader = None
            self.records = {}


_manager = None
_lock = threading.Lock()


def manager():
    global _manager
    with _lock:
        if _manager is None:
            _manager = WebMatch()
        return _manager


def shutdown():
    if _manager:
        _manager.close()
