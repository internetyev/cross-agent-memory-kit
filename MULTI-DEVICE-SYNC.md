# Multi-device memory sync (hybrid Cloudflare backend)

By default `mcp-memory-service` stores everything in one local SQLite database.
That is perfect for a single machine. To share one memory across several devices
(two laptops, a desktop, etc.), switch the server to its **hybrid** backend:

- each device keeps a fast **local SQLite cache**, and
- **Cloudflare (D1 + Vectorize)** is the shared source of truth.

Both devices can run at the same time. There is no shared SQLite file, so there
is no risk of file-sync corruption (the classic failure mode of putting a SQLite
DB in Dropbox/iCloud).

```
Device A  ─┐                            ┌─ Device B
local cache │   background sync          │ local cache
           └──►  Cloudflare D1  ◄────────┘
                 + Vectorize (source of truth)
```

## One-time: create the Cloudflare resources

You need a (free-tier-friendly) Cloudflare account. Create a D1 database and a
Vectorize index, then a scoped API token. Using `wrangler`:

```sh
# 1. D1 database (note the returned database_id)
wrangler d1 create mcp-memory

# 2. Vectorize index - 768 dims, cosine, to match the embedding model below
wrangler vectorize create mcp-memory --dimensions=768 --metric=cosine
```

Then, in the Cloudflare dashboard, create an **API token** with permissions for
**D1 (edit)**, **Vectorize (edit)**, and **Workers AI (read)**, and copy your
**Account ID** from the dashboard sidebar.

Record these four values (keep the token secret - never commit it):

| Variable | Where it comes from |
|---|---|
| `CLOUDFLARE_API_TOKEN` | the API token you just created (secret) |
| `CLOUDFLARE_ACCOUNT_ID` | dashboard sidebar / `wrangler whoami` |
| `CLOUDFLARE_D1_DATABASE_ID` | output of `wrangler d1 create` |
| `CLOUDFLARE_VECTORIZE_INDEX` | the index name, e.g. `mcp-memory` |

## Configure each device

Point the `memory` MCP server at the hybrid backend by adding these env vars to
its server block. For Claude Code (`~/.claude.json`, under `mcpServers`):

```json
"memory": {
  "type": "stdio",
  "command": "<HOME>/.local/share/mcp-memory-service-venv/bin/python",
  "args": ["-m", "mcp_memory_service.server"],
  "env": {
    "MCP_MEMORY_STORAGE_BACKEND": "hybrid",
    "CLOUDFLARE_API_TOKEN": "<YOUR_CLOUDFLARE_API_TOKEN>",
    "CLOUDFLARE_ACCOUNT_ID": "<YOUR_CLOUDFLARE_ACCOUNT_ID>",
    "CLOUDFLARE_D1_DATABASE_ID": "<YOUR_D1_DATABASE_ID>",
    "CLOUDFLARE_VECTORIZE_INDEX": "mcp-memory",
    "CLOUDFLARE_EMBEDDING_MODEL": "@cf/baai/bge-base-en-v1.5",
    "HYBRID_SYNC_ON_STARTUP": "true"
  }
}
```

Replace `<HOME>` with your home directory (the wizard does this for you). The
embedding model `@cf/baai/bge-base-en-v1.5` produces 768-dim vectors, which is
why the Vectorize index above is created with `--dimensions=768`.

Restart the agent. On a device's first start its local cache is empty; with
`HYBRID_SYNC_ON_STARTUP=true` it pulls all existing memories down from
Cloudflare into a fresh local `sqlite_vec.db`.

## How it behaves

- **No shared file.** Each device has its own local cache. Cloudflare is the only
  shared store. Devices may run simultaneously.
- **Eventually consistent.** Writes hit the local cache instantly and sync up to
  Cloudflare on a short background interval. A write on device A is visible on
  device B after the next sync (seconds to minutes), not instantly. Tune with
  `HYBRID_SYNC_INTERVAL` (seconds) if needed.
- **Offline-safe.** If Cloudflare is unreachable, reads and writes still hit the
  local cache and sync up later.

## Migrating an existing local-only store to hybrid

If you already have memories in a local `sqlite_vec.db`, back it up first, then
let the hybrid backend push them up on first start. Before switching, snapshot:

```sh
mkdir -p ~/mcp-memory-backups/$(date +%Y%m%d-%H%M%S)
cp -a "$HOME/Library/Application Support/mcp-memory/." \
      ~/mcp-memory-backups/$(date +%Y%m%d-%H%M%S)/   # macOS path
```

After the switch, verify the D1 row count and the Vectorize vector count match
your local memory count before relying on a second device.

## Rollback to local-only

Set `MCP_MEMORY_STORAGE_BACKEND=sqlite_vec` (or remove the Cloudflare env block)
and restart. Your local cache remains a complete copy of the store.

## Other agents

The same `env` block works for any MCP client. Note that some clients (e.g.
Hermes) filter the subprocess environment, so the Cloudflare variables must be
listed explicitly under that server's `env`, not inherited from the shell. See
[README.md](README.md) for per-agent config file locations.
