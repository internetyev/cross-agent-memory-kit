from __future__ import annotations

from pathlib import Path

from distill.transcript_schema import NormalizedTranscript, TranscriptMessage


def load_fake_transcript(source_path: str | Path | None = None) -> NormalizedTranscript:
    path = Path(source_path) if source_path else None
    return NormalizedTranscript(
        agent="fake",
        session_id="fake-session",
        source_path=path,
        messages=[
            TranscriptMessage(role="user", text="Build a reusable memory distiller."),
            TranscriptMessage(role="assistant", text="Created a central engine and adapters."),
        ],
        cwd="/tmp/fake",
        started_at="2026-05-06T00:00:00Z",
        ended_at="2026-05-06T00:05:00Z",
        metadata={"fixture": True},
    )
