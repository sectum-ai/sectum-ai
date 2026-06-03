#!/usr/bin/env bash
#
# examples/rag-pipeline-bleed/run.sh
#
# Reproduces the Class 2 entity-bleed at the RAG-*pipeline* end (the engineering
# spec, section 7). The retrieval-pivot demo probes the raw vector store; this one
# issues the same benign shared-entity queries through the RAG pipeline adapter -
# the customer-facing endpoint - so a shared-index retriever wrapped in a
# tenant-aware-looking pipeline is caught against the contract a customer actually
# uses. Seed a substrate, run the rag-pipeline-bleed probe against the leaky demo
# stack, assemble a tamper-evident evidence pack, and verify it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
out="$here/out"

sectum-ai() { uv run --quiet --project "$repo_root" sectum-ai "$@"; }

rm -rf "$out"
mkdir -p "$out"

echo "==> 1/4  Seed the marker substrate (4 synthetic tenants, canary markers)"
sectum-ai seed --workdir "$out" --config "$here/sectum.yaml"

echo
echo "==> 2/4  Probe the RAG pipeline (a shared-index retriever behind the endpoint)"
# 'sectum-ai probe' exits 2 when it confirms cross-tenant leaks - the expected
# outcome on the leaky demo stack, so tolerate the non-zero exit.
sectum-ai probe --workdir "$out" --probe rag-pipeline-bleed || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum-ai report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum-ai verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
