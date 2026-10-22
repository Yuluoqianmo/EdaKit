"""Owned Allegro subprocess builds with checked, non-overwriting publication."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from ..library import library_names
from ..storage import atomic_write
from ..services.footprint import prepare_footprint
from .validation import validate_pin_mapping


def manufacturing_notes(component):
    if any(p.drill_mm for p in component.footprint.padstacks):
        return ['通孔/槽孔未定义负片电源层 ANTI/THERMAL，请按工程规则配置后再用于负片层设计。']
    return []


def cadence_install(config):
    if config.cadence_root:
        root = Path(config.cadence_root)
    else:
        from ..install.deploy import find_capture_tcl_root
        root = find_capture_tcl_root().parents[2]
    if not (root / 'tools/bin/allegro.exe').is_file():
        raise ValueError('未找到 Allegro，请在库设置中指定 Cadence 安装目录')
    return root


def skill_path(path):
    return str(Path(path).resolve().as_posix()).replace('\\', '\\\\').replace('"', '\\"')


def automation_script(result):
    folder = Path(result['directory'])
    drawing = skill_path(result['drawing'])
    manual = skill_path(folder / 'manual_build.il')
    report = skill_path(folder / 'native-pins.txt')
    success = skill_path(folder / 'native-success.txt')
    diagnostic = skill_path(folder / 'native-design.txt')
    errors = skill_path(folder / 'native-errors.txt')
    shape_steps = []
    for name in result.get('shapeSymbols', []):
        shape_steps.extend([
            f'    (unless (axlOpenDesign ?design "{skill_path(folder / (name + ".dra"))}" ?mode "w" ?noMru t) (error "EdaKit: open shape failed"))',
            '    (edakit_clear_template)',
            f'    (load "{skill_path(folder / (name + ".il"))}")'])
    if shape_steps:
        shape_steps.append(f'    (unless (axlOpenDesign ?design "{drawing}" ?mode "w" ?noMru t) (error "EdaKit: reopen package failed"))')
    shapes = '\n'.join(shape_steps)
    mechanics = skill_path(folder / 'native-mechanical.txt')
    padreport = skill_path(folder / 'native-padstacks.txt')
    # Startup opens a private copy of the vendor package template.
    return f'''(defun edakit_clear_template ()
    (axlVisibleDesign t)
    (axlClearSelSet)
    (axlSetFindFilter ?enabled (list "all") ?onButtons (list "all"))
    (axlAddSelectAll)
    (when (axlGetSelSet) (unless (axlDeleteObject (axlGetSelSet)) (error "EdaKit: template cleanup failed")))
    (axlClearSelSet)
    (axlAddSelectAll)
    (when (or (axlGetSelSet) (axlDBGetDesign)->pins) (error "EdaKit: template still contains figures"))
    (axlClearSelSet))
(let ((edakitResult nil) (edakitFile nil) (errport (outfile "{errors}")))
  (setq edakitResult (errset (progn
    (axlSetVariable "noconfirm" t)
    (axlSetVariable "psmpath" '("{skill_path(folder)}" "."))
    (axlSetVariable "padpath" '("{skill_path(folder)}" "."))
{shapes}
    (unless (equal (lowerCase (simplifyFilename (axlGetDrawingName))) (lowerCase (simplifyFilename "{drawing}"))) (error "EdaKit: wrong automatic build drawing"))
    (unless (axlIsSymbolEditor) (error "EdaKit: expected symbol editor"))
    (axlVisibleDesign t)
    (axlClearSelSet)
    (axlSetFindFilter ?enabled (list "all") ?onButtons (list "all"))
    (axlAddSelectAll)
    (when (axlGetSelSet) (unless (axlDeleteObject (axlGetSelSet)) (error "EdaKit: template cleanup failed")))
    (axlClearSelSet)
    (axlAddSelectAll)
    (when (or (axlGetSelSet) (axlDBGetDesign)->pins) (error "EdaKit: template still contains figures"))
    (axlClearSelSet)
    (setq edakitFile (outfile "{diagnostic}"))
    (fprintf edakitFile "%L\\n" (axlGetParam "paramDesign")->??)
    (close edakitFile)
    (load "{manual}")
    (setq edakitFile (outfile "{report}"))
    (unless edakitFile (error "EdaKit: cannot write native pin report"))
    (foreach edakitPin (axlDBGetDesign)->pins
      (when (and edakitPin->number (not (equal edakitPin->number "")))
        (fprintf edakitFile "%s|%.4f|%.4f\\n" edakitPin->number (xCoord edakitPin->xy) (yCoord edakitPin->xy))))
    (close edakitFile)
    (setq edakitFile (outfile "{mechanics}"))
    (foreach edakitPin (axlDBGetDesign)->pins
      (unless (and edakitPin->number (not (equal edakitPin->number "")))
        (fprintf edakitFile "%.4f|%.4f\\n" (xCoord edakitPin->xy) (yCoord edakitPin->xy))))
    (close edakitFile)
    (setq edakitFile (outfile "{padreport}"))
    (foreach edakitPad (axlDBGetDesign)->padstacks
      (fprintf edakitFile "%s|%.4f|%.4f|%.4f|%.4f|%L\\n" edakitPad->name
        (max edakitPad->drillDiameter edakitPad->drillSizeWidth)
        (max edakitPad->drillDiameter edakitPad->drillSizeHeight)
        (xCoord (or edakitPad->drillOffset 0:0)) (yCoord (or edakitPad->drillOffset 0:0)) edakitPad->plating))
    (close edakitFile)
    (setq edakitFile (outfile "{success}"))
    (fprintf edakitFile "COMPILED\\n")
    (close edakitFile)
    t
  ) t))
  (unless edakitResult (printf "EdaKit: automatic build failed; see allegro.log\\n"))
  (drain errport)
  (close errport)
)
'''


def validate_outputs(component, result):
    folder = Path(result['directory'])
    if not (folder / 'native-success.txt').is_file():
        raise RuntimeError('Allegro 未完成原生构建，请查看构建日志')
    outputs = {p.name.lower(): p for p in folder.iterdir() if p.is_file()}
    for ext in ('.dra', '.psm'):
        target = outputs.get((result['footprint'] + ext).lower())
        if target is None or target.stat().st_size == 0:
            raise RuntimeError('缺少有效的原生输出：' + ext)
    actual = {}
    for line in (folder / 'native-pins.txt').read_text(encoding='utf-8').splitlines():
        number, x, y = line.split('|')
        if number in actual:
            raise RuntimeError('原生封装引脚编号重复：' + number)
        actual[number] = (float(x), float(y))
    expected = {ps.name: (ps.x_mm, ps.y_mm) for ps in component.footprint.padstacks if not ps.mechanical}
    if actual.keys() != expected.keys():
        raise RuntimeError('原生封装引脚编号与输入不一致')
    for number, xy in expected.items():
        if any(abs(a-b) > .0002 for a, b in zip(actual[number], xy)):
            raise RuntimeError('原生封装引脚坐标不一致：' + number)
    # Padstack filenames are emitted explicitly by the calibrated generator.
    import re
    script = (folder / 'manual_build.il').read_text(encoding='utf-8')
    padnames = set(re.findall(r'EK_[a-f0-9]{20}\.pad', script))
    if not padnames or any(n.lower() not in outputs or outputs[n.lower()].stat().st_size == 0 for n in padnames):
        raise RuntimeError('原生 padstack 输出缺失')
    from .identity import pad_name
    if any(p.drill_mm for p in component.footprint.padstacks):
        readback = {}
        for line in (folder / 'native-padstacks.txt').read_text().splitlines():
            name,w,h,x,y,plating = line.split('|')
            readback[name.lower()] = (float(w),float(h),float(x),float(y),plating.strip('"'))
        for p in component.footprint.padstacks:
            if not p.drill_mm:
                continue
            native = readback.get(pad_name(p).lower())
            expected_drill = (p.slot_width_mm or p.drill_mm,p.slot_height_mm or p.drill_mm,
                              p.drill_offset_x_mm,p.drill_offset_y_mm)
            if native is None or any(abs(a-b) > .0002 for a,b in zip(native[:4],expected_drill)) or native[4].upper().replace('-','_') != ('PLATED' if p.hole_plated else 'NON_PLATED'):
                raise RuntimeError('原生钻孔尺寸、方向、偏移或镀孔属性不一致：' + p.name)
    expected_holes = sorted((p.x_mm,p.y_mm) for p in component.footprint.padstacks if p.mechanical)
    if expected_holes:
        actual_holes = sorted(tuple(map(float,line.split('|'))) for line in
            (folder / 'native-mechanical.txt').read_text().splitlines())
        if len(expected_holes) != len(actual_holes) or any(abs(a-b) > .0002
                for x,y in zip(expected_holes, actual_holes) for a,b in zip(x,y)):
            raise RuntimeError('原生机械孔数量或坐标不一致')
    dependencies = []
    for name in result.get('shapeSymbols', []):
        for ext in ('.dra', '.ssm'):
            target = outputs.get((name+ext).lower())
            if target is None or target.stat().st_size == 0:
                raise RuntimeError('自定义焊盘形状文件缺失：' + name+ext)
            dependencies.append(target)
    return [outputs[(result['footprint'] + ext).lower()] for ext in ('.dra', '.psm')] + [outputs[n.lower()] for n in sorted(padnames)] + dependencies


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish(component, result, files, library):
    library = Path(library)
    index_path = library / 'edakit-library.json'
    lock_path = library / '.edakit-publish.lock'
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('封装库正在发布，稍后重试') from None
    created = []
    try:
        index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {'version': 1, 'files': {}, 'packages': {}}
        identity = library_names(component)
        previous = index['packages'].get(result['footprint'])
        if previous and previous.get('geometryDigest') != identity['geometryDigest']:
            raise RuntimeError('同名封装的完整几何摘要冲突，保留原文件')
        planned = []
        for source in files:
            target = library / source.name.lower()
            digest = file_hash(source)
            if target.exists():
                existing = file_hash(target)
                if existing != digest and index['files'].get(target.name) != existing:
                    raise RuntimeError('同名库文件内容冲突，保留原文件：' + str(target))
                # A tracked, unmodified binary can contain a different build
                # timestamp. The filename encodes its geometry identity.
                digest = existing
            planned.append((source, target, digest))
        for source, target, digest in planned:
            if not target.exists():
                with target.open('xb') as stream:
                    stream.write(source.read_bytes())
                created.append((target, digest))
            index['files'][target.name] = digest
        index['packages'][result['footprint']] = {**identity, 'cid': component.cid,
            'sourceFootprint': component.footprint.name, 'status': 'compiled',
            'pinCount': sum(not p.mechanical for p in component.footprint.padstacks),
            'mechanicalCount': sum(p.mechanical for p in component.footprint.padstacks),
            'files': {target.name: digest for _, target, digest in planned}}
        atomic_write(index_path, json.dumps(index, ensure_ascii=False, indent=2))
    except BaseException:
        for target, digest in created:
            if target.exists() and file_hash(target) == digest:
                target.unlink()
        raise
    finally:
        os.close(descriptor)
        lock_path.unlink()


def run_owned(args, folder, environment, options, log_name, stopping, timeout, launch):
    if stopping is not None and stopping.is_set():
        raise RuntimeError('Allegro 构建已取消')
    with (folder / log_name).open('wb') as log:
        process = launch(args, cwd=folder, env=environment, stdout=log, stderr=subprocess.STDOUT, **options)
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if (stopping is not None and stopping.is_set()) or time.monotonic() > deadline:
                    raise RuntimeError('Allegro 构建已取消或超时；请确认许可证和安装配置。日志目录：' + str(folder))
                time.sleep(.2)
            if process.returncode:
                raise RuntimeError('Allegro 构建失败；日志：' + str(folder / log_name))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def upgraded_template(template, root, library, folder, environment, options, stopping, timeout, launch):
    """Reuse an upgraded private vendor template, checked against tool and file identity."""
    doctor = root / 'tools/bin/dbdoctor.exe'
    stamp = doctor.stat()
    key = hashlib.sha256(json.dumps([str(root.resolve()), file_hash(template),
                                    stamp.st_size, stamp.st_mtime_ns]).encode()).hexdigest()
    cache = Path(library) / '.edakit-cache' / 'native-template' / key
    seed = cache / 'seed.dra'
    receipt = cache / 'seed.json'
    try:
        if json.loads(receipt.read_text())['sha256'] == file_hash(seed):
            return seed, True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    temporary = folder / 'template.dra'
    shutil.copy2(template, temporary)
    run_owned([str(doctor), '-no_dbcheck', '-no_backup', str(temporary)],
              folder, environment, options, 'upgrade.log', stopping, min(timeout, 60), launch)
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise RuntimeError('Cadence 模板升级未产生有效文件')
    cache.mkdir(parents=True, exist_ok=True)
    pending = cache / (uuid.uuid4().hex + '.tmp')
    try:
        shutil.copy2(temporary, pending)
        os.replace(pending, seed)
        atomic_write(receipt, json.dumps({'sha256': file_hash(seed)}))
    finally:
        pending.unlink(missing_ok=True)
    return seed, False


def build_footprint(component, config, *, stopping=None, timeout=150, launch=subprocess.Popen, progress=None):
    started = time.perf_counter()
    def phase(message):
        if progress:
            progress(message)
    phase('正在校验封装库，查找可复用封装')
    if not config.footprint_lib or not Path(config.footprint_lib).is_absolute():
        raise ValueError('请先在库设置中指定完整的 PCB 封装库目录')
    if component.symbol is None or component.footprint is None:
        raise ValueError('缺少原理图符号或 PCB 封装，无法校验引脚配对')
    validate_pin_mapping(component.symbol, component.footprint)
    cached = compiled_result(component, config.footprint_lib)
    if cached is not None:
        cached['elapsedSeconds'] = round(time.perf_counter() - started, 3)
        return cached
    root = cadence_install(config)
    template = root / 'share/pcb/examples/board_design/symbols/smdres.dra'
    if not template.is_file():
        raise ValueError('Cadence 安装缺少 package symbol 模板 smdres.dra')
    result = prepare_footprint(component, config.footprint_lib)
    folder = Path(result['directory'])
    atomic_write(folder / 'automatic.il', automation_script(result))
    atomic_write(folder / 'automatic.scr', 'skill load("' + skill_path(folder / 'automatic.il') + '")\nexit\nfillin no\n')
    environment = os.environ.copy()
    environment['PATH'] = str(root / 'tools/bin') + os.pathsep + environment.get('PATH', '')
    for variable in ('CDSROOT', 'CDS_INST_DIR', 'PCB_INST_DIR'):
        environment[variable] = str(root)
    # Use the user's actual license/product setup, isolated from open designs.
    args = [str(root / 'tools/bin/allegro.exe'), '-nograph', '-safe', '-noopengl',
            '-product', 'Allegro_performance', '-p', str(folder),
            '-s', str(folder / 'automatic.scr'), result['drawing']]
    options = {}
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        options['startupinfo'] = startup
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    phase('正在准备 Cadence 后台编译环境')
    seed, template_reused = upgraded_template(template, root, config.footprint_lib, folder,
        environment, options, stopping, timeout, launch)
    shutil.copy2(seed, result['drawing'])
    for name in result.get('shapeSymbols', []):
        shutil.copy2(seed, folder / (name+'.dra'))
    phase('正在后台编译焊盘和 PCB 封装')
    run_owned(args, folder, environment, options, 'process.log', stopping, timeout, launch)
    try:
        phase('正在核对原生引脚并保存封装库')
        files = validate_outputs(component, result)
        publish(component, result, files, config.footprint_lib)
    except Exception as error:
        raise RuntimeError(str(error) + '；日志目录：' + str(folder)) from error
    notes = manufacturing_notes(component)
    result.update(status='compiled', nativeBuildVerified=True, directory=config.footprint_lib,
                  drawing=str(Path(config.footprint_lib) / (result['footprint'].lower() + '.dra')),
                  command='', message='PCB 封装已自动生成并保存到封装库' + ('；' + ' '.join(notes) if notes else ''),
                  warnings=notes, logDirectory=str(folder),
                  backend='allegro-nograph', templateReused=template_reused,
                  elapsedSeconds=round(time.perf_counter() - started, 3))
    return result


def compiled_result(component, library):
    folder = Path(library)
    path = folder / 'edakit-library.json'
    identity = library_names(component)
    try:
        record = json.loads(path.read_text(encoding='utf-8'))['packages'][identity['footprint']]
        if record['geometryDigest'] != identity['geometryDigest'] or record['status'] != 'compiled':
            return None
        files = record['files']
        required = {identity['footprint'].lower() + ext for ext in ('.dra', '.psm')}
        if (record.get('pinCount') != sum(not p.mechanical for p in component.footprint.padstacks)
                or record.get('mechanicalCount', 0) != sum(p.mechanical for p in component.footprint.padstacks)
                or record.get('namingVersion') != identity['namingVersion']
                or not required.issubset(files) or not any(name.endswith('.pad') for name in files)
                or any(Path(name).name != name or file_hash(folder / name) != digest for name, digest in files.items())):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    notes = manufacturing_notes(component)
    return {'status': 'compiled', 'nativeBuildVerified': True, 'reused': True,
            'directory': str(folder), 'footprint': identity['footprint'],
            'drawing': str(folder / (identity['footprint'].lower() + '.dra')),
            'command': '', 'message': '已复用封装库中校验通过的原生文件' + ('；' + ' '.join(notes) if notes else ''),
            'warnings': notes}


class FootprintJobs:
    def __init__(self, builder=build_footprint):
        self.builder = builder
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.jobs = {}
        self.worker = None

    def submit(self, component, config):
        import uuid
        with self.lock:
            if self.stop.is_set():
                raise ValueError('服务正在关闭')
            if self.worker is not None and self.worker.is_alive():
                raise ValueError('已有封装正在构建，请等待完成')
            while len(self.jobs) >= 64:
                del self.jobs[next(iter(self.jobs))]
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {'job': job_id, 'status': 'building', 'cid': component.cid}
            self.worker = threading.Thread(target=self._run, args=(job_id, component, config), daemon=True)
            self.worker.start()
            return dict(self.jobs[job_id])

    def _run(self, job_id, component, config):
        def progress(message):
            with self.lock:
                self.jobs[job_id]['message'] = message
        try:
            result = self.builder(component, config, stopping=self.stop, progress=progress)
        except Exception as error:
            result = {'status': 'failed', 'message': str(error)}
        with self.lock:
            self.jobs[job_id].update(result)

    def status(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError('构建任务不存在，请重新生成')
            return dict(self.jobs[job_id])

    def close(self):
        self.stop.set()
        if self.worker is not None:
            self.worker.join(timeout=7)
