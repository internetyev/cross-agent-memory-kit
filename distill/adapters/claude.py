from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from distill.provenance import build_source_provenance
from distill.transcript_schema import NormalizedTranscript, TranscriptMessage


def _content_text(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if text:
                    parts.append(text)
        return parts
    return []


def load_claude_transcript(path: str | Path, session_id: str | None = None) -> NormalizedTranscript:
    source_path = Path(path)
    messages: list[TranscriptMessage] = []
    started_at = None
    ended_at = None
    cwd = None

    with source_path.open() as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            timestamp = row.get("timestamp")
            started_at = started_at or timestamp
            ended_at = timestamp or ended_at
            cwd = cwd or row.get("cwd")

            role = row.get("type")
            if role not in {"user", "assistant"}:
                continue

            content = row.get("content") or row.get("message", {}).get("content")
            for text in _content_text(content):
                messages.append(TranscriptMessage(role=role, text=text, timestamp=timestamp))

    normalized_session_id = session_id or source_path.stem
    metadata = build_source_provenance(
        source_agent="claude",
        source_session_id=normalized_session_id,
        source_path=source_path,
        source_cwd=cwd,
        source_started_at=started_at,
        source_ended_at=ended_at,
        source_surface="cli",
        source_provider="anthropic",
        ingestion_method="session-end-hook",
    )

    return NormalizedTranscript(
        agent="claude",
        session_id=normalized_session_id,
        source_path=source_path,
        messages=messages,
        cwd=cwd,
        started_at=started_at,
        ended_at=ended_at,
        metadata=metadata,
    )
