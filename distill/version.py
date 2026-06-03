from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_PATH = REPO_ROOT / "VERSION"


def get_setup_version() -> str:
    return VERSION_PATH.read_text().strip()


__version__ = get_setup_version()
