---
name: mcp-memory-query
description: >
  Query the mcp-memory-service to retrieve stored facts, decisions, notes, and session
  learnings. Use this skill whenever the user asks what you remember, wants to recall
  past decisions or conventions, asks "do you know anything about X", references "last
  time we discussed", says "check your memory", "look in memory", "search memory for",
  "what's stored about", or any phrase implying retrieval from a persistent knowledge
  store. Also use proactively before starting a complex task to surface known pitfalls
  via mistake notes. Covers: memory search, memory browse, mistake note lookup.
---

# MCP Memory Query

Retrieve and present information from the mcp-memory-service. The service stores
facts, decisions, conventions, session learnings, and mistake patterns across
conversations.

---

## Shared cross-device memory (hybrid Cloudflare backend)

When the `hybrid` backend is configured, this memory is a **single shared store
across all of the user's devices**, not a per-machine database. The MCP server
keeps a fast local SQLite cache on each device, and **Cloudflare (D1 + Vectorize)**
is the shared source of truth. Implications when answering:

(If the server runs the local-only `sqlite_vec` backend instead, ignore this
section - the store is just the single local database.)

- **Eventually consistent.** A memory stored on another device appears here after
  the next background sync (seconds to minutes), not instantly. If a lookup returns
  nothing for something the user expects, say it may have been written on another
  device and not synced yet - do **not** assert "nothing was ever stored".
- **Writes are global.** Anything stored via this skill is visible on every device
  after sync. Confirm with: "Stored - it'll sync to your other devices shortly."
- **Offline-safe.** If Cloudflare is unreachable, reads/writes still hit the local
  cache and sync up later; results may be slightly behind the shared store.
- The backend is configured in the `memory` MCP server `env` in `~/.claude.json`
  (`MCP_MEMORY_STORAGE_BACKEND=hybrid` + `CLOUDFLARE_*`). The skill never needs to
  set this; it only queries via the `mcp__memory__*` tools.

---

## Available tools

| Tool | When to use |
|---|---|
| `mcp__memory__memory_search` | Primary retrieval - semantic, exact, or hybrid search |
| `mcp__memory__memory_list` | Browse all memories or filter by tag/type |
| `mcp__memory__mistake_note_search` | Look up known error patterns before starting a task |
| `mcp__memory__memory_stats` | Show service health / cache stats |
| `mcp__memory__memory_health` | Check database health |

---

## Refresh session memories first

Before any query, run the Codex session scanner so recent quiet sessions are stored
before retrieval:

```bash
~/.local/share/mcp-memory-service-venv/bin/python \
  "$MCP_MEMORY_SETUP_REPO/wrappers/codex_session_scan.py" \
  --quiet-minutes 30 \
  --lookback-days 3650 \
  --limit 0
```

`$MCP_MEMORY_SETUP_REPO` is the local checkout of `cross-agent-memory-kit`
(set it to wherever you cloned this repo, e.g. `~/src/cross-agent-memory-kit`).
The venv path `~/.local/share/mcp-memory-service-venv/bin/python` is the same on
every device.

This is best effort: if the scanner fails, report the failure briefly and continue
with the requested lookup. Do not run it with `--dry-run`. The active conversation
may not be saved yet because sessions must be quiet for 30 minutes before scanning.

---

## Query flow

### 1. Pick the right tool

- **"tokens burned" / "token usage" / "how many tokens" / "cost of memory" / "memory hook cost" / "distillation cost" / "haiku tokens" / "codex tokens"** - use the token-usage report wrapper, not `memory_search`.
- **"what do you remember about X"** / **"find memories about X"** - use `memory_search`
  with `mode: "semantic"` (default). Add `quality_boost: 0.3` for important lookups.
- **"show all my memories"** / **"list everything stored"** - use `memory_list`.
- **"find memories tagged important"** / **"show decisions"** - use `memory_list` with
  `tags` or `memory_type` filter.
- **"anything from last week"** / **"recent notes"** - use `memory_search` with
  `time_expr` (e.g. `"last week"`) or `after`/`before` dates.
- **"check for mistakes about X"** / before starting a task - use `mistake_note_search`.
- **"how is memory service doing"** - use `memory_stats` or `memory_health`.

### Token-usage mode

Use this for questions like:

- "How many tokens were burned for memory storage yesterday?"
- "Tokens burned today by the SessionEnd hook?"
- "Tokens burned for memory writing by Claude only last month?"
- "Cost breakdown by provider for the last 7 days."
- "Which sessions burned the most tokens this week?"

Run the canonical report helper from the setup repo. It reads the `distill_runs`
SQLite table and must not re-parse hook logs or load all memories:

```bash
PY=~/.local/share/mcp-memory-service-venv/bin/python
"$PY" "$MCP_MEMORY_SETUP_REPO/wrappers/usage_report.py" --range yesterday
"$PY" "$MCP_MEMORY_SETUP_REPO/wrappers/usage_report.py" --range today --agent claude
"$PY" "$MCP_MEMORY_SETUP_REPO/wrappers/usage_report.py" --range last-7-days --provider claude-cli
"$PY" "$MCP_MEMORY_SETUP_REPO/wrappers/usage_report.py" --range last-month --agent codex --successful-only
```

(`$MCP_MEMORY_SETUP_REPO` is your local checkout of this repo. Token-usage data
is per-device - it reads the local `distill_runs` table, not the shared
Cloudflare store.)

Supported filters:

- Time: `--range today|yesterday|last-7-days|this-week|last-week|this-month|last-month`, or `--from YYYY-MM-DD --to YYYY-MM-DD`.
- Agent: `--agent claude`, `--agent codex`, `--agent cursor`, or omit for all.
- Provider: `--provider claude-cli`, `--provider codex-cli`, `--provider anthropic-api`, etc., or omit for all.
- Status: omit to include all statuses, use `--successful-only` for stored/empty runs, or `--status stored,failed,skipped`.

Answer from the report totals and top sessions. Include the caveat line when the
report says the period predates the `distill_runs` cutover. If CLI and API providers
are mixed, say that the report is token usage, not a precise currency cost, because
CLI providers are usually subscription-billed.

### 2. Run the search

For `memory_search`, always include:
- `query`: the user's topic, rephrased as a short noun phrase if needed
- `limit`: 10 by default; increase to 20-30 if the user wants a broad sweep
- `quality_boost: 0.3` when precision matters (user asks for "best" or "most
  important" memories)
- `max_response_chars: 30000` when the result set might be large

### 3. Present results clearly

Structure your answer as:

```
Found N memories about "[topic]":

1. [Memory content, trimmed to the key fact]
   Tags: [tags] | Type: [type] | Stored: [date]

2. ...

[If nothing found]: No memories stored about "[topic]". Would you like me to store
something now?
```

- Lead with the most relevant fact, not metadata.
- When available in result metadata, include a compact provenance line:
  `Origin: <source_agent> | Ingestion: <ingestion_method> | Distiller: <distiller_provider>/<distiller_model> | Source session: <source_session_id>`.
- If the query was broad and there are many results, group by type or tag.
- If results look stale or contradictory, mention it so the user can decide whether to
  update them.
- For mistake notes, format as: "Known pitfall: [error pattern] - [correct action]".

---

## Storing new memories (if the user asks)

If the user says "remember this", "store this", or "save this to memory", use
`mcp__memory__memory_store`:

```json
{
  "content": "<the fact or note to store>",
  "metadata": {
    "tags": "tag1,tag2",
    "type": "note|decision|convention|reference"
  }
}
```

Confirm back: "Stored. I'll be able to retrieve this in future sessions."

---

## Harvesting session learnings

If the user says "harvest memories", "extract learnings from this session", or "save
what we learned today", use `mcp__memory__memory_harvest`:

- Default: `dry_run: true` - preview first, ask the user to confirm before storing.
- Then re-run with `dry_run: false` to commit.

---

## Edge cases

- **No results**: tell the user nothing was found; offer to store something or try a
  different query (exact mode vs. semantic, or broader terms).
- **Too many results**: ask the user to narrow down with a tag, date range, or type
  filter.
- **Service unavailable**: report the error clearly; do not silently fall back to
  guessing from context.
