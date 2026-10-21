"""Keep windowed builds observable without allocating a console."""

import os
from pathlib import Path
import sys


def configure_background_streams() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "edakit"
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / "background.log").open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream



def configure_logging():
    import logging
    from logging.handlers import RotatingFileHandler
    from .config import app_dir
    logger = logging.getLogger("edakit")
    if logger.handlers:
        return
    handler = RotatingFileHandler(app_dir() / "service.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
