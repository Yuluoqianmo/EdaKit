from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import threading
import time

from edakit.render.scheduling import coalesced


def test_identical_concurrent_cache_misses_render_once():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    @coalesced
    @lru_cache(maxsize=2)
    def render(key):
        calls.append(key)
        entered.set()
        assert release.wait(5)
        return key * 2

    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(render, "part")
        assert entered.wait(5)
        others = [pool.submit(render, "part") for _ in range(3)]
        time.sleep(.05)
        release.set()
        assert [job.result() for job in [first] + others] == ["partpart"] * 4
    assert calls == ["part"]
    assert render("part") == "partpart"
    assert calls == ["part"]


def test_failed_render_can_be_retried():
    calls = []

    @coalesced
    @lru_cache(maxsize=2)
    def render(key):
        calls.append(key)
        if len(calls) == 1:
            raise ValueError("render failed")
        return b"png"

    import pytest
    with pytest.raises(ValueError):
        render("part")
    assert render("part") == b"png"
