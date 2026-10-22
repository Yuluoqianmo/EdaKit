"""Workbench library settings, preserving unrelated options."""
from pathlib import Path
import threading

from ..config import Config
from ..install import allegro_env

SETTINGS_LOCK = threading.RLock()


def read_settings():
    cfg = Config.load()
    detected = cfg.cadence_root
    if not detected:
        from ..install.deploy import find_capture_tcl_root, spb_root_from_tcl
        from ..errors import DeployError
        try:
            root = spb_root_from_tcl(find_capture_tcl_root())
            if root and (root / 'tools/bin/allegro.exe').is_file():
                detected = str(root)
        except (DeployError, OSError):
            pass
    return {'symbol_lib': cfg.symbol_lib or str(Path(cfg.project_olb).parent),
            'footprint_lib': cfg.footprint_lib, 'step_lib': cfg.effective_step_lib, 'cadence_root': detected,
            'cadence_detected': bool(detected and (Path(detected) / 'tools/bin/allegro.exe').is_file())}


def save_settings(values):
    with SETTINGS_LOCK:
        cfg = Config.load()
        for key in ('symbol_lib', 'footprint_lib', 'step_lib', 'cadence_root'):
            value = str(values.get(key, cfg.effective_step_lib if key == 'step_lib' else '')).strip().strip('"')
            if not value and key == 'cadence_root':
                cfg.cadence_root = ''
                continue
            path = Path(value)
            if not value or not path.is_absolute() or any(c in value for c in '\r\n\x00'):
                raise ValueError('请输入完整的绝对目录路径：' + key)
            if path.exists() and not path.is_dir():
                raise ValueError('路径必须是目录：' + value)
            if key == 'cadence_root' and not (path / 'tools/bin/allegro.exe').is_file():
                raise ValueError('该 Cadence 安装目录下没有 tools/bin/allegro.exe')
            if key in ('footprint_lib', 'step_lib'):
                allegro_env.build_block(value)
            setattr(cfg, key, str(path.resolve()))
        cfg.project_olb = str(Path(cfg.symbol_lib) / 'EdaKit.olb')
        cfg.ensure_dirs()
        # Only update the marked user block; retain all other library paths.
        env_path = ''
        if cfg.auto_config_allegro:
            env_path = str(allegro_env.configure(cfg.footprint_lib, step_dir=cfg.effective_step_lib, cadence_root=cfg.cadence_root or None))
        cfg.save()
        from ..install import capture_ini
        message, capture_path = '库路径已保存', ''
        try:
            capture_path = str(capture_ini.configure(cfg.footprint_lib, cadence_root=cfg.cadence_root) or '')
        except (OSError, ValueError) as error:
            message += '；Capture 封装查看路径同步失败：' + str(error)
        return {**read_settings(), 'message': message, 'allegro_env': env_path, 'capture_ini': capture_path}
