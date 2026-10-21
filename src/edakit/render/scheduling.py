"""Coalesce identical concurrent previews and bound CPU render concurrency."""
from concurrent.futures import Future
from functools import wraps
import threading

_render_slot = threading.Semaphore(1)


def bounded_render(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        with _render_slot:
            return fn(*args, **kwargs)
    return run


def coalesced(fn):
    lock = threading.Lock()
    active = {}

    @wraps(fn)
    def run(*args, **kwargs):
        key = (args, tuple(sorted(kwargs.items())))
        with lock:
            future = active.get(key)
            leader = future is None
            if leader:
                future = active[key] = Future()
        if not leader:
            return future.result()
        try:
            result = fn(*args, **kwargs)
            future.set_result(result)
            return result
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with lock:
                del active[key]

    run.cache_clear = fn.cache_clear
    run.cache_info = fn.cache_info
    return run
