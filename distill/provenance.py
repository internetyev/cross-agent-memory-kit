from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

PROVENANCE_VERSION = 1


def build_source_provenance(
    *,
    source_agent: str,
    source_session_id: str,
    source_path: Optional[str | Path],
    source_cwd: Optional[str],
    source_started_at: Optional[str],
    source_ended_at: Optional[str],
    source_surface: str,
    ingestion_method: str,
    source_provider: Optional[str] = None,
    source_model: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return normalized provenance metadata for a transcript source."""
    provenance = {
        "provenance_version": PROVENANCE_VERSION,
        "source_agent": source_agent,
        "source_surface": source_surface,
        "source_provider": source_provider,
        "source_model": source_model,
        "source_transcript_path": str(source_path) if source_path else None,
        "source_session_id": source_session_id,
        "source_cwd": source_cwd,
        "source_started_at": source_started_at,
        "source_ended_at": source_ended_at,
        "ingestion_method": ingestion_method,
    }
    if extra:
        provenance.update(extra)
    return {key: value for key, value in provenance.items() if value is not None}


def memory_provenance_metadata(
    transcript_metadata: dict[str, Any],
    *,
    agent: str,
    session_id: str,
    source_path: Optional[str | Path],
    distiller_provider: Optional[str],
    distiller_model: Optional[str],
) -> dict[str, Any]:
    """Return storage metadata with canonical provenance plus legacy aliases."""
    metadata = dict(transcript_metadata)
    metadata.update(
        {
            "source": "session-distill",
            "agent": agent,
            "session_id": session_id,
            "source_path": str(source_path) if source_path else None,
            "source_agent": metadata.get("source_agent", agent),
            "source_session_id": metadata.get("source_session_id", session_id),
            "source_transcript_path": metadata.get(
                "source_transcript_path",
                str(source_path) if source_path else None,
            ),
            "distiller_provider": distiller_provider,
            "distiller_model": distiller_model,
        }
    )
    return {key: value for key, value in metadata.items() if value is not None}


def provenance_tags(metadata: dict[str, Any], fallback_agent: str) -> list[str]:
    tags = [
        f"agent:{metadata.get('source_agent') or fallback_agent}",
        _tag("surface", metadata.get("source_surface")),
        _tag("provider", metadata.get("source_provider")),
        _tag("ingestion", metadata.get("ingestion_method")),
        _tag("distiller", metadata.get("distiller_provider")),
    ]
    return [tag for tag in tags if tag]


def _tag(prefix: str, value: Any) -> Optional[str]:
    if not value:
        return None
    return f"{prefix}:{str(value).strip().lower()}"
