#!/usr/bin/env python3
"""
Claude Code SessionEnd wrapper for the shared mcp-memory-service distiller.

This wrapper owns Claude-specific trigger behavior only:
  - read Claude hook JSON from stdin
  - locate the Claude transcript
  - use the Claude transcript adapter
  - log to the historical Claude hook log path

Distillation rules, provider calls, registry loading, and storage live in
`distill/` so other agents can reuse the same behavior.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from distill.adapters.claude import load_claude_transcript
from distill.engine import run_distillation
from distill.logs import make_file_logger

LOG_PATH = Path.home() / ".claude" / "logs" / "distill-session.log"


def main() -> None:
    logger = make_file_logger(LOG_PATH)

    try:
        hook_input = json.load(sys.stdin)
    except Exception as exc:
        logger(f"could not parse hook stdin: {exc}")
        return

    session_id = hook_input.get("session_id", "unknown")
    transcript_path = hook_input.get("transcript_path") or hook_input.get("transcriptPath")

    if not transcript_path or not os.path.exists(transcript_path):
        cwd = hook_input.get("cwd", os.getcwd())
        slug = cwd.replace("/", "-")
        candidate = Path.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl"
        if candidate.exists():
            transcript_path = str(candidate)
        else:
            logger(f"no transcript found for session {session_id} at {candidate}")
            return

    transcript = load_claude_transcript(transcript_path, session_id=session_id)
    run_distillation(transcript, logger)


if __name__ == "__main__":
    main()
