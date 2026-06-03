# cross-agent-memory-kit

**English** | [Українська](README.uk.md)

**What is it for:** AI coding agents start every session cold. They forget the decisions, conventions, and dead ends from your last conversation, so you keep re-explaining the same context. This kit gives them a persistent, self-updating memory: after each session it distills what happened into durable facts and stores them, so the next session - on any agent, on any of your machines - already knows.

Reproducible configuration for [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) on macOS and Linux machines (not tested on Windows), plus the custom Claude Code skill and post-session distillation hook that wrap it.

This repo is the **source of truth**. Point any AI agent (Claude Code, Codex, Gemini, Cursor, Windsurf, Lovable, Kiro, ...) at this folder and it has everything needed to reproduce the setup on a fresh machine.

Current setup version: `0.2.0-dev` from `VERSION`.

## What you get when you reproduce this

1. **`mcp-memory-service`** running locally as a stdio MCP server. SQLite-vec storage. Persists facts, decisions, conventions, mistake notes, and session distillations across conversations.
2. A **`/mcp-memory-query` skill** (or its equivalent for non-Claude agents) that teaches the agent how to retrieve from the service.
3. A **post-session distillation hook** that, after each Claude Code session, sends the transcript to a chosen LLM (Claude, Codex, Gemini, OpenRouter, ...) and stores the extracted artifacts + facts back into the memory service.
4. **LangSmith tracing** for every distillation call, so you can see prompt, response, latency, and cost per session in the LangSmith dashboard.
5. **Optional multi-device sync.** Switch the server to its hybrid backend and one memory is shared across all your machines, with Cloudflare (D1 + Vectorize) as the source of truth and a local SQLite cache per device. See [MULTI-DEVICE-SYNC.md](MULTI-DEVICE-SYNC.md).

## Repo layout

```
cross-agent-memory-kit/
├── onboard.py                        # interactive install wizard (start here)
├── .env.example                      # template - copy to .env and fill in
├── .env                              # (gitignored) actual secrets
├── .gitignore
├── LICENSE
├── README.md                         # this file
├── MULTI-DEVICE-SYNC.md              # share one memory across devices (Cloudflare)
├── CHANGELOG.md
├── VERSION                           # machine-readable setup repo version
├── USECASES.md                       # what this setup is used for
├── LESSONS_LEARNED.md                # gotchas, design decisions
├── config/
│   └── providers.example.yaml        # provider/model config for the hook
├── hooks/
│   └── distill_session.py            # Claude Code SessionEnd wrapper
├── distill/
│   ├── engine.py                     # shared distillation flow
│   ├── prompt.md                     # single source of truth for memory rules
│   ├── storage.py                    # writes to mcp-memory-service DB
│   ├── providers.py                  # LLM provider calls and config
│   ├── registry.py                   # optional project/client slug registry
│   └── adapters/                     # raw transcript -> normalized transcript
├── wrappers/
│   ├── codex_session_scan.py         # Codex pull-based scanner/wrapper
│   ├── cursor_session_scan.py        # Cursor pull-based scanner/wrapper
│   ├── provenance_backfill.py        # dry-run provenance audit/backfill helper
│   └── usage_report.py               # token usage report from distill_runs
├── launchd/
│   └── memory-distill.plist.template # rendered per-machine by the watcher installers
├── skills/
│   └── mcp-memory-query/
│       └── SKILL.md                  # the skill / system-prompt content
└── scripts/
    ├── install.sh                    # idempotent low-level installer
    ├── check_version.py              # VERSION / changelog / tag verification
    ├── install_codex_watcher.sh      # installs the Codex launchd scanner
    └── install_cursor_watcher.sh     # installs the Cursor launchd scanner
```

## Prerequisites

- macOS or Linux (Windows untested).
- Python 3.10+ available as `python3`.
- One or more of these LLM CLIs / API keys:
  - `claude` CLI (Anthropic-logged-in) - subscription auth, used by default
  - `codex` CLI - subscription auth
  - `gemini` CLI - subscription auth
  - `cursor-agent` CLI - subscription auth
  - `OPENROUTER_API_KEY` - per-token billing
  - `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` - per-token billing

You only need ONE provider configured. The hook picks based on `config/providers.yaml`.

## Quickstart: the interactive wizard

The fastest path is `onboard.py`. It walks you through everything: creates/reuses
the venv, picks a distillation provider, optionally configures the Cloudflare
hybrid backend for multi-device sync, writes `.env` and `config/providers.yaml`,
and prints the exact MCP server block to paste into your agent's config. It never
overwrites an existing memory database.

```bash
git clone <this-repo> cross-agent-memory-kit
cd cross-agent-memory-kit
python3 onboard.py            # interactive; --help for non-interactive flags
```

The wizard never edits your agent config files for you - it prints the JSON/TOML
block and tells you where to paste it, so it can't corrupt a config by guessing.

## Quickstart: manual

If you prefer to do it by hand:

```bash
git clone <this-repo> cross-agent-memory-kit
cd cross-agent-memory-kit
cp .env.example .env                    # then edit .env with your keys
cp config/providers.example.yaml config/providers.yaml   # then edit if you want a non-default provider
bash scripts/install.sh                 # idempotent: creates/reuses venv, prints MCP config blocks
```

`install.sh` does the following, idempotently:

1. Creates a Python venv at `~/.local/share/mcp-memory-service-venv/` only if it does not already exist.
2. Checks whether `mcp-memory-service`, LangSmith, LangChain providers, `python-dotenv`, and `pyyaml` already import successfully.
3. Skips dependency installation when the existing venv is healthy.
4. Installs missing dependencies without forcing upgrades when the venv is incomplete.
5. Prints the MCP server block to add to each AI agent's config.
6. Does **not** auto-edit agent configs, install skills, wire hooks, or modify the memory database.

To intentionally upgrade Python packages, pass:

```bash
bash scripts/install.sh --upgrade-deps
```

## Existing install: preservation-first rule

If `mcp-memory-service` is already working through Claude Code or another agent, do **not** reinstall from scratch. Do not delete or recreate:

- `~/.local/share/mcp-memory-service-venv/`
- `~/Library/Application Support/mcp-memory/` on macOS
- `~/.local/share/mcp-memory/` on Linux
- any `sqlite_vec.db`, `sqlite_vec.db-wal`, or `sqlite_vec.db-shm` files

For Codex, Cursor, Gemini, or Kiro on a machine that already has the service, the usual task is only:

1. Point the agent's MCP config at the existing venv Python:

   ```text
   /Users/<you>/.local/share/mcp-memory-service-venv/bin/python -m mcp_memory_service.server
   ```

2. Install the agent-specific retrieval instructions or skill.
3. Restart the agent so the MCP tools are loaded.

`scripts/install.sh` is safe to run for verification because it now reuses an existing healthy venv and preserves the database path it detects. Still, agents should prefer registering the existing server over running package installation when the venv and DB are already present.

## Manual setup, per AI agent

### Claude Code

The MCP server config goes into `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "memory": {
      "type": "stdio",
      "command": "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python",
      "args": ["-m", "mcp_memory_service.server"],
      "env": {}
    }
  }
}
```

The skill goes into `~/.claude/skills/mcp-memory-query/SKILL.md` (copy from `skills/mcp-memory-query/SKILL.md` in this repo).

The SessionEnd hook goes into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/cross-agent-memory-kit/hooks/distill_session.py",
            "async": true,
            "timeout": 300
          }
        ]
      }
    ]
  }
}
```

The hook script's shebang points at the venv Python (which has `mcp_memory_service` importable). It is only a Claude wrapper; distillation rules live in `distill/prompt.md` and the shared engine under `distill/`.

### Codex CLI

MCP servers are registered in `~/.codex/config.toml`:

```toml
[mcp_servers.memory]
command = "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python"
args = ["-m", "mcp_memory_service.server"]
```

For Codex skills, copy the repo skill folder directly:

```bash
mkdir -p ~/.codex/skills/mcp-memory-query
cp skills/mcp-memory-query/SKILL.md ~/.codex/skills/mcp-memory-query/SKILL.md
```

Only create a Codex-specific copy in this repo, for example `skills/codex_mcp-memory-query/SKILL.md`, if the installed Codex skill must diverge from the shared skill. As of 2026-05-06, the Codex-installed skill is identical to `skills/mcp-memory-query/SKILL.md`, so no separate Codex copy is needed.

Codex doesn't currently expose a SessionEnd hook. The repo provides a pull-based scanner that watches Codex session JSONL files and calls the shared distillation engine with Codex provider defaults:

```bash
python wrappers/codex_session_scan.py --dry-run --quiet-minutes 0 --lookback-days 2 --limit 2
```

Install the macOS launchd watcher:

```bash
bash scripts/install_codex_watcher.sh
```

The installer first marks existing quiet Codex sessions as `baseline` in `~/.local/state/cross-agent-memory-kit/codex-processed.json`, then runs the scanner daily at 04:00 local time. Future quiet sessions are distilled once with `DISTILL_PROVIDER=codex-cli` and `DISTILL_MODEL=gpt-5.1-low`. The launchd job uses `--limit 0` so the daily run drains all unprocessed quiet sessions instead of stopping after a small batch. Codex provider calls use `codex exec --ephemeral` so distillation calls do not create new Codex session logs for the scanner to ingest.

Codex scanner logs:

```text
~/.local/state/cross-agent-memory-kit/logs/codex.log
~/.local/state/cross-agent-memory-kit/logs/codex-launchd.out.log
~/.local/state/cross-agent-memory-kit/logs/codex-launchd.err.log
```

### Cursor

Cursor's MCP config lives in `~/.cursor/mcp.json` with the same shape as Claude Code's `mcpServers` block.

For the skill: paste `SKILL.md` contents into a Cursor Project Rule under `.cursor/rules/mcp-memory-query.mdc`.

Cursor doesn't expose a SessionEnd hook. The repo provides a pull-based scanner that watches Cursor session JSONL files and calls the shared distillation engine with Cursor provider defaults:

```bash
python wrappers/cursor_session_scan.py --dry-run --quiet-minutes 0 --lookback-days 2 --limit 2
```

Install the macOS launchd watcher:

```bash
bash scripts/install_cursor_watcher.sh
```

The installer first marks existing quiet Cursor sessions as `baseline` in `~/.local/state/cross-agent-memory-kit/cursor-processed.json`, then runs the scanner daily at 04:00 local time. Future quiet sessions are distilled once with `DISTILL_PROVIDER=cursor-cli` and `DISTILL_MODEL=sonnet-4`. The launchd job uses `--limit 0` so the daily run drains all unprocessed quiet sessions.

Cursor scanner logs:

```text
~/.local/state/cross-agent-memory-kit/logs/cursor.log
~/.local/state/cross-agent-memory-kit/logs/cursor-launchd.out.log
~/.local/state/cross-agent-memory-kit/logs/cursor-launchd.err.log
```

### Gemini CLI

Gemini CLI uses `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "memory": {
      "command": "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python",
      "args": ["-m", "mcp_memory_service.server"]
    }
  }
}
```

Skill equivalent: paste `SKILL.md` into `GEMINI.md` at the project root.

Hook: same as Codex/Cursor - manual or scheduled invocation.

### Kiro.dev

Kiro reads `~/.kiro/settings/mcp.json`. Same `mcpServers` shape as Claude Code. Skills get pasted into Kiro's steering doc.

### Hermes Agent

Hermes Agent has a native MCP client and reads MCP servers from `~/.hermes/config.yaml` under `mcp_servers`. To reuse the existing memory service install without changing Claude Code's setup, add only the Hermes block below:

```yaml
mcp_servers:
  memory:
    command: "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python"
    args: ["-m", "mcp_memory_service.server"]
    env: {}
    timeout: 120
    connect_timeout: 60
```

Prefer editing the YAML directly for this server, because the `-m` Python argument can be confused with Hermes' top-level `-m/--model` CLI option in some shells/versions.

If the memory server needs environment variables, for example a hybrid Cloudflare backend, put them under `mcp_servers.memory.env` in `~/.hermes/config.yaml`. Hermes filters subprocess environments by default, so do not rely on shell secrets being inherited automatically.

Install the Hermes retrieval skill separately from the Claude skill so tool names can differ:

```bash
mkdir -p ~/.hermes/skills/mcp/mcp-memory-query
cp skills/mcp-memory-query/SKILL.md ~/.hermes/skills/mcp/mcp-memory-query/SKILL.md
# Then edit the Hermes copy so Claude-style tool names such as
# mcp__memory__memory_search become Hermes native MCP names such as
# mcp_memory_memory_search.
```

Hermes does not use Claude Code's `SessionEnd` hook. For session distillation, use an agent-specific scanner/wrapper if one exists, run the shared hook manually with the appropriate transcript adapter, or add a Hermes-specific wrapper later. Do not place the Claude `SessionEnd` block in Hermes config.

After editing `~/.hermes/config.yaml`, restart Hermes or run `/reload-mcp`. Verify with:

```bash
hermes mcp list
hermes mcp test memory
```

Hermes registers tools with the `mcp_{server}_{tool}` naming convention, so the memory server tools appear as names like `mcp_memory_memory_search`, `mcp_memory_memory_store`, and `mcp_memory_memory_health` after reload.

## Multi-provider distillation

`config/providers.yaml` (gitignored, copy from `providers.example.yaml`) controls which LLM the post-session hook calls.

```yaml
default_provider: claude-cli
providers:
  claude-cli:
    model: claude-haiku-4-5-20251001
  codex-cli:
    model: gpt-5.1-low
  gemini-cli:
    model: gemini-2.5-flash
  openrouter-api:
    model: anthropic/claude-haiku-4.5
  ...
```

By default, hook invocations use `default_provider`, currently `claude-cli` with `claude-haiku-4-5-20251001`. Use environment variables at the agent hook / wrapper boundary to select another provider for that agent without changing hook code:

```bash
DISTILL_PROVIDER=codex-cli DISTILL_MODEL=gpt-5.1-low python hooks/distill_session.py
```

For example, keep the Claude Code SessionEnd hook unprefixed so it stays on Haiku. For Codex, the scanner wrapper sets `DISTILL_PROVIDER=codex-cli DISTILL_MODEL=gpt-5.1-low` before it calls the shared engine.

## Distillation architecture

All agents share one memory policy:

```text
Agent wrapper -> transcript adapter -> shared engine -> storage
```

- Wrappers own trigger mechanics and state. Claude is push-based (`hooks/distill_session.py` receives one SessionEnd event). Codex and Cursor are pull-based (`wrappers/codex_session_scan.py`, `wrappers/cursor_session_scan.py`) and track processed sessions independently.
- Adapters own raw transcript parsing. They emit the dataclasses in `distill/transcript_schema.py`.
- The shared engine owns registry loading, prompt rendering, provider calls, and storage orchestration.
- `distill/prompt.md` is the policy source of truth for artifact rules, fact rules, exclusions, output schema, and memory type guidance. Do not duplicate these rules in per-agent wrappers.
- Stored memories carry normalized provenance metadata (`source_agent`, `source_surface`, `source_provider`, `source_session_id`, `ingestion_method`, `distiller_provider`, `distiller_model`) plus compatibility aliases (`agent`, `session_id`, `source_path`, `source`). Stored memories are also tagged with origin and routing tags such as `agent:claude`, `agent:codex`, `agent:cursor`, `surface:cli`, `ingestion:codex-scanner`, and `distiller:claude-cli`.

Supported providers:

| Provider | Type | Auth | Default model |
|----------|------|------|---------------|
| `claude-cli` | CLI subprocess | `claude` CLI subscription | `claude-haiku-4-5-20251001` |
| `codex-cli` | CLI subprocess | `codex` CLI subscription | (codex's own default) |
| `gemini-cli` | CLI subprocess | `gemini` CLI subscription | `gemini-2.5-flash` |
| `cursor-cli` | CLI subprocess | `cursor-agent` CLI subscription | `sonnet-4` |
| `anthropic-api` | LangChain | `ANTHROPIC_API_KEY` | `claude-haiku-4-5` |
| `openai-api` | LangChain | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `gemini-api` | LangChain | `GOOGLE_API_KEY` | `gemini-1.5-flash` |
| `openrouter-api` | LangChain | `OPENROUTER_API_KEY` | `anthropic/claude-haiku-4.5` |

## LangSmith tracing

Every distillation call is wrapped in `@traceable("distill.<provider>")` plus an outer `@traceable("distill.session")`. When `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` is set in `.env`, runs show up in the LangSmith project named by `LANGSMITH_PROJECT` (default `mcp-memory-service-hook`).

This is how you'll later compare provider/model quality and cost per session.

## Distillation usage accounting

Each distillation run writes a structured usage line to its log and a row into the memory SQLite DB table `distill_runs`. Rows are written for `stored`, `empty`, `skipped`, and `failed` runs, so token accounting can include sessions that did not produce memories.

The table records source provenance, distiller provider/model, token counts, cache token fields when exposed by the provider, wall seconds, status, returned/stored memory counts, and transcript/prompt character counts.

Use the report helper for token questions:

```bash
python wrappers/usage_report.py --range yesterday
python wrappers/usage_report.py --range last-7-days --agent claude
python wrappers/usage_report.py --range this-month --provider codex-cli --output json
```

CLI providers such as `claude-cli`, `codex-cli`, `gemini-cli`, and `cursor-cli` are usually subscription-billed, while API providers may be per-token billed. The report intentionally returns token usage, not a currency estimate.

## Provenance backfill

New session-distilled memories store normalized provenance going forward. Older memories can be audited without rewriting anything:

```bash
python wrappers/provenance_backfill.py
```

The helper classifies obvious legacy rows by existing `metadata.agent`, `agent:*` tags, transcript/path prefixes such as `~/.claude`, `~/.codex`, `~/.cursor`, and `metadata.source = session-end-hook`. It falls back to `unknown` when origin cannot be proven. Use `--apply` only after reviewing the dry-run counts.

## Storage location

The MCP server writes to:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/mcp-memory/sqlite_vec.db` |
| Linux | `~/.local/share/mcp-memory/sqlite_vec.db` |
| Other | `~/.mcp-memory/sqlite_vec.db` |

The hook writes directly to the same DB so the MCP server's tools see hook-written data. Override with `MCP_MEMORY_SQLITE_VEC_PATH` if you need a different location.

## Verifying the install

After `scripts/install.sh` finishes:

```bash
# 1. MCP server starts
/Users/<you>/.local/share/mcp-memory-service-venv/bin/python -m mcp_memory_service.server --help

# 2. Hook syntax-checks
python3 -c "import ast; ast.parse(open('hooks/distill_session.py').read()); print('ok')"

# 3. Hook can find its deps (run from the venv)
/Users/<you>/.local/share/mcp-memory-service-venv/bin/python -c "
from langsmith import traceable
import mcp_memory_service.storage.sqlite_vec
print('deps ok')
"

# 4. End a Claude Code session - check that the log gained a new entry
tail -1 ~/.claude/logs/distill-session.log

# 5. Version contract is coherent
python scripts/check_version.py

# 6. Token usage report can read the DB
python wrappers/usage_report.py --range today
```

## Versioning and releases

`VERSION` is the machine-readable source of truth for the setup repo version. `distill.__version__` reads that file at runtime.

This repo uses semantic versioning:

- Patch: documentation, tests, or compatible installer/hook fixes.
- Minor: setup-contract additions such as new wrappers, provenance fields, usage tables, or backward-compatible skill behavior.
- Major: incompatible install, memory-schema, or hook contract changes.

Release checklist:

1. Move relevant `CHANGELOG.md` entries out of `Unreleased`.
2. Update `VERSION`.
3. Run `python scripts/check_version.py`.
4. Tag release commits as `vX.Y.Z`.
5. Document migration steps for memory-schema or provenance-schema changes.

## See also

- [MULTI-DEVICE-SYNC.md](MULTI-DEVICE-SYNC.md) - share one memory across devices via the Cloudflare hybrid backend
- [USECASES.md](USECASES.md) - what this setup is used for in practice
- [CHANGELOG.md](CHANGELOG.md) - history of changes to this setup
- [LESSONS_LEARNED.md](LESSONS_LEARNED.md) - gotchas and design decisions
