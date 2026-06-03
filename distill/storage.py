from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from distill.logs import Logger, null_logger
from distill.provenance import memory_provenance_metadata, provenance_tags
from distill.transcript_schema import NormalizedTranscript


def default_db_path() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/mcp-memory/sqlite_vec.db")
    if sys.platform.startswith("linux"):
        return os.path.expanduser("~/.local/share/mcp-memory/sqlite_vec.db")
    return os.path.expanduser("~/.mcp-memory/sqlite_vec.db")


async def store_results(
    distilled: dict,
    transcript: NormalizedTranscript,
    logger: Logger = null_logger,
    *,
    distiller_provider: Optional[str] = None,
    distiller_model: Optional[str] = None,
) -> tuple[int, int]:
    from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
    from mcp_memory_service.services.memory_service import MemoryService

    db_path = os.environ.get("MCP_MEMORY_SQLITE_VEC_PATH") or default_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    storage = SqliteVecMemoryStorage(db_path=db_path)
    await storage.initialize()
    service = MemoryService(storage)

    # SqliteVecMemoryStorage applies WAL and busy_timeout pragmas during
    # initialize(); keep storage construction centralized so concurrency
    # behavior is not reimplemented by agent wrappers.
    sid_short = transcript.session_id[:8]
    base_metadata = memory_provenance_metadata(
        transcript.metadata,
        agent=transcript.agent,
        session_id=transcript.session_id,
        source_path=transcript.source_path,
        distiller_provider=distiller_provider,
        distiller_model=distiller_model,
    )
    base_tags = provenance_tags(base_metadata, transcript.agent)
    artifacts_stored = 0
    facts_stored = 0

    for artifact in distilled.get("artifacts", []) or []:
        slug = (artifact.get("client_or_project") or "unknown").strip().lower()
        # Per-domain slug for multi-domain projects. Distinct from `client_or_project`:
        # `client_or_project=acme, domain=storefront` means the artifact is
        # scoped to the storefront.acme.com site owned by the acme project.
        domain = (artifact.get("domain") or "").strip().lower() or None
        artifact_type = (artifact.get("type") or "artifact").strip().lower()
        path = artifact.get("path")
        summary = (artifact.get("summary") or "").strip()
        if not summary:
            continue

        content_header = f"ARTIFACT: {artifact_type} for {slug}"
        if domain and domain != slug:
            content_header += f" (domain: {domain})"
        content_parts = [
            content_header,
            f"path: {path}" if path else None,
            summary,
        ]
        content = "\n".join(part for part in content_parts if part)
        tag_list = [
            "artifact",
            *base_tags,
            f"client:{slug}",
            f"type:{artifact_type}",
            f"session-{sid_short}",
        ]
        if domain and domain != slug:
            tag_list.append(f"domain:{domain}")
        tags = _dedupe_tags(tag_list)
        metadata = {
            **base_metadata,
            "client_or_project": slug,
            "domain": domain,
            "artifact_type": artifact_type,
            "path": path,
        }
        result = await service.store_memory(
            content=content,
            tags=tags,
            memory_type="artifact",
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
        if result.get("success"):
            artifacts_stored += 1
            logger(f"  artifact stored [{slug}/{artifact_type}]: {summary[:80]}")
        else:
            logger(f"  artifact store failed: {result.get('error')}")

    for fact in distilled.get("facts", []) or []:
        content = (fact.get("content") or "").strip()
        if not content:
            continue
        raw_tags = fact.get("tags", [])
        fact_tags = [raw_tags] if isinstance(raw_tags, str) else list(raw_tags or [])
        tags = _dedupe_tags(fact_tags + [*base_tags, "session-distill", f"session-{sid_short}"])
        result = await service.store_memory(
            content=content,
            tags=tags,
            memory_type=fact.get("memory_type", "note"),
            metadata=base_metadata,
        )
        if result.get("success"):
            facts_stored += 1
            logger(f"  fact stored: {content[:80]}")
        else:
            logger(f"  fact store failed: {result.get('error')}")

    return artifacts_stored, facts_stored


def record_distill_run(
    *,
    transcript: NormalizedTranscript,
    usage: Any,
    status: str,
    reason: Optional[str] = None,
    transcript_chars: int = 0,
    prompt_chars: int = 0,
    artifacts_returned: int = 0,
    facts_returned: int = 0,
    artifacts_stored: int = 0,
    facts_stored: int = 0,
    run_started_at: Optional[datetime] = None,
    run_ended_at: Optional[datetime] = None,
    logger: Logger = null_logger,
) -> None:
    db_path = os.environ.get("MCP_MEMORY_SQLITE_VEC_PATH") or default_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    started = run_started_at or datetime.now().astimezone()
    ended = run_ended_at or datetime.now().astimezone()
    metadata = memory_provenance_metadata(
        transcript.metadata,
        agent=transcript.agent,
        session_id=transcript.session_id,
        source_path=transcript.source_path,
        distiller_provider=getattr(usage, "provider", None),
        distiller_model=getattr(usage, "model", None),
    )

    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.executescript(_DISTILL_RUNS_SCHEMA)
            conn.execute(
                """
                INSERT INTO distill_runs (
                    run_started_at,
                    run_ended_at,
                    source_agent,
                    source_surface,
                    source_session_id,
                    source_transcript_path,
                    source_cwd,
                    source_started_at,
                    source_ended_at,
                    ingestion_method,
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    cache_creation_input_tokens,
                    cache_read_input_tokens,
                    total_tokens,
                    wall_seconds,
                    status,
                    reason,
                    transcript_chars,
                    prompt_chars,
                    artifacts_returned,
                    facts_returned,
                    artifacts_stored,
                    facts_stored,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started.isoformat(timespec="seconds"),
                    ended.isoformat(timespec="seconds"),
                    metadata.get("source_agent", transcript.agent),
                    metadata.get("source_surface"),
                    metadata.get("source_session_id", transcript.session_id),
                    metadata.get("source_transcript_path"),
                    metadata.get("source_cwd"),
                    metadata.get("source_started_at"),
                    metadata.get("source_ended_at"),
                    metadata.get("ingestion_method"),
                    getattr(usage, "provider", None),
                    getattr(usage, "model", None),
                    getattr(usage, "input_tokens", None),
                    getattr(usage, "output_tokens", None),
                    getattr(usage, "cache_creation_input_tokens", None),
                    getattr(usage, "cache_read_input_tokens", None),
                    getattr(usage, "total_tokens", None),
                    getattr(usage, "wall_seconds", None),
                    status,
                    reason,
                    transcript_chars,
                    prompt_chars,
                    artifacts_returned,
                    facts_returned,
                    artifacts_stored,
                    facts_stored,
                    json.dumps(metadata, sort_keys=True),
                ),
            )
    except Exception as exc:
        logger(f"  distill run record failed: {exc}")


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for tag in tags:
        if not tag or tag in seen:
            continue
        seen.add(tag)
        deduped.append(tag)
    return deduped


_DISTILL_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS distill_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_started_at TEXT NOT NULL,
    run_ended_at TEXT NOT NULL,
    source_agent TEXT NOT NULL,
    source_surface TEXT,
    source_session_id TEXT NOT NULL,
    source_transcript_path TEXT,
    source_cwd TEXT,
    source_started_at TEXT,
    source_ended_at TEXT,
    ingestion_method TEXT,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_creation_input_tokens INTEGER,
    cache_read_input_tokens INTEGER,
    total_tokens INTEGER,
    wall_seconds REAL,
    status TEXT NOT NULL,
    reason TEXT,
    transcript_chars INTEGER DEFAULT 0,
    prompt_chars INTEGER DEFAULT 0,
    artifacts_returned INTEGER DEFAULT 0,
    facts_returned INTEGER DEFAULT 0,
    artifacts_stored INTEGER DEFAULT 0,
    facts_stored INTEGER DEFAULT 0,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_distill_runs_started ON distill_runs(run_started_at);
CREATE INDEX IF NOT EXISTS idx_distill_runs_agent ON distill_runs(source_agent);
CREATE INDEX IF NOT EXISTS idx_distill_runs_provider ON distill_runs(provider);
CREATE INDEX IF NOT EXISTS idx_distill_runs_status ON distill_runs(status);
"""
