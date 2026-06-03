# Use cases

What this setup is actually used for. If a use case isn't here, it probably isn't worth the complexity.

## 1. Cross-session memory for AI coding agents

**Problem:** every new Claude Code / Codex / Cursor session starts cold. Conventions, decisions, and "we already tried that" knowledge gets lost between conversations.

**Solution:** `mcp-memory-service` stores facts as embeddings in SQLite-vec. The `/mcp-memory-query` skill teaches the agent to retrieve them when the user asks "what do you remember about X" or similar.

## 2. Automatic harvesting of session learnings

**Problem:** even with a memory service, you have to remember to say "save this" - so most useful learnings never get stored.

**Solution:** the post-session hook reads each session's transcript at end-of-session, asks an LLM to extract two things, and stores them automatically:

- **Artifacts** - concrete deliverables (a new feature, a refactor, a script, a migration, a design doc). Tagged by project slug.
- **Facts** - durable, cross-project insights (preferences, decisions, gotchas, reference paths).

Both flow into the same memory service the agent queries during a session.

## 3. Searchable record of "what was built for project X"

**Problem:** reconstructing what was done in a project over time is hard. Git history captures diffs, but not the decisions made or the analysis behind them.

**Solution:** every artifact stored by the hook is tagged with a project slug and `type:<artifact-type>`. Querying `memory_search` with a project tag returns every artifact produced for that project across every session.

## 4. Provider-agnostic experimentation

**Problem:** you want to compare distillation quality and cost across Claude Haiku, GPT, Gemini, and various OpenRouter models without rewriting the hook.

**Solution:** `config/providers.yaml` selects the active provider declaratively. Switching is a one-line edit. With LangSmith enabled, it captures latency, cost, and output for every run, making A/B comparison straightforward.

## 5. Reproducible setup across machines

**Problem:** when you move to a new machine or onboard another AI agent, the existing setup is scattered across `~/.claude/`, app config dirs, and `~/Library/Application Support/`.

**Solution:** this repo. `python3 onboard.py` (or `bash scripts/install.sh`) reproduces everything from a single `git clone`. Add the Cloudflare hybrid backend and the same memory follows you to every device.

## What this is NOT for

- Not a general-purpose knowledge base. Use a notes app or wiki for that.
- Not for storing secrets, API keys, or credentials. The prompt explicitly excludes them.
- Not for ephemeral session state - that's what the in-session conversation is for.
- Not for replacing CLAUDE.md / AGENTS.md project instructions. Those are the agent's working contract; memory is for things that emerge across many sessions.
