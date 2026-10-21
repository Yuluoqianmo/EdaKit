"""Publish complete files only; readers never observe partial writes."""
import os
from pathlib import Path
import tempfile
import time


def atomic_write(path: Path, content: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers may briefly deny replacement while opening a status file.
        for attempt in range(6):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.01)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
