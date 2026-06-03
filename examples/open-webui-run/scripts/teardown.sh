#!/usr/bin/env bash
#
# examples/open-webui-run/scripts/teardown.sh
#
# Tear down the Open WebUI lab and remove its data volumes (webui.db, uploads,
# the embedded ChromaDB). Also clears local run artifacts under out/. Leaves
# .env in place.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

echo "==> Stopping Open WebUI + Ollama and removing volumes"
docker compose down -v --remove-orphans

echo "==> Clearing local run artifacts (out/)"
rm -rf out

echo "Done. Re-create with ./scripts/up.sh && ./scripts/provision.sh"
