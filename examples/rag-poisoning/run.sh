#!/usr/bin/env bash
#
# examples/rag-poisoning/run.sh
#
# Reproduces Attack Class 3 - adversarial RAG poisoning - end to end
# (the engineering spec, section 7). Tenant Y plants poisoned content
# into the shared vector index that is designed to act as a retrieval
# pivot; the probe measures the marker-bleed delta between the
# baseline run and the post-poisoning run. A bleed delta > 0 is a
# confirmed poisoning vulnerability.
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
echo "==> 2/4  Probe RAG poisoning (plant poisoned docs + measure bleed delta)"
sectum probe --workdir "$out" --probe rag-poisoning || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
