#!/usr/bin/env bash
# Idempotent installer for cross-agent-memory-kit.
# Safe to re-run. Skips work that's already done and preserves the existing
# memory database.
#
# What it does:
#   1. Creates ~/.local/share/mcp-memory-service-venv/ with Python 3.10+
#      only when that venv does not already exist.
#   2. Reuses existing dependencies when they import successfully. Use
#      --upgrade-deps to intentionally upgrade them.
#   3. Prints next-step instructions for registering the MCP server with common
#      AI agents (Claude Code, Codex, Cursor, Gemini, Kiro).
#
# It does NOT auto-modify your AI agent's config files - that's a destructive
# operation and we'd rather show you the JSON to paste than guess wrong.
#
# It does NOT delete, recreate, compact, migrate, or overwrite the memory DB.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${MCP_MEMORY_VENV:-$HOME/.local/share/mcp-memory-service-venv}"
UPGRADE_DEPS=0

usage() {
  cat <<'EOF'
Usage: bash scripts/install.sh [--upgrade-deps]

Default behavior is preservation-first:
  - reuse an existing venv
  - skip pip/uv install when required imports already work
  - never delete or rewrite the memory database

Options:
  --upgrade-deps   intentionally upgrade mcp-memory-service and hook deps
  -h, --help       show this help
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --upgrade-deps)
      UPGRADE_DEPS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ -n "${MCP_MEMORY_SQLITE_VEC_PATH:-}" ]; then
  DB_PATH="$MCP_MEMORY_SQLITE_VEC_PATH"
else
  case "$(uname -s)" in
    Darwin)
      DB_PATH="$HOME/Library/Application Support/mcp-memory/sqlite_vec.db"
      ;;
    Linux)
      DB_PATH="${XDG_DATA_HOME:-$HOME/.local/share}/mcp-memory/sqlite_vec.db"
      ;;
    *)
      DB_PATH="$HOME/.mcp-memory/sqlite_vec.db"
      ;;
  esac
fi

# Prefer `uv` (fast; what we use day-to-day). Fall back to stdlib venv + pip.
USE_UV=0
if command -v uv >/dev/null 2>&1; then
  USE_UV=1
fi

deps_ok() {
  "$PY" - <<'PY'
import importlib
mods = ["mcp_memory_service", "langsmith", "langchain_anthropic",
        "langchain_openai", "langchain_google_genai", "dotenv", "yaml"]
missing = []
for mod in mods:
    try:
        importlib.import_module(mod)
    except Exception as exc:
        missing.append(f"{mod}: {exc}")
if missing:
    for item in missing:
        print(f"  missing: {item}")
    raise SystemExit(1)
PY
}

verify_deps() {
  "$PY" - <<'PY'
import importlib
mods = ["mcp_memory_service", "langsmith", "langchain_anthropic",
        "langchain_openai", "langchain_google_genai", "dotenv", "yaml"]
for mod in mods:
    importlib.import_module(mod)
    print(f"  ok: {mod}")
PY
}

# ---- 1. venv ---------------------------------------------------------------

echo "==> Memory DB path: $DB_PATH"
if [ -f "$DB_PATH" ]; then
  echo "==> Existing memory DB found; preserving it"
else
  echo "==> No memory DB found at that path yet; the server will create one on first use"
fi

if [ ! -d "$VENV" ]; then
  echo "==> Creating venv at $VENV"
  if [ "$USE_UV" -eq 1 ]; then
    uv venv --python 3.12 "$VENV" 2>/dev/null || uv venv --python 3.11 "$VENV" 2>/dev/null || uv venv "$VENV"
  else
    PY="$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)"
    if [ -z "$PY" ]; then
      echo "ERROR: need python3.10+ on PATH" >&2
      exit 1
    fi
    "$PY" -m venv "$VENV"
  fi
else
  echo "==> Reusing venv at $VENV"
fi

PY="$VENV/bin/python"

# ---- 2. dependencies -------------------------------------------------------

echo "==> Checking mcp-memory-service + LangSmith + LangChain dependencies"

DEPS=(
  mcp-memory-service
  langsmith
  langchain-anthropic
  langchain-openai
  langchain-google-genai
  python-dotenv
  pyyaml
)

if deps_ok && [ "$UPGRADE_DEPS" -eq 0 ]; then
  echo "==> Existing dependencies import successfully; skipping install/upgrade"
else
  if [ "$UPGRADE_DEPS" -eq 1 ]; then
    echo "==> Upgrading dependencies because --upgrade-deps was provided"
    PIP_FLAGS=(--quiet --upgrade)
  else
    echo "==> Installing missing dependencies without forcing upgrades"
    PIP_FLAGS=(--quiet)
  fi

  if [ "$USE_UV" -eq 1 ]; then
    VIRTUAL_ENV="$VENV" uv pip install "${PIP_FLAGS[@]}" "${DEPS[@]}"
    # Optional - SDK-native LangSmith integration with the Claude Agent SDK.
    VIRTUAL_ENV="$VENV" uv pip install "${PIP_FLAGS[@]}" 'langsmith[claude-agent-sdk]' || true
  else
    "$VENV/bin/pip" install -q pip wheel
    "$VENV/bin/pip" install "${PIP_FLAGS[@]}" "${DEPS[@]}"
    "$VENV/bin/pip" install "${PIP_FLAGS[@]}" 'langsmith[claude-agent-sdk]' || true
  fi
fi

# ---- 3. sanity checks ------------------------------------------------------

echo "==> Verifying"
verify_deps

# ---- 4. hook executable ----------------------------------------------------

chmod +x "$REPO_ROOT/hooks/distill_session.py"

# ---- 5. .env / config check -----------------------------------------------

if [ ! -f "$REPO_ROOT/.env" ]; then
  echo "==> No .env yet. Copy .env.example and fill in:"
  echo "    cp $REPO_ROOT/.env.example $REPO_ROOT/.env"
fi

if [ ! -f "$REPO_ROOT/config/providers.yaml" ]; then
  echo "==> No providers.yaml. Copy from example to override defaults:"
  echo "    cp $REPO_ROOT/config/providers.example.yaml $REPO_ROOT/config/providers.yaml"
fi

# ---- 6. agent-registration instructions -----------------------------------

cat <<EOF

==> Install complete.

Memory DB preserved at:
  $DB_PATH

To register the MCP server with your AI agent, add this block to its config:

  command: $VENV/bin/python
  args:    ["-m", "mcp_memory_service.server"]
  type:    stdio

Per-agent file paths:

  Claude Code  ~/.claude.json                        (mcpServers.memory)
  Hermes       ~/.hermes/config.yaml                  (mcp_servers.memory)
  Codex CLI    ~/.codex/config.toml                  ([mcp_servers.memory])
  Cursor       ~/.cursor/mcp.json                    (mcpServers.memory)
  Gemini CLI   ~/.gemini/settings.json               (mcpServers.memory)
  Kiro         ~/.kiro/settings/mcp.json             (mcpServers.memory)

For Hermes Agent, edit `~/.hermes/config.yaml` directly and add:

  mcp_servers:
    memory:
      command: $VENV/bin/python
      args: ["-m", "mcp_memory_service.server"]
      env: {}
      timeout: 120
      connect_timeout: 60

Then restart Hermes or run `/reload-mcp`. Use a separate Hermes skill copy because
Hermes names native MCP tools like `mcp_memory_memory_search`, not Claude's
`mcp__memory__memory_search` names.

For Claude Code, also wire the SessionEnd hook (see README.md).

For non-Claude agents, the SessionEnd hook is Claude-Code-specific. Either run
$REPO_ROOT/hooks/distill_session.py manually after each session, or schedule it.
EOF
