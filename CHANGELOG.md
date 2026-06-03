# Changelog

All notable changes to the cross-agent-memory-kit repo are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `onboard.py` interactive install wizard: verifies Python, runs the installer, picks a provider, optionally configures the Cloudflare hybrid backend, writes `.env`/`providers.yaml`, and prints the MCP server block and Claude hook block to paste. Never edits agent configs or the memory DB.
- `MULTI-DEVICE-SYNC.md` guide for sharing one memory across devices via the Cloudflare D1 + Vectorize hybrid backend.
- `LICENSE` (MIT).
- `domain` field on stored artifact memories. When the distiller identifies that an artifact is scoped to one specific domain of a multi-domain project, the per-domain slug is recorded both as `metadata.domain` and as a `domain:<slug>` tag, so per-domain artifacts are searchable and filterable independently from whole-project artifacts. The artifact's header line also names the domain when present.

### Changed

- Generalized for public release: the distillation prompt is now domain-neutral (software-project examples instead of one specific workflow); the client/project registry is opt-in via `MCP_MEMORY_CLIENTS_YAML` with no hardcoded default path; launchd jobs are rendered per-machine from `launchd/memory-distill.plist.template`; and the host label is configurable via `MCP_MEMORY_HOST_LABEL`.
- Registry loader (`distill/registry.py`) now parses the new client/project `slug` field and the `domains` list (host + per-domain slug + primary flag + status + notes), and includes them in the prompt registry presented to the distiller. Bare-string domain entries are upgraded to mappings on read.
- Distiller prompt now teaches identification by domain `host` or per-domain `slug`, and asks for a `domain` field on each artifact when the session is clearly scoped to one domain.
- Shared `distill/` package with transcript schema, Claude/Codex/fake adapters, central prompt, provider calls, storage, and distillation engine.
- Codex scanner wrapper (`wrappers/codex_session_scan.py`) with quiet-file checks and wrapper-owned processed-session state at `~/.local/state/cross-agent-memory-kit/codex-processed.json`.
- Cursor adapter (`distill/adapters/cursor.py`) plus Cursor scanner wrapper (`wrappers/cursor_session_scan.py`) with its own processed-session state at `~/.local/state/cross-agent-memory-kit/cursor-processed.json`.
- macOS launchd plist and installer for running Codex memory distillation daily.
- macOS launchd plist and installer for Cursor memory distillation (`launchd/com.mcp-memory.cursor-distill.plist`, `scripts/install_cursor_watcher.sh`).
- Adapter contract tests and six transcript fixtures.
- Normalized provenance metadata for stored session-distilled memories, including `source_agent`, `source_surface`, `source_provider`, `source_session_id`, `ingestion_method`, `distiller_provider`, and compatibility aliases.
- Distiller token-usage capture for CLI/API providers plus the `distill_runs` SQLite table for stored, empty, skipped, and failed runs.
- `wrappers/usage_report.py` for token usage summaries by day, provider, agent, and top sessions.
- `wrappers/provenance_backfill.py`, a dry-run-first helper for auditing and backfilling normalized provenance onto legacy memory rows.
- `VERSION`, `distill.__version__`, and `scripts/check_version.py` as the setup repo version contract.

### Changed

- `hooks/distill_session.py` is now a thin Claude Code wrapper around the shared engine instead of owning the memory policy itself.
- Codex memory distillation launchd job now runs daily at 04:00 local time and drains all unprocessed quiet sessions per run.
- `mcp-memory-query` skill now runs the Codex session scanner before lookups so quiet sessions are stored before retrieval.
- `scripts/install.sh` is now preservation-first: it reuses an existing venv, skips dependency installation when required imports work, and requires `--upgrade-deps` for intentional package upgrades.
- README now warns future agents not to delete/recreate the memory venv or SQLite database when adding Codex/Cursor/Gemini/Kiro access to an existing Claude-installed service.
- Codex setup instructions now use `~/.codex/skills/mcp-memory-query/SKILL.md` directly and document that no separate `codex_` skill is needed while it matches the shared skill.
- README now documents the shared distillation architecture and the existing per-invocation `DISTILL_PROVIDER` / `DISTILL_MODEL` mechanism for choosing a different distillation model per agent without memory-policy changes.
- README now documents the Cursor scanner flow and launchd scheduler, mirroring Codex watcher behavior.
- `mcp-memory-query` skill now recognizes token-usage questions and routes them through the canonical usage report helper.

## [0.1.0] - 2026-05-06

### Added

- Initial repo, captures the working state of mcp-memory-service from a working local install.
- `hooks/distill_session.py` - multi-provider post-session distillation hook (Claude CLI, Codex CLI, Gemini CLI, Cursor CLI, plus Anthropic/OpenAI/Gemini/OpenRouter APIs via LangChain). Replaces the previous Claude-CLI-only version that lived at `~/.claude/scripts/distill_session.py`.
- LangSmith `@traceable` instrumentation on every provider call plus an outer `distill.session` span.
- `config/providers.example.yaml` - declarative provider/model selection. Local override at `config/providers.yaml` (gitignored).
- `skills/mcp-memory-query/SKILL.md` - copied from `~/.claude/skills/mcp-memory-query/SKILL.md`.
- `.env.example` - documents all expected env vars (LANGSMITH_*, OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY).
- `scripts/install.sh` - idempotent installer.
- `README.md` with per-agent setup blocks for Claude Code, Codex CLI, Cursor, Gemini CLI, Kiro.
- `USECASES.md`, `LESSONS_LEARNED.md`.

### Changed

- The Claude Code SessionEnd hook in `~/.claude/settings.json` now points at `hooks/distill_session.py` inside this repo instead of the in-place copy under `~/.claude/scripts/`. The repo is the source of truth.
- Storage path detection is now OS-aware (macOS / Linux / fallback) instead of hardcoded to the macOS path.
- `LANGCHAIN_API_KEY` env var renamed to `LANGSMITH_API_KEY` to match the official LangSmith Python SDK convention. Both still work because LangSmith reads either, but new docs recommend `LANGSMITH_API_KEY`.
