#!/usr/bin/env bash
#
# examples/tenant-boundary-fetch/run.sh
#
# Reproduces Attack Class 1 - direct tenant boundary fetch - end to end
# (the engineering spec, section 7). From one tenant's authenticated
# session, the probe enumerates the canary document IDs of every other
# tenant and issues a fetch for each. A document that comes back is a
# table-stakes authorisation failure: the vector store / API did not
# scope by tenant.
#
# This is the BOLA-style probe every multi-tenant security buyer
# expects to see covered. Sectum's value-add over a generic API
# fuzzer is manifest-grounded zero-FP detection: the canaries are
# planted by the substrate, so a returned document is a confirmed
# leak with no judge required.
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
echo "==> 2/4  Probe the API boundary (cross-tenant doc-id fetch enumeration)"
sectum-ai probe --workdir "$out" --probe tenant-boundary-fetch || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum-ai report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum-ai verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
