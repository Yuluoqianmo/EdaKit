"""本地 HTTP 服务 —— 给商城网页界面提供 JSON API。

用标准库 http.server，零额外依赖，方便 PyInstaller 打包。

端点:
    GET  /                            商城页面
    GET  /static/<file>               前端静态资源
    GET  /api/search?q=&page=&size=   关键词搜索
    GET  /api/browse?cat=&page=&size= 分类浏览
    GET  /api/categories              分类树 (缓存)
    GET  /api/part/<cid>              元件详情 (含预览图 URL)
    GET  /api/svg/symbol/<cid>.svg    符号预览 (自己渲染)
    GET  /api/svg/footprint/<cid>.svg 封装预览 (自己渲染)
    GET  /api/obj/<uuid>              3D OBJ 代理
    POST /api/place                   {cid} → 加入放置队列
    GET  /api/place/status?seq=       查放置结果
    GET  /api/config                  读配置
    POST /api/config                  写配置
    GET  /api/status                  Capture 是否在线
"""

from __future__ import annotations

import json
import uuid
import logging
import os
import socket
import threading
import time
import hashlib
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..bridge.queue import capture_alive, read_response
from ..catalog.facets import clean_params
from ..catalog.glossary import display_params
from ..catalog import MallClient
from ..easyeda.parse import parse_component
from ..errors import FetchError, LcscError, ParseError, UpstreamChangedError
from ..fetch import Fetcher
from ..pipeline import stage_component
from ..services.catalog import CatalogService
from ..services.component import ComponentService
from ..services.preview import PreviewService, PreviewMissing, model_bytes as _model_bytes
from ..services.placement import PlacementService, PreparationOptions, boolean
from ..bridge.sessions import live_sessions
from ..services.tasks import TaskCoordinator, TaskUnavailable, Superseded
from ..config import Config


WEB_DIR = Path(__file__).parent / "web"

class ApplicationServices:
    def __init__(self):
        self.catalog = CatalogService(lambda: MallClient(), _part_dict)
        self.components = ComponentService(lambda: Fetcher(), parse_component)
        self.tasks = TaskCoordinator()
        self.preview = PreviewService()
        self.placement = PlacementService(lambda *a, **kw: stage_component(*a, **kw))
        from ..footprint.native import FootprintJobs
        self.footprints = FootprintJobs()


class MallHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)
        self.request_id = uuid.uuid4().hex
        self.started_at = time.perf_counter()

    server_version = "edakit"

    # ---- 基础 ---- #
    def log_message(self, fmt: str, *args: Any) -> None:  # 安静点
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str, *, cache: bool = False) -> None:
        try:
            etag = '"' + hashlib.sha256(body).hexdigest() + '"' if cache else None
            if etag and self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
                self.end_headers()
                return
            self.send_response(code)
            self.send_header("X-Request-ID", self.request_id)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=0, must-revalidate" if cache else "no-store")
            if etag:
                self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _jsonp(self, qs: dict[str, list[str]], obj: Any) -> bool:
        """Return JSONP for the legacy viewer; CEF requests plain JSON."""
        cb = (qs.get("cb") or [""])[0].strip()
        if not cb:
            return False
        body = "/*lcsc*/" + cb + "(" + json.dumps(obj, ensure_ascii=False) + ");"
        self._send(200, body.encode("utf-8"), "application/javascript; charset=utf-8")
        return True

    def _error(self, exc: Exception, code: int = 500) -> None:
        error_code = "upstream_failed" if code == 502 else "invalid_request" if code == 400 else "service_busy" if code == 503 else "internal_error"
        logging.getLogger(__name__).warning("http request_id=%s status=%s path=%s error=%s", self.request_id, code, urlparse(self.path).path, str(exc), exc_info=code == 500)
        obj = {"error": type(exc).__name__, "errorCode": error_code, "message": str(exc), "requestId": self.request_id}
        qs = parse_qs(urlparse(self.path).query)
        if not self._jsonp(qs, obj):
            self._json(obj, code)

    def _read_body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > 1_048_576:
            raise ValueError("Request body size is invalid")
        if n == 0:
            return {}
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            return body
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid JSON request") from exc

    # ---- 缓存 ---- #
    def _component(self, cid: str) -> Any:
        return self.server.services.components.get(cid)


    def _capture_online(self, qs):
        session = (qs.get("session") or [""])[0]
        return session in live_sessions() if session else capture_alive()

    # ---- 路由 ---- #
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                return self._static("embed.html")
            if path in ("/embed", "/embed.html"):
                return self._static("embed.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path == "/api/search":
                return self._search(qs)
            if path == "/api/browse":
                return self._browse(qs)
            if path == "/api/categories":
                return self._categories(qs)
            if path.startswith("/api/part/"):
                return self._part(path[len("/api/part/"):], qs)
            # Capture 内嵌页签用的 JSONP 别名（IE7 内核无 JSON.parse）
            if path == "/api/es/search":
                return self._search(qs)
            if path == "/api/es/browse":
                return self._browse(qs)
            if path == "/api/es/categories":
                return self._categories(qs)
            if path in ("/api/es/packages", "/api/packages"):
                return self._packages(qs)
            if path in ("/api/es/facets", "/api/facets"):
                return self._facets(qs)
            if path.startswith("/api/es/part/"):
                return self._part(path[len("/api/es/part/"):], qs)
            if path.startswith("/api/es/product/"):
                return self._product(path[len("/api/es/product/"):], qs)
            if path == "/api/es/datasheet/open":
                return self._open_datasheet(qs)
            if path == "/api/es/status":
                return self._jsonp(qs, {"capture_online": self._capture_online(qs)}) or self._json(
                    {"capture_online": self._capture_online(qs)}
                )
            if path == "/api/es/place":
                return self._place_from_qs(qs)
            if path == "/api/es/footprint":
                result = self.server.services.footprints.submit(self._component((qs.get('cid') or [''])[0]), Config.load())
                return self._jsonp(qs, result) or self._json(result)
            if path == '/api/es/footprint/status':
                result = self.server.services.footprints.status((qs.get('job') or [''])[0])
                return self._jsonp(qs, result) or self._json(result)
            if path == '/api/es/library/browse':
                from ..services.directory_picker import start_picker
                result = start_picker((qs.get('initial') or [''])[0])
                return self._jsonp(qs, result) or self._json(result)
            if path == '/api/es/library/browse/status':
                from ..services.directory_picker import picker_status
                result = picker_status((qs.get('job') or [''])[0])
                return self._jsonp(qs, result) or self._json(result)
            if path in ('/api/es/library/settings', '/api/es/library/settings/save'):
                from ..services.library_settings import read_settings, save_settings
                result = save_settings({k: v[0] for k, v in qs.items()}) if path.endswith('/save') else read_settings()
                return self._jsonp(qs, result) or self._json(result)
            if path == "/api/es/place/status":
                seq = (qs.get("seq") or [""])[0]
                result = {"result": read_response(seq)}
                return self._jsonp(qs, result) or self._json(result)
            if path.startswith("/api/png/symbol/"):
                return self._png(path, "symbol", qs)
            if path.startswith("/api/png/footprint/"):
                return self._png(path, "footprint", qs)
            if path.startswith("/api/png/model3d/"):
                return self._png(path, "model3d", qs)
            if path.startswith("/api/svg/symbol/"):
                return self._svg(path, "symbol")
            if path.startswith("/api/svg/footprint/"):
                return self._svg(path, "footprint")
            if path.startswith("/api/obj/"):
                return self._obj(path[len("/api/obj/"):])
            if path == "/api/place/status":
                seq = (qs.get("seq") or [""])[0]
                return self._json({"result": read_response(seq)})
            if path == "/api/config":
                return self._json(asdict(Config.load()))
            if path == "/api/status":
                return self._json({"capture_online": self._capture_online(qs)})
            if path == "/api/health":
                return self._json({"ok": True})
            self._json({"error": "not_found", "path": path}, 404)
        except (UpstreamChangedError, FetchError) as e:
            self._error(e, 502)
        except (ParseError, LcscError, ValueError) as e:
            self._error(e, 400)
        except Exception as e:  # noqa: BLE001 —— 顶层兜底，保证服务不崩
            self._error(e, 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/place":
                return self._place()
            if path == "/api/config":
                return self._save_config()
            self._json({"error": "not_found", "path": path}, 404)
        except (UpstreamChangedError, FetchError) as e:
            self._error(e, 502)
        except (LcscError, ValueError) as e:
            self._error(e, 400)
        except Exception as e:  # noqa: BLE001
            self._error(e, 500)

    # ---- 静态 ---- #
    def _static(self, rel: str) -> None:
        # 防目录穿越
        target = (WEB_DIR / rel).resolve()
        if not target.is_relative_to(WEB_DIR.resolve()) or not target.is_file():
            self._json({"error": "not_found"}, 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".json": "application/json; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype, cache=target.suffix in (".css", ".js"))

    # ---- API ---- #
    def _search(self, qs: dict[str, list[str]]) -> None:
        kw = (qs.get("q") or [""])[0].strip()
        page = int((qs.get("page") or ["1"])[0])
        size = int((qs.get("size") or ["30"])[0])
        if not kw:
            obj = {"parts": [], "total": 0, "page": 1, "pageSize": size}
            if not self._jsonp(qs, obj):
                self._json(obj)
            return
        package = (qs.get("package") or [""])[0].strip()
        cat = int((qs.get("cat") or ["0"])[0])
        res = self.server.services.catalog.search(kw, page=page, size=size,
            package=package, cat=cat, filters=self._filters(qs))
        obj = {
            "parts": [_part_dict(p) for p in res.parts],
            "total": res.total,
            "page": res.page,
            "pageSize": res.page_size,
            "keyword": kw,
        }
        if not self._jsonp(qs, obj):
            self._json(obj)

    def _browse(self, qs: dict[str, list[str]]) -> None:
        cat = int((qs.get("cat") or ["0"])[0])
        page = int((qs.get("page") or ["1"])[0])
        size = int((qs.get("size") or ["30"])[0])
        package = (qs.get("package") or [""])[0].strip()
        if not cat:
            obj = {"parts": [], "total": 0, "page": 1, "pageSize": size}
            if not self._jsonp(qs, obj):
                self._json(obj)
            return
        res = self.server.services.catalog.browse(cat, page=page, size=size,
            package=package, filters=self._filters(qs))
        obj = {
            "parts": [_part_dict(p) for p in res.parts],
            "total": res.total,
            "page": res.page,
            "pageSize": res.page_size,
        }
        if not self._jsonp(qs, obj):
            self._json(obj)

    def _category_data(self) -> list[dict]:
        return self.server.services.catalog.category_data()


    def _categories(self, qs: dict[str, list[str]]) -> None:
        obj = {"categories": self._category_data()}
        if not self._jsonp(qs, obj):
            self._json(obj)

    def _leaf_ids(self, cat: int) -> list[int]:
        return self.server.services.catalog.leaf_ids(cat)


    def _packages(self, qs: dict[str, list[str]]) -> None:
        cat = int((qs.get("cat") or ["0"])[0])
        keyword = (qs.get("q") or [""])[0].strip()
        obj = self.server.services.catalog.options("packages", cat, keyword) if cat or keyword else {"packages": [], "total": 0}
        if not self._jsonp(qs, obj):
            self._json(obj)


    @staticmethod
    def _filters(qs: dict[str, list[str]]) -> dict[str, Any]:
        params = clean_params({key[6:]: values for key, values in qs.items() if key.startswith("param.")})
        obj: dict[str, Any] = {"params": params} if params else {}
        packages = qs.get("package") or []
        if len(packages) > 50 or any(len(v) > 300 for v in packages):
            raise ValueError("封装筛选数量或长度超限")
        if len(packages) > 1:
            obj["packages"] = packages
        brands = qs.get("brand") or []
        if len(brands) > 50 or any(not v.isdecimal() or len(v) > 12 for v in brands):
            raise ValueError("品牌筛选格式错误")
        if brands:
            obj["brand_ids"] = brands
        return obj

    def _facets(self, qs: dict[str, list[str]]) -> None:
        cat = int((qs.get("cat") or ["0"])[0])
        keyword = (qs.get("q") or [""])[0].strip()
        obj = self.server.services.catalog.options("facets", cat, keyword) if cat or keyword else {"facets": [], "total": 0, "scope": "category-keyword"}
        if not self._jsonp(qs, obj):
            self._json(obj)


    def _part(self, cid: str, qs: dict[str, list[str]]) -> None:
        cid = cid.strip().upper()
        comp = self._component(cid)

        # 顺便判断该元件是否真有 CAD 数据 (符号/封装)
        out: dict[str, Any] = {
            "cid": comp.cid,
            "title": comp.title,
            "hasSymbol": comp.symbol is not None,
            "hasFootprint": comp.footprint is not None,
            "symbolUrl": f"/api/svg/symbol/{cid}.svg",
            "footprintUrl": f"/api/svg/footprint/{cid}.svg",
            "symbolPngUrl": f"/api/png/symbol/{cid}.png",
            "footprintPngUrl": f"/api/png/footprint/{cid}.png",
        }
        if comp.symbol:
            out["datasheet"] = safe_web_url(comp.symbol.datasheet)
            out["prefix"] = comp.symbol.prefix
            out["pinCount"] = len(comp.symbol.pins)
            out["size"] = {"w": round(comp.symbol.width_mm, 2), "h": round(comp.symbol.height_mm, 2)}
            out["description"] = comp.symbol.description
            out["manufacturer"] = comp.symbol.manufacturer
            out["mpn"] = comp.symbol.mpn
        if comp.footprint:
            out["footprint"] = comp.footprint.name
            out["isSmd"] = comp.footprint.is_smd
            out["padCount"] = len(comp.footprint.pads)
            out["padstacks"] = len(comp.footprint.padstacks)
        if comp.model3d:
            out["model3d"] = {"uuid": comp.model3d.uuid, "objUrl": f"/api/obj/{comp.model3d.uuid}"}
        if not self._jsonp(qs, out):
            self._json(out)

    def _product_data(self, cid: str) -> dict:
        import re
        cid = cid.strip().upper()
        if not re.fullmatch(r"C[0-9]+", cid):
            raise ValueError("无效的立创编号")
        return self.server.services.catalog.product(cid)


    def _product(self, cid: str, qs: dict[str, list[str]]) -> None:
        data = self._product_data(cid)
        if not self._jsonp(qs, data):
            self._json(data)

    def _open_datasheet(self, qs: dict[str, list[str]]) -> None:
        cid = (qs.get("cid") or [""])[0].strip().upper()
        try:
            data = self._product_data(cid)
            url = data["datasheet"]
        except FetchError:
            url = ""
        if not url:
            comp = self._component(cid)
            url = safe_web_url(comp.symbol.datasheet if comp.symbol else "")
        if not url:
            raise FetchError("该元件暂无可用的数据手册链接")
        os.startfile(url)
        out = {"ok": True, "message": "已在系统默认浏览器打开数据手册"}
        if not self._jsonp(qs, out):
            self._json(out)

    def _svg(self, path: str, kind: str) -> None:
        # /api/svg/{kind}/{cid}.svg
        name = path.rsplit("/", 1)[-1]
        cid = name[:-4] if name.lower().endswith(".svg") else name
        comp = self._component(cid)
        try:
            svg = self.server.services.preview.svg(comp, kind)
        except PreviewMissing as exc:
            self._json({"error": str(exc)}, 404)
            return
        self._send(200, svg.encode("utf-8"), "image/svg+xml; charset=utf-8")

    def _png(self, path: str, kind: str, qs: dict[str, list[str]]) -> None:
        lane = (qs.get("lane") or [""])[0][:120]
        revision = int((qs.get("revision") or ["0"])[0])
        try:
            with self.server.services.tasks.slot(lane, revision):
                return self._png_work(path, kind, qs)
        except Superseded:
            self._send(204, b"", "image/png")
        except TaskUnavailable as exc:
            self._error(exc, 503)

    def _png_work(self, path: str, kind: str, qs: dict[str, list[str]]) -> None:
        try:
            size = int((qs.get("size") or ["1024"])[0])
            if size not in (512, 1024, 2048, 4096):
                raise ValueError("unsupported preview size")
        except ValueError as exc:
            self._error(exc, 400)
            return
        cid = path.rsplit("/", 1)[-1].removesuffix(".png")
        comp = self._component(cid)
        yaw = int((qs.get("yaw") or ["35"])[0]) % 360
        pitch = max(-85, min(85, int((qs.get("pitch") or ["55"])[0])))
        try:
            body = self.server.services.preview.png(comp, kind, size, yaw, pitch)
        except PreviewMissing as exc:
            self._json({"error": str(exc)}, 404)
            return
        self._send(200, body, "image/png", cache=True)

    def _obj(self, uuid: str) -> None:
        """3D OBJ 代理 —— 避免前端直接跨域访问 modules.easyeda.com。"""
        self._send(200, _model_bytes(uuid), "model/obj")

    def _place(self) -> None:
        self._do_place(self._read_body())

    def _place_from_qs(self, qs: dict[str, list[str]]) -> None:
        """JSONP 放置（Capture 内嵌页签）：页面本身就在 Capture 里，
        不需要切窗口。"""
        params = {k: (v[0] if v else "") for k, v in qs.items()}
        self._do_place(params, 0, embedded=True)

    def _do_place(self, params: dict[str, Any], browser_hwnd: int = 0, *, embedded: bool = False) -> None:
        cid = (params.get("cid") or "").strip().upper()
        if not cid:
            self._json({"error": "missing_cid"}, 400)
            return
        cfg = Config.load()
        if boolean(params.get("force_cursor")):
            cfg.place_mode = "cursor"
        comp = self._component(cid)
        if comp.symbol is None:
            obj = {"error": "no_symbol", "message": "该元件没有原理图符号，无法放置到原理图"}
            if not self._jsonp({"cb": [params.get("cb", "")]}, obj):
                self._json(obj, 400)
            return
        options = PreparationOptions(capture_only=embedded, download_step=not embedded)
        out = self.server.services.placement.submit(comp, cfg, options,
            target=params.get("session", ""), stage_only=params.get("stage_only", False))
        if not self._jsonp({"cb": [params.get("cb", "")]}, out):
            self._json(out)


    def _save_config(self) -> None:
        body = self._read_body()
        data = asdict(Config.load())
        data.update(body)
        cfg = Config.from_dict(data)
        cfg.ensure_dirs()
        cfg.save()
        self._json(asdict(cfg))



def safe_web_url(url: str) -> str:
    url = str(url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    return url if parsed.scheme.lower() in ("http", "https") and parsed.netloc else ""


def _part_dict(p: Any) -> dict[str, Any]:
    return {
        "cid": p.cid,
        "model": p.model,
        "brand": p.brand,
        "package": p.package,
        "description": p.description,
        "stock": p.stock,
        "category": p.category,
        "categoryPath": p.category_path,
        "catalogId": p.catalog_id,
        "image": p.image_url,
        "datasheet": safe_web_url(p.datasheet_url),
        "price": p.price_str,
        "prices": [{"qty": x.qty, "price": x.price, "cur": x.currency} for x in p.prices],
        "params": p.params,
        "paramDisplay": display_params(p.params, p.catalog_id),
        "url": p.url,
        "basic": p.is_basic,
        "preferred": p.is_preferred,
    }


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class ApplicationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.request_slots = threading.BoundedSemaphore(48)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 1\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_slots.release()

    def server_close(self):
        if hasattr(self, "services"):
            self.services.tasks.close()
            if hasattr(self.services, 'footprints'):
                self.services.footprints.close()
        super().server_close()


def make_server(port: int = 0, verbose: bool = True, *, services=None) -> ThreadingHTTPServer:
    httpd = ApplicationServer(("127.0.0.1", port), MallHandler)
    httpd.services = services if services is not None else ApplicationServices()
    httpd.verbose = verbose  # type: ignore[attr-defined]
    httpd.daemon_threads = True
    return httpd


def serve_forever(port: int = 0, verbose: bool = True) -> tuple[ThreadingHTTPServer, str]:
    """启动服务并返回 (server, url)。调用方负责 shutdown。"""
    httpd = make_server(port, verbose)
    actual = httpd.server_address[1]
    url = f"http://127.0.0.1:{actual}/"
    # Capture 的内嵌页签（OpenURL）需要知道当前端口 —— 写进 url.txt 供 TCL 读取。
    try:
        from ..config import app_dir
        from ..storage import atomic_write
        atomic_write(app_dir() / "url.txt", url + "\n")
    except Exception:  # noqa: BLE001
        pass
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, url
