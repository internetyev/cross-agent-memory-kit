from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from distill.provenance import build_source_provenance
from distill.transcript_schema import NormalizedTranscript, TranscriptMessage


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
        return "\n".join(parts)
    return ""


def load_cursor_transcript(path: str | Path) -> NormalizedTranscript:
    source_path = Path(path)
    messages: list[TranscriptMessage] = []
    session_id = source_path.stem
    started_at = None
    ended_at = None
    metadata: dict[str, Any] = {}

    with source_path.open() as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            timestamp = row.get("timestamp")
            started_at = started_at or timestamp
            ended_at = timestamp or ended_at

            role = row.get("role")
            if role not in {"user", "assistant"}:
                continue

            payload = row.get("message") or {}
            text = _content_text(payload.get("content"))
            if not text:
                continue
            messages.append(TranscriptMessage(role=role, text=text, timestamp=timestamp))

            model = row.get("model")
            if model and "model" not in metadata:
                metadata["model"] = model

    metadata = build_source_provenance(
        source_agent="cursor",
        source_session_id=session_id,
        source_path=source_path,
        source_cwd=None,
        source_started_at=started_at,
        source_ended_at=ended_at,
        source_surface="cli",
        source_provider="anthropic",
        source_model=metadata.get("model"),
        ingestion_method="cursor-scanner",
        extra=metadata,
    )

    return NormalizedTranscript(
        agent="cursor",
        session_id=session_id,
        source_path=source_path,
        messages=messages,
        cwd=None,
        started_at=started_at,
        ended_at=ended_at,
        metadata=metadata,
    )
