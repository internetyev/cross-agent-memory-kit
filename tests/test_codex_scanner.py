from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from distill.engine import DistillationRunResult
from wrappers.codex_session_scan import (
    ScannerAlreadyRunning,
    ScannerLock,
    load_state,
    record_failure,
    retry_due,
    run_scan,
)


class CodexScannerTests(unittest.TestCase):
    def test_failure_attempts_back_off_then_quarantine(self) -> None:
        state = {"version": 2, "processed": {}, "failures": {}}
        now = datetime(2026, 6, 29, tzinfo=timezone.utc)
        path = Path("/tmp/session.jsonl")

        first = record_failure(
            state,
            "session-1",
            path,
            "provider down",
            now=now,
            max_attempts=3,
            backoff_seconds=60,
        )
        self.assertEqual(first["attempt_count"], 1)
        self.assertEqual(first["next_retry_at"], (now + timedelta(seconds=60)).isoformat())
        self.assertFalse(first["quarantined"])
        self.assertFalse(retry_due(first, now + timedelta(seconds=59)))
        self.assertTrue(retry_due(first, now + timedelta(seconds=60)))

        second = record_failure(
            state,
            "session-1",
            path,
            "provider still down",
            now=now + timedelta(seconds=60),
            max_attempts=3,
            backoff_seconds=60,
        )
        self.assertEqual(second["next_retry_at"], (now + timedelta(seconds=180)).isoformat())

        third = record_failure(
            state,
            "session-1",
            path,
            "provider still down",
            now=now + timedelta(seconds=180),
            max_attempts=3,
            backoff_seconds=60,
        )
        self.assertEqual(third["attempt_count"], 3)
        self.assertTrue(third["quarantined"])
        self.assertIsNone(third["next_retry_at"])

    def test_state_migration_adds_failure_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            path.write_text(json.dumps({"version": 1, "processed": {"a": {}}}))
            state = load_state(path)
        self.assertEqual(state["version"], 2)
        self.assertEqual(state["failures"], {})

    def test_circuit_breaker_stops_consecutive_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = make_paths(Path(tmpdir), 4)
            args = make_args(Path(tmpdir), paths, limit=4, circuit_breaker=2)
            transcripts = [SimpleNamespace(session_id=f"session-{index}") for index in range(4)]
            failed = DistillationRunResult(status="failed", reason="provider broken")

            with patch(
                "wrappers.codex_session_scan.load_codex_transcript",
                side_effect=transcripts,
            ):
                summary = run_scan(args, lambda _message: None, distill_fn=lambda _t, _l: failed)

            self.assertEqual(summary.handled, 2)
            self.assertEqual(summary.failures, 2)
            self.assertTrue(summary.circuit_breaker)
            state = load_state(args.state_path)
            self.assertEqual(len(state["failures"]), 2)

    def test_scan_limit_is_finite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = make_paths(Path(tmpdir), 4)
            args = make_args(Path(tmpdir), paths, limit=2, circuit_breaker=3)
            transcripts = [SimpleNamespace(session_id=f"session-{index}") for index in range(4)]
            empty = DistillationRunResult(status="empty")

            with patch(
                "wrappers.codex_session_scan.load_codex_transcript",
                side_effect=transcripts,
            ):
                summary = run_scan(args, lambda _message: None, distill_fn=lambda _t, _l: empty)

            self.assertEqual(summary.handled, 2)
            self.assertEqual(summary.empty, 2)
            self.assertEqual(len(load_state(args.state_path)["processed"]), 2)

    def test_parse_failure_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = make_paths(Path(tmpdir), 1)
            args = make_args(Path(tmpdir), paths, limit=1, circuit_breaker=3)
            with patch(
                "wrappers.codex_session_scan.load_codex_transcript",
                side_effect=ValueError("broken transcript"),
            ):
                summary = run_scan(args, lambda _message: None)

            self.assertEqual(summary.failures, 1)
            failures = load_state(args.state_path)["failures"]
            failure_id = f"parse:{paths[0].resolve()}"
            self.assertIn(failure_id, failures)
            self.assertEqual(failures[failure_id]["attempt_count"], 1)

    def test_single_instance_lock_rejects_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "scanner.lock"
            with ScannerLock(lock_path):
                with self.assertRaises(ScannerAlreadyRunning):
                    with ScannerLock(lock_path):
                        pass


def make_paths(root: Path, count: int) -> list[Path]:
    paths = []
    for index in range(count):
        path = root / f"session-{index}.jsonl"
        path.write_text("{}\n")
        paths.append(path)
    return paths


def make_args(root: Path, paths: list[Path], *, limit: int, circuit_breaker: int):
    return SimpleNamespace(
        state_path=root / "state.json",
        session_path=paths,
        lookback_days=2,
        quiet_minutes=0,
        limit=limit,
        reset_failure=[],
        reprocess=False,
        retry_quarantined=False,
        mark_existing=False,
        dry_run=False,
        max_attempts=3,
        backoff_seconds=60,
        circuit_breaker=circuit_breaker,
    )


if __name__ == "__main__":
    unittest.main()
