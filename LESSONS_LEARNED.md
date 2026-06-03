# Lessons learned

Design decisions, gotchas, and rules surfaced while building or operating this setup. Add an entry here when you make a non-obvious choice or hit a non-obvious problem.

## L1 - The hook must run from the same venv as the MCP server

The hook calls `from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage` to write to the same DB the MCP server reads. That import only resolves when running under the venv where `mcp-memory-service` was installed.

**How to apply:** the hook's shebang or its launcher must point at `~/.local/share/mcp-memory-service-venv/bin/python`. If you put the shebang at `/usr/bin/env python3`, the import fails and nothing gets stored.

## L2 - Storage path is OS-specific - read from the package's own config

Hardcoding `~/Library/Application Support/mcp-memory/sqlite_vec.db` worked on macOS but breaks on Linux. The fix is the OS-detect helper in `_default_db_path()`, not a hardcoded path. If `mcp-memory-service` ever changes its data dir convention, this is the one place to update.

## L3 - Claude CLI subprocess is fragile - parse defensively

`claude -p --output-format json` returns a wrapper that can fail in three different ways: nonzero exit, `is_error: true`, or wrapper that's not parseable JSON. The hook handles all three; do not collapse them into a single try/except.

The wrapper's `result` field is itself a free-form string that may contain markdown fences, prose, or extra JSON objects. Use `_extract_json_object` to find the FIRST balanced `{...}`, do not feed the whole thing to `json.loads`.

## L4 - LangSmith env var is `LANGSMITH_API_KEY`, not `LANGCHAIN_API_KEY`

The original `.env` used `LANGCHAIN_API_KEY` because that's what some older LangChain examples show. The current LangSmith SDK accepts both, but the canonical name is `LANGSMITH_API_KEY` and the docs use that. New `.env.example` standardizes on the canonical name.

## L5 - `client_or_project` slug must come from the canonical registry, not from a guess

If the distillation prompt lets the LLM invent slugs, you get `myapp` AND `my-app` AND `my_app` for the same project across different sessions, and search by tag stops working.

**How to apply:** point `MCP_MEMORY_CLIENTS_YAML` at a registry file (see `distill/registry.py` for the expected shape). The prompt pre-loads it and tells the LLM to use the `id` field verbatim. A regex fallback parses the YAML even if `pyyaml` chokes on it. The feature is opt-in: with no registry set, the distiller infers a slug from the repo/folder or uses `unknown`.

## L6 - Sessions with `0 chars of user/assistant text` are normal

The Claude Code transcript JSONL sometimes contains only system / tool-result entries when the user immediately exited or when the session was a tool-only invocation. The `MIN_USEFUL_CHARS` floor (500) silently skips those - do not log them as errors.

## L7 - `async: true` in the hook config is required

Without it, Claude Code blocks the session-close UI on the LLM call (which can take 30-60 seconds). With it, the hook runs detached and the UI returns immediately. The `timeout: 300` is a safety belt for the hook itself.

## L8 - Multi-provider config: keep CLI providers as the default

CLI providers (claude/codex/gemini/cursor) are subscription-billed. API providers cost real money per session. The default provider is always a CLI one to avoid accidental token bills. Only switch to an API provider explicitly via `config/providers.yaml` or the `DISTILL_PROVIDER` env var.

## L9 - `@traceable` is a no-op when langsmith is not installed

The hook works without LangSmith - tracing simply disappears. The `_traced` helper falls back to a passthrough decorator. Do not gate hook execution on LangSmith availability.

## L10 - Adding a new agent is not the same as reinstalling memory

When Claude Code already has `mcp-memory-service` installed, adding Codex, Cursor, Gemini, or Kiro should normally only register that agent's MCP config and copy the retrieval instructions. Reinstalling packages is unnecessary and can make future agents nervous about the SQLite history.

**How to apply:** first check for the existing venv at `~/.local/share/mcp-memory-service-venv/` and the DB at the OS default path. If both exist, point the new agent at the venv Python. Run `scripts/install.sh` only as a preservation-first verification step, and use `--upgrade-deps` only when the user explicitly asks to upgrade packages.

## L11 - Model choice belongs at the hook invocation boundary

The hook already supports `DISTILL_PROVIDER` and `DISTILL_MODEL`, so agent-specific model selection does not require transcript-source detection in code. The invoking agent, wrapper, or scheduled job should set the env vars it needs.

**How to apply:** keep Claude Code's SessionEnd command unprefixed so it uses `default_provider` (`claude-cli` Haiku). For Codex distillation, run the same hook with `DISTILL_PROVIDER=codex-cli DISTILL_MODEL=gpt-5.1-low`. Apply the same pattern for Cursor, Gemini, or API-backed providers.

## L12 - Adapters normalize transcripts; wrappers own triggers and state

Do not put agent-specific field names or trigger behavior in the distillation engine. Claude and Codex transcript files use different schemas, and Claude is push-based while Codex is pull-based.

**How to apply:** raw transcript parsing lives in `distill/adapters/`; each adapter emits `NormalizedTranscript` from `distill/transcript_schema.py`. Claude's wrapper handles one SessionEnd event. Codex's wrapper scans files and owns `codex-processed.json`. The shared engine receives only normalized transcripts and never branches on `agent == "codex"` for state tracking.

## L13 - Keep memory policy in the prompt until there is a second consumer

The rules for artifacts, facts, exclusions, output schema, and memory types live in `distill/prompt.md`. A separate `policy.yaml` would duplicate policy until a concrete validator or non-prompt consumer exists.

**How to apply:** when changing what gets remembered, edit `distill/prompt.md` first. Add structured policy only if another component needs to enforce the same rules outside the prompt.

## L14 - Codex CLI distillation must be ephemeral

The Codex scanner invokes `codex exec` as the LLM provider. If those provider calls create normal Codex session logs, the scanner can later pick up its own distillation sessions and create noisy recursion.

**How to apply:** `distill/providers.py` runs Codex provider calls with `codex exec --ephemeral`. Keep that flag unless Codex changes how it logs non-interactive sessions.
