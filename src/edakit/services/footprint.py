"""Prepare isolated native package builds from the workbench."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import uuid

from ..library import library_names
from ..footprint.skill import generate_skill
from ..footprint.validation import validate_pin_mapping
from ..storage import atomic_write


def prepare_footprint(component, library):
    if component.footprint is None:
        raise ValueError('该器件没有 PCB 封装数据')
    report = validate_pin_mapping(component.symbol, component.footprint) if component.symbol else None
    if report is None:
        raise ValueError('缺少原理图符号，无法校验引脚配对')
    fp = deepcopy(component.footprint)
    source = fp.name
    names = library_names(component)
    fp.name = names['footprint']
    folder = Path(library) / '.edakit-builds' / component.cid / (
        datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    script = generate_skill(fp, output_dir=folder,
                           refdes_prefix=component.symbol.prefix, manual=True)
    folder.mkdir(parents=True, exist_ok=False)
    from ..footprint.shapes import shape_scripts
    shapes = shape_scripts(fp, folder)
    for name, content in shapes.items():
        atomic_write(folder / (name + '.il'), content)
    script_path = folder / 'manual_build.il'
    atomic_write(script_path, script)
    report.update(source_footprint_name=source, footprint_name=fp.name, **names,
                  status='candidate', native_build_verified=False)
    atomic_write(folder / 'pinmap.json', json.dumps(report, ensure_ascii=False, indent=2))
    drawing = (folder / (fp.name + '.dra')).as_posix()
    command = 'skill load("' + script_path.as_posix() + '")'
    message = ('PCB Footprint: ' + fp.name + '\n'
               'File > New > Package symbol\nDrawing Name: ' + drawing + '\n\n' + command)
    atomic_write(folder / 'BUILD.txt', 'EdaKit isolated build diagnostics.\n'
                 'Use the workbench Generate PCB Footprint button for automatic compilation.\n'
                 'Footprint: ' + fp.name + '\n')
    return {'status': 'candidate', 'footprint': fp.name, 'directory': str(folder),
            'drawing': drawing, 'command': command, 'message': message,
            'nativeBuildVerified': False, 'shapeSymbols': sorted(shapes)}
