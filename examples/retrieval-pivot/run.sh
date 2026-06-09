#!/usr/bin/env bash
#
# examples/retrieval-pivot/run.sh
#
# Reproduces Attack Class 2 - the organic entity-bleed Retrieval Pivot - end to
# end: seed a marker substrate, run the probe suite against the intentionally
# leaky demo stack, assemble a tamper-evident evidence pack, and verify it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
out="$here/out"

sectum-ai() { uv run --quiet --project "$repo_root" sectum-ai "$@"; }

rm -rf "$out"
mkdir -p "$out"

echo "==> 1/4  Seed the marker substrate (4 synthetic tenants, canary markers)"
sectum-ai seed --workdir "$out" --config "$here/sectum-ai.yaml"

echo
echo "==> 2/4  Probe the demo stack (a single shared vector index - no isolation)"
# 'sectum-ai probe' exits 2 when it confirms cross-tenant leaks. That is the
# expected outcome on the leaky demo stack, so tolerate the non-zero exit.
rc=0; sectum-ai probe --workdir "$out" || rc=$?
if [ "$rc" -ne 2 ]; then
  echo "FAIL: expected confirmed cross-tenant leaks (exit 2), got $rc" >&2
  exit 1
fi

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum-ai report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum-ai verify "$out/evidence.json" --allow-unanchored

echo
echo "Artifacts written to: $out"
