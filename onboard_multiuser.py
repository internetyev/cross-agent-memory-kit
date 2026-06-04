#!/usr/bin/env python3
"""
Multi-user onboarding wizard for cross-agent-memory-kit.

Use this instead of onboard.py when ONE Claude (or other agent) account is
shared by several people - a company team, or a family - and each person needs
their own PRIVATE memory while still sharing a common pool of team/family-wide
memory.

It configures HARD ISOLATION: two MCP memory servers per person, each backed by
a separate store.

    memory-shared    -> the shared Cloudflare D1 + Vectorize everyone connects to
    memory-private   -> THIS person's own Cloudflare D1 + Vectorize (private)

Others physically cannot read your private database - privacy is enforced by
separate databases and tokens, not by tags. See MULTI-USER.md for the full
threat model and the one-time Cloudflare resource setup
(scripts/setup_multiuser_cloudflare.sh).

What this wizard does:
  1. Verify Python 3.10+ and run the installer (reuses an existing venv).
  2. Pick a distillation provider for the post-session hook.
  3. Collect this person's identity + the shared and private Cloudflare stores.
  4. Write .env so the post-session hook distills into the PRIVATE store and
     tags every memory with owner:<person> scope:private.
  5. Write config/providers.yaml.
  6. Print BOTH MCP server blocks to paste into the agent config, plus the
     Claude SessionEnd hook block and the multi-user skill install command.

Safety (same as onboard.py):
  - Never edits your agent config files; it prints blocks for you to paste.
  - Never deletes, recreates, or migrates any memory database.
  - Re-runnable. Pass --force to overwrite an existing .env.

Stdlib only - run with system python3:

    python3 onboard_multiuser.py
    python3 onboard_multiuser.py --help     # non-interactive flags
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Reuse the single-user wizard's helpers so the two stay in lockstep.
from onboard import (
    AGENTS,
    CF_EMBED_MODEL,
    DEFAULT_VENV,
    PROVIDER_ENV_KEY,
    PROVIDERS,
    REPO_ROOT,
    ask,
    ask_choice,
    ask_yes,
    check_python,
    print_hook_block,
    render_block,
    run_installer,
    say,
    step,
    write_providers_yaml,
)


def cache_base_dir() -> Path:
    """Where mcp-memory-service keeps its local SQLite cache, per OS."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "mcp-memory"
    if sys.platform.startswith("linux"):
        return Path.home() / ".local" / "share" / "mcp-memory"
    return Path.home() / ".mcp-memory"


def store_env(cf: dict, cache_path: Path) -> dict:
    """Hybrid backend env for one store (shared or private)."""
    return {
        "MCP_MEMORY_STORAGE_BACKEND": "hybrid",
        "MCP_MEMORY_SQLITE_VEC_PATH": str(cache_path),
        "CLOUDFLARE_API_TOKEN": cf.get("token") or "<YOUR_CLOUDFLARE_API_TOKEN>",
        "CLOUDFLARE_ACCOUNT_ID": cf.get("account") or "<YOUR_CLOUDFLARE_ACCOUNT_ID>",
        "CLOUDFLARE_D1_DATABASE_ID": cf.get("d1") or "<YOUR_D1_DATABASE_ID>",
        "CLOUDFLARE_VECTORIZE_INDEX": cf.get("index") or "mcp-memory",
        "CLOUDFLARE_EMBEDDING_MODEL": CF_EMBED_MODEL,
        "HYBRID_SYNC_ON_STARTUP": "true",
    }


def ask_store(label: str, defaults: dict, *, noninteractive: bool) -> dict:
    say(f"\n  {label} Cloudflare store:")
    return {
        "account": ask("CLOUDFLARE_ACCOUNT_ID", defaults.get("account", ""), noninteractive=noninteractive),
        "d1": ask("CLOUDFLARE_D1_DATABASE_ID", defaults.get("d1", ""), noninteractive=noninteractive),
        "index": ask("CLOUDFLARE_VECTORIZE_INDEX", defaults.get("index", "mcp-memory"), noninteractive=noninteractive),
        "token": ask("CLOUDFLARE_API_TOKEN (kept out of the repo)", defaults.get("token", ""), noninteractive=noninteractive),
    }


def write_env_multiuser(
    *,
    provider: str,
    person: str,
    private_cache: Path,
    force: bool,
    langsmith: bool,
    ls_key: str,
    api_key: str,
) -> None:
    """Write .env with the multi-user routing block.

    The post-session hook reads .env (via distill/providers.py), so pointing
    MCP_MEMORY_SQLITE_VEC_PATH at the private cache is what makes distilled
    session memories land in the PRIVATE store. MEMORY_OWNER / MEMORY_DEFAULT_SCOPE
    tag each memory so its owner and intended audience are searchable.
    """
    env_path = REPO_ROOT / ".env"
    if env_path.exists() and not force:
        say("  .env already exists - leaving it untouched (use --force to overwrite).")
        say("  Make sure it contains these lines so the hook writes to the private store:")
        say(f"    MEMORY_OWNER={person}")
        say("    MEMORY_DEFAULT_SCOPE=private")
        say(f'    MCP_MEMORY_SQLITE_VEC_PATH={private_cache}')
        return
    template = (REPO_ROOT / ".env.example").read_text()
    out = template
    if langsmith and ls_key:
        out = out.replace("LANGSMITH_TRACING=false", "LANGSMITH_TRACING=true")
        out = out.replace("LANGSMITH_API_KEY=", f"LANGSMITH_API_KEY={ls_key}", 1)
    key_name = PROVIDER_ENV_KEY.get(provider)
    if key_name and api_key:
        out = out.replace(f"{key_name}=", f"{key_name}={api_key}", 1)

    multiuser_block = (
        "\n"
        "# =============================================================================\n"
        "# Multi-user routing (written by onboard_multiuser.py)\n"
        "# =============================================================================\n"
        "# The post-session distillation hook reads this file. These three lines make\n"
        "# the hook write distilled memories into THIS person's private store and tag\n"
        "# them with the owner + default scope. The shared/private MCP servers get\n"
        "# their own env in the agent config blocks; these only affect the hook.\n"
        f"MEMORY_OWNER={person}\n"
        "MEMORY_DEFAULT_SCOPE=private\n"
        f'MCP_MEMORY_SQLITE_VEC_PATH={private_cache}\n'
    )
    env_path.write_text(out + multiuser_block)
    env_path.chmod(0o600)
    say(f"  Wrote {env_path} (chmod 600) with multi-user routing for '{person}'.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Multi-user onboarding wizard for cross-agent-memory-kit.")
    ap.add_argument("--agent", choices=list(AGENTS), help="agent to print config for")
    ap.add_argument("--provider", choices=PROVIDERS, help="distillation provider")
    ap.add_argument("--person", help="this person's identity slug, e.g. alice")
    ap.add_argument("--venv", type=Path, default=DEFAULT_VENV, help=f"venv path (default {DEFAULT_VENV})")
    # Shared store
    ap.add_argument("--shared-account-id", default="")
    ap.add_argument("--shared-d1-id", default="")
    ap.add_argument("--shared-vectorize", default="mcp-memory-shared")
    ap.add_argument("--shared-token", default=os.environ.get("CLOUDFLARE_API_TOKEN", ""))
    # Private store
    ap.add_argument("--private-account-id", default="")
    ap.add_argument("--private-d1-id", default="")
    ap.add_argument("--private-vectorize", default="")
    ap.add_argument("--private-token", default="")
    ap.add_argument("--no-install", action="store_true", help="skip running scripts/install.sh")
    ap.add_argument("--force", action="store_true", help="overwrite existing .env")
    ap.add_argument("-y", "--yes", action="store_true", help="non-interactive; use defaults/flags")
    args = ap.parse_args()
    ni = args.yes

    say("=" * 70)
    say("  cross-agent-memory-kit - MULTI-USER onboarding wizard")
    say("  (shared account, hard-isolated private memory per person)")
    say("=" * 70)

    step(1, "Checking Python")
    check_python()
    say(f"  OK: Python {sys.version.split()[0]}")

    step(2, "Installing mcp-memory-service into a venv")
    py = run_installer(args.venv, args.no_install)

    step(3, "Distillation provider for the post-session hook")
    say("  CLI providers (claude-cli, codex-cli, ...) are subscription-billed and need no API key.")
    provider = args.provider or ask_choice(
        "Which provider should the hook use?", PROVIDERS, "claude-cli", noninteractive=ni
    )
    api_key = ""
    if provider in PROVIDER_ENV_KEY:
        key_name = PROVIDER_ENV_KEY[provider]
        api_key = os.environ.get(key_name, "")
        if not api_key:
            api_key = ask(f"{key_name} (leave blank to fill in .env later)", "", noninteractive=ni)

    langsmith = False
    ls_key = ""
    if not ni:
        langsmith = ask_yes("Enable LangSmith tracing of distillation calls?", False, noninteractive=ni)
        if langsmith:
            ls_key = ask("LANGSMITH_API_KEY", "", noninteractive=ni)

    step(4, "Who is this person?")
    say("  A short lowercase slug used in tags (owner:<slug>) and the private cache path.")
    person = (args.person or ask("Person slug, e.g. alice", "", noninteractive=ni)).strip().lower()
    if not person:
        say("ERROR: a person slug is required for a multi-user install.")
        sys.exit(1)

    step(5, "Cloudflare stores (run scripts/setup_multiuser_cloudflare.sh first if you have not)")
    say("  You need TWO stores: the shared one (same for everyone) and this")
    say("  person's private one (unique per person). See MULTI-USER.md.")

    shared = ask_store(
        "SHARED",
        {
            "account": args.shared_account_id,
            "d1": args.shared_d1_id,
            "index": args.shared_vectorize or "mcp-memory-shared",
            "token": args.shared_token,
        },
        noninteractive=ni,
    )

    reuse_creds = False
    if not ni:
        reuse_creds = ask_yes(
            "Is the private store in the SAME Cloudflare account/token as the shared one?",
            True,
            noninteractive=ni,
        )
    private_defaults = {
        "account": args.private_account_id or (shared["account"] if reuse_creds else ""),
        "d1": args.private_d1_id,
        "index": args.private_vectorize or f"mcp-memory-{person}",
        "token": args.private_token or (shared["token"] if reuse_creds else ""),
    }
    private = ask_store("PRIVATE", private_defaults, noninteractive=ni)

    base = cache_base_dir()
    shared_cache = base / "shared" / "sqlite_vec.db"
    private_cache = base / f"private-{person}" / "sqlite_vec.db"

    for cf, name in ((shared, "shared"), (private, "private")):
        if not all([cf["account"], cf["d1"], cf["token"]]):
            say(f"  NOTE: some {name} Cloudflare values are blank - the printed block will")
            say("        contain <PLACEHOLDER>s for you to fill in.")

    step(6, "Writing local config")
    write_env_multiuser(
        provider=provider,
        person=person,
        private_cache=private_cache,
        force=args.force,
        langsmith=langsmith,
        ls_key=ls_key,
        api_key=api_key,
    )
    write_providers_yaml(provider, args.force)

    step(7, "Your TWO MCP server blocks")
    agent = args.agent or ask_choice(
        "Which agent are you configuring?", list(AGENTS), "claude", noninteractive=ni
    )
    label, cfg_path, _, _ = AGENTS[agent]
    shared_block = render_block(agent, py, store_env(shared, shared_cache), server_name="memory-shared")
    private_block = render_block(agent, py, store_env(private, private_cache), server_name="memory-private")

    say(f"\n  Paste BOTH of these into {label}'s config at {cfg_path}")
    say("  (merge them under the same mcpServers / mcp_servers key - do not nest):\n")
    say("  --- shared store (same for everyone) ---")
    say(shared_block)
    say("\n  --- private store (unique to this person) ---")
    say(private_block)

    if agent == "claude":
        say("\n  And add this SessionEnd hook to ~/.claude/settings.json.")
        say("  It reads .env, so it writes distilled memories to the PRIVATE store:\n")
        print_hook_block(py)
        say("\n  Then install the multi-user retrieval skill:")
        say("    mkdir -p ~/.claude/skills/mcp-memory-multiuser")
        say(f"    cp {REPO_ROOT/'skills'/'mcp-memory-multiuser'/'SKILL.md'} ~/.claude/skills/mcp-memory-multiuser/")

    say("\n" + "=" * 70)
    say("  Done. Restart your agent so it loads BOTH memory servers.")
    say(f"  The tools will appear as mcp__memory-shared__* and mcp__memory-private__*.")
    say("  Re-run this wizard on each device with the SAME shared store and the")
    say(f"  SAME private store for '{person}'. Use a DIFFERENT private store per person.")
    say("=" * 70)


if __name__ == "__main__":
    main()
