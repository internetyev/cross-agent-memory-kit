"""Cross-platform raw-session-spend ingester.

This is distinct from `distill_runs` (which tracks the *distillation pipeline's*
own token use). This module reads RAW session transcripts from any platform
(Claude Code, Cowork, Codex, Hermes, ...) and records per-session token usage,
attributed to platform / machine / model / client, into a `session_usage` table.

Design constraints (per the chosen deployment model: per-machine harvest + merge):
- No server. Each machine ingests its own local transcripts into a local DB.
- Idempotent: re-ingesting the same session updates its row, never duplicates.
- Deterministic: cost is a list-price ESTIMATE from a fixed table; it is a
  relative signal, not a bill (the user is on a Claude Max subscription).
- Schema-tolerant: tolerates missing fields and the several transcript shapes.

The reporting layer (separate module) aggregates `session_usage` by model,
client, platform, and machine. This module only ingests.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import socket
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .storage import default_db_path

# ---------------------------------------------------------------------------
# Price table: USD per 1M tokens (input, output, cache_write_5m, cache_read).
# List-price estimate only. Extend as new models appear.
# ---------------------------------------------------------------------------
PRICES: dict[str, tuple[float, float, float, float]] = {
    "opus": (15.0, 75.0, 18.75, 1.50),
    "sonnet": (3.0, 15.0, 3.75, 0.30),
    "haiku": (0.80, 4.0, 1.0, 0.08),
    # OpenAI / codex (rough public list prices; refine per model as needed)
    "gpt-5": (1.25, 10.0, 0.0, 0.125),
    "gpt-4o": (2.5, 10.0, 0.0, 1.25),
    "gpt-4o-mini": (0.15, 0.60, 0.0, 0.075),
    "gemini-2.5": (1.25, 10.0, 0.0, 0.31),
    "gemini-1.5": (1.25, 5.0, 0.0, 0.31),
}


def price_for(model: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    if not model:
        return None
    m = model.lower()
    # longest key first so "gpt-4o-mini" wins over "gpt-4o"
    for key in sorted(PRICES, key=len, reverse=True):
        if key in m:
            return PRICES[key]
    return None


def estimate_cost(model: Optional[str], inp: int, out: int, cw: int, cr: int) -> float:
    pr = price_for(model)
    if not pr:
        return 0.0
    return (inp * pr[0] + out * pr[1] + cw * pr[2] + cr * pr[3]) / 1_000_000


# ---------------------------------------------------------------------------
# session_usage schema
# ---------------------------------------------------------------------------
SESSION_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_usage (
    session_key   TEXT PRIMARY KEY,   -- platform|machine|session_id (stable, idempotent)
    platform      TEXT NOT NULL,      -- claude-code | cowork | codex | hermes | antigravity | chat
    machine       TEXT NOT NULL,      -- hostname (mb1 / mb2 / ...)
    session_id    TEXT,
    model         TEXT,               -- dominant model for the session
    client_slug   TEXT,               -- mapped via client-registry, or 'unmapped'
    project_dir   TEXT,               -- raw project/cwd label the attribution came from
    month         TEXT,               -- YYYY-MM of last activity (report bucket)
    input_tokens          INTEGER DEFAULT 0,
    output_tokens         INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    cache_read_tokens     INTEGER DEFAULT 0,
    total_tokens          INTEGER DEFAULT 0,
    est_cost_usd  REAL DEFAULT 0,
    record_count  INTEGER DEFAULT 0,
    first_ts      TEXT,
    last_ts       TEXT,
    source_file   TEXT,
    ingested_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_session_usage_month   ON session_usage(month);
CREATE INDEX IF NOT EXISTS idx_session_usage_client  ON session_usage(client_slug);
CREATE INDEX IF NOT EXISTS idx_session_usage_platform ON session_usage(platform);
"""


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or default_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in SESSION_USAGE_SCHEMA.strip().split(";"):
        if stmt.strip():
            conn.execute(stmt)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Transcript parsing (Claude Code / Cowork JSONL shape)
# ---------------------------------------------------------------------------
def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _short_host() -> str:
    """Short machine label for provenance. Override with MCP_MEMORY_HOST_LABEL
    if you want a stable name across hostname changes."""
    label = os.environ.get("MCP_MEMORY_HOST_LABEL")
    if label:
        return label
    return socket.gethostname().lower().split(".")[0]


def iter_jsonl_sessions(root: str) -> dict[str, list[dict]]:
    """Group records by sessionId across every *.jsonl under root (skipping
    audit.jsonl, which double-counts). Returns {session_id: [records]}."""
    sessions: dict[str, list[dict]] = {}
    for fp in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        if os.path.basename(fp) == "audit.jsonl":
            continue
        try:
            fh = open(fp, "r", errors="replace")
        except Exception:
            continue
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                sid = rec.get("sessionId") or fp
                rec.setdefault("_source_file", fp)
                sessions.setdefault(sid, []).append(rec)
    return sessions


def summarize_session(records: list[dict], client_map) -> Optional[dict]:
    """Collapse one session's records into a single usage row dict."""
    inp = out = cw = cr = 0
    rec_count = 0
    model_tokens: dict[str, int] = {}
    first = last = None
    cwd = None
    source_file = None
    for rec in records:
        ts = _parse_ts(rec.get("timestamp"))
        if ts:
            first = ts if first is None or ts < first else first
            last = ts if last is None or ts > last else last
        cwd = cwd or rec.get("cwd")
        source_file = source_file or rec.get("_source_file")
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(usage, dict):
            continue
        i = usage.get("input_tokens", 0) or 0
        o = usage.get("output_tokens", 0) or 0
        c_w = usage.get("cache_creation_input_tokens", 0) or 0
        c_r = usage.get("cache_read_input_tokens", 0) or 0
        inp += i; out += o; cw += c_w; cr += c_r
        rec_count += 1
        model = msg.get("model")
        if model and model != "<synthetic>":
            model_tokens[model] = model_tokens.get(model, 0) + i + o + c_w + c_r
    if rec_count == 0 and inp == out == cw == cr == 0:
        return None
    dominant_model = max(model_tokens, key=model_tokens.get) if model_tokens else None
    client_slug, project_dir = client_map(cwd, source_file)
    month = (last or first).strftime("%Y-%m") if (last or first) else None
    return {
        "model": dominant_model,
        "client_slug": client_slug,
        "project_dir": project_dir,
        "month": month,
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_tokens": cw,
        "cache_read_tokens": cr,
        "total_tokens": inp + out + cw + cr,
        "est_cost_usd": round(estimate_cost(dominant_model, inp, out, cw, cr), 4),
        "record_count": rec_count,
        "first_ts": first.isoformat() if first else None,
        "last_ts": last.isoformat() if last else None,
        "source_file": source_file,
    }


# ---------------------------------------------------------------------------
# Client attribution (via client-registry; falls back to 'unmapped')
# ---------------------------------------------------------------------------
def build_client_mapper():
    """Return a fn(cwd, source_file) -> (client_slug, project_dir_label).

    Matches the cwd / source path against client-registry slugs, domains, and
    aliases. Everything unmatched returns ('unmapped', <best label>)."""
    try:
        from .registry import load_registry
        clients, projects = load_registry()
    except Exception:
        clients, projects = [], []

    needles: list[tuple[str, str]] = []  # (substring, slug)
    for entry in (clients or []) + (projects or []):
        slug = entry.get("slug") or entry.get("id")
        if not slug:
            continue
        needles.append((slug.lower(), slug))
        for alias in entry.get("aliases") or []:
            if alias:
                needles.append((str(alias).lower(), slug))
        for d in entry.get("domains") or []:
            host = (d.get("host") or "").lower()
            dslug = d.get("slug") or slug
            if host:
                needles.append((host, dslug))
                needles.append((host.split(".")[0], dslug))
    # longest needle first for specificity
    needles.sort(key=lambda x: len(x[0]), reverse=True)

    def mapper(cwd: Optional[str], source_file: Optional[str]) -> tuple[str, Optional[str]]:
        hay = " ".join(filter(None, [cwd or "", source_file or ""])).lower()
        label = cwd or (os.path.dirname(source_file) if source_file else None)
        if not hay:
            return "unmapped", label
        for needle, slug in needles:
            if len(needle) >= 3 and needle in hay:
                return slug, label
        return "unmapped", label

    return mapper


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
def ingest_root(
    *,
    platform: str,
    root: str,
    machine: Optional[str] = None,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    machine = machine or _short_host()
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        return {"platform": platform, "root": root, "ingested": 0, "skipped_reason": "root not found"}
    client_map = build_client_mapper()
    conn = connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    sessions = iter_jsonl_sessions(root)
    n = 0
    for sid, records in sessions.items():
        row = summarize_session(records, client_map)
        if row is None:
            continue
        key = f"{platform}|{machine}|{sid}"
        conn.execute(
            """
            INSERT INTO session_usage
              (session_key, platform, machine, session_id, model, client_slug,
               project_dir, month, input_tokens, output_tokens,
               cache_creation_tokens, cache_read_tokens, total_tokens,
               est_cost_usd, record_count, first_ts, last_ts, source_file, ingested_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_key) DO UPDATE SET
               model=excluded.model, client_slug=excluded.client_slug,
               project_dir=excluded.project_dir, month=excluded.month,
               input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens,
               cache_creation_tokens=excluded.cache_creation_tokens,
               cache_read_tokens=excluded.cache_read_tokens,
               total_tokens=excluded.total_tokens, est_cost_usd=excluded.est_cost_usd,
               record_count=excluded.record_count, first_ts=excluded.first_ts,
               last_ts=excluded.last_ts, source_file=excluded.source_file,
               ingested_at=excluded.ingested_at
            """,
            (
                key, platform, machine, sid, row["model"], row["client_slug"],
                row["project_dir"], row["month"], row["input_tokens"], row["output_tokens"],
                row["cache_creation_tokens"], row["cache_read_tokens"], row["total_tokens"],
                row["est_cost_usd"], row["record_count"], row["first_ts"], row["last_ts"],
                row["source_file"], now,
            ),
        )
        n += 1
    conn.commit()
    conn.close()
    return {"platform": platform, "machine": machine, "root": root, "ingested": n}


# Default platform roots (this machine). Override on the CLI.
def default_roots() -> dict[str, str]:
    home = os.path.expanduser("~")
    return {
        "claude-code": os.path.join(home, ".claude", "projects"),
        "cowork": os.path.join(
            home, "Library", "Application Support", "Claude", "local-agent-mode-sessions"
        ),
    }


def main(argv: Optional[list[str]] = None) -> None:
    p = argparse.ArgumentParser(description="Ingest raw cross-platform session usage.")
    p.add_argument("--platform", help="Platform label (claude-code, cowork, codex, hermes, ...).")
    p.add_argument("--root", help="Transcript root to scan.")
    p.add_argument("--machine", default=None, help="Machine label (default: derived from hostname).")
    p.add_argument("--db-path", default=None)
    p.add_argument("--all-default", action="store_true", help="Ingest all default platform roots on this machine.")
    args = p.parse_args(argv)

    results = []
    if args.all_default:
        for plat, root in default_roots().items():
            results.append(ingest_root(platform=plat, root=root, machine=args.machine, db_path=args.db_path))
    else:
        if not args.platform or not args.root:
            p.error("provide --platform and --root, or use --all-default")
        results.append(ingest_root(platform=args.platform, root=args.root, machine=args.machine, db_path=args.db_path))

    for r in results:
        print(json.dumps(r))


if __name__ == "__main__":
    main()
