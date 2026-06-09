#!/usr/bin/env bash
#
# examples/rag-poisoning/run.sh
#
# Reproduces Attack Class 3 - adversarial RAG poisoning - end to end
# (the engineering spec, section 7). Tenant Y plants poisoned content
# into the shared vector index that is designed to act as a retrieval
# pivot; the probe then queries the poison's lure from every tenant
# and flags any query whose retrieved context carries Y's canary. A
# retrieved foreign canary is a confirmed poisoning vulnerability.
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
echo "==> 2/4  Probe RAG poisoning (plant poisoned docs + measure bleed delta)"
sectum-ai probe --workdir "$out" --probe rag-poisoning || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum-ai report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum-ai verify "$out/evidence.json" --allow-unanchored

echo
echo "Artifacts written to: $out"
