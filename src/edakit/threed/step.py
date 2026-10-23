"""STEP / OBJ 下载。

EasyEDA 只提供 OBJ 与 STEP，不提供 .wrl；.wrl 要本地由 OBJ 转 (VRML2, mm→inch)。
本工具默认用 STEP (3D Canvas 直接吃)。
"""

from __future__ import annotations

from pathlib import Path

import re
import requests
from ..storage import atomic_write

from ..errors import FetchError

STEP_URL = "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{uuid}"
OBJ_URL = "https://modules.easyeda.com/3dmodel/{uuid}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) edakit"


class StepFetcher:
    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Referer": "https://easyeda.com/"})

    def _get(self, url: str) -> bytes:
        try:
            with self.session.get(url, timeout=self.timeout, stream=True) as response:
                if response.status_code != 200:
                    raise FetchError(f"下载 3D 模型 HTTP {response.status_code}: {url}")
                data = bytearray()
                for chunk in response.iter_content(65536):
                    if len(data) + len(chunk) > 50_000_000:
                        raise FetchError("3D model exceeds 50 MB")
                    data.extend(chunk)
                return bytes(data)
        except requests.RequestException as error:
            raise FetchError(f"下载 3D 模型失败: {error}") from error

    def download_step(self, uuid: str, out_path: str | Path) -> Path:
        data = self.download_step_bytes(uuid)
        atomic_write(Path(out_path), data)
        return Path(out_path)

    def download_step_bytes(self, uuid: str) -> bytes:
        data = self._get(STEP_URL.format(uuid=validate_model_id(uuid)))
        if not data.lstrip().startswith(b"ISO-10303-21;") or not data.rstrip().endswith(b"END-ISO-10303-21;"):
            raise FetchError("Downloaded STEP is invalid or incomplete")
        return data

    def download_obj(self, uuid: str, out_path: str | Path) -> Path:
        data = self._get(OBJ_URL.format(uuid=validate_model_id(uuid)))
        atomic_write(Path(out_path), data)
        return Path(out_path)

    def download_obj_bytes(self, uuid: str) -> bytes:
        """下载 OBJ 到内存 (给预览代理用)。"""
        return self._get(OBJ_URL.format(uuid=validate_model_id(uuid)))


def validate_model_id(value):
    value = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid model identifier")
    return value
