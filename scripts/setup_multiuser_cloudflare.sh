#!/usr/bin/env bash
#
# Create the Cloudflare D1 + Vectorize resources for a multi-user
# cross-agent-memory-kit install (hard isolation: one shared store + one
# private store per person).
#
# This wraps `wrangler`. It is idempotent-ish: wrangler errors loudly if a
# resource with the same name already exists, in which case just read the
# existing IDs from the Cloudflare dashboard or `wrangler d1 list`.
#
# Usage:
#   scripts/setup_multiuser_cloudflare.sh shared
#   scripts/setup_multiuser_cloudflare.sh private <person-slug>
#
# Examples:
#   scripts/setup_multiuser_cloudflare.sh shared          # run ONCE for the team/family
#   scripts/setup_multiuser_cloudflare.sh private alice   # run once PER person
#   scripts/setup_multiuser_cloudflare.sh private kids    # a shared-among-kids private store is fine too
#
# After each run, copy the printed database_id / index name into
# onboard_multiuser.py (or your agent config). Keep the API token secret.
#
# The Vectorize index is 768-dim / cosine to match the default embedding model
# @cf/baai/bge-base-en-v1.5 used by MULTI-DEVICE-SYNC.md.
set -euo pipefail

DIMENSIONS=768
METRIC=cosine

die() { echo "ERROR: $*" >&2; exit 1; }

command -v wrangler >/dev/null 2>&1 || die "wrangler not found. Install it: npm i -g wrangler  (then 'wrangler login')."

mode="${1:-}"

create_store() {
  # $1 = D1 database name, $2 = Vectorize index name, $3 = human label
  local d1_name="$1" vec_name="$2" label="$3"
  echo "============================================================"
  echo "  Creating the ${label} store"
  echo "    D1 database  : ${d1_name}"
  echo "    Vectorize idx: ${vec_name} (${DIMENSIONS}-dim, ${METRIC})"
  echo "============================================================"

  echo "+ wrangler d1 create ${d1_name}"
  wrangler d1 create "${d1_name}" || echo "  (if it already exists, look up its id with: wrangler d1 list)"

  echo "+ wrangler vectorize create ${vec_name} --dimensions=${DIMENSIONS} --metric=${METRIC}"
  wrangler vectorize create "${vec_name}" --dimensions="${DIMENSIONS}" --metric="${METRIC}" \
    || echo "  (if it already exists, reuse the same name)"

  cat <<EOF

  Done. Record for the ${label} store:
    CLOUDFLARE_D1_DATABASE_ID  = <the database_id printed above by 'd1 create'>
    CLOUDFLARE_VECTORIZE_INDEX = ${vec_name}
  Also have ready (from the dashboard):
    CLOUDFLARE_ACCOUNT_ID      = <dashboard sidebar / 'wrangler whoami'>
    CLOUDFLARE_API_TOKEN       = <a token with D1 edit + Vectorize edit + Workers AI read>

EOF
}

case "${mode}" in
  shared)
    create_store "mcp-memory-shared" "mcp-memory-shared" "SHARED (team/family-wide)"
    echo "Next: run 'scripts/setup_multiuser_cloudflare.sh private <person>' once per person,"
    echo "then run 'python3 onboard_multiuser.py' on each device."
    ;;
  private)
    person="${2:-}"
    [ -n "${person}" ] || die "private mode needs a person slug: scripts/setup_multiuser_cloudflare.sh private alice"
    # normalize to lowercase, strip unsafe chars
    person="$(printf '%s' "${person}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9-' '-' | sed 's/-\{1,\}/-/g; s/^-//; s/-$//')"
    [ -n "${person}" ] || die "person slug reduced to empty after normalization"
    create_store "mcp-memory-${person}" "mcp-memory-${person}" "PRIVATE store for '${person}'"
    echo "Next: run 'python3 onboard_multiuser.py --person ${person}' on ${person}'s device(s)."
    ;;
  *)
    cat >&2 <<EOF
Usage:
  $0 shared                 # run ONCE for the whole team/family
  $0 private <person-slug>  # run once per person (e.g. 'private alice')
EOF
    exit 2
    ;;
esac
