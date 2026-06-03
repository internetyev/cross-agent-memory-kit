#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from glob import glob
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from distill.adapters.codex import load_codex_transcript
from distill.engine import run_distillation
from distill.logs import make_file_logger

STATE_ROOT = Path.home() / ".local" / "state" / "cross-agent-memory-kit"
DEFAULT_STATE_PATH = STATE_ROOT / "codex-processed.json"
DEFAULT_LOG_PATH = STATE_ROOT / "logs" / "codex.log"
DEFAULT_SESSION_GLOBS = [
    Path.home() / ".codex" / "sessions" / "**" / "*.jsonl",
    Path.home() / ".codex" / "archived_sessions" / "*.jsonl",
]


def main() -> None:
    args = parse_args()
    logger = make_file_logger(args.log_path)

    os.environ.setdefault("DISTILL_PROVIDER", args.provider)
    os.environ.setdefault("DISTILL_MODEL", args.model)

    state = load_state(args.state_path)
    candidates = list(iter_candidates(args.lookback_days, args.quiet_minutes))
    processed_this_run = 0
    limit = None if args.limit <= 0 or args.mark_existing else args.limit

    logger(
        f"scan start: candidates={len(candidates)} limit={limit or 'none'} "
        f"provider={os.environ.get('DISTILL_PROVIDER')} model={os.environ.get('DISTILL_MODEL')}"
    )

    for path in candidates:
        if limit is not None and processed_this_run >= limit:
            break

        try:
            transcript = load_codex_transcript(path)
        except Exception as exc:
            logger(f"  failed to parse {path}: {exc}")
            continue

        existing = state["processed"].get(transcript.session_id)
        if existing and not args.reprocess:
            continue

        if args.mark_existing:
            state["processed"][transcript.session_id] = {
                "path": str(path),
                "agent": "codex",
                "status": "baseline",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "mtime": path.stat().st_mtime,
                "reason": "marked existing before watcher activation",
            }
            processed_this_run += 1
            continue

        if args.dry_run:
            logger(f"  dry-run would distill {transcript.session_id} from {path}")
            processed_this_run += 1
            continue

        result = run_distillation(transcript, logger)
        if result.status == "failed":
            logger(f"  not marking {transcript.session_id} processed after failed distillation")
            continue

        state["processed"][transcript.session_id] = {
            "path": str(path),
            "agent": "codex",
            "status": result.status,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "mtime": path.stat().st_mtime,
            "artifacts_stored": result.artifacts_stored,
            "facts_stored": result.facts_stored,
            "reason": result.reason,
        }
        save_state(args.state_path, state)
        processed_this_run += 1

    if args.mark_existing and not args.dry_run:
        save_state(args.state_path, state)

    logger(f"scan complete: processed={processed_this_run}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan Codex session JSONL files and distill unprocessed sessions.")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--quiet-minutes", type=int, default=30)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--provider", default="codex-cli")
    parser.add_argument("--model", default="gpt-5.1-low")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--mark-existing", action="store_true", help="Mark matching sessions as baseline without distilling them.")
    return parser.parse_args()


def iter_candidates(lookback_days: int, quiet_minutes: int) -> list[Path]:
    now = time.time()
    min_mtime = now - (lookback_days * 24 * 60 * 60)
    quiet_before = now - (quiet_minutes * 60)
    paths: dict[Path, float] = {}

    for pattern in DEFAULT_SESSION_GLOBS:
        for raw_path in glob(str(pattern), recursive=True):
            path = Path(raw_path)
            if not path.is_file():
                continue
            mtime = path.stat().st_mtime
            if mtime < min_mtime or mtime > quiet_before:
                continue
            paths[path] = mtime

    return [path for path, _mtime in sorted(paths.items(), key=lambda item: item[1])]


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "processed": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"version": 1, "processed": {}}
    if not isinstance(data, dict):
        return {"version": 1, "processed": {}}
    data.setdefault("version", 1)
    data.setdefault("processed", {})
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)


if __name__ == "__main__":
    main()
