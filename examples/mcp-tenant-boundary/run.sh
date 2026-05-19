#!/usr/bin/env bash
#
# examples/mcp-tenant-boundary/run.sh
#
# Reproduces Attack Class 7 - cross-tenant agent tool-call hijacking - end to
# end: seed a substrate, run the Class 7 probe against an MCP server with the
# confused-deputy and token-passthrough flaws, assemble a tamper-evident
# evidence pack, and verify it.
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
echo "==> 2/4  Probe the MCP server (confused-deputy and token-passthrough)"
# 'sectum probe' exits 2 when it confirms cross-tenant leaks - expected on the
# leaky demo MCP server, so tolerate the non-zero exit.
sectum probe --workdir "$out" --probe agent-tool-hijack || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
