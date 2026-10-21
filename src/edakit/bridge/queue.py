"""与 Capture 的桥 (队列 + 配置)。

商城界面（独立进程）不能直接操作 Capture —— 只有 Capture 进程内的 TCL 能放置元件。
所以走「文件队列」:

    商城进程                      Capture TCL 插件
    ---------                    ----------------
    写 req_<seq>.req     ──►     每 400ms 轮询队列目录
                                 执行放置 (XMATIC + PlacePart)
    读 resp_<seq>.resp   ◄──     写结果

**为什么用 key=value 文本而不是 JSON**: Capture 自带的 Tcl 不一定装了 tcllib 的 json
包，解析 JSON 会失败；而 `key=value` 一行一条，Tcl 一个 foreach 就能读，零依赖。

选文件队列而不是 socket 的原因同上: Capture 的 Tcl 不一定编译了 socket 扩展，
而文件读写永远可用。延迟 ~0.4s，人感觉不到。
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config, app_dir  # compatibility exports
from ..storage import atomic_write

# --------------------------------------------------------------------------- #
# key=value 文本格式
# --------------------------------------------------------------------------- #
def _dump_kv(data: dict[str, Any]) -> str:
    lines = []
    for k, v in data.items():
        if v is None:
            v = ""
        elif isinstance(v, bool):
            v = "1" if v else "0"   # TCL 侧只认 0/1，不认 True/False
        s = str(v).replace("\r", " ").replace("\n", " ")
        lines.append(f"{k}={s}")
    return "\n".join(lines) + "\n"


def _load_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


# --------------------------------------------------------------------------- #
# 队列
# --------------------------------------------------------------------------- #
def queue_dir() -> Path:
    d = app_dir() / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class PlaceRequest:
    """一次「放置到原理图」的请求。"""

    seq: str = ""
    cid: str = ""
    part_name: str = ""
    footprint: str = ""
    olb_xml: str = ""      # 商城侧已生成的符号库 XML
    project_olb: str = ""  # 目标累积库
    follow_cursor: bool = False
    x_mil: float = 500.0
    y_mil: float = 500.0
    stage_only: bool = False
    created: float = 0.0
    props: dict[str, str] = field(default_factory=dict)
    protocol_version: int = 2
    command: str = "place"
    target_session: str = ""
    expires: float = 0.0
    symbol_digest: str = ""

    def submit(self) -> Path:
        if not self.seq:
            self.seq = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        if not self.created:
            self.created = time.time()
        validate_seq(self.seq)
        if self.target_session and not re.fullmatch(r"[0-9]+(?:--?[0-9]+)?", self.target_session):
            raise ValueError("Invalid target session")
        if not self.expires:
            self.expires = self.created + 300
        data = asdict(self)
        props = data.pop("props", {}) or {}
        for k, v in props.items():
            data[f"prop_{k}"] = v
        path = queue_dir() / f"req_{self.seq}.req"
        content = _dump_kv(data)
        import hashlib
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        # Permanent submission receipt: reusing a request ID never replays placement.
        receipt = path.with_suffix(".submitted")
        try:
            with receipt.open("x", encoding="ascii") as stream:
                stream.write(digest)
        except FileExistsError:
            if receipt.read_text(encoding="ascii") != digest:
                raise ValueError("Request identifier already used with different content")
            if not path.exists() and not path.with_name(f"resp_{self.seq}.resp").exists() and not list(path.parent.glob(path.name + ".*.work")):
                raise ValueError("Request publication was interrupted; inspect its status before retrying")
            return path
        try:
            atomic_write(path, content)
        except BaseException:
            receipt.unlink(missing_ok=True)
            raise
        return path


def read_response(seq: str) -> dict[str, Any] | None:
    validate_seq(seq)
    path = queue_dir() / f"resp_{seq}.resp"
    if not path.exists():
        return None
    try:
        kv = _load_kv(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    result = {
        "seq": kv.get("seq", seq),
        "ok": kv.get("ok", "0") in ("1", "true", "yes"),
        "message": kv.get("message", ""),
        "stage": kv.get("stage", ""),
    }
    if "olb_reused" in kv:
        result["olb_reused"] = kv["olb_reused"] == "1"
    for key in ("error_code", "target_session", "protocol_version", "request_id"):
        if key in kv:
            result[key] = kv[key]
    return result


def pending_requests() -> list[dict[str, str]]:
    out = []
    for p in sorted(queue_dir().glob("req_*.req")):
        try:
            out.append(_load_kv(p.read_text(encoding="utf-8")))
        except OSError:
            continue
    return out


def capture_alive(max_age: float = 30.0) -> bool:
    hb = queue_dir() / "heartbeat.txt"
    if not hb.exists():
        return False
    try:
        kv = _load_kv(hb.read_text(encoding="utf-8"))
        return (time.time() - float(kv.get("ts", 0))) < max_age
    except (OSError, ValueError):
        return False


def clear_queue() -> int:
    """清空队列 (调试用)。返回删除的请求数。"""
    n = 0
    for p in queue_dir().glob("req_*.req"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


def validate_seq(seq):
    if not isinstance(seq, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", seq):
        raise ValueError("Invalid request identifier")
