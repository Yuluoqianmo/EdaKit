"""STEP / OBJ 下载。

EasyEDA 只提供 OBJ 与 STEP，不提供 .wrl；.wrl 要本地由 OBJ 转 (VRML2, mm→inch)。
本工具默认用 STEP (3D Canvas 直接吃)。
"""

from __future__ import annotations

from pathlib import Path

import requests

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
            r = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise FetchError(f"下载 3D 模型失败: {e}") from e
        if r.status_code != 200:
            raise FetchError(f"下载 3D 模型 HTTP {r.status_code}: {url}")
        return r.content

    def download_step(self, uuid: str, out_path: str | Path) -> Path:
        data = self.download_step_bytes(uuid)
        Path(out_path).write_bytes(data)
        return Path(out_path)

    def download_step_bytes(self, uuid: str) -> bytes:
        return self._get(STEP_URL.format(uuid=uuid))

    def download_obj(self, uuid: str, out_path: str | Path) -> Path:
        data = self._get(OBJ_URL.format(uuid=uuid))
        Path(out_path).write_bytes(data)
        return Path(out_path)

    def download_obj_bytes(self, uuid: str) -> bytes:
        """下载 OBJ 到内存 (给预览代理用)。"""
        return self._get(OBJ_URL.format(uuid=uuid))
