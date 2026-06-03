You are reading an AI coding-agent session transcript. Extract two things:

(A) ARTIFACTS - concrete deliverables this session produced.
(B) FACTS - durable cross-project insights worth remembering, not tied to any specific artifact.

===============================================================================
OPTIONAL PROJECT REGISTRY
===============================================================================

If a registry is provided below, each line has the form:

  - <slug> (<Display Name>) [domains: host1->dslug1*, host2->dslug2, ...] [aliases: ...]

The leading `<slug>` is the canonical project slug used as the
`client_or_project` tag. A trailing `*` on a domain entry marks the primary
domain. `host->dslug` means the hostname `host` resolves to the per-domain
slug `dslug`.

Identification rules:

1. Use the canonical `<slug>` for the `client_or_project` field
   (e.g. "my-app", "backend-api", "docs-site").
2. Match case-insensitively against: the slug itself, every domain `host`,
   every per-domain `dslug`, and every alias.
3. If the session is clearly scoped to one specific domain of a multi-domain
   project, set `domain` to that domain's per-domain `dslug`. Otherwise omit
   `domain` (or set it to null).
4. If the session's project is not in the list (or no registry is provided),
   infer a short kebab-case slug from the repo/folder name, or use "unknown".

{registry}

===============================================================================
(A) ARTIFACTS - what counts
===============================================================================

Include:
- A primary deliverable the session was about (a feature, module, migration, API, document, dataset, report, ...)
- A new feature, script, tool, or significant code module that was authored
- A significant decision document or piece of analysis produced
- A configuration change with lasting effect (new service, dependency, schema migration, CI/infra change)

EXCLUDE:
- Trivial edits (typo fixes, rephrasing, small bug fixes under ~10 lines)
- Failed attempts or scrapped explorations
- Files the agent only READ but did not substantively create/modify
- Auto-generated logs, tmp files, debug output
- Helper edits supporting a primary deliverable (only log the deliverable itself, not every supporting file)

Most sessions produce 0-2 artifacts. Be strict.

For each artifact:
- `client_or_project`: kebab-case canonical slug (e.g. "my-app", "backend-api"). Use "unknown" only if you genuinely cannot tell from the session context (paths, file names, conversation).
- `domain`: per-domain slug when the artifact is scoped to one specific domain of a multi-domain project. Omit or set null otherwise.
- `type`: short kebab-case category. Common: feature, refactor, bugfix, script, tool, module, api, schema-migration, config, ci, infra, test, doc, analysis, hook, skill, mcp-config. Coin a new one only if none fit.
- `path`: absolute filesystem path of the primary output file, or null if the artifact is conceptual or multi-file.
- `summary`: 1-3 plain sentences. WHAT was built, the KEY CHOICES made, NOT a description of the artifact's full contents. Example: "Added a rate limiter to the public API. Chose a token-bucket per API key over a fixed window to avoid burst-at-boundary. Limits are configurable via env and default to 100 req/min."

SPECIAL CASE - completed project milestones: if the session definitively ships, closes,
or reaches a named milestone of a tracked project, log it as a FACT with memory_type
"completed-project" (see facts section) rather than as an artifact - there is no single
output file to point at, and what matters is the closure event itself.

===============================================================================
(B) FACTS - what counts
===============================================================================

Include:
- A user preference or working style (the user prefers X because Y)
- A persistent decision, gotcha, or constraint about a tool/workflow/codebase
- A non-obvious technical reference (paths, IDs, structure - never secrets)
- Confirmation that a non-obvious approach worked (validated judgment calls)

EXCLUDE:
- Ephemeral chatter, things obvious from the codebase, anything already in CLAUDE.md / AGENTS.md / persistent project memory
- Duplicates of facts you would expect to already exist
- Secrets of any kind (API keys, tokens, passwords, private URLs)

Most sessions yield 0-2 facts. Be strict.

===============================================================================
(C) MEMORY TYPE REFERENCE
===============================================================================

The `memory_type` field on each fact controls how it is later retrieved and filtered.
Choose the MOST SPECIFIC type that fits; do not default to "note".

| memory_type        | Use when...                                                                 |
|--------------------|-----------------------------------------------------------------------------|
| preference         | User states a working style, format, or tooling preference.                 |
| decision           | A choice was locked in about a tool, workflow, or architecture.             |
| reference          | A non-obvious path, ID, URL, or structural fact needed for future work.     |
| project            | Ongoing project state: phase, open blockers, next steps.                    |
| feedback           | A correction the user gave the agent (do X, stop doing Y).                  |
| completed-project  | A tracked project or milestone was fully closed this session. Capture:      |
|                    | project name, what shipped, date. Use even for partial milestones.          |
|                    | Example: "Shipped v1 of the auth service: email+password login, JWT         |
|                    | sessions, password reset. Deployed to staging. Closed 2026-06-01."          |
| lesson             | An explicit outcome - something worked or failed - worth applying next time.|
|                    | Stronger than "decision" (which records what was chosen) because it         |
|                    | includes the result. Always state: what was tried, what happened, and what  |
|                    | to do differently (or keep doing).                                          |
|                    | Example: "Mocking the DB in integration tests hid a real migration bug.     |
|                    | Fix: run integration tests against a disposable Postgres container."        |

===============================================================================
OUTPUT FORMAT
===============================================================================

Raw JSON only. No markdown fences, no prose, no explanation. Your entire response
must be a single JSON object that starts with `{` and ends with `}`. Schema:

{
  "artifacts": [
    {
      "client_or_project": "kebab-case-slug-or-unknown",
      "domain": "per-domain-slug-or-null",
      "type": "kebab-case-category",
      "path": "/absolute/path/or/null",
      "summary": "1-3 sentences on what was built and key choices"
    }
  ],
  "facts": [
    {
      "content": "self-contained sentence so it makes sense out of context",
      "tags": ["short", "kebab-case", "tags"],
      "memory_type": "preference|decision|reference|project|feedback|completed-project|lesson"
    }
  ]
}

If neither artifacts nor facts qualify, return: {"artifacts": [], "facts": []}
