"""Bounded, synchronized TTL caches with per-key request coalescing."""
from collections import OrderedDict
from collections.abc import MutableMapping
from concurrent.futures import Future
from threading import RLock
import time


class Cache(MutableMapping):
    def __init__(self, capacity=128, ttl=600):
        self.capacity, self.ttl = capacity, ttl
        self._items = OrderedDict()
        self._active = {}
        self._lock = RLock()

    def __getitem__(self, key):
        with self._lock:
            expires, value = self._items[key]
            if time.monotonic() >= expires:
                del self._items[key]
                raise KeyError(key)
            self._items.move_to_end(key)
            return value

    def __setitem__(self, key, value):
        with self._lock:
            self._items[key] = (time.monotonic() + self.ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def __delitem__(self, key):
        with self._lock:
            del self._items[key]

    def __iter__(self):
        with self._lock:
            return iter(list(self._items))

    def __len__(self):
        with self._lock:
            return len(self._items)

    def clear(self):
        with self._lock:
            self._items.clear()

    def get_or_load(self, key, loader):
        with self._lock:
            try:
                return self[key]
            except KeyError:
                pass
            future = self._active.get(key)
            leader = future is None
            if leader:
                future = self._active[key] = Future()
        if not leader:
            return future.result()
        try:
            value = loader()
            self[key] = value
            future.set_result(value)
            return value
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._active.pop(key, None)
