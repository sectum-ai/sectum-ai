#!/usr/bin/env bash
#
# examples/semantic-cache/run.sh
#
# Reproduces Attack Class 4 - semantic / prompt-cache contamination -
# end to end (the engineering spec, section 7). Tenant X primes the
# cache with a query whose answer contains a HARD_CANARY; tenant Y
# issues a semantically-near query. On a cache that does not key by
# tenant, tenant Y receives tenant X's cached answer (canary intact).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
out="$here/out"

sectum() { uv run --quiet --project "$repo_root" sectum "$@"; }

rm -rf "$out"
mkdir -p "$out"

echo "==> 1/4  Seed the marker substrate (4 synthetic tenants, canary markers)"
sectum seed --workdir "$out"

echo
echo "==> 2/4  Probe the semantic cache (cross-tenant hit on a primed canary)"
sectum probe --workdir "$out" --probe semantic-cache-contamination || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
