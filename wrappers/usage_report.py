#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from distill.storage import default_db_path


def main() -> None:
    args = parse_args()
    start, end, label = resolve_range(args)
    db_path = args.db_path or default_db_path()
    report = build_report(
        db_path=db_path,
        start=start,
        end=end,
        label=label,
        agent=args.agent,
        provider=args.provider,
        statuses=_statuses(args),
        top=args.top,
    )
    if args.output == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text_report(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report mcp-memory-service distillation token usage.")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--range", default="today", help="today, yesterday, last-7-days, this-week, last-week, this-month, last-month")
    parser.add_argument("--from", dest="from_date", default=None, help="Inclusive YYYY-MM-DD start date.")
    parser.add_argument("--to", dest="to_date", default=None, help="Exclusive YYYY-MM-DD end date.")
    parser.add_argument("--agent", default=None, help="Filter source_agent, e.g. claude or codex.")
    parser.add_argument("--provider", default=None, help="Filter distiller provider, e.g. claude-cli or codex-cli.")
    parser.add_argument("--status", default=None, help="Comma-separated statuses to include.")
    parser.add_argument("--successful-only", action="store_true", help="Shortcut for --status stored,empty.")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--output", choices=["text", "json"], default="text")
    return parser.parse_args()


def build_report(
    *,
    db_path: str,
    start: datetime,
    end: datetime,
    label: str,
    agent: Optional[str],
    provider: Optional[str],
    statuses: Optional[list[str]],
    top: int,
) -> dict[str, Any]:
    if not Path(db_path).exists():
        return empty_report(db_path, start, end, label, agent, provider, statuses, "database not found")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if not table_exists(conn, "distill_runs"):
            return empty_report(db_path, start, end, label, agent, provider, statuses, "distill_runs table not found")

        where_sql, params = where_clause(start, end, agent, provider, statuses)
        totals = row_to_dict(conn.execute(f"""
            SELECT
                COUNT(*) AS run_count,
                COALESCE(SUM(COALESCE(input_tokens, 0)), 0) AS input_tokens,
                COALESCE(SUM(COALESCE(output_tokens, 0)), 0) AS output_tokens,
                COALESCE(SUM(COALESCE(cache_creation_input_tokens, 0)), 0) AS cache_creation_input_tokens,
                COALESCE(SUM(COALESCE(cache_read_input_tokens, 0)), 0) AS cache_read_input_tokens,
                COALESCE(SUM(COALESCE(total_tokens, 0)), 0) AS total_tokens,
                ROUND(COALESCE(SUM(COALESCE(wall_seconds, 0)), 0), 3) AS wall_seconds,
                SUM(CASE WHEN input_tokens IS NULL AND output_tokens IS NULL AND total_tokens IS NULL THEN 1 ELSE 0 END) AS missing_usage_runs
            FROM distill_runs
            {where_sql}
        """, params).fetchone())
        by_day = query_breakdown(conn, where_sql, params, "substr(run_started_at, 1, 10)", "day")
        by_provider = query_breakdown(conn, where_sql, params, "COALESCE(provider, 'unknown')", "provider")
        by_agent = query_breakdown(conn, where_sql, params, "COALESCE(source_agent, 'unknown')", "agent")
        top_sessions = [
            row_to_dict(row)
            for row in conn.execute(f"""
                SELECT
                    source_session_id,
                    source_agent,
                    provider,
                    model,
                    status,
                    run_started_at,
                    transcript_chars,
                    COALESCE(total_tokens, COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0) + COALESCE(cache_creation_input_tokens, 0) + COALESCE(cache_read_input_tokens, 0)) AS total_tokens
                FROM distill_runs
                {where_sql}
                ORDER BY total_tokens DESC, run_started_at DESC
                LIMIT ?
            """, [*params, top]).fetchall()
        ]
        first_run = conn.execute("SELECT MIN(run_started_at) FROM distill_runs").fetchone()[0]

    caveats = []
    if first_run and start.isoformat(timespec="seconds") < first_run:
        caveats.append(f"Usage data starts at {first_run}; older memory writes in this period have no distill_runs rows.")
    if any(row["provider"].endswith("-cli") for row in by_provider):
        caveats.append("CLI providers are usually subscription-billed; API providers may be per-token billed, so this is a token report, not a currency-cost report.")

    return {
        "db_path": db_path,
        "range": {
            "label": label,
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
        },
        "filters": {
            "agent": agent or "all",
            "provider": provider or "all",
            "statuses": statuses or "all",
        },
        "totals": totals,
        "by_day": by_day,
        "by_provider": by_provider,
        "by_agent": by_agent,
        "top_sessions": top_sessions,
        "caveats": caveats,
        "empty_reason": None,
    }


def query_breakdown(
    conn: sqlite3.Connection,
    where_sql: str,
    params: list[Any],
    expression: str,
    label: str,
) -> list[dict[str, Any]]:
    return [
        row_to_dict(row)
        for row in conn.execute(f"""
            SELECT
                {expression} AS {label},
                COUNT(*) AS run_count,
                COALESCE(SUM(COALESCE(input_tokens, 0)), 0) AS input_tokens,
                COALESCE(SUM(COALESCE(output_tokens, 0)), 0) AS output_tokens,
                COALESCE(SUM(COALESCE(cache_creation_input_tokens, 0)), 0) AS cache_creation_input_tokens,
                COALESCE(SUM(COALESCE(cache_read_input_tokens, 0)), 0) AS cache_read_input_tokens,
                COALESCE(SUM(COALESCE(total_tokens, 0)), 0) AS total_tokens,
                ROUND(COALESCE(SUM(COALESCE(wall_seconds, 0)), 0), 3) AS wall_seconds
            FROM distill_runs
            {where_sql}
            GROUP BY {expression}
            ORDER BY {label}
        """, params).fetchall()
    ]


def where_clause(
    start: datetime,
    end: datetime,
    agent: Optional[str],
    provider: Optional[str],
    statuses: Optional[list[str]],
) -> tuple[str, list[Any]]:
    clauses = ["run_started_at >= ?", "run_started_at < ?"]
    params: list[Any] = [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")]
    if agent:
        clauses.append("source_agent = ?")
        params.append(agent)
    if provider:
        clauses.append("provider = ?")
        params.append(provider)
    if statuses:
        placeholders = ", ".join("?" for _status in statuses)
        clauses.append(f"status IN ({placeholders})")
        params.extend(statuses)
    return "WHERE " + " AND ".join(clauses), params


def resolve_range(args: argparse.Namespace) -> tuple[datetime, datetime, str]:
    now = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if args.from_date or args.to_date:
        start = parse_local_date(args.from_date) if args.from_date else today
        end = parse_local_date(args.to_date) if args.to_date else now
        return start, end, f"{start.date()} to {end.date()}"

    label = args.range.strip().lower().replace("_", "-").replace(" ", "-")
    if label == "today":
        return today, today + timedelta(days=1), "today"
    if label == "yesterday":
        return today - timedelta(days=1), today, "yesterday"
    if label.startswith("last-") and label.endswith("-days"):
        days = int(label.removeprefix("last-").removesuffix("-days"))
        return today - timedelta(days=max(days - 1, 0)), today + timedelta(days=1), f"last {days} days"
    if label == "this-week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=7), "this week"
    if label == "last-week":
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=7), "last week"
    if label == "this-month":
        start = today.replace(day=1)
        return start, next_month(start), "this month"
    if label == "last-month":
        this_month = today.replace(day=1)
        start = (this_month - timedelta(days=1)).replace(day=1)
        return start, this_month, "last month"
    raise SystemExit(f"unsupported --range: {args.range}")


def parse_local_date(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)


def next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _statuses(args: argparse.Namespace) -> Optional[list[str]]:
    if args.successful_only:
        return ["stored", "empty"]
    if not args.status:
        return None
    return [status.strip() for status in args.status.split(",") if status.strip()]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone()
    return row is not None


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def empty_report(
    db_path: str,
    start: datetime,
    end: datetime,
    label: str,
    agent: Optional[str],
    provider: Optional[str],
    statuses: Optional[list[str]],
    reason: str,
) -> dict[str, Any]:
    return {
        "db_path": db_path,
        "range": {
            "label": label,
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
        },
        "filters": {
            "agent": agent or "all",
            "provider": provider or "all",
            "statuses": statuses or "all",
        },
        "totals": {
            "run_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "total_tokens": 0,
            "wall_seconds": 0,
            "missing_usage_runs": 0,
        },
        "by_day": [],
        "by_provider": [],
        "by_agent": [],
        "top_sessions": [],
        "caveats": [],
        "empty_reason": reason,
    }


def print_text_report(report: dict[str, Any]) -> None:
    totals = report["totals"]
    print(f"Memory distillation token usage: {report['range']['label']}")
    print(f"Range: {report['range']['start']} -> {report['range']['end']}")
    print(
        "Filters: "
        f"agent={report['filters']['agent']} "
        f"provider={report['filters']['provider']} "
        f"statuses={display_filter(report['filters']['statuses'])}"
    )
    if report.get("empty_reason"):
        print(f"No usage data: {report['empty_reason']}")
        return
    print(
        "Totals: "
        f"runs={totals['run_count']} "
        f"input={totals['input_tokens']} "
        f"output={totals['output_tokens']} "
        f"cache_create={totals['cache_creation_input_tokens']} "
        f"cache_read={totals['cache_read_input_tokens']} "
        f"total={totals['total_tokens']} "
        f"wall={totals['wall_seconds']}s "
        f"missing_usage={totals['missing_usage_runs']}"
    )
    print_section("By day", report["by_day"], "day")
    print_section("By provider", report["by_provider"], "provider")
    print_section("By agent", report["by_agent"], "agent")
    print_top_sessions(report["top_sessions"])
    for caveat in report["caveats"]:
        print(f"Caveat: {caveat}")


def print_section(title: str, rows: Iterable[dict[str, Any]], key: str) -> None:
    rows = list(rows)
    if not rows:
        return
    print(f"\n{title}:")
    for row in rows:
        print(
            f"  {row[key]}  "
            f"runs={row['run_count']} "
            f"input={row['input_tokens']} "
            f"output={row['output_tokens']} "
            f"cache_read={row['cache_read_input_tokens']} "
            f"total={row['total_tokens']}"
        )


def display_filter(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def print_top_sessions(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    print("\nTop sessions:")
    for row in rows:
        session = str(row["source_session_id"])[:12]
        print(
            f"  {session}  "
            f"agent={row['source_agent']} "
            f"provider={row['provider']} "
            f"status={row['status']} "
            f"total={row['total_tokens']} "
            f"chars={row['transcript_chars']}"
        )


if __name__ == "__main__":
    main()
