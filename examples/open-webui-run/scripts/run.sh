#!/usr/bin/env bash
#
# examples/open-webui-run/scripts/run.sh
#
# DRY-RUN validation of the Open WebUI harness: confirm end-to-end wiring and
# that detection is manifest-grounded, against the LIVE instance. It runs:
#   - the flagship Class 2 (rag-pipeline-bleed) through the RAG shim, and
#   - Class 1 (cross-user file fetch) against Open WebUI's file API,
# then prints the Retrieval-Pivot Rate and the Class 1 verdict.
#
# It deliberately STOPS at validated readiness: it does NOT assemble the official
# signed evidence pack or the full multi-class production run. That final run is
# the operator's to trigger - see the README "Operator's actual run" runbook.
#
# Prereqs (in order): ./scripts/up.sh, ./scripts/provision.sh, and the RAG shim
# running (./scripts/serve_shim.sh &) in the mode you want to validate
# (SECTUM_OWUI_MODE in .env: shared => expect RPR high; isolated => expect ~0%).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
cd "$here"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi
: "${SECTUM_OWUI_MODE:=shared}"
: "${SECTUM_SHIM_PORT:=8099}"
: "${SECTUM_OWUI_MAP:=out/tenant-map.json}"

sectum-ai() { uv run --quiet --project "$repo_root" sectum-ai "$@"; }

if [[ "$SECTUM_OWUI_MODE" == "isolated" ]]; then
  config="$here/sectum-ai.isolated.yaml"
  workdir="out/sectum-isolated"
else
  config="$here/sectum-ai.yaml"
  workdir="out/sectum"
fi

echo "==> 0/3  Preflight: RAG shim reachable on :${SECTUM_SHIM_PORT} (mode=${SECTUM_OWUI_MODE})"
curl -fsS -X POST "http://127.0.0.1:${SECTUM_SHIM_PORT}/" \
  -H 'Content-Type: application/json' -d '{"tenant":"preflight","query":"ping"}' \
  >/dev/null 2>&1 || true   # a 502 (unknown tenant) still proves the shim is up
if ! curl -sS -o /dev/null -X POST "http://127.0.0.1:${SECTUM_SHIM_PORT}/" \
     -H 'Content-Type: application/json' -d '{"tenant":"preflight","query":"ping"}'; then
  echo "ERROR: RAG shim not reachable; start it: ./scripts/serve_shim.sh &" >&2
  exit 1
fi
echo "    shim is up."

echo
echo "==> 1/3  Flagship Class 2 (rag-pipeline-bleed) through Open WebUI chat-with-knowledge"
# Exits 2 when it confirms cross-tenant leaks (the expected shared-mode outcome).
sectum-ai probe --workdir "$workdir" --config "$config" \
  --probe rag-pipeline-bleed --output json | tee "$workdir/class2-summary.json" || true

echo
echo "==> 2/3  Class 1 (cross-user file fetch) against Open WebUI's file API"
python3 scripts/class1_boundary_fetch.py "$workdir/substrate.json" "$SECTUM_OWUI_MAP" || true

echo
echo "==> 3/3  Dry-run readiness summary"
rpr=$(python3 -c "import json,sys; d=json.load(open('$workdir/class2-summary.json')); print(d.get('retrieval_pivot_rate'))" 2>/dev/null || echo "n/a")
echo "  mode:                 ${SECTUM_OWUI_MODE}"
echo "  Class 2 RPR:          ${rpr}"
echo "  Class 1 summary:      out/class1-boundary.json"
echo "  Class 2 run record:   ${workdir}/run.json"
echo
echo "Validated wiring only. For the OPERATOR'S official signed run, see the"
echo "README 'Operator's actual run' section (seed -> upload -> probe per class"
echo "-> report --tsa --rekor -> verify)."
