"""Bound synchronous work and discard superseded queued preview requests."""
from contextlib import contextmanager
from threading import Condition
import time


class TaskUnavailable(RuntimeError):
    pass


class Superseded(TaskUnavailable):
    pass


class TaskCoordinator:
    def __init__(self, workers=4, pending=16, timeout=25):
        self.workers, self.pending, self.timeout = workers, pending, timeout
        self.active = self.waiting = 0
        self.latest = {}
        self.closed = False
        self.condition = Condition()

    @contextmanager
    def slot(self, lane="", revision=0):
        deadline = time.monotonic() + self.timeout
        with self.condition:
            if self.closed or self.waiting >= self.pending:
                raise TaskUnavailable("Preview queue is busy; retry shortly")
            if lane:
                stamp, previous = self.latest.get(lane, (0, -1))
                if revision < previous:
                    raise Superseded("Preview superseded")
                self.latest[lane] = (time.monotonic(), revision)
                # Active browser lanes are retained for 60 seconds; cap metadata too.
                for key, (stamp, _) in list(self.latest.items()):
                    if stamp < time.monotonic() - 60:
                        del self.latest[key]
                while len(self.latest) > 256:
                    del self.latest[next(iter(self.latest))]
            self.waiting += 1
            try:
                while self.active >= self.workers:
                    if self.closed:
                        raise TaskUnavailable("Service stopping")
                    if lane and self.latest.get(lane, (0, revision))[1] != revision:
                        raise Superseded("Preview superseded")
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TaskUnavailable("Preview queue timeout")
                    self.condition.wait(min(left, .25))
                if self.closed:
                    raise TaskUnavailable("Service stopping")
                if lane and self.latest.get(lane, (0, revision))[1] != revision:
                    raise Superseded("Preview superseded")
                self.active += 1
            finally:
                self.waiting -= 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
