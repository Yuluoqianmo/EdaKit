"""Allegro snapshot -> native IPC-2581 -> existing cadence-ibom HTML engine."""
from __future__ import annotations
import csv
import ctypes
import datetime
import hashlib
import json
import math
import os
import subprocess
import sys
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET
from ..config import Config, app_dir
from ..storage import atomic_write
from . import reference

NS = {'i': 'http://webstds.ipc.org/2581'}
HEADERS = ['description', 'value', 'part', 'references', 'footprint', 'quantity', 'manufacturer', 'manufacturer_pn']
ATTRIBUTES = ['VALUE', 'DEVICE', 'PCB_FOOTPRINT', 'Manufacturer', 'Manufacturer_PN', 'Description', 'PART_NUMBER', 'BOM_IGNORE', 'COMP_VALUE', 'COMP_PACKAGE', 'PART_TYPE', 'MANUFACTURER', 'DESCRIPTION', 'TYPE']


def settings(data=None):
    path = app_dir() / 'ibom' / 'settings.json'
    if data is None:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'outputFolder': '', 'bomByBoard': {}}
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))
    return data


def board_key(source):
    return str(Path(source).resolve()).casefold()


def native_bom(ipc: Path):
    root = ET.parse(ipc).getroot()
    refs, ignored = {}, set()
    def props(node):
        out = {}
        for item in node.findall('.//i:Textual', NS):
            out[item.get('textualCharacteristicName', '').casefold()] = item.get('textualCharacteristicValue', '')
        for item in node.findall('i:NonstandardAttribute', NS):
            out[item.get('name', '').casefold()] = item.get('value', '')
        return out
    for item in root.findall('.//i:BomItem', NS):
        values = props(item)
        for ref in item.findall('i:RefDes', NS):
            name = ref.get('name', '').strip().upper()
            if ref.get('populate', 'true').casefold() == 'false':
                ignored.add(name)
            refs[name] = (values, item.get('OEMDesignNumberRef', ''))
    rows = []
    seen = set()
    for component in root.findall('.//i:Step/i:Component', NS):
        name = component.get('refDes', '').strip().upper()
        if not name or name in seen:
            raise ValueError('PCB 位号为空或重复，请先检查 PCB：' + name)
        seen.add(name)
        base, part = refs.get(name, ({}, ''))
        values = {**base, **props(component)}
        if name in ignored or values.get('bom_ignore', '').casefold() in ('true', 'yes', '1'):
            ignored.add(name)
            continue
        def get(*names, values=values):
            return next((values[n] for n in names if values.get(n)), '')
        rows.append(dict(zip(HEADERS, [get('description', 'desc'), get('value', 'comp_value'), get('物料编码', 'material_code', 'part_number') or part, name, component.get('packageRef', ''), 1, get('manufacturer'), get('manufacturer_pn')])))
    # Consolidate identical physical materials, not schematic symbol units.
    groups = {}
    for row in rows:
        identity = tuple(row[k] for k in HEADERS if k not in ('references', 'quantity'))
        if identity in groups:
            groups[identity]['references'] += ', ' + row['references']
            groups[identity]['quantity'] += 1
        else:
            groups[identity] = row.copy()
    return list(groups.values()), ignored


def load_labels(path):
    labels = {}
    if path:
        with Path(path).open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream, delimiter='\t'):
                values = {key: float(row[key]) for key in ('minX', 'minY', 'maxX', 'maxY', 'rotation')}
                if not all(math.isfinite(v) for v in values.values()) or values['maxX'] <= values['minX'] or values['maxY'] <= values['minY']:
                    raise ValueError('PCB 丝印文字范围无效')
                if row['side'] not in ('top', 'bottom'):
                    raise ValueError('PCB 丝印文字层无效')
                labels[(row['refdes'].upper(), row['side'])] = dict(values, side=row['side'], mirrored=row['mirrored'] == '1')
    return labels


def generate(board, *, source=None, output=None, bom=None, cadence_root=None, open_result=False, runner=subprocess.run, progress=None, use_board=False, labels=None):
    def stage(message):
        if progress:
            progress(message)
    stage('正在检查 PCB 快照与输出目录')
    board = Path(board).resolve()
    if not board.is_file():
        raise ValueError('当前 PCB 快照不存在')
    source = Path(source or board).resolve()
    cfg = settings()
    destination = Path(output or cfg.get('outputFolder') or source.parent / 'Output_Files' / 'iBOM')
    if not destination.is_absolute():
        raise ValueError('导出目录必须是完整路径')
    destination.mkdir(parents=True, exist_ok=True)
    root = Path(cadence_root or Config.load().cadence_root or '')
    if not (root / 'tools/bin/ipc2581_out.exe').is_file():
        from ..footprint.native import cadence_install
        root = cadence_install(Config.load())
    exe = root / 'tools/bin/ipc2581_out.exe'
    token = datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    job = app_dir() / 'ibom' / 'jobs' / token
    job.mkdir(parents=True)
    ipc, attrs = job / 'board.xml', job / 'attributes.txt'
    attrs.write_text(''.join('Component/' + key + '\n' for key in sorted({name.upper() for name in ATTRIBUTES})), encoding='ascii')
    command = [str(exe), '-b', '-p', '-t', '-c', '-d', '-D', '-O', '-k', '-f', '1.03', '-u', 'MILLIMETER', '-g', str(attrs), '-o', str(ipc), str(board)]
    env = dict(os.environ, CDSROOT=str(root), ALLEGRO_ROOT=str(root), ipc2581_compdef_all_attrs='1')
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    try:
        stage('正在运行 Allegro IPC-2581 导出程序')
        with (job / 'ipc-export.log').open('wb') as log:
            result = runner(command, cwd=job, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300, **options)
        if result.returncode not in (0, 1) or not ipc.is_file() or ipc.stat().st_size == 0:
            raise ValueError('Allegro IPC-2581 导出失败，日志：' + str(job / 'ipc-export.log'))
        stage('IPC 导出完成，正在读取器件属性和 BOM')
        rows, ignored = native_bom(ipc)
        if not rows:
            raise ValueError('PCB 中没有可导出的已放置器件')
        native_csv = job / 'pcb-bom.csv'
        with native_csv.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writeheader(); writer.writerows(rows)
        overlay = None if use_board else (bom or cfg.get('bomByBoard', {}).get(board_key(source)))
        bom_path = Path(overlay) if overlay else native_csv
        if not bom_path.is_file():
            raise ValueError('配置的 BOM 文件不存在，请重新选择或切回 PCB 属性：' + str(bom_path))
        # Include this project's Chinese header without changing native PN rules.
        reference.BOM_ALIASES['厂家型号'] = 'manufacturer_pn'
        if overlay:
            normalized = job / 'final-bom.csv'
            selected = reference.load_bom_rows(bom_path)
            with normalized.open('w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=HEADERS)
                writer.writeheader()
                for row in selected:
                    remaining = [r for r in row['references'] if r not in ignored]
                    if row['references'] and not remaining:
                        continue
                    writer.writerow(dict(zip(HEADERS, [row['description'], row['value'], row['part'], ', '.join(remaining), row['footprint'], len(remaining) if row['references'] else row['quantity'], row['manufacturer'], row['manufacturerPn']])))
            input_bom = normalized
        else:
            input_bom = bom_path
        options = reference.RuntimeOptions(bom=bom_path, placement=None, ipc=ipc, board_top=None, board_bottom=None, board_top_pdf=None, board_bottom_pdf=None, title=source.stem + ' · 交互式 BOM', project='', author='', version='', created_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), placement_unit='auto', include_test_points=False, testpoint_rules={'packageInclude': ['TP', 'testcoupf']}, image_placement={}, output=destination / (source.stem + '_iBOM_' + token + '.html'))
        options.bom = input_bom
        stage('正在解析 PCB 封装、焊盘和板框几何')
        payload = reference.build_payload(options)
        native_labels = load_labels(labels)
        for component in payload['components']:
            component['refdesLabel'] = native_labels.get((component['refdes'], component['side']))
        from .preview3d import prepare
        stage('正在查找 Allegro 库路径中的真实 3D 模型')
        prepare(payload, ipc, source, labels)
        atomic_write(job / 'models3d.json', json.dumps({
            'models': len(payload['preview3d']['models']),
            'components': payload['preview3d']['diagnostics'],
            'warnings': payload['preview3d']['warnings'],
        }, ensure_ascii=False, indent=2))
        # Keep progress stable for the same board/BOM, separate different boards.
        payload['meta']['projectKey'] = hashlib.sha256((board_key(source) + json.dumps([(r['references'], r['manufacturerPn'], r['value']) for r in payload['bomRows']], ensure_ascii=False)).encode()).hexdigest()
        payload['meta'].update(sourceBom=bom_path.name if overlay else 'PCB 属性', sourceIpc=source.name, sourcePlacement='')
        if not payload['components']:
            raise ValueError('BOM 与 PCB 没有可定位的器件，请检查位号')
        # Exclude native non-populated references even when an external BOM includes them.
        stage('正在生成离线 HTML 与导出报告')
        html = reference.render_html(payload)
        with options.output.open('x', encoding='utf-8', newline='\n') as f:
            f.write(html)
        report = reference.render_generation_report(payload, options.output, token)
        atomic_write(job / 'report.txt', report)
        atomic_write(options.output.with_suffix('.report.txt'), report)
        receipt = {'html': str(options.output), 'report': str(options.output.with_suffix('.report.txt')), 'job': str(job), 'bomRows': len(payload['bomRows']), 'components': len(payload['components']), 'source': str(source), 'overlay': str(bom_path) if overlay else ''}
        atomic_write(job / 'result.json', json.dumps(receipt, ensure_ascii=False, indent=2))
        if open_result:
            os.startfile(str(options.output))
        stage('导出完成：%s 组物料，%s 个器件' % (receipt['bomRows'], receipt['components']))
        return receipt
    except Exception as error:
        atomic_write(job / 'error.txt', str(error))
        raise


def choose_bom():
    from ctypes import wintypes as w
    class OPENFILENAME(ctypes.Structure):
        _fields_ = [('lStructSize', w.DWORD), ('hwndOwner', w.HWND), ('hInstance', w.HINSTANCE), ('lpstrFilter', w.LPCWSTR), ('lpstrCustomFilter', w.LPWSTR), ('nMaxCustFilter', w.DWORD), ('nFilterIndex', w.DWORD), ('lpstrFile', w.LPWSTR), ('nMaxFile', w.DWORD), ('lpstrFileTitle', w.LPWSTR), ('nMaxFileTitle', w.DWORD), ('lpstrInitialDir', w.LPCWSTR), ('lpstrTitle', w.LPCWSTR), ('Flags', w.DWORD), ('nFileOffset', w.WORD), ('nFileExtension', w.WORD), ('lpstrDefExt', w.LPCWSTR), ('lCustData', ctypes.c_ssize_t), ('lpfnHook', ctypes.c_void_p), ('lpTemplateName', w.LPCWSTR), ('pvReserved', ctypes.c_void_p), ('dwReserved', w.DWORD), ('FlagsEx', w.DWORD)]
    buffer = ctypes.create_unicode_buffer(32768)
    dialog = OPENFILENAME()
    dialog.lStructSize = ctypes.sizeof(dialog)
    # Never parent a worker dialog to the editor waiting for its launcher.
    dialog.hwndOwner = None
    dialog.lpstrFile = ctypes.cast(buffer, w.LPWSTR)
    dialog.nMaxFile = len(buffer)
    dialog.lpstrFilter = 'BOM 表格\0*.xlsx;*.csv;*.tsv;*.txt\0\0'
    dialog.lpstrTitle = '选择当前 PCB 的最终 BOM（按位号关联）'
    dialog.Flags = 0x1000 | 0x800 | 0x8 | 0x80000  # file/path must exist, no chdir, explorer
    api = ctypes.WinDLL('comdlg32')
    api.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAME)]
    if api.GetOpenFileNameW(ctypes.byref(dialog)):
        return buffer.value
    code = api.CommDlgExtendedError()
    if code:
        raise OSError('BOM 文件选择失败：' + hex(code))
    return ''


def command(args):
    try:
        if args.cmd == 'ibom-export' and getattr(args, 'dialog', False):
            from .window import launch
            return launch(args)
        if args.cmd == 'ibom-export' and getattr(args, 'dialog_worker', False):
            from .window import show
            return show(args)
        if args.cmd == 'ibom-settings' and getattr(args, 'detach', False):
            # The batch launcher must exit before any modal UI is displayed.
            # An independent process keeps Allegro's command loop responsive.
            launch = [sys.executable]
            if not getattr(sys, 'frozen', False):
                launch += ['-m', 'edakit']
            launch += ['ibom-settings', '--source', str(args.source)]
            for option in ('pick_folder', 'choose_bom', 'clear_bom', 'notify'):
                if getattr(args, option, False):
                    launch.append('--' + option.replace('_', '-'))
            flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
            # A new one-file process must own its extraction directory after
            # this short-lived launcher exits and removes its temporary files.
            child_env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
            subprocess.Popen(launch, creationflags=flags, close_fds=True,
                             env=child_env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        if args.cmd == 'ibom-export':
            result = generate(args.board, source=args.source, output=args.output, bom=args.bom, cadence_root=args.cadence_root, open_result=args.open, labels=getattr(args, 'labels', None))
            print(json.dumps(result, ensure_ascii=False))
        else:
            cfg = settings()
            if args.pick_folder:
                from ..services.directory_picker import _pick_directory
                folder = _pick_directory(cfg.get('outputFolder', ''), None)
                if folder:
                    cfg['outputFolder'] = folder
            if args.choose_bom:
                selected = choose_bom()
                if selected:
                    cfg.setdefault('bomByBoard', {})[board_key(args.source)] = selected
            if args.clear_bom:
                cfg.setdefault('bomByBoard', {}).pop(board_key(args.source), None)
            settings(cfg)
        return 0
    except Exception as error:
        atomic_write(app_dir() / 'ibom' / 'last-error.txt', str(error))
        if getattr(args, 'notify', False) and os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, str(error), 'EdaKit iBOM', 0x10 | 0x10000)
        return 2
