#!/usr/bin/env bash
#
# examples/erasure-attestation/run.sh
#
# Reproduces Attack Class 11 - the GDPR Article 17 erasure-verification wedge:
# seed a substrate, run the erasure workflow for one tenant, and independently
# verify the resulting attestation pack.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
out="$here/out"

sectum-ai() { uv run --quiet --project "$repo_root" sectum-ai "$@"; }

rm -rf "$out"
mkdir -p "$out"

echo "==> 1/3  Seed the marker substrate"
sectum-ai seed --workdir "$out" --config "$here/sectum-ai.yaml"

echo
echo "==> 2/3  Run the erasure-verification workflow for 'Acme Robotics'"
sectum-ai erasure --workdir "$out" --target-tenant "Acme Robotics"

echo
echo "==> 3/3  Independently verify the erasure attestation"
sectum-ai verify "$out/erasure-evidence.json"

echo
echo "Attestation PDF: $out/erasure-attestation.pdf"
echo "Evidence JSON:   $out/erasure-evidence.json"
echo
echo "To see a failing erasure (a store that only soft-deletes), run:"
echo "  uv run sectum-ai erasure --workdir $out --soft-delete"
