"""One model-to-package transform for native STEP mapping and the OBJ preview.

The package parser retains source XY coordinates. Its SVGNODE outline is the
placement authority; c_origin can be stale (notably C23630). Rotate local model
axes, centre the rotated XY bounds on that outline, and place the lowest point
at SVGNODE z. Negative z is retained for through-board leads and recessed parts.
No scale or guessed pin renumbering is applied.
"""
import hashlib
import json
import math
from pathlib import Path
import re
from functools import lru_cache

from ..storage import atomic_write
from .preview import parse_obj
from .step import StepFetcher

ASSEMBLY_VERSION = 2


def identity(model):
    if model is None:
        return None
    return {'version': ASSEMBLY_VERSION, 'uuid': model.uuid,
            'rotation': model.rotation_deg, 'origin': model.origin_mm,
            'outline': model.outline_center_mm, 'z': model.z_mm}


def rotate(point, angles):
    x, y, z = point
    a, b, c = (math.radians(v) for v in angles)
    y, z = y*math.cos(a)-z*math.sin(a), y*math.sin(a)+z*math.cos(a)
    x, z = x*math.cos(b)+z*math.sin(b), -x*math.sin(b)+z*math.cos(b)
    return (x*math.cos(c)-y*math.sin(c), x*math.sin(c)+y*math.cos(c), z)


def placement(model, obj_data):
    values = (*model.origin_mm, model.z_mm, *model.rotation_deg,
              *(model.outline_center_mm or ()))
    if not all(math.isfinite(v) for v in values):
        raise ValueError('3D 模型位置或旋转参数无效')
    angles = tuple(round(v % 360, 6) for v in model.rotation_deg)
    centre = model.outline_center_mm or model.origin_mm
    return _placement(angles, (centre[0], -centre[1]), model.z_mm, obj_data)


@lru_cache(maxsize=8)
def _placement(angles, centre, z_mm, obj_data):
    points = [rotate(p, angles) for p in parse_obj(obj_data).vertices]
    bounds = [(min(p[i] for p in points), max(p[i] for p in points)) for i in range(3)]
    offset = (centre[0]-sum(bounds[0])/2, centre[1]-sum(bounds[1])/2,
              z_mm-bounds[2][0])
    return angles, tuple(round(v, 6) for v in offset)


def valid_step(data):
    stripped = data.strip()
    if (len(data) > 80_000_000 or not stripped.startswith(b'ISO-10303-21;')
            or not stripped.endswith(b'END-ISO-10303-21;')
            or b'DATA;' not in data or b'FILE_SCHEMA' not in data):
        raise ValueError('下载结果不是有效的 STEP 模型，未保存或绑定')
    return data


def prepare_model(component, step_library):
    model = component.model3d
    if model is None:
        return None
    if not re.fullmatch(r'[a-fA-F0-9]{32}', model.uuid):
        raise ValueError('3D 模型 UUID 无效')
    folder = Path(step_library)
    if not folder.is_absolute():
        raise ValueError('请在库设置中指定完整的 STP 库目录')
    folder.mkdir(parents=True, exist_ok=True)
    name = 'ek3d_' + model.uuid.lower() + '.stp'
    path = folder / name
    receipt = folder / (name + '.json')
    obj_path = folder / (name + '.obj')
    fetcher = StepFetcher()
    # Never replace an untracked or edited user's model with the same name.
    if path.exists():
        try:
            saved = json.loads(receipt.read_text(encoding='utf-8'))
            raw = path.read_bytes()
            if saved['sha256'] != hashlib.sha256(raw).hexdigest():
                raise ValueError('STP 库同名模型已被修改，请保留文件并检查：' + str(path))
            valid_step(raw)
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError('STP 库同名模型缺少有效校验记录：' + str(path)) from error
    else:
        raw = valid_step(fetcher.download_step_bytes(model.uuid))
        # Exclusive creation avoids overwriting a concurrent download.
        with path.open('xb') as stream:
            stream.write(raw)
        saved = {'uuid': model.uuid, 'sha256': hashlib.sha256(raw).hexdigest()}
        atomic_write(receipt, json.dumps(saved, indent=2))
    try:
        data = obj_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != saved.get('objSha256'):
            raise ValueError('refresh OBJ')
        parse_obj(data)
    except (OSError, ValueError):
        from ..services.preview import model_bytes
        data = model_bytes(model.uuid)
        parse_obj(data)
        atomic_write(obj_path, data)
        saved['objSha256'] = hashlib.sha256(data).hexdigest()
        atomic_write(receipt, json.dumps(saved, indent=2))
    angles, offset = placement(model, data)
    return {'version': ASSEMBLY_VERSION, 'file': name, 'path': str(path),
            'sha256': saved['sha256'], 'rotation': angles, 'offset': offset,
            'source': identity(model)}


def binding_skill(binding, report):
    """17.2 S079 consumes STEP offsets in mils even in an mm drawing.

    Set explicit mil units for the call, then restore mm before readback/save.
    This avoids the observed 0.0254 scaling bug after changing template units.
    """
    from ..footprint.native import skill_path
    rx, ry, rz = binding['rotation']
    ox, oy, oz = (v / .0254 for v in binding['offset'])
    return f'''    (axlSetVariable "steppath" '("{skill_path(Path(binding['path']).parent)}" "."))
    (unless (axlDBChangeDesignUnits "mils" 4) (error "EdaKit: STEP units failed"))
    (unless (axlStepSet 'primary nil "{binding['file']}"
      '(rotation_x {rx:.6f} rotation_y {ry:.6f} rotation_z {rz:.6f}
        offset_x {ox:.6f} offset_y {oy:.6f} offset_z {oz:.6f}))
      (error "EdaKit: STEP binding failed"))
    (unless (axlDBChangeDesignUnits "millimeters" 4) (error "EdaKit: restore units failed"))
    (let ((mapping (axlStepGet nil 'primary nil)) (port (outfile "{skill_path(report)}")))
      (unless mapping (error "EdaKit: STEP readback failed"))
      (fprintf port "%s|%.6f|%.6f|%.6f|%.6f|%.6f|%.6f\\n" mapping->step_name
        mapping->rotation_x mapping->rotation_y mapping->rotation_z
        mapping->offset_x mapping->offset_y mapping->offset_z)
      (close port))
'''


def validate_binding(binding, report):
    values = Path(report).read_text().strip().split('|')
    if (len(values) != 7 or Path(values[0]).name.lower() != binding['file'].lower()
            or any(not math.isfinite(float(a)) or abs(float(a)-b) > .0002
                   for a,b in zip(values[1:], (*binding['rotation'], *binding['offset'])))):
        raise RuntimeError('原生 3D 模型或旋转、偏移与预览不一致')
