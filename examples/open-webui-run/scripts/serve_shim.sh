#!/usr/bin/env bash
#
# examples/open-webui-run/scripts/serve_shim.sh
#
# Start the Sectum<->Open WebUI RAG shim. It reads .env for SECTUM_OWUI_MODE
# (isolated|shared), the model, and the tenant map. Run it in the background
# (append &) before invoking the probes; stop it with Ctrl-C or `kill`.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi
: "${SECTUM_OWUI_MODE:=shared}"
: "${SECTUM_SHIM_HOST:=127.0.0.1}"
: "${SECTUM_SHIM_PORT:=8099}"
: "${SECTUM_OWUI_MAP:=out/tenant-map.json}"
export SECTUM_OWUI_MODE SECTUM_SHIM_HOST SECTUM_SHIM_PORT SECTUM_OWUI_MAP OWUI_OLLAMA_MODEL

exec python3 scripts/rag_shim.py
