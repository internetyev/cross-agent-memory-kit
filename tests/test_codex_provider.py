from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from distill.providers import _call_codex_cli, traced


class CodexProviderTests(unittest.TestCase):
    def run_provider(self, final_message: str | None, *, returncode: int = 0, stderr: str = ""):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            if final_message is not None:
                output_path = Path(cmd[cmd.index("--output-last-message") + 1])
                output_path.write_text(final_message)
            return SimpleNamespace(
                returncode=returncode,
                stdout="tokens used: input=12 output=4 total=16\n",
                stderr=stderr,
            )

        logs = []
        with patch("distill.providers.shutil.which", return_value="/usr/local/bin/codex"):
            with patch("distill.providers.subprocess.run", side_effect=fake_run):
                result = _call_codex_cli("x" * 200_000, "gpt-test", logs.append)
        return result, captured, logs

    def test_successful_final_message_parsing(self) -> None:
        result, _captured, _logs = self.run_provider('{"artifacts":[],"facts":[]}')
        self.assertEqual(result.data, {"artifacts": [], "facts": []})
        self.assertIsNone(result.error)
        self.assertEqual(result.usage.total_tokens, 16)

    def test_prompt_is_sent_through_stdin(self) -> None:
        prompt = "x" * 200_000
        result, captured, _logs = self.run_provider('{"artifacts":[],"facts":[]}')
        self.assertIsNotNone(result.data)
        self.assertEqual(captured["kwargs"]["input"], prompt)
        self.assertEqual(captured["cmd"][-1], "-")
        self.assertNotIn(prompt, captured["cmd"])
        self.assertIn("--ignore-user-config", captured["cmd"])
        self.assertIn("--output-schema", captured["cmd"])

    def test_zero_exit_with_empty_output_is_actionable(self) -> None:
        result, _captured, _logs = self.run_provider(None)
        self.assertIsNone(result.data)
        self.assertIn("no final message", result.error or "")

    def test_nonzero_exit_preserves_diagnostics(self) -> None:
        result, _captured, _logs = self.run_provider(
            None,
            returncode=2,
            stderr="unknown model selector",
        )
        self.assertIsNone(result.data)
        self.assertIn("exit 2", result.error or "")
        self.assertIn("unknown model selector", result.error or "")

    def test_malformed_json_is_actionable(self) -> None:
        result, _captured, _logs = self.run_provider("{broken")
        self.assertIsNone(result.data)
        self.assertIn("malformed JSON", result.error or "")

    def test_timeout_is_actionable(self) -> None:
        logs = []
        with patch("distill.providers.shutil.which", return_value="/usr/local/bin/codex"):
            with patch(
                "distill.providers.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["codex"], 600),
            ):
                result = _call_codex_cli("prompt", None, logs.append)
        self.assertIn("timed out", result.error or "")

    def test_tracing_is_disabled_without_explicit_opt_in(self) -> None:
        old_tracing = os.environ.get("LANGSMITH_TRACING")
        old_legacy = os.environ.get("LANGCHAIN_TRACING_V2")
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        try:
            def sample():
                return "ok"

            wrapped = traced("test.disabled")(sample)
            self.assertIs(wrapped, sample)
            self.assertEqual(wrapped(), "ok")
        finally:
            restore_env("LANGSMITH_TRACING", old_tracing)
            restore_env("LANGCHAIN_TRACING_V2", old_legacy)


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
