#!/usr/bin/env bash
#
# examples/memory-contamination/run.sh
#
# Reproduces Attack Class 8 - persistent memory contamination (SpAIware-class) -
# end to end: seed a substrate, run the Class 8 probe against a long-term memory
# store with tenant scope removed, assemble a tamper-evident evidence pack, and
# verify it. The engineering spec, section 7.
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
echo "==> 2/4  Probe the long-term memory store (SpAIware-class contamination)"
# 'sectum-ai probe' exits 2 when it confirms cross-tenant leaks - expected on the
# leaky demo memory store, so tolerate the non-zero exit.
rc=0; sectum-ai probe --workdir "$out" --probe memory-contamination || rc=$?
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
