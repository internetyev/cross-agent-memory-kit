from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from distill.adapters.claude import load_claude_transcript
from distill.adapters.codex import load_codex_transcript
from distill.adapters.cursor import load_cursor_transcript
from distill.adapters.fake import load_fake_transcript
from distill.providers import DistillerUsage, _usage_from_codex_stdout, _usage_from_mapping
from distill.storage import _identity_tags_and_metadata, record_distill_run
from wrappers.usage_report import build_report

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


class TranscriptAdapterTests(unittest.TestCase):
    def test_fake_adapter_contract(self) -> None:
        transcript = load_fake_transcript()
        self.assertEqual(transcript.agent, "fake")
        self.assertEqual(transcript.session_id, "fake-session")
        self.assertEqual([message.role for message in transcript.messages], ["user", "assistant"])

    def test_claude_adapter_normalizes_messages(self) -> None:
        transcript = load_claude_transcript(FIXTURES / "claude_minimal.jsonl", session_id="claude-session-1")
        self.assertEqual(transcript.agent, "claude")
        self.assertEqual(transcript.session_id, "claude-session-1")
        self.assertEqual(transcript.cwd, "/tmp/claude")
        self.assertEqual(transcript.metadata["source_agent"], "claude")
        self.assertEqual(transcript.metadata["source_surface"], "cli")
        self.assertEqual(transcript.metadata["source_provider"], "anthropic")
        self.assertEqual(transcript.metadata["ingestion_method"], "session-end-hook")
        self.assertIn("[USER]\nPlease add", transcript.user_assistant_text())
        self.assertIn("[ASSISTANT]\nAdded", transcript.user_assistant_text())

    def test_codex_adapter_normalizes_messages(self) -> None:
        transcript = load_codex_transcript(FIXTURES / "codex_minimal.jsonl")
        self.assertEqual(transcript.agent, "codex")
        self.assertEqual(transcript.session_id, "codex-session-1")
        self.assertEqual(transcript.cwd, "/tmp/codex")
        self.assertEqual(transcript.metadata["originator"], "Codex Desktop")
        self.assertEqual(transcript.metadata["source_agent"], "codex")
        self.assertEqual(transcript.metadata["source_surface"], "desktop-app")
        self.assertEqual(transcript.metadata["source_provider"], "openai")
        self.assertEqual(transcript.metadata["ingestion_method"], "codex-scanner")
        self.assertIn("[USER]\nCreate", transcript.user_assistant_text())
        self.assertIn("[ASSISTANT]\nCreated", transcript.user_assistant_text())

    def test_cursor_adapter_normalizes_messages(self) -> None:
        transcript = load_cursor_transcript(FIXTURES / "cursor_minimal.jsonl")
        self.assertEqual(transcript.agent, "cursor")
        self.assertEqual(transcript.session_id, "cursor_minimal")
        self.assertIsNone(transcript.cwd)
        self.assertEqual(transcript.metadata["source_agent"], "cursor")
        self.assertEqual(transcript.metadata["source_surface"], "cli")
        self.assertEqual(transcript.metadata["source_provider"], "anthropic")
        self.assertEqual(transcript.metadata["ingestion_method"], "cursor-scanner")
        self.assertIn("[USER]\nPlease create", transcript.user_assistant_text())
        self.assertIn("[ASSISTANT]\nCreated", transcript.user_assistant_text())

    def test_empty_tool_only_transcript_has_no_messages(self) -> None:
        transcript = load_claude_transcript(FIXTURES / "empty_tool_only.jsonl")
        self.assertEqual(transcript.messages, [])
        self.assertEqual(transcript.user_assistant_text(), "")

    def test_malformed_lines_are_ignored(self) -> None:
        transcript = load_claude_transcript(FIXTURES / "malformed_line.jsonl")
        self.assertEqual(len(transcript.messages), 1)
        self.assertIn("valid line", transcript.user_assistant_text())

    def test_usage_mapping_normalizes_common_fields(self) -> None:
        logs = []
        usage = _usage_from_mapping(
            "claude-cli",
            "haiku",
            {
                "input_tokens": "1,234",
                "output_tokens": 56,
                "cache_creation_input_tokens": 7,
                "cache_read_input_tokens": 8,
            },
            time.perf_counter(),
            logs.append,
        )
        self.assertEqual(usage.input_tokens, 1234)
        self.assertEqual(usage.output_tokens, 56)
        self.assertEqual(usage.cache_creation_input_tokens, 7)
        self.assertEqual(usage.cache_read_input_tokens, 8)
        self.assertEqual(usage.total_tokens, 1305)

    def test_codex_usage_parser_handles_tokens_used_line(self) -> None:
        logs = []
        usage = _usage_from_codex_stdout(
            "codex-cli",
            "gpt-test",
            "work\n tokens used: input=321 output=45 total=366\n{\"facts\":[],\"artifacts\":[]}",
            time.perf_counter(),
            logs.append,
        )
        self.assertEqual(usage.input_tokens, 321)
        self.assertEqual(usage.output_tokens, 45)
        self.assertEqual(usage.total_tokens, 366)

    def test_record_distill_run_falls_back_when_metadata_missing(self) -> None:
        transcript = load_fake_transcript()
        usage = DistillerUsage.zero("fake-provider", "fake-model")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.db")
            old_path = os.environ.get("MCP_MEMORY_SQLITE_VEC_PATH")
            os.environ["MCP_MEMORY_SQLITE_VEC_PATH"] = db_path
            try:
                record_distill_run(
                    transcript=transcript,
                    usage=usage,
                    status="skipped",
                    reason="test",
                    transcript_chars=10,
                )
                with sqlite3.connect(db_path) as conn:
                    row = conn.execute(
                        "SELECT source_agent, source_session_id, provider, model, status, total_tokens FROM distill_runs"
                    ).fetchone()
                self.assertEqual(row, ("fake", "fake-session", "fake-provider", "fake-model", "skipped", 0))
            finally:
                restore_env(old_path)

    def test_usage_report_reads_distill_runs_table(self) -> None:
        transcript = load_fake_transcript()
        usage = DistillerUsage(
            provider="claude-cli",
            model="haiku",
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=5,
            total_tokens=125,
            wall_seconds=2.5,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "memory.db")
            old_path = os.environ.get("MCP_MEMORY_SQLITE_VEC_PATH")
            os.environ["MCP_MEMORY_SQLITE_VEC_PATH"] = db_path
            try:
                record_distill_run(transcript=transcript, usage=usage, status="stored")
                start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                report = build_report(
                    db_path=db_path,
                    start=start,
                    end=start + timedelta(days=1),
                    label="today",
                    agent=None,
                    provider=None,
                    statuses=None,
                    top=5,
                )
                self.assertEqual(report["totals"]["run_count"], 1)
                self.assertEqual(report["totals"]["total_tokens"], 125)
                self.assertEqual(report["by_provider"][0]["provider"], "claude-cli")
            finally:
                restore_env(old_path)


class IdentityTaggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in ("MEMORY_OWNER", "MEMORY_SCOPE", "MEMORY_DEFAULT_SCOPE")}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_unset_owner_yields_nothing(self) -> None:
        tags, metadata = _identity_tags_and_metadata()
        self.assertEqual(tags, [])
        self.assertEqual(metadata, {})

    def test_owner_and_default_scope_tagged(self) -> None:
        os.environ["MEMORY_OWNER"] = "Alice"
        os.environ["MEMORY_DEFAULT_SCOPE"] = "Private"
        tags, metadata = _identity_tags_and_metadata()
        self.assertIn("owner:alice", tags)
        self.assertIn("scope:private", tags)
        self.assertEqual(metadata["owner"], "alice")
        self.assertEqual(metadata["memory_scope"], "private")

    def test_memory_scope_overrides_default_scope(self) -> None:
        os.environ["MEMORY_OWNER"] = "bob"
        os.environ["MEMORY_DEFAULT_SCOPE"] = "private"
        os.environ["MEMORY_SCOPE"] = "shared"
        tags, metadata = _identity_tags_and_metadata()
        self.assertIn("scope:shared", tags)
        self.assertNotIn("scope:private", tags)
        self.assertEqual(metadata["memory_scope"], "shared")


def restore_env(old_path: str | None) -> None:
    if old_path is None:
        os.environ.pop("MCP_MEMORY_SQLITE_VEC_PATH", None)
    else:
        os.environ["MCP_MEMORY_SQLITE_VEC_PATH"] = old_path


if __name__ == "__main__":
    unittest.main()
