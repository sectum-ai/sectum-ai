#!/usr/bin/env bash
#
# examples/open-webui-run/scripts/up.sh
#
# Stand up the self-hosted Open WebUI lab (Open WebUI + a tiny Ollama), wait
# until Open WebUI is healthy, and pull the local chat model. Idempotent: safe
# to re-run.
#
# This is OUR OWN deployment - lawful security testing of a stack we control.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

if [[ ! -f .env ]]; then
  echo "ERROR: no .env found. Copy .env.example to .env and fill it in:" >&2
  echo "  cp .env.example .env  &&  \$EDITOR .env" >&2
  echo "  (generate WEBUI_SECRET_KEY with: openssl rand -hex 32)" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

: "${OWUI_PORT:=3000}"
: "${OWUI_BASE_URL:=http://localhost:${OWUI_PORT}}"
: "${OWUI_OLLAMA_MODEL:=qwen2.5:0.5b}"

echo "==> 0/3  Preflight: docker"
docker info >/dev/null 2>&1 || { echo "ERROR: docker is not available" >&2; exit 1; }

echo "==> 1/3  docker compose up (image tag: ${OWUI_IMAGE_TAG:-v0.9.6})"
docker compose up -d

echo
echo "==> 2/3  Wait for Open WebUI health at ${OWUI_BASE_URL}/health"
deadline=$(( $(date +%s) + 300 ))
until curl -fsS "${OWUI_BASE_URL}/health" >/dev/null 2>&1; do
  if (( $(date +%s) > deadline )); then
    echo "ERROR: Open WebUI did not become healthy within 300s" >&2
    docker compose logs --tail 50 open-webui >&2 || true
    exit 1
  fi
  sleep 3
done
echo "    Open WebUI is up."

echo
echo "==> 3/3  Pull the local chat model into Ollama: ${OWUI_OLLAMA_MODEL}"
# Pull inside the ollama container so it lands in the shared volume.
docker compose exec -T ollama ollama pull "${OWUI_OLLAMA_MODEL}"

echo
echo "Open WebUI ready at ${OWUI_BASE_URL}"
echo "Next: ./scripts/provision.sh   (seed the substrate + create users + upload corpora)"
