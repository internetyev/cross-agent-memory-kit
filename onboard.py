#!/usr/bin/env python3
"""
Interactive onboarding wizard for cross-agent-memory-kit.

Walks you through a full install:
  1. Verify Python 3.10+.
  2. Create/reuse the venv and install deps (delegates to scripts/install.sh).
  3. Choose a distillation provider for the post-session hook.
  4. Choose local-only storage or the Cloudflare hybrid backend (multi-device).
  5. Write .env and config/providers.yaml (without clobbering existing files).
  6. Print the exact MCP server block to paste into your agent's config, plus
     the Claude Code SessionEnd hook block.

Safety:
  - Never edits your agent config files. It prints the block and tells you where
    to paste it, so it cannot corrupt a config by guessing.
  - Never deletes, recreates, or migrates the memory database.
  - Re-runnable. Existing .env / providers.yaml are left untouched unless you
    pass --force.

Stdlib only - run it with system python3, before the venv exists:

    python3 onboard.py
    python3 onboard.py --help        # non-interactive flags
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_VENV = Path.home() / ".local" / "share" / "mcp-memory-service-venv"

PROVIDERS = [
    "claude-cli", "codex-cli", "gemini-cli", "cursor-cli",
    "anthropic-api", "openai-api", "gemini-api", "openrouter-api",
]
CLI_PROVIDERS = {"claude-cli", "codex-cli", "gemini-cli", "cursor-cli"}
PROVIDER_ENV_KEY = {
    "anthropic-api": "ANTHROPIC_API_KEY",
    "openai-api": "OPENAI_API_KEY",
    "gemini-api": "GOOGLE_API_KEY",
    "openrouter-api": "OPENROUTER_API_KEY",
}

AGENTS = {
    "claude":  ("Claude Code", "~/.claude.json", "json",  "mcpServers"),
    "codex":   ("Codex CLI",   "~/.codex/config.toml", "toml", "mcp_servers"),
    "cursor":  ("Cursor",      "~/.cursor/mcp.json", "json", "mcpServers"),
    "gemini":  ("Gemini CLI",  "~/.gemini/settings.json", "json", "mcpServers"),
    "kiro":    ("Kiro",        "~/.kiro/settings/mcp.json", "json", "mcpServers"),
    "hermes":  ("Hermes",      "~/.hermes/config.yaml", "yaml", "mcp_servers"),
}

CF_EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"


# --------------------------------------------------------------------------- #
# Small I/O helpers
# --------------------------------------------------------------------------- #
def say(msg: str = "") -> None:
    print(msg)


def step(n: int, msg: str) -> None:
    print(f"\n\033[1m[{n}]\033[0m {msg}")


def ask(prompt: str, default: str | None = None, *, noninteractive: bool) -> str:
    if noninteractive:
        return default or ""
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"  {prompt}{suffix}: ").strip()
    except EOFError:
        ans = ""
    return ans or (default or "")


def ask_choice(prompt: str, choices: list[str], default: str, *, noninteractive: bool) -> str:
    if noninteractive:
        return default
    say(f"  {prompt}")
    for i, c in enumerate(choices, 1):
        mark = " (default)" if c == default else ""
        say(f"    {i}. {c}{mark}")
    raw = ask("choose a number", str(choices.index(default) + 1), noninteractive=noninteractive)
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(choices):
            return choices[idx]
    except ValueError:
        if raw in choices:
            return raw
    return default


def ask_yes(prompt: str, default: bool, *, noninteractive: bool) -> bool:
    if noninteractive:
        return default
    d = "Y/n" if default else "y/N"
    ans = ask(f"{prompt} ({d})", "", noninteractive=noninteractive).lower()
    if not ans:
        return default
    return ans.startswith("y")


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
def check_python() -> None:
    if sys.version_info < (3, 10):
        say(f"ERROR: Python 3.10+ required, found {sys.version.split()[0]}.")
        sys.exit(1)


def run_installer(venv: Path, skip: bool) -> Path:
    py = venv / "bin" / "python"
    if skip:
        say(f"  Skipping installer (--no-install). Expecting venv python at {py}")
        return py
    installer = REPO_ROOT / "scripts" / "install.sh"
    env = dict(os.environ, MCP_MEMORY_VENV=str(venv))
    say(f"  Running {installer} (venv: {venv})")
    try:
        subprocess.run(["bash", str(installer)], check=True, env=env)
    except subprocess.CalledProcessError as exc:
        say(f"ERROR: installer failed (exit {exc.returncode}). Fix the error above and re-run.")
        sys.exit(1)
    return py


def write_env(provider: str, force: bool, *, noninteractive: bool,
              langsmith: bool, ls_key: str, api_key: str) -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.exists() and not force:
        say(f"  .env already exists - leaving it untouched (use --force to overwrite).")
        return
    template = (REPO_ROOT / ".env.example").read_text()
    out = template
    if langsmith and ls_key:
        out = out.replace("LANGSMITH_TRACING=false", "LANGSMITH_TRACING=true")
        out = out.replace("LANGSMITH_API_KEY=", f"LANGSMITH_API_KEY={ls_key}", 1)
    key_name = PROVIDER_ENV_KEY.get(provider)
    if key_name and api_key:
        out = out.replace(f"{key_name}=", f"{key_name}={api_key}", 1)
    env_path.write_text(out)
    env_path.chmod(0o600)
    say(f"  Wrote {env_path} (chmod 600).")


def write_providers_yaml(provider: str, force: bool) -> None:
    path = REPO_ROOT / "config" / "providers.yaml"
    if path.exists() and not force:
        say("  config/providers.yaml already exists - leaving it untouched.")
        return
    example = (REPO_ROOT / "config" / "providers.example.yaml").read_text()
    out = []
    for line in example.splitlines():
        if line.startswith("default_provider:"):
            out.append(f"default_provider: {provider}")
        else:
            out.append(line)
    path.write_text("\n".join(out) + "\n")
    say(f"  Wrote {path} (default_provider: {provider}).")


def build_server_env(backend: str, cf: dict) -> dict:
    if backend != "hybrid":
        return {}
    return {
        "MCP_MEMORY_STORAGE_BACKEND": "hybrid",
        "CLOUDFLARE_API_TOKEN": cf.get("token") or "<YOUR_CLOUDFLARE_API_TOKEN>",
        "CLOUDFLARE_ACCOUNT_ID": cf.get("account") or "<YOUR_CLOUDFLARE_ACCOUNT_ID>",
        "CLOUDFLARE_D1_DATABASE_ID": cf.get("d1") or "<YOUR_D1_DATABASE_ID>",
        "CLOUDFLARE_VECTORIZE_INDEX": cf.get("index") or "mcp-memory",
        "CLOUDFLARE_EMBEDDING_MODEL": CF_EMBED_MODEL,
        "HYBRID_SYNC_ON_STARTUP": "true",
    }


def render_block(agent: str, py: Path, server_env: dict) -> str:
    label, cfg_path, fmt, root_key = AGENTS[agent]
    args = ["-m", "mcp_memory_service.server"]
    if fmt == "json":
        block = {root_key: {"memory": {
            "type": "stdio",
            "command": str(py),
            "args": args,
            "env": server_env,
        }}}
        return json.dumps(block, indent=2)
    if fmt == "toml":
        lines = [f"[{root_key}.memory]",
                 f'command = "{py}"',
                 f'args = {json.dumps(args)}']
        for k, v in server_env.items():
            lines.append(f'env.{k} = "{v}"')
        return "\n".join(lines)
    # yaml (hermes)
    lines = [f"{root_key}:", "  memory:", f'    command: "{py}"',
             f"    args: {json.dumps(args)}"]
    if server_env:
        lines.append("    env:")
        for k, v in server_env.items():
            lines.append(f'      {k}: "{v}"')
    else:
        lines.append("    env: {}")
    lines += ["    timeout: 120", "    connect_timeout: 60"]
    return "\n".join(lines)


def print_hook_block(py: Path) -> None:
    hook = REPO_ROOT / "hooks" / "distill_session.py"
    block = {
        "hooks": {"SessionEnd": [
            {"hooks": [{
                "type": "command",
                "command": f"{py} {hook}",
                "async": True,
                "timeout": 300,
            }]}
        ]}
    }
    say(json.dumps(block, indent=2))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Interactive onboarding wizard for cross-agent-memory-kit.")
    ap.add_argument("--agent", choices=list(AGENTS), help="agent to print config for")
    ap.add_argument("--provider", choices=PROVIDERS, help="distillation provider")
    ap.add_argument("--backend", choices=["local", "hybrid"], help="storage backend")
    ap.add_argument("--venv", type=Path, default=DEFAULT_VENV, help=f"venv path (default {DEFAULT_VENV})")
    ap.add_argument("--cf-account-id", default="")
    ap.add_argument("--cf-d1-id", default="")
    ap.add_argument("--cf-vectorize", default="mcp-memory")
    ap.add_argument("--cf-token", default=os.environ.get("CLOUDFLARE_API_TOKEN", ""),
                    help="Cloudflare API token (defaults to $CLOUDFLARE_API_TOKEN; avoid passing on the CLI)")
    ap.add_argument("--no-install", action="store_true", help="skip running scripts/install.sh")
    ap.add_argument("--force", action="store_true", help="overwrite existing .env / providers.yaml")
    ap.add_argument("-y", "--yes", action="store_true", help="non-interactive; use defaults/flags")
    args = ap.parse_args()
    ni = args.yes

    say("=" * 70)
    say("  cross-agent-memory-kit - onboarding wizard")
    say("=" * 70)

    step(1, "Checking Python")
    check_python()
    say(f"  OK: Python {sys.version.split()[0]}")

    step(2, "Installing mcp-memory-service into a venv")
    py = run_installer(args.venv, args.no_install)

    step(3, "Distillation provider for the post-session hook")
    say("  CLI providers (claude-cli, codex-cli, ...) are subscription-billed and need no API key.")
    provider = args.provider or ask_choice("Which provider should the hook use?",
                                            PROVIDERS, "claude-cli", noninteractive=ni)
    api_key = ""
    if provider in PROVIDER_ENV_KEY:
        key_name = PROVIDER_ENV_KEY[provider]
        api_key = args.__dict__.get("api_key", "") or os.environ.get(key_name, "")
        if not api_key:
            api_key = ask(f"{key_name} (leave blank to fill in .env later)", "", noninteractive=ni)

    langsmith = False
    ls_key = ""
    if not ni:
        langsmith = ask_yes("Enable LangSmith tracing of distillation calls?", False, noninteractive=ni)
        if langsmith:
            ls_key = ask("LANGSMITH_API_KEY", "", noninteractive=ni)

    step(4, "Storage backend")
    say("  local  = one SQLite database on this machine (simplest).")
    say("  hybrid = shared across devices via Cloudflare D1 + Vectorize (see MULTI-DEVICE-SYNC.md).")
    backend = args.backend or ask_choice("Which backend?", ["local", "hybrid"], "local", noninteractive=ni)
    cf = {}
    if backend == "hybrid":
        cf = {
            "account": args.cf_account_id or ask("CLOUDFLARE_ACCOUNT_ID", "", noninteractive=ni),
            "d1": args.cf_d1_id or ask("CLOUDFLARE_D1_DATABASE_ID", "", noninteractive=ni),
            "index": args.cf_vectorize or ask("CLOUDFLARE_VECTORIZE_INDEX", "mcp-memory", noninteractive=ni),
            "token": args.cf_token or ask("CLOUDFLARE_API_TOKEN (kept out of the repo)", "", noninteractive=ni),
        }
        if not all([cf["account"], cf["d1"], cf["token"]]):
            say("  NOTE: some Cloudflare values are blank - the printed block will contain"
                " <PLACEHOLDER>s for you to fill in. See MULTI-DEVICE-SYNC.md to create the resources.")

    step(5, "Writing local config")
    write_env(provider, args.force, noninteractive=ni, langsmith=langsmith, ls_key=ls_key, api_key=api_key)
    write_providers_yaml(provider, args.force)

    step(6, "Your MCP server block")
    agent = args.agent or ask_choice("Which agent are you configuring?",
                                      list(AGENTS), "claude", noninteractive=ni)
    label, cfg_path, _, _ = AGENTS[agent]
    server_env = build_server_env(backend, cf)
    say(f"\n  Paste this into {label}'s config at {cfg_path}:\n")
    say(render_block(agent, py, server_env))

    if agent == "claude":
        say("\n  And add this SessionEnd hook to ~/.claude/settings.json:\n")
        print_hook_block(py)
        say("\n  Then copy the retrieval skill:")
        say(f"    mkdir -p ~/.claude/skills/mcp-memory-query")
        say(f"    cp {REPO_ROOT/'skills'/'mcp-memory-query'/'SKILL.md'} ~/.claude/skills/mcp-memory-query/")

    say("\n" + "=" * 70)
    say("  Done. Restart your agent so it loads the MCP server.")
    if backend == "hybrid":
        say("  Run the wizard again on each other device with the SAME Cloudflare values.")
    say("=" * 70)


if __name__ == "__main__":
    main()
