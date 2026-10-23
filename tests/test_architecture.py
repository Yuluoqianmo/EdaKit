"""Service boundaries, concurrent publication, queue ownership and shutdown."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import runpy
import subprocess
import threading
import time

import pytest

from edakit.bridge import queue
from edakit.config import Config
from edakit.services.cache import Cache
from edakit.services.tasks import TaskCoordinator, Superseded, TaskUnavailable

ROOT = Path(__file__).resolve().parents[1]


def test_generated_assets_are_current():
    runpy.run_path(str(ROOT / "tools/build_web.py"))["build"](check=True)


def test_config_migrates_version_and_preserves_unknown_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cfg = Config.from_dict({"project_olb": "D:/existing/project.olb", "future_setting": 42})
    cfg.save()
    loaded = Config.load()
    assert loaded.config_version == 1
    assert loaded.project_olb == "D:/existing/project.olb"
    assert loaded.extra["unknown_fields"]["future_setting"] == 42


@pytest.mark.parametrize("change", [{"port": "1"}, {"place_mode": "broken"},
    {"place_x_mil": float("nan")}, {"auto_config_allegro": "false"}, {"config_version": 2}])
def test_invalid_config_is_rejected(change):
    with pytest.raises(ValueError):
        Config.from_dict(change)


def test_concurrent_requests_are_complete_at_publication(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    def submit(i):
        request = queue.PlaceRequest(cid="C" + str(i), part_name="x" * 20000)
        return request.submit()
    with ThreadPoolExecutor(max_workers=12) as pool:
        paths = list(pool.map(submit, range(60)))
    assert len(set(paths)) == 60
    for path in paths:
        data = queue._load_kv(path.read_text(encoding="utf-8"))
        assert data["protocol_version"] == "2"
        assert len(data["part_name"]) == 20000
        assert float(data["expires"]) > float(data["created"])
    assert not list(queue.queue_dir().glob("*.tmp"))


def test_cache_coalesces_and_is_bounded():
    cache = Cache(capacity=2)
    count = []
    def load():
        count.append(1)
        time.sleep(.05)
        return object()
    with ThreadPoolExecutor(max_workers=10) as pool:
        values = list(pool.map(lambda _: cache.get_or_load("same", load), range(10)))
    assert len(count) == 1
    assert all(value is values[0] for value in values)
    cache["two"] = 2
    cache["three"] = 3
    assert len(cache) == 2 and "same" not in cache


def test_cache_failure_can_retry():
    cache = Cache()
    with pytest.raises(ValueError):
        cache.get_or_load("key", lambda: (_ for _ in ()).throw(ValueError("bad")))
    assert cache.get_or_load("key", lambda: 42) == 42


def test_request_retry_does_not_publish_again_after_consumption(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    request = queue.PlaceRequest(cid="C1", seq="retry")
    path = request.submit()
    path.unlink()
    (path.parent / "resp_retry.resp").write_text("seq=retry\nok=1\nstage=place\n")
    request.submit()
    assert not path.exists()
    with pytest.raises(ValueError):
        queue.PlaceRequest(cid="C2", seq="retry").submit()


def test_signed_tcl_clock_token_is_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = queue.PlaceRequest(cid="C1", target_session="123--2147483648").submit()
    assert "target_session=123--2147483648" in path.read_text()


def test_stage_only_retains_symbol_less_cli_support(tmp_path, monkeypatch):
    from edakit.easyeda.model import Component
    from edakit.pipeline import Staged
    from edakit.services.placement import PlacementService, PreparationOptions
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    service = PlacementService(lambda *a, **kw: Staged(cid="C1"), target_resolver=lambda _: "")
    result = service.submit(Component(cid="C1"), Config(), PreparationOptions(), stage_only=True)
    assert queue.pending_requests()[0]["stage_only"] == "1"
    assert result["staged"]["cid"] == "C1"


def test_maintenance_expires_queued_request_and_recovers_cleanup(tmp_path, monkeypatch):
    from edakit.bridge.sessions import maintain_queue
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    request = queue.PlaceRequest(cid="C1", seq="expired", expires=1)
    path = request.submit()
    path.rename(path.with_name(path.name + ".cleanup"))
    maintain_queue()
    assert queue.read_response("expired")["error_code"] == "request_expired"
    assert not list(path.parent.glob("*.cleanup"))


def test_cache_ttl_expires(monkeypatch):
    from edakit.services import cache as module
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    cache = Cache(ttl=5)
    cache["key"] = 42
    clock[0] += 6
    assert cache.get_or_load("key", lambda: 43) == 43


def test_task_queue_discards_superseded_work_and_closes_waiters():
    tasks = TaskCoordinator(workers=1)
    started = threading.Event()
    release = threading.Event()
    def occupy():
        with tasks.slot():
            started.set()
            release.wait(3)
    def preview(revision):
        try:
            with tasks.slot("browser", revision):
                return revision
        except Superseded:
            return "superseded"
    with ThreadPoolExecutor(max_workers=3) as pool:
        occupied = pool.submit(occupy)
        assert started.wait(1)
        old = pool.submit(preview, 1)
        deadline = time.monotonic() + 2
        while tasks.waiting < 1 and time.monotonic() < deadline:
            time.sleep(.005)
        new = pool.submit(preview, 2)
        assert old.result(timeout=2) == "superseded"
        release.set()
        assert new.result(timeout=2) == 2
        occupied.result()
    tasks.close()
    with pytest.raises(TaskUnavailable):
        with tasks.slot():
            pass
    assert tasks.waiting == tasks.active == 0


def test_target_requires_live_session(monkeypatch):
    from edakit.bridge import sessions
    monkeypatch.setattr(sessions, "live_sessions", lambda: {"10-123": 10, "11-456": 11})
    assert sessions.resolve_target("11-456") == "11-456"
    with pytest.raises(ValueError):
        sessions.resolve_target()
    with pytest.raises(ValueError):
        sessions.resolve_target("10-old")


@pytest.mark.skipif(__import__("os").name != "nt", reason="native Windows process probe")
def test_maintenance_fails_interrupted_claim_without_replaying(tmp_path, monkeypatch):
    from edakit.bridge.sessions import maintain_queue
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    request = queue.PlaceRequest(cid="C1", seq="interrupted")
    path = request.submit()
    claimed = path.with_name(path.name + ".4294967294.work")
    path.rename(claimed)
    maintain_queue()
    assert not claimed.exists() and not path.exists()
    assert queue.read_response(request.seq)["error_code"] == "host_interrupted"
    maintain_queue()
    assert queue.read_response(request.seq)["stage"] == "interrupted"


@pytest.mark.skipif(__import__("os").name != "nt", reason="native Windows process probe")
def test_dead_library_lock_is_released(tmp_path, monkeypatch):
    from edakit.bridge.sessions import maintain_queue
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    lock = queue.queue_dir() / "capture-library.lock"
    lock.write_text("pid=4294967294\n")
    maintain_queue()
    assert not lock.exists()


def test_http_connection_limit_recovers_after_disconnect():
    import socket
    import urllib.request
    from edakit.server.app import make_server
    server = make_server(0, False)
    server.request_slots = threading.BoundedSemaphore(2)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clients = []
    address = server.server_address
    try:
        for _ in range(2):
            client = socket.create_connection(address, timeout=2)
            client.sendall(b"GET /api/health HTTP/1.0\r\nHost: localhost\r\n")
            clients.append(client)
        deadline = time.monotonic() + 2
        while server.request_slots._value and time.monotonic() < deadline:
            time.sleep(.005)
        with socket.create_connection(address, timeout=2) as rejected:
            assert b"503" in rejected.recv(1024)
        for client in clients:
            client.close()
        clients.clear()
        deadline = time.monotonic() + 2
        while server.request_slots._value < 2 and time.monotonic() < deadline:
            time.sleep(.005)
        with urllib.request.urlopen(f"http://127.0.0.1:{address[1]}/api/health", timeout=2) as response:
            assert json.loads(response.read())["ok"]
    finally:
        for client in clients:
            client.close()
        server.shutdown()
        server.server_close()


def test_tcl_consumers_claim_once_and_respect_target(tmp_path, monkeypatch):
    from test_tcl_plugin import TCLSH, PLUGIN
    if not TCLSH:
        pytest.skip("Tcl unavailable")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    driver = tmp_path / "consumer.tcl"
    driver.write_text(r'''
proc after {args} {}
proc RegisterAction {args} {}
proc InsertXMLMenu {args} {}
source [lindex $argv 0]
set ::edakit::sessionId [lindex $argv 1]
rename ::edakit::handleOne ::edakit::realHandle
proc ::edakit::handleOne {path} {
    set f [open [file join [locateQueueDir] calls.txt] a]
    puts $f [pid]; close $f
    # Keep the claim visible so another consumer encounters it.
    after_real 100
    realHandle $path
}
::edakit::processQueue
'''.replace('proc after {args} {}', 'rename after after_real\nproc after {args} {}'), encoding="ascii")
    # Route is intentionally different from the startup session, so source cannot consume it.
    request = queue.PlaceRequest(cid="C1", seq="claim", target_session="123-456", stage_only=True)
    request.submit()
    processes = [subprocess.Popen([TCLSH, str(driver), str(PLUGIN), "123-456"], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for process in processes:
        out, err = process.communicate(timeout=10)
        assert process.returncode == 0, (out, err)
    assert len((queue.queue_dir() / "calls.txt").read_text().splitlines()) == 1
    assert queue.read_response("claim")["ok"]
    assert not list(queue.queue_dir().glob("*.work"))


def test_export_reuses_pipeline_and_keeps_name_consistent(tmp_path, monkeypatch):
    from edakit.easyeda.parse import parse_component
    from edakit.services.export import ExportService
    from edakit.symbol.naming import capture_part_name
    from edakit.symbol.prepared import CAPTURE_PART_REVISION
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "runtime"))
    payload = json.loads((ROOT / "tests/data/C2040.json").read_text(encoding="utf-8"))
    component = parse_component("C2040", payload)
    component.symbol.name = "HOARG0603-1/10W-5.1KR-0.1%-TCR25"
    staged = ExportService().bundle(component, tmp_path / "bundle")
    from edakit.library import library_names
    alias = library_names(component)['symbol']
    assert staged.part_name == alias
    assert alias in staged.symbol_xml.read_text(encoding="utf-8")
    assert alias in (staged.workdir / "capture_place.tcl").read_text(encoding="utf-8")
    assert staged.footprint_skill.is_file()
