from pathlib import Path
import time

from edakit.server.lifecycle import CaptureSessions, remove_owned_url


class FakeProcess:
    def __init__(self, created=0):
        self.created = created
        self.running = True
        self.closed = False

    def alive(self):
        return self.running

    def close(self):
        self.closed = True


def test_multiple_hosts_and_busy_heartbeat_do_not_stop_service(tmp_path):
    processes = {123: FakeProcess(), 456: FakeProcess()}
    for pid in processes:
        (tmp_path / f"{pid}.owner").write_text(str(pid))
    monitor = CaptureSessions(tmp_path, opener=processes.__getitem__, grace=0)
    assert not monitor.should_stop()
    processes[123].running = False
    assert not monitor.should_stop()
    assert not (tmp_path / "123.owner").exists()
    processes[456].running = False
    assert monitor.should_stop()
    assert all(p.closed for p in processes.values())


def test_stale_pid_reuse_is_not_adopted(tmp_path):
    path = tmp_path / "123.owner"
    path.write_text("123")
    process = FakeProcess(created=path.stat().st_mtime + 10)
    monitor = CaptureSessions(tmp_path, opener=lambda pid: process, grace=0)
    assert monitor.should_stop()
    assert process.closed and not path.exists()


def test_missing_process_registration_is_cleaned(tmp_path):
    path = tmp_path / "123.owner"
    path.write_text("123")

    def missing(pid):
        raise ProcessLookupError(pid)

    assert CaptureSessions(tmp_path, opener=missing, grace=0).should_stop()
    assert not path.exists()


def test_cleanup_preserves_url_written_by_another_service(tmp_path):
    path = tmp_path / "url.txt"
    path.write_text("http://127.0.0.1:2000/\n")
    remove_owned_url(path, "http://127.0.0.1:1000/")
    assert path.exists()
    remove_owned_url(path, "http://127.0.0.1:2000/")
    assert not path.exists()

def test_managed_service_repairs_missing_or_overwritten_discovery(tmp_path):
    from edakit.server.lifecycle import publish_owned_url
    path = tmp_path / 'url.txt'
    publish_owned_url(tmp_path, 'http://127.0.0.1:1234/')
    stamp = path.stat().st_mtime_ns
    publish_owned_url(tmp_path, 'http://127.0.0.1:1234/')
    assert path.stat().st_mtime_ns == stamp
    path.unlink()
    publish_owned_url(tmp_path, 'http://127.0.0.1:1234/')
    assert path.read_text().strip() == 'http://127.0.0.1:1234/'
    path.write_text('http://127.0.0.1:dead/')
    publish_owned_url(tmp_path, 'http://127.0.0.1:1234/')
    assert path.read_text().strip() == 'http://127.0.0.1:1234/'
