"""Python ↔ Capture 文件队列测试。

用 key=value 而不是 JSON，是因为 Capture 自带的 Tcl 不一定有 json 包。
这里同时验证「TCL 能读懂」所依赖的格式约定。
"""

import time
from pathlib import Path

import pytest

from edakit.bridge import queue


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_kv_roundtrip():
    text = queue._dump_kv({"a": 1, "b": "x y", "c": None})
    assert queue._load_kv(text) == {"a": "1", "b": "x y", "c": ""}


def test_dump_kv_uses_readable_booleans():
    # TCL 侧只判断 "1"/"true"，所以不能写成 True/False
    text = queue._dump_kv({"stage_only": True, "follow_cursor": False})
    kv = queue._load_kv(text)
    assert kv["stage_only"] == "1"
    assert kv["follow_cursor"] == "0"


def test_dump_kv_strips_newlines():
    kv = queue._load_kv(queue._dump_kv({"msg": "a\nb\rc"}))
    assert kv["msg"] == "a b c"


def test_load_kv_skips_comments_and_blank_lines():
    kv = queue._load_kv("# comment\n\ncid=C1\nbadline\nx = y \n")
    assert kv == {"cid": "C1", "x": "y"}


def test_submit_writes_request_file():
    req = queue.PlaceRequest(cid="C2040", part_name="RP2040", footprint="LQFN-56",
                             olb_xml=r"C:\x\C2040.olb.xml", project_olb=r"C:\x\p.olb",
                             props={"PCB Footprint": "LQFN-56"})
    path = req.submit()
    assert path.exists()
    assert path.name == f"req_{req.seq}.req"
    kv = queue._load_kv(path.read_text(encoding="utf-8"))
    assert kv["cid"] == "C2040"
    assert kv["part_name"] == "RP2040"
    assert kv["prop_PCB Footprint"] == "LQFN-56"
    assert "created" in kv


def test_response_parsing():
    seq = "t1"
    (queue.queue_dir() / f"resp_{seq}.resp").write_text(
        "seq=t1\nok=1\nmessage=已放置\nstage=place\n", encoding="utf-8"
    )
    res = queue.read_response(seq)
    assert res == {"seq": "t1", "ok": True, "message": "已放置", "stage": "place"}


def test_response_missing_is_none():
    assert queue.read_response("nope") is None


def test_capture_alive_reads_heartbeat():
    assert queue.capture_alive() is False
    (queue.queue_dir() / "heartbeat.txt").write_text(
        f"ts={time.time()}\npid=1\n", encoding="utf-8"
    )
    assert queue.capture_alive() is True
    # 过期心跳视为离线
    (queue.queue_dir() / "heartbeat.txt").write_text("ts=1\n", encoding="utf-8")
    assert queue.capture_alive() is False


def test_pending_and_clear():
    for cid in ("C1", "C2"):
        queue.PlaceRequest(cid=cid).submit()
    assert len(queue.pending_requests()) == 2
    assert queue.clear_queue() == 2
    assert queue.pending_requests() == []


def test_config_defaults_and_save(tmp_path):
    cfg = queue.Config.load()
    assert Path(cfg.footprint_lib).as_posix() == "D:/EdaKit/Libraries/Footprints"
    cfg.place_mode = "cursor"
    cfg.footprint_lib = str(tmp_path / "lib")
    cfg.save()
    cfg2 = queue.Config.load()
    assert cfg2.place_mode == "cursor"
    assert cfg2.footprint_lib == str(tmp_path / "lib")
    cfg2.symbol_lib = str(tmp_path / "symbols")
    cfg2.step_lib = str(tmp_path / "step")
    cfg2.ensure_dirs()
    assert (tmp_path / "lib").is_dir()


def test_legacy_config_migrates_without_replaying_requests(tmp_path):
    import json
    legacy = tmp_path / "lcsc2cadence"
    legacy.mkdir()
    (legacy / "config.json").write_text(json.dumps({
        "footprint_lib": "D:/existing/library",
        "project_olb": "D:/existing/project.olb", "place_mode": "slot"
    }), encoding="utf-8")
    (legacy / "queue").mkdir()
    (legacy / "queue/req_old.req").write_text("cid=C2040")
    cfg = queue.Config.load()
    assert cfg.footprint_lib == "D:/existing/library"
    assert cfg.project_olb == "D:/existing/project.olb"
    assert cfg.place_mode == "slot"
    assert (tmp_path / "edakit/config.json").exists()
    assert queue.pending_requests() == []
    cfg.place_mode = "cursor"
    cfg.save()
    assert queue.Config.load().place_mode == "cursor"
    assert (legacy / "config.json").exists()
