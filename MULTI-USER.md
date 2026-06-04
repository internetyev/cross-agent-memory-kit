# Multi-user memory on a shared account (private + shared)

Sometimes one Claude (or Codex / Cursor / Gemini) account is used by **several
people**:

- a **company** with a single shared Claude subscription, where every employee
  wants their own memory and only some of it shared across the company, or
- a **family** account shared by spouses, children, and relatives, where some
  memory is household-wide and some is personal.

The plain [MULTI-DEVICE-SYNC.md](MULTI-DEVICE-SYNC.md) setup shares **one**
memory across all devices - which is exactly what you do **not** want here,
because it would merge everyone's memory into one pool.

This guide sets up a split instead:

- a **shared** memory store everyone connects to (team/family-wide facts), and
- a **private** memory store **per person** that only they can read.

```
                          ┌──────────────────────────┐
   Alice's agent  ───────►│  SHARED store (D1 + Vec)  │◄─────── Bob's agent
   memory-shared          │  team / family-wide       │         memory-shared
        │                 └──────────────────────────┘              │
        ▼                                                            ▼
 ┌───────────────────┐                                  ┌───────────────────┐
 │ Alice PRIVATE store│                                  │ Bob PRIVATE store │
 │  (D1 + Vectorize)  │   Bob cannot read this  ✗        │  (D1 + Vectorize) │
 │  memory-private    │                                  │  memory-private   │
 └───────────────────┘                                  └───────────────────┘
```

## Why hard isolation (separate databases), not tags

A single shared database with `owner:alice` tags would **not** be private:
anyone whose agent can reach that database can list every row regardless of
tags. Tags organize; they do not isolate.

True privacy needs a **database boundary**. So each person gets their own
Cloudflare D1 + Vectorize index (ideally with a token that can only touch that
database), and everyone additionally connects to one shared database. Each
person therefore runs **two MCP memory servers**:

| MCP server | Tool prefix | Backed by |
|---|---|---|
| `memory-shared` | `mcp__memory-shared__*` | the one shared D1 + Vectorize |
| `memory-private` | `mcp__memory-private__*` | that person's own D1 + Vectorize |

The agent sees both toolsets. The companion skill
([skills/mcp-memory-multiuser/SKILL.md](skills/mcp-memory-multiuser/SKILL.md))
teaches it to **read from both** and **write to private by default**, promoting
to shared only on a clear signal.

The `scope:private` / `scope:shared` and `owner:<person>` tags still get
written (they make a memory's intended audience searchable), but they are
descriptive only - the privacy guarantee comes from the separate databases.

## Threat model (read this for the company case)

- **Within one Cloudflare account, an API token scoped to D1-edit can read every
  D1 database in that account.** So if all private stores live in one company
  Cloudflare account and everyone shares one token, a curious employee with that
  token could read colleagues' private stores by pointing at their D1 id.
- For a **family**, that is usually fine - one account, one token, trust assumed.
- For a **company** that needs real confidentiality, give each person a
  Cloudflare API token scoped to **only their own** D1 database + Vectorize
  index (Cloudflare supports resource-scoped tokens), or put each person's
  private store in their **own** Cloudflare account and keep only the shared
  store in a common account. The shared store's token is the only one everyone
  holds.
- The local SQLite caches live under each person's OS user account. If several
  people share **one OS login** on one machine, they can read each other's local
  caches on disk - this setup assumes each person has their own OS user account
  (or their own machine).

## One-time: create the Cloudflare resources

You need a Cloudflare account (free tier is fine to start). Use the helper:

```sh
# Run ONCE for the whole team/family - creates the shared store:
scripts/setup_multiuser_cloudflare.sh shared

# Run ONCE PER PERSON - creates that person's private store:
scripts/setup_multiuser_cloudflare.sh private alice
scripts/setup_multiuser_cloudflare.sh private bob
```

Each run prints a `database_id`. Record, per store:

| Value | From |
|---|---|
| `CLOUDFLARE_ACCOUNT_ID` | dashboard sidebar / `wrangler whoami` |
| `CLOUDFLARE_D1_DATABASE_ID` | output of `wrangler d1 create` |
| `CLOUDFLARE_VECTORIZE_INDEX` | the index name (e.g. `mcp-memory-shared`, `mcp-memory-alice`) |
| `CLOUDFLARE_API_TOKEN` | a token with **D1 edit + Vectorize edit + Workers AI read** (secret) |

The Vectorize indexes are created 768-dim / cosine to match the default
embedding model `@cf/baai/bge-base-en-v1.5`.

If a resource name already exists, the helper says so; look up the existing id
with `wrangler d1 list` and reuse it.

## Configure each person's device: the wizard

On each person's machine, run the multi-user wizard:

```sh
git clone <this-repo> cross-agent-memory-kit
cd cross-agent-memory-kit
python3 onboard_multiuser.py            # interactive; --help for non-interactive flags
```

It will:

1. Reuse/create the venv (same as `onboard.py`; never touches an existing DB).
2. Ask for a distillation provider for the post-session hook.
3. Ask **who this person is** (`alice`) and for the **shared** and **private**
   Cloudflare store values.
4. Write `.env` so the post-session hook distills into **this person's private
   store** and tags memories `owner:alice scope:private`.
5. Write `config/providers.yaml`.
6. Print **both** MCP server blocks (`memory-shared` + `memory-private`), the
   Claude `SessionEnd` hook block, and the skill install command.

Run it again on each of that person's other devices with the **same** shared
store and the **same** private store. Use a **different** private store for each
different person.

## What the wizard prints (Claude Code example)

Two server blocks to merge under `mcpServers` in `~/.claude.json`:

```json
{
  "mcpServers": {
    "memory-shared": {
      "type": "stdio",
      "command": "/Users/alice/.local/share/mcp-memory-service-venv/bin/python",
      "args": ["-m", "mcp_memory_service.server"],
      "env": {
        "MCP_MEMORY_STORAGE_BACKEND": "hybrid",
        "MCP_MEMORY_SQLITE_VEC_PATH": "/Users/alice/Library/Application Support/mcp-memory/shared/sqlite_vec.db",
        "CLOUDFLARE_API_TOKEN": "<SHARED_TOKEN>",
        "CLOUDFLARE_ACCOUNT_ID": "<SHARED_ACCOUNT_ID>",
        "CLOUDFLARE_D1_DATABASE_ID": "<SHARED_D1_ID>",
        "CLOUDFLARE_VECTORIZE_INDEX": "mcp-memory-shared",
        "CLOUDFLARE_EMBEDDING_MODEL": "@cf/baai/bge-base-en-v1.5",
        "HYBRID_SYNC_ON_STARTUP": "true"
      }
    },
    "memory-private": {
      "type": "stdio",
      "command": "/Users/alice/.local/share/mcp-memory-service-venv/bin/python",
      "args": ["-m", "mcp_memory_service.server"],
      "env": {
        "MCP_MEMORY_STORAGE_BACKEND": "hybrid",
        "MCP_MEMORY_SQLITE_VEC_PATH": "/Users/alice/Library/Application Support/mcp-memory/private-alice/sqlite_vec.db",
        "CLOUDFLARE_API_TOKEN": "<ALICE_PRIVATE_TOKEN>",
        "CLOUDFLARE_ACCOUNT_ID": "<ALICE_ACCOUNT_ID>",
        "CLOUDFLARE_D1_DATABASE_ID": "<ALICE_PRIVATE_D1_ID>",
        "CLOUDFLARE_VECTORIZE_INDEX": "mcp-memory-alice",
        "CLOUDFLARE_EMBEDDING_MODEL": "@cf/baai/bge-base-en-v1.5",
        "HYBRID_SYNC_ON_STARTUP": "true"
      }
    }
  }
}
```

Two things make this work:

- **Distinct `MCP_MEMORY_SQLITE_VEC_PATH` per server.** Each server keeps its own
  local SQLite cache, so the two stores never collide on disk
  (`.../mcp-memory/shared/` vs `.../mcp-memory/private-alice/`).
- **Distinct Cloudflare D1 per server.** The cache only mirrors the D1 that is
  the real source of truth.

The same two blocks work for Codex (`~/.codex/config.toml`), Cursor
(`~/.cursor/mcp.json`), Gemini, Kiro, and Hermes - just in that agent's config
format. See [README.md](README.md) for each agent's file location and the fact
that some clients (Hermes) require the `env` vars listed explicitly.

## How the post-session hook routes to private

The distillation hook (`hooks/distill_session.py` and the Codex/Cursor scanners)
reads `.env` at import time. The multi-user wizard adds three lines:

```sh
MEMORY_OWNER=alice
MEMORY_DEFAULT_SCOPE=private
MCP_MEMORY_SQLITE_VEC_PATH=/Users/alice/Library/Application Support/mcp-memory/private-alice/sqlite_vec.db
```

So after every session, the distilled memories are written into Alice's
**private** local cache (which the `memory-private` server syncs up to her
private Cloudflare D1) and tagged `owner:alice scope:private`. The hook never
writes to the shared store on its own - sharing is always a deliberate act
through the skill.

This is the single routing lever, so it is also auditable: `MEMORY_OWNER`
unset = single-user behavior, unchanged.

## How retrieval and sharing behave (the skill)

Install the multi-user skill instead of `mcp-memory-query`:

```sh
mkdir -p ~/.claude/skills/mcp-memory-multiuser
cp skills/mcp-memory-multiuser/SKILL.md ~/.claude/skills/mcp-memory-multiuser/
```

It teaches the agent to:

- **Read from both stores** and label each hit `(private)` or
  `(shared - visible to everyone)`.
- **Write to private by default.** It only stores to the shared store when the
  user clearly means it for everyone ("share this with the team", a plainly
  team-wide convention), and asks a one-line question first if a possibly
  sensitive note is ambiguous.
- Answer scoped questions: "what do **I** have on X" -> private only; "what does
  the **team** know about X" -> shared only.

## Family variant (one Cloudflare account, multiple D1 databases)

For a family the threat model is relaxed, so one Cloudflare account and one
token are fine. You still get multiple D1 databases - one shared, plus one per
person - which keeps each person's memory in its own database:

```sh
scripts/setup_multiuser_cloudflare.sh shared          # family-wide
scripts/setup_multiuser_cloudflare.sh private mom
scripts/setup_multiuser_cloudflare.sh private dad
scripts/setup_multiuser_cloudflare.sh private kids     # a shared-among-kids store is fine
```

A subgroup store (e.g. `kids`) is just a "private" store that more than one
person connects to: point each of their `onboard_multiuser.py` runs at the same
private D1. So a family can have three tiers: family-wide shared, a kids store,
and each parent's own private store - all separate D1 databases under one
account.

## Verifying

After pasting both blocks and restarting the agent:

1. Both servers load - the agent exposes `mcp__memory-shared__*` **and**
   `mcp__memory-private__*` tools.
2. Store a private note ("remember privately: my editor is helix"), then on a
   **second device for the same person** confirm it appears after sync.
3. Store a shared note ("share with the team: we deploy on Fridays"), then from
   **another person's** device confirm it appears in their shared store but the
   private note does **not**.
4. End a session and check the hook log: the new memory should be tagged
   `owner:<person>` and `scope:private`.
   ```sh
   tail -5 ~/.claude/logs/distill-session.log
   ```

## Rollback

To collapse back to a single shared memory (no private split), remove the
`memory-private` block and the multi-user lines from `.env`, keep only
`memory-shared` (or switch it back to the plain `memory` block from
MULTI-DEVICE-SYNC.md), and restart. Local caches remain intact.

## See also

- [MULTI-DEVICE-SYNC.md](MULTI-DEVICE-SYNC.md) - the single-store hybrid backend this builds on
- [skills/mcp-memory-multiuser/SKILL.md](skills/mcp-memory-multiuser/SKILL.md) - the retrieval + write-routing policy
- [config/profiles.example.yaml](config/profiles.example.yaml) - reference shape of one person's resolved stores
- [README.md](README.md) - per-agent config file locations
