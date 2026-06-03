#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_PATH = REPO_ROOT / "VERSION"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    version = VERSION_PATH.read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-(?:dev|alpha|beta|rc)(?:\.\d+)?)?", version):
        print(f"invalid VERSION: {version}", file=sys.stderr)
        return 1

    from distill import __version__

    if __version__ != version:
        print(f"distill.__version__={__version__} does not match VERSION={version}", file=sys.stderr)
        return 1

    changelog = CHANGELOG_PATH.read_text()
    if is_release_version(version):
        if f"## [{version}]" not in changelog:
            print(f"CHANGELOG.md does not contain release section [{version}]", file=sys.stderr)
            return 1
        tag = f"v{version}"
        tags = subprocess.run(
            ["git", "tag", "--list", tag],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if tags.returncode != 0 or tags.stdout.strip() != tag:
            print(f"release VERSION={version} requires git tag {tag}", file=sys.stderr)
            return 1
    elif "## [Unreleased]" not in changelog:
        print("development VERSION requires CHANGELOG.md [Unreleased] section", file=sys.stderr)
        return 1

    print(f"version ok: {version}")
    return 0


def is_release_version(version: str) -> bool:
    return "-" not in version


if __name__ == "__main__":
    raise SystemExit(main())
