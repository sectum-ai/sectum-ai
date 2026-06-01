#!/usr/bin/env bash
#
# examples/ikea-extraction/run.sh
#
# Reproduces Attack Class 10 - IKEA-style implicit benign extraction -
# end to end (the engineering spec, section 7). A multi-turn benign
# query sequence from tenant Y surfaces tenant X content from a
# shared vector index; no prompt injection required. The pattern is
# from the Silent Leaks / IKEA paper (arXiv 2505.15420), which
# reported 91% extraction efficiency and 96% attack success against
# an adaptive attacker.
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
echo "==> 2/4  Probe IKEA-style benign extraction (benign multi-turn sequence)"
sectum probe --workdir "$out" --probe ikea-extraction || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
