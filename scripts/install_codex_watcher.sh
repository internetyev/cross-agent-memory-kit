#!/usr/bin/env bash
# Install the macOS launchd job that distills quiet Codex sessions daily at 04:00.
# Generates the plist from launchd/memory-distill.plist.template with this
# machine's paths - nothing absolute is baked into the repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${MCP_MEMORY_VENV:-$HOME/.local/share/mcp-memory-service-venv}"
PY="$VENV/bin/python"
SCANNER="$REPO_ROOT/wrappers/codex_session_scan.py"
LABEL="com.mcp-memory.codex-distill"
TEMPLATE="$REPO_ROOT/launchd/memory-distill.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
STATE_ROOT="$HOME/.local/state/cross-agent-memory-kit"
LOG_OUT="$STATE_ROOT/logs/codex-launchd.out.log"
LOG_ERR="$STATE_ROOT/logs/codex-launchd.err.log"
# Keep the launchd PATH portable across Intel (/usr/local) and Apple Silicon
# (/opt/homebrew) Macs, and include the user's ~/.local/bin.
LAUNCHD_PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

mkdir -p "$HOME/Library/LaunchAgents" "$STATE_ROOT/logs"

# Mark all currently-quiet Codex sessions as baseline so the first run does not
# distill years of history.
"$PY" "$SCANNER" \
  --mark-existing \
  --quiet-minutes 30 \
  --lookback-days 3650 \
  --limit 0

# Render the template -> destination plist.
sed \
  -e "s|__LABEL__|$LABEL|g" \
  -e "s|__PYTHON__|$PY|g" \
  -e "s|__SCANNER__|$SCANNER|g" \
  -e "s|__PATH__|$LAUNCHD_PATH|g" \
  -e "s|__LOG_OUT__|$LOG_OUT|g" \
  -e "s|__LOG_ERR__|$LOG_ERR|g" \
  "$TEMPLATE" > "$PLIST_DST"

launchctl bootout "gui/$(id -u)" "$PLIST_DST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed Codex memory distillation watcher:"
echo "  $PLIST_DST"
echo
echo "Logs:"
echo "  $STATE_ROOT/logs/codex.log"
echo "  $LOG_OUT"
echo "  $LOG_ERR"
