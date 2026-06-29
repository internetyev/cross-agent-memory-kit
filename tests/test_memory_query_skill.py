from __future__ import annotations

import unittest
from pathlib import Path


class MemoryQuerySkillTests(unittest.TestCase):
    def test_normal_lookup_does_not_invoke_scanner(self) -> None:
        skill = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "mcp-memory-query"
            / "SKILL.md"
        ).read_text()
        self.assertIn("Retrieval is read-only by default", skill)
        self.assertIn("Only refresh session memories when the user explicitly asks", skill)
        self.assertNotIn("Before any query, run the Codex session scanner", skill)
        self.assertNotIn("--lookback-days 3650", skill)


if __name__ == "__main__":
    unittest.main()
