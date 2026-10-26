"""Exclusive short leases preserve Sessions across HTTP request threads."""
from contextlib import contextmanager
import threading


class ServiceClosing(RuntimeError):
    pass


class ClientPool:
    def __init__(self, factory, max_idle=8):
        self.factory, self.max_idle = factory, max_idle
        self._idle, self._closed, self._lock = [], False, threading.Lock()

    @contextmanager
    def lease(self):
        with self._lock:
            if self._closed:
                raise ServiceClosing('Service is closing')
            client = self._idle.pop() if self._idle else self.factory()
        failed = False
        try:
            yield client
        except BaseException:
            failed = True
            raise
        finally:
            with self._lock:
                retire = self._closed or failed or len(self._idle) >= self.max_idle
                if not retire:
                    self._idle.append(client)
            if retire:
                client.close()

    def close(self):
        with self._lock:
            self._closed = True
            idle, self._idle = self._idle, []
        for client in idle:
            client.close()


def invoke(factory, method, *args, **kwargs):
    client = factory()
    if hasattr(client, '__enter__'):
        with client as owned:
            return getattr(owned, method)(*args, **kwargs)
    try:
        return getattr(client, method)(*args, **kwargs)
    finally:
        if hasattr(client, 'close'):
            client.close()
