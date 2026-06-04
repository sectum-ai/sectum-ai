#!/usr/bin/env bash
#
# examples/open-webui-run/scripts/provision.sh
#
# The integration flow's seed + upload stages:
#   1. `sectum-ai seed` generates the synthetic-tenant corpora + ground-truth
#      manifest (which marker belongs to which tenant).
#   2. provision_owui.py registers the admin + 4 tenant users in Open WebUI and
#      uploads each tenant's marker-bearing pivot docs into the matching user's
#      Knowledge (and into the shared collection), preserving the planted
#      markers, then writes out/tenant-map.json (the bridge the shim reads).
#
# Re-runnable: re-seeding is deterministic (fixed seed), and provisioning signs
# in to existing users rather than failing.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
cd "$here"

if [[ ! -f .env ]]; then
  echo "ERROR: no .env; cp .env.example .env and fill it in" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a
: "${OWUI_BASE_URL:=http://localhost:${OWUI_PORT:-3000}}"
: "${SECTUM_OWUI_MAP:=out/tenant-map.json}"

sectum-ai() { uv run --quiet --project "$repo_root" sectum-ai "$@"; }

mkdir -p out

echo "==> 1/2  Seed the marker substrate (4 synthetic tenants, canary markers)"
# Seed into the workdir the configs point at so probe/report find it.
sectum-ai seed --workdir out/sectum --config "$here/sectum-ai.yaml"
# The isolated run reads the SAME deterministic substrate from its own workdir.
sectum-ai seed --workdir out/sectum-isolated --config "$here/sectum-ai.isolated.yaml"

echo
echo "==> 2/2  Upload each tenant's corpus into Open WebUI Knowledge via the API"
python3 scripts/provision_owui.py \
  out/sectum/substrate.json \
  "$OWUI_BASE_URL" \
  "$SECTUM_OWUI_MAP"

echo
echo "Provisioned. Next: start the RAG shim, then run the probes:"
echo "  ./scripts/serve_shim.sh &      # background, mode from SECTUM_OWUI_MODE"
echo "  ./scripts/run.sh               # dry-run: flagship Class 2 + Class 1"
