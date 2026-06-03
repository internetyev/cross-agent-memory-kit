from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

Logger = Callable[[str], None]


def null_logger(_msg: str) -> None:
    return None


def make_file_logger(path: Path) -> Logger:
    def log(msg: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")

    return log
