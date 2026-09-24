#!/usr/bin/env bash
#
# examples/embedding-inversion/run.sh
#
# Reproduces Attack Class 6 - embedding inversion across tenants -
# end to end (the engineering spec, section 7). If embeddings are
# reachable cross-tenant on a shared index, tenant Y can attempt to
# recover tenant X source content via approximate nearest-neighbour
# reconstruction of an ENTITY_CANARY's embedding.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
out="$here/out"

sectum-ai() { uv run --quiet --project "$repo_root" sectum-ai "$@"; }

rm -rf "$out"
mkdir -p "$out"

echo "==> 1/4  Seed the marker substrate (4 synthetic tenants, canary markers)"
sectum-ai seed --workdir "$out"

echo
echo "==> 2/4  Probe embedding inversion (the demo store ranks lexically; see the README)"
rc=0; sectum-ai probe --workdir "$out" --probe embedding-inversion || rc=$?
if [ "$rc" -ne 2 ]; then
  echo "FAIL: expected confirmed cross-tenant leaks (exit 2), got $rc" >&2
  exit 1
fi

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum-ai report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum-ai verify "$out/evidence.json" --allow-unanchored --allow-synthetic

echo
echo "Artifacts written to: $out"
