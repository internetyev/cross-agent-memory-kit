---
name: mcp-memory-multiuser
description: >
  Query and store memory when ONE agent account is shared by several people (a
  company team or a family) and each person has a PRIVATE memory store plus a
  SHARED team/family store. Use whenever the user asks what you remember, wants
  to recall past decisions or conventions, says "check your memory", "search
  memory for", "what's stored about", references "last time we discussed", or
  asks to remember/store/save something. Routes reads across both stores and
  routes writes to the right store (private by default, shared only when the
  user clearly means it for everyone). Covers: memory search, memory browse,
  storing memories, mistake note lookup, in a shared-account setup.
---

# MCP Memory Query - multi-user (shared account)

This setup has **two** memory servers, configured because one agent account is
shared by several people:

| Server | Tools | What it holds |
|---|---|---|
| `memory-shared` | `mcp__memory-shared__*` | Team/family-wide memory everyone sees |
| `memory-private` | `mcp__memory-private__*` | **This person's** private memory only |

Hard isolation: the two servers point at **separate databases with separate
tokens**. This person physically cannot read anyone else's private store, and
others cannot read theirs. Privacy is enforced by the database boundary, not by
tags. The `owner:<person>` / `scope:<private|shared>` tags only describe a
memory's intended audience.

If you only see one set of `mcp__memory__*` tools (no `-shared` / `-private`
suffix), this is a single-user install - use the `mcp-memory-query` skill
instead.

---

## Reading: query BOTH stores, then merge

For any recall ("what do you remember about X", "find memories about X",
"check your memory"), search **both** servers and combine the results:

1. `mcp__memory-private__memory_search` with the user's topic.
2. `mcp__memory-shared__memory_search` with the same topic.
3. Merge, de-duplicate, and present together. Label each hit with its origin so
   the user knows what is private vs shared:
   - Private hit -> tag it `(private)`.
   - Shared hit -> tag it `(shared - visible to the whole team/family)`.

Use the same call conventions as the single-user skill:
- `query`: the topic as a short noun phrase.
- `limit`: 10 each by default; raise to 20-30 for a broad sweep.
- `quality_boost: 0.3` when precision matters.
- `max_response_chars: 30000` when result sets may be large.

For mistake notes / known pitfalls before a task, check
`mcp__memory-private__mistake_note_search` first, then
`mcp__memory-shared__mistake_note_search`.

Presentation:

```
Found N memories about "[topic]":

Private (only you):
1. [fact] - Tags / Type / Stored
Shared (whole team/family):
1. [fact] - Tags / Type / Stored

[If nothing found]: No memories stored about "[topic]" in your private or the
shared store. Want me to save one? (I'll keep it private unless you say it's for
everyone.)
```

Eventual consistency caveat (hybrid Cloudflare backend): a memory written on
another device appears after the next background sync (seconds to minutes). If a
lookup returns nothing the user expected, say it may not have synced yet rather
than asserting it was never stored.

---

## Writing: private by default, shared only on a clear signal

When the user says "remember this", "store this", "save this to memory", decide
which store to write to. **Default to private.** This protects the user from
leaking personal notes into a store the whole team/family can read.

Write to **`memory-shared`** only when the content is clearly meant for
everyone. Signals:

- The user says so: "share this with the team", "everyone should know",
  "save this to the family/team memory", "this is a shared convention".
- It is plainly a team/family-wide fact (a shared standard, a household rule, a
  company-wide convention, a shared resource URL).

Write to **`memory-private`** (default) when:

- The user says "remember this for me", "my note", "just for me", or says
  nothing about audience.
- The content is personal, role-specific, or about this person's own line of
  work.

**If it is ambiguous and might be sensitive, ask one short question** before
writing to shared: "Save this to your private memory, or share it with the whole
team?" Never silently publish a personal note to the shared store - that is a
one-way information leak.

Store call:

```json
{
  "content": "<the fact or note>",
  "metadata": { "tags": "tag1,tag2", "type": "note|decision|convention|reference" }
}
```

Use `mcp__memory-private__memory_store` or `mcp__memory-shared__memory_store`
accordingly. Confirm back which store you used:
- Private: "Stored privately - only you can see this."
- Shared: "Stored in the shared memory - visible to the whole team/family."

To **move** a memory from private to shared later, store it in the shared store
and (optionally) delete the private copy; there is no cross-store move tool.

---

## Harvesting session learnings

If the user says "harvest memories" / "extract learnings from this session", run
`mcp__memory-private__memory_harvest` with `dry_run: true` first and preview.
Session learnings are personal by default, so commit them to the **private**
store unless the user asks to share. (The post-session distillation hook already
writes to the private store automatically.)

---

## Edge cases

- **Only one store responds**: report which store is unavailable; still return
  results from the one that worked.
- **Nothing found**: say so for both stores; offer to store (private by default).
- **Too many results**: ask the user to narrow by tag, date, or type.
- **User asks "what does the team know about X"**: query only `memory-shared`.
- **User asks "what do I have on X"**: query only `memory-private`.
