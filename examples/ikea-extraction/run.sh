#!/usr/bin/env bash
#
# examples/ikea-extraction/run.sh
#
# Reproduces Attack Class 10 - IKEA-style implicit benign extraction -
# end to end (the engineering spec, section 7). A multi-turn benign
# query strategy from tenant Y incrementally reconstructs tenant X
# content via a shared RAG pipeline; no prompt injection required.
# Based on the Silent Leaks / IKEA paper (arXiv 2505.15420): 91%
# extraction efficiency, 96% attack success via benign queries.
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
echo "==> 2/4  Probe IKEA-style benign extraction (multi-turn reconstruction)"
sectum probe --workdir "$out" --probe ikea-extraction || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
