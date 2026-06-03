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
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"text", "input_text", "output_text"}:
                text = item.get("text")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return ""


def load_codex_transcript(path: str | Path) -> NormalizedTranscript:
    source_path = Path(path)
    messages: list[TranscriptMessage] = []
    session_id = source_path.stem
    started_at = None
    ended_at = None
    cwd = None
    metadata: dict[str, Any] = {}

    with source_path.open() as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            timestamp = row.get("timestamp")
            started_at = started_at or timestamp
            ended_at = timestamp or ended_at

            if row.get("type") == "session_meta":
                payload = row.get("payload") or {}
                session_id = payload.get("id") or session_id
                cwd = cwd or payload.get("cwd")
                metadata.update({
                    "originator": payload.get("originator"),
                    "cli_version": payload.get("cli_version"),
                    "codex_source": payload.get("source"),
                    "model_provider": payload.get("model_provider"),
                    "source_model": payload.get("model") or payload.get("model_slug"),
                })
                continue

            payload = row.get("payload") or {}
            if row.get("type") != "response_item" or payload.get("type") != "message":
                continue

            role = payload.get("role")
            if role not in {"user", "assistant"}:
                continue

            text = _content_text(payload.get("content"))
            if text:
                messages.append(TranscriptMessage(role=role, text=text, timestamp=timestamp))

    source_surface = "desktop-app" if metadata.get("codex_source") == "desktop" else "cli"
    metadata = build_source_provenance(
        source_agent="codex",
        source_session_id=session_id,
        source_path=source_path,
        source_cwd=cwd,
        source_started_at=started_at,
        source_ended_at=ended_at,
        source_surface=source_surface,
        source_provider=metadata.get("model_provider"),
        source_model=metadata.get("source_model"),
        ingestion_method="codex-scanner",
        extra=metadata,
    )

    return NormalizedTranscript(
        agent="codex",
        session_id=session_id,
        source_path=source_path,
        messages=messages,
        cwd=cwd,
        started_at=started_at,
        ended_at=ended_at,
        metadata={k: v for k, v in metadata.items() if v is not None},
    )
