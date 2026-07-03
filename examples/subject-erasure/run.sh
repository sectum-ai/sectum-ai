#!/usr/bin/env bash
#
# examples/subject-erasure/run.sh
#
# A3: verify a REAL data subject's erasure - by record id and by content
# fingerprint - after your own deletion has run for a GDPR Art. 17 / CCPA request,
# then independently verify the per-subject attestation.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
out="$here/out"

sectum-ai() { uv run --quiet --project "$repo_root" sectum-ai "$@"; }

rm -rf "$out"
mkdir -p "$out"

echo "==> 1/3  Seed a substrate (tenant resolution + the pack's manifest binding)"
sectum-ai seed --workdir "$out" --config "$here/sectum-ai.yaml"

echo
echo "==> 2/3  Verify the subject's erasure by id and by content fingerprint"
sectum-ai erasure --subject "$here/subject.yaml" --workdir "$out" --config "$here/sectum-ai.yaml"

echo
echo "==> 3/3  Independently verify the per-subject attestation"
sectum-ai verify "$out/erasure-evidence.json" --allow-unanchored

echo
echo "This demo runs against the built-in synthetic store, so it reports ERASED with a"
echo "warning that no live adapter is configured. Point 'vector_store' in sectum-ai.yaml"
echo "at your real Qdrant/pgvector to verify production data - see"
echo "tests/integration/test_subject_erasure_qdrant.py for a live, residual-catching run."
