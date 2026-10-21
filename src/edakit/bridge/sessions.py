"""Resolve host identity and fail interrupted work without replaying side effects."""
import re
import time
from .queue import app_dir, queue_dir, _load_kv, _dump_kv
from ..storage import atomic_write


def live_sessions():
    from ..server.lifecycle import WindowsProcess
    result = {}
    for path in (app_dir() / "capture_hosts").glob("*.owner"):
        process = None
        try:
            if not path.stem.isdecimal():
                continue
            stamp = path.stat().st_mtime
            data = _load_kv(path.read_text(encoding="utf-8"))
            process = WindowsProcess(int(path.stem))
            if process.created <= stamp + .01 and process.alive():
                result[data.get("session", path.stem)] = int(path.stem)
        except (OSError, ValueError):
            continue
        finally:
            if process:
                process.close()
    return result


def resolve_target(target=""):
    if not isinstance(target, str):
        raise ValueError("Invalid target session")
    sessions = live_sessions()
    if target:
        if target not in sessions:
            raise ValueError("Capture session has closed; reopen the workbench")
        return target
    if len(sessions) > 1:
        raise ValueError("Multiple Capture sessions; choose a target session")
    return next(iter(sessions), "")  # retain offline CLI staging compatibility


def maintain_queue():
    from ..server.lifecycle import WindowsProcess
    directory = queue_dir()
    now = time.time()
    # Clear the cross-host OLB lock only after verifying its owner has exited.
    lock = directory / "capture-library.lock"
    process = None
    try:
        stamp = lock.stat().st_mtime_ns
        data = _load_kv(lock.read_text(encoding="utf-8"))
        process = WindowsProcess(int(data["pid"]))
        alive = process.alive() and process.created <= stamp / 1_000_000_000 + .01
        if not alive and lock.stat().st_mtime_ns == stamp:
            lock.unlink()
    except ProcessLookupError:
        try:
            if lock.stat().st_mtime_ns == stamp:
                lock.unlink()
        except FileNotFoundError:
            pass
    except (OSError, KeyError, ValueError):
        pass
    finally:
        if process:
            process.close()
    sessions = None
    for path in list(directory.glob("*.work")) + list(directory.glob("req_*.req")) + list(directory.glob("req_*.cleanup")):
        try:
            data = _load_kv(path.read_text(encoding="utf-8"))
            match = re.fullmatch(r"req_([A-Za-z0-9_-]{1,100})\.req(?:\.([0-9]+)\.work)?(?:\.cleanup)?", path.name)
            if not match:
                continue
            seq, owner = match.groups()
            code = ""
            if owner:
                process = None
                try:
                    process = WindowsProcess(int(owner))
                    if process.alive() and process.created <= path.stat().st_mtime + .01:
                        continue
                except ProcessLookupError:
                    pass
                finally:
                    if process:
                        process.close()
                code = "host_interrupted"
            elif float(data.get("expires", "0")) and now > float(data["expires"]):
                code = "request_expired"
            if not code and not owner and data.get("target_session"):
                if sessions is None:
                    sessions = live_sessions()
                if data["target_session"] not in sessions:
                    code = "host_closed"
            if not code:
                continue
            # Compete for ownership with consumers and other maintenance calls.
            claimed = path if path.suffix == ".cleanup" else path.with_name(path.name + ".cleanup")
            if claimed != path:
                try:
                    path.rename(claimed)
                except FileNotFoundError:
                    continue
            response = directory / f"resp_{seq}.resp"
            existing = _load_kv(response.read_text(encoding="utf-8")) if response.exists() else {}
            if not existing or existing.get("stage") == "waiting-schematic":
                atomic_write(response, _dump_kv({"seq": seq, "ok": False,
                    "stage": "interrupted" if owner else "expired" if code == "request_expired" else "rejected", "error_code": code,
                    "message": "Capture exited during operation; verify the schematic before retrying" if owner else "Request expired; submit again" if code == "request_expired" else "Target Capture session closed; reopen the workbench"}))
            claimed.unlink()
        except (OSError, ValueError):
            continue
