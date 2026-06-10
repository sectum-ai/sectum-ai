#!/usr/bin/env bash
#
# examples/agent-tool-hijack/run.sh
#
# Reproduces Attack Class 7 - cross-tenant agent tool-call hijacking - from the
# agent-adapter perspective: seed a substrate, run the Class 7 probe against an
# in-memory MCP server with both the confused-deputy and token-passthrough
# flaws turned on, assemble a tamper-evident evidence pack, and verify it.
#
# The Class 7 probe today verifies the *MCP surface* (Class 7 v1 per the
# engineering spec, section 7). The story this example tells is the
# agent-adapter half of that surface: who *calls* the MCP server, and how to
# swap that caller between the seven shipped agent kinds (fake, http,
# langgraph, autogen, crewai, openai-assistants, anthropic-tooluse) so the same
# leak shows up regardless of which agent framework a customer uses. The wiring
# snippets and connect-time
# factory functions live alongside this script in factories.py.
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
echo "==> 2/4  Probe Class 7 from the agent-adapter perspective"
echo "         (the leaky in-memory MCP server stands in for any backend an"
echo "         agent might reach; swap the agent adapter via sectum-ai.yaml -"
echo "         see README.md and factories.py)"
# 'sectum-ai probe' exits 2 when it confirms cross-tenant leaks - expected on the
# leaky demo MCP server, so tolerate the non-zero exit.
rc=0; sectum-ai probe --workdir "$out" --probe agent-tool-hijack || rc=$?
if [ "$rc" -ne 2 ]; then
  echo "FAIL: expected confirmed cross-tenant leaks (exit 2), got $rc" >&2
  exit 1
fi

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum-ai report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum-ai verify "$out/evidence.json" --allow-unanchored

echo
echo "Artifacts written to: $out"
echo
echo "Next: read README.md to swap the agent caller from FakeAgent to a real"
echo "LangGraph / AutoGen / CrewAI integration via the factory pattern."
