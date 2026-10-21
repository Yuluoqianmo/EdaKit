"""取数层。

EasyEDA 免鉴权端点 (非官方支持路径，随时可能变；专业版 API 已要求鉴权就是信号)。
所有端点仅带 UA/Referer 即可。
"""

from __future__ import annotations

from typing import Any

import requests

from .errors import FetchError, UpstreamChangedError

COMPONENT_URL = "https://easyeda.com/api/products/{cid}/components"
SVG_URL = "https://easyeda.com/api/products/{cid}/svgs"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) edakit"


class Fetcher:
    def __init__(self, timeout: float = 30.0, retries: int = 3) -> None:
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Referer": "https://easyeda.com/"})

    def _get_json(self, url: str) -> dict[str, Any]:
        last: Exception | None = None
        for _ in range(self.retries):
            try:
                r = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                last = e
                continue
            if r.status_code != 200:
                last = FetchError(f"HTTP {r.status_code}: {url}")
                continue
            try:
                return r.json()
            except ValueError as e:
                raise UpstreamChangedError(
                    f"上游返回非 JSON，可能端点已变更: {url}"
                ) from e
        raise FetchError(f"取数失败 (已重试 {self.retries} 次): {last}")

    def get_component(self, cid: str) -> dict[str, Any]:
        """拉元件数据, 返回 result 字段 (已剥外层)。"""
        cid = cid.strip().upper()
        if not cid.startswith("C"):
            cid = "C" + cid
        payload = self._get_json(COMPONENT_URL.format(cid=cid))
        if not payload.get("success"):
            raise UpstreamChangedError(
                f"元件 {cid} 取数失败: success={payload.get('success')} "
                f"code={payload.get('code')} msg={payload.get('message')}"
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise UpstreamChangedError(f"响应缺少 result 对象: {cid}")
        return result

    def get_preview_svg(self, cid: str) -> str:
        payload = self._get_json(SVG_URL.format(cid=cid.strip().upper()))
        return payload.get("result", "") or ""
