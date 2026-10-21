"""Versioned application settings; library paths are preserved during migration."""
import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from .storage import atomic_write

APP_DIR_NAME = "edakit"


def app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# 配置 (Python 侧用 JSON，TCL 侧只读少数几个键)
# --------------------------------------------------------------------------- #
@dataclass
class Config:
    """用户配置。"""

    footprint_lib: str = ""      # 全局封装库目录 (.dra/.psm/.pad/.step)
    symbol_lib: str = ""         # Explicit Capture library directory; empty preserves legacy project_olb.
    project_olb: str = ""        # Capture 累积工程库
    cadence_root: str = ""       # SPB 安装根，留空自动探测
    calib: str = "easyeda2kicad"  # 3D 校准口径
    schema_profile: str = ""     # Capture 库 XML schema profile
    auto_config_allegro: bool = True
    switch_to_capture: bool = True   # 双击后最小化商城浏览器、OrCAD 切到前台
    place_mode: str = "cursor"    # cursor = PlacePartEx; slot = direct PlacePart
    place_x_mil: float = 500.0
    place_y_mil: float = 500.0
    port: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
    config_version: int = 1

    @classmethod
    def load(cls) -> "Config":
        path = app_dir() / "config.json"
        # Migrate settings, preserving absolute library paths. Never replay
        # legacy queue requests or reuse a stale server/heartbeat marker.
        if not path.exists():
            legacy = path.parent.parent / "lcsc2cadence" / "config.json"
            if legacy.is_file():
                try:
                    data = json.loads(legacy.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        cfg = cls.from_dict(data)
                        cfg.save()
                        return cfg
                except (OSError, ValueError, TypeError):
                    pass
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return cls.from_dict(data)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError("Invalid configuration file; preserve it for repair") from exc
        cfg = cls()
        cfg.footprint_lib = str(app_dir() / "footprint_lib")
        cfg.project_olb = str(app_dir() / "project.olb")
        return cfg

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Configuration must be an object")
        data = dict(data)
        version = data.get("config_version", 1)
        if type(version) is not int or version != 1:
            raise ValueError("Unsupported configuration version")
        known = set(cls.__dataclass_fields__)
        unknown = {k: v for k, v in data.items() if k not in known}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.validate()
        cfg.extra = dict(cfg.extra)
        if unknown:
            if not isinstance(cfg.extra.get("unknown_fields", {}), dict):
                raise ValueError("Invalid unknown configuration fields")
            cfg.extra.setdefault("unknown_fields", {}).update(unknown)
        return cfg

    def validate(self):
        for name in ("footprint_lib", "symbol_lib", "project_olb", "cadence_root", "calib", "schema_profile", "place_mode"):
            if not isinstance(getattr(self, name), str):
                raise ValueError("Invalid configuration field: " + name)
        for name in ("auto_config_allegro", "switch_to_capture"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("Invalid configuration field: " + name)
        if self.place_mode not in ("cursor", "slot"):
            raise ValueError("Invalid placement mode")
        if type(self.port) is not int or not 0 <= self.port <= 65535:
            raise ValueError("Invalid port")
        for value in (self.place_x_mil, self.place_y_mil):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid placement coordinates")
        if not isinstance(self.extra, dict):
            raise ValueError("Invalid extra configuration")
        if type(self.config_version) is not int or self.config_version != 1:
            raise ValueError("Unsupported configuration version")

    def save(self) -> None:
        self.validate()
        atomic_write(app_dir() / "config.json", json.dumps(asdict(self), ensure_ascii=False, indent=2))

    def ensure_dirs(self) -> None:
        if self.symbol_lib:
            Path(self.symbol_lib).mkdir(parents=True, exist_ok=True)
            self.project_olb = str(Path(self.symbol_lib) / 'EdaKit.olb')
        if self.footprint_lib:
            Path(self.footprint_lib).mkdir(parents=True, exist_ok=True)
        if self.project_olb:
            Path(self.project_olb).parent.mkdir(parents=True, exist_ok=True)
        (app_dir() / "queue").mkdir(parents=True, exist_ok=True)


