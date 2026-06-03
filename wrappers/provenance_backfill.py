#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from distill.provenance import PROVENANCE_VERSION
from distill.storage import default_db_path


def main() -> None:
    args = parse_args()
    db_path = args.db_path or default_db_path()
    report = inspect_memories(db_path, apply=args.apply, limit=args.limit)
    print_report(report, applied=args.apply)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit/backfill normalized memory provenance metadata.")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit for testing.")
    parser.add_argument("--apply", action="store_true", help="Rewrite metadata/tags. Default is dry-run.")
    return parser.parse_args()


def inspect_memories(db_path: str, *, apply: bool, limit: int) -> dict[str, Any]:
    if not Path(db_path).exists():
        return {"db_path": db_path, "error": "database not found"}

    counts: Counter[str] = Counter()
    updated = 0
    samples: dict[str, list[str]] = {}
    query = "SELECT id, content_hash, tags, metadata FROM memories WHERE deleted_at IS NULL ORDER BY id"
    if limit > 0:
        query += f" LIMIT {limit}"

    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        rows = conn.execute(query).fetchall()
        for memory_id, content_hash, tags_raw, metadata_raw in rows:
            tags = parse_tags(tags_raw)
            metadata = parse_metadata(metadata_raw)
            agent = classify_agent(tags, metadata)
            counts[agent] += 1
            samples.setdefault(agent, [])
            if len(samples[agent]) < 5:
                samples[agent].append(content_hash)

            new_metadata, new_tags = backfilled(metadata, tags, agent)
            if new_metadata == metadata and new_tags == tags:
                continue
            updated += 1
            if apply:
                conn.execute(
                    "UPDATE memories SET metadata = ?, tags = ?, updated_at = COALESCE(updated_at, created_at) WHERE id = ?",
                    (json.dumps(new_metadata, sort_keys=True), ",".join(new_tags), memory_id),
                )

    return {
        "db_path": db_path,
        "inspected": sum(counts.values()),
        "would_update": updated,
        "counts": dict(counts),
        "samples": samples,
    }


def backfilled(metadata: dict[str, Any], tags: list[str], agent: str) -> tuple[dict[str, Any], list[str]]:
    if agent == "unknown" and metadata.get("source_agent") == "unknown":
        return metadata, tags

    new_metadata = dict(metadata)
    new_metadata.setdefault("provenance_version", PROVENANCE_VERSION)
    new_metadata.setdefault("source_agent", agent)
    new_metadata.setdefault("agent", agent)
    if metadata.get("session_id"):
        new_metadata.setdefault("source_session_id", metadata["session_id"])
    if metadata.get("source_path"):
        new_metadata.setdefault("source_transcript_path", metadata["source_path"])
    if metadata.get("path") and not new_metadata.get("source_transcript_path"):
        new_metadata.setdefault("source_transcript_path", metadata["path"])
    new_metadata.setdefault("ingestion_method", infer_ingestion(metadata, agent))
    new_metadata.setdefault("source_surface", infer_surface(agent))

    new_tags = list(tags)
    for tag in [f"agent:{agent}", f"ingestion:{new_metadata['ingestion_method']}", f"surface:{new_metadata['source_surface']}"]:
        if tag and tag not in new_tags:
            new_tags.append(tag)
    return new_metadata, new_tags


def classify_agent(tags: list[str], metadata: dict[str, Any]) -> str:
    source_agent = metadata.get("source_agent") or metadata.get("agent")
    if source_agent:
        return normalize_agent(str(source_agent))

    for tag in tags:
        if tag.startswith("agent:"):
            return normalize_agent(tag.split(":", 1)[1])

    paths = " ".join(
        str(metadata.get(key) or "")
        for key in ("source_path", "source_transcript_path", "path")
    )
    if "/.codex/" in paths:
        return "codex"
    if "/.claude/" in paths:
        return "claude"
    if "/.cursor/" in paths:
        return "cursor"
    if metadata.get("source") == "session-end-hook":
        return "claude"
    return "unknown"


def normalize_agent(agent: str) -> str:
    agent = agent.strip().lower()
    if agent in {"claude-code", "claude_code"}:
        return "claude"
    return agent or "unknown"


def infer_ingestion(metadata: dict[str, Any], agent: str) -> str:
    source = str(metadata.get("source") or "")
    if source in {"session-end-hook", "session-distill"} and agent == "claude":
        return "session-end-hook"
    if agent == "codex":
        return "codex-scanner"
    if agent == "cursor":
        return "cursor-scanner"
    if source:
        return source
    return "legacy-backfill"


def infer_surface(agent: str) -> str:
    if agent == "codex":
        return "desktop-app"
    if agent in {"claude", "cursor"}:
        return "cli"
    return "unknown"


def parse_tags(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def parse_metadata(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def print_report(report: dict[str, Any], *, applied: bool) -> None:
    if report.get("error"):
        print(f"No provenance audit: {report['error']} ({report['db_path']})")
        return
    mode = "applied" if applied else "dry-run"
    print(f"Provenance backfill {mode}: inspected={report['inspected']} would_update={report['would_update']}")
    for agent, count in sorted(report["counts"].items()):
        samples = ", ".join(report["samples"].get(agent, []))
        print(f"  {agent}: {count} sample_hashes={samples}")
    if not applied:
        print("No rows changed. Re-run with --apply to update metadata/tags.")


if __name__ == "__main__":
    main()
