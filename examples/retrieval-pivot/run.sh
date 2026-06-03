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

sectum() { uv run --quiet --project "$repo_root" sectum "$@"; }

rm -rf "$out"
mkdir -p "$out"

echo "==> 1/4  Seed the marker substrate (4 synthetic tenants, canary markers)"
sectum seed --workdir "$out" --config "$here/sectum.yaml"

echo
echo "==> 2/4  Probe the demo stack (a single shared vector index - no isolation)"
# 'sectum probe' exits 2 when it confirms cross-tenant leaks. That is the
# expected outcome on the leaky demo stack, so tolerate the non-zero exit.
sectum probe --workdir "$out" || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
