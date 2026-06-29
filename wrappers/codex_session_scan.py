#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path
from typing import Any

os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from distill.adapters.codex import load_codex_transcript
from distill.engine import run_distillation
from distill.logs import make_file_logger

STATE_ROOT = Path.home() / ".local" / "state" / "cross-agent-memory-kit"
DEFAULT_STATE_PATH = STATE_ROOT / "codex-processed.json"
DEFAULT_LOG_PATH = STATE_ROOT / "logs" / "codex.log"
DEFAULT_LOCK_PATH = STATE_ROOT / "codex-scan.lock"
DEFAULT_SESSION_GLOBS = [
    Path.home() / ".codex" / "sessions" / "**" / "*.jsonl",
    Path.home() / ".codex" / "archived_sessions" / "*.jsonl",
]
DEFAULT_SCAN_LIMIT = 5
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 3600
DEFAULT_CIRCUIT_BREAKER = 3


class ScannerAlreadyRunning(RuntimeError):
    pass


class ScannerLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            self.handle = None
            raise ScannerAlreadyRunning(f"scanner lock is held: {self.path}") from exc
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


@dataclass
class ScanSummary:
    candidates: int = 0
    handled: int = 0
    successes: int = 0
    empty: int = 0
    skips: int = 0
    failures: int = 0
    quarantined: int = 0
    deferred: int = 0
    circuit_breaker: bool = False

    def format(self) -> str:
        return (
            f"candidates={self.candidates} handled={self.handled} "
            f"successes={self.successes} empty={self.empty} skips={self.skips} "
            f"failures={self.failures} quarantined={self.quarantined} "
            f"deferred={self.deferred} circuit_breaker={str(self.circuit_breaker).lower()}"
        )


def main() -> None:
    args = parse_args()
    logger = make_file_logger(args.log_path)

    os.environ["DISTILL_PROVIDER"] = args.provider
    if args.model:
        os.environ["DISTILL_MODEL"] = args.model
    else:
        os.environ.pop("DISTILL_MODEL", None)

    try:
        with ScannerLock(args.lock_path):
            summary = run_scan(args, logger)
    except ScannerAlreadyRunning as exc:
        logger(f"scan skipped: {exc}")
        return
    logger(f"scan complete: {summary.format()}")


def run_scan(args: argparse.Namespace, logger, *, distill_fn=run_distillation) -> ScanSummary:
    state = load_state(args.state_path)
    for session_id in args.reset_failure:
        state["failures"].pop(session_id, None)
    if args.reset_failure:
        save_state(args.state_path, state)

    candidates = (
        [path.expanduser().resolve() for path in args.session_path]
        if args.session_path
        else list(iter_candidates(args.lookback_days, args.quiet_minutes))
    )
    summary = ScanSummary(candidates=len(candidates))
    logger(
        f"scan start: candidates={len(candidates)} limit={args.limit} "
        f"provider={os.environ.get('DISTILL_PROVIDER')} "
        f"model={os.environ.get('DISTILL_MODEL') or 'codex-default'}"
    )
    consecutive_failures = 0

    for path in candidates:
        if summary.handled >= args.limit:
            break

        parse_failure_id = f"parse:{path}"
        parse_failure = state["failures"].get(parse_failure_id)
        if parse_failure:
            if parse_failure.get("quarantined") and not args.retry_quarantined:
                summary.quarantined += 1
                continue
            if parse_failure.get("quarantined") and args.retry_quarantined:
                state["failures"].pop(parse_failure_id, None)
                parse_failure = None
                save_state(args.state_path, state)
            if parse_failure and not retry_due(parse_failure):
                summary.deferred += 1
                continue

        try:
            transcript = load_codex_transcript(path)
        except Exception as exc:
            summary.handled += 1
            summary.failures += 1
            consecutive_failures += 1
            logger(f"  failed to parse {path}: {exc}")
            failure = record_failure(
                state,
                parse_failure_id,
                path,
                f"transcript parse failed: {exc}",
                now=datetime.now(timezone.utc),
                max_attempts=args.max_attempts,
                backoff_seconds=args.backoff_seconds,
            )
            save_state(args.state_path, state)
            if failure["quarantined"]:
                summary.quarantined += 1
            if consecutive_failures >= args.circuit_breaker:
                summary.circuit_breaker = True
                logger(f"  circuit breaker activated after {consecutive_failures} consecutive failures")
                break
            continue

        session_id = transcript.session_id
        if parse_failure_id in state["failures"]:
            state["failures"].pop(parse_failure_id, None)
            save_state(args.state_path, state)
        existing = state["processed"].get(session_id)
        if existing and not args.reprocess:
            summary.deferred += 1
            continue

        failure = state["failures"].get(session_id)
        if failure:
            if failure.get("quarantined") and not args.retry_quarantined:
                summary.quarantined += 1
                continue
            if failure.get("quarantined") and args.retry_quarantined:
                state["failures"].pop(session_id, None)
                failure = None
                save_state(args.state_path, state)
            if failure and not retry_due(failure):
                summary.deferred += 1
                continue

        summary.handled += 1
        now = datetime.now(timezone.utc)
        if args.mark_existing:
            state["processed"][session_id] = processed_record(
                path,
                "baseline",
                now,
                reason="marked existing before watcher activation",
            )
            state["failures"].pop(session_id, None)
            save_state(args.state_path, state)
            summary.skips += 1
            consecutive_failures = 0
            continue

        if args.dry_run:
            logger(f"  dry-run would distill {session_id} from {path}")
            summary.skips += 1
            consecutive_failures = 0
            continue

        result = distill_fn(transcript, logger)
        if result.status == "failed":
            error = result.reason or "distillation failed without a reason"
            failure = record_failure(
                state,
                session_id,
                path,
                error,
                now=now,
                max_attempts=args.max_attempts,
                backoff_seconds=args.backoff_seconds,
            )
            save_state(args.state_path, state)
            summary.failures += 1
            consecutive_failures += 1
            if failure["quarantined"]:
                summary.quarantined += 1
                logger(f"  quarantined {session_id} after {failure['attempt_count']} failed attempts")
            else:
                logger(f"  retry for {session_id} deferred until {failure['next_retry_at']}")
            if consecutive_failures >= args.circuit_breaker:
                summary.circuit_breaker = True
                logger(f"  circuit breaker activated after {consecutive_failures} consecutive failures")
                break
            continue

        state["processed"][session_id] = processed_record(
            path,
            result.status,
            now,
            artifacts_stored=result.artifacts_stored,
            facts_stored=result.facts_stored,
            reason=result.reason,
        )
        state["failures"].pop(session_id, None)
        save_state(args.state_path, state)
        consecutive_failures = 0
        if result.status == "stored":
            summary.successes += 1
        elif result.status == "empty":
            summary.empty += 1
        else:
            summary.skips += 1

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan Codex session JSONL files and distill unprocessed sessions.")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--quiet-minutes", type=int, default=30)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--limit", type=positive_int, default=DEFAULT_SCAN_LIMIT)
    parser.add_argument("--provider", default="codex-cli")
    parser.add_argument("--model", default="gpt-5.5", help="Codex model selector.")
    parser.add_argument("--max-attempts", type=positive_int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--backoff-seconds", type=positive_int, default=DEFAULT_BACKOFF_SECONDS)
    parser.add_argument("--circuit-breaker", type=positive_int, default=DEFAULT_CIRCUIT_BREAKER)
    parser.add_argument("--session-path", type=Path, action="append", default=[])
    parser.add_argument("--retry-quarantined", action="store_true")
    parser.add_argument("--reset-failure", action="append", default=[], metavar="SESSION_ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--mark-existing", action="store_true", help="Mark matching sessions as baseline without distilling them.")
    return parser.parse_args()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


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
        return {"version": 2, "processed": {}, "failures": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"version": 2, "processed": {}, "failures": {}}
    if not isinstance(data, dict):
        return {"version": 2, "processed": {}, "failures": {}}
    data["version"] = 2
    data.setdefault("processed", {})
    data.setdefault("failures", {})
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)


def processed_record(
    path: Path,
    status: str,
    now: datetime,
    *,
    artifacts_stored: int = 0,
    facts_stored: int = 0,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "path": str(path),
        "agent": "codex",
        "status": status,
        "processed_at": now.isoformat(),
        "mtime": path.stat().st_mtime,
        "artifacts_stored": artifacts_stored,
        "facts_stored": facts_stored,
        "reason": reason,
    }


def record_failure(
    state: dict[str, Any],
    session_id: str,
    path: Path,
    error: str,
    *,
    now: datetime,
    max_attempts: int,
    backoff_seconds: int,
) -> dict[str, Any]:
    previous = state["failures"].get(session_id) or {}
    attempt_count = int(previous.get("attempt_count", 0)) + 1
    quarantined = attempt_count >= max_attempts
    delay = min(backoff_seconds * (2 ** (attempt_count - 1)), 7 * 24 * 60 * 60)
    entry = {
        "path": str(path),
        "attempt_count": attempt_count,
        "last_attempt_at": now.isoformat(),
        "error_summary": " ".join(error.split())[:1000],
        "next_retry_at": None if quarantined else (now + timedelta(seconds=delay)).isoformat(),
        "quarantined": quarantined,
    }
    state["failures"][session_id] = entry
    return entry


def retry_due(failure: dict[str, Any], now: datetime | None = None) -> bool:
    if failure.get("quarantined"):
        return False
    next_retry_at = failure.get("next_retry_at")
    if not next_retry_at:
        return True
    current = now or datetime.now(timezone.utc)
    try:
        due_at = datetime.fromisoformat(next_retry_at)
    except (TypeError, ValueError):
        return True
    return due_at <= current


if __name__ == "__main__":
    main()
