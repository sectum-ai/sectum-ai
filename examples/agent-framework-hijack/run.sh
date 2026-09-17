#!/usr/bin/env bash
#
# examples/agent-framework-hijack/run.sh
#
# Reproduces Attack Class 7 - cross-tenant agent tool-call hijacking - from the
# agent-framework end: seed a substrate, run the direct agent-framework probe
# against the in-memory FakeAgent with both leak knobs on (confused-deputy +
# tool-call passthrough), assemble a tamper-evident evidence pack, and verify
# it. Where examples/agent-tool-hijack/ verifies the leaky MCP server an agent
# calls, this example verifies the *agent caller* itself - no MCP server in
# the loop - and surfaces the same kinds of cross-tenant findings via the
# agent's final output rather than the tool result.
#
# The probe runs against every shipped v1 agent backend (`fake` / `http` /
# `langgraph` / `autogen` / `crewai` / `openai-assistants` /
# `anthropic-tooluse`); this script drives the fake so it stays
# credential-free and runs end-to-end in CI.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
out="$here/out"

sectum-ai() { uv run --quiet --project "$repo_root" sectum-ai "$@"; }

rm -rf "$out"
mkdir -p "$out"

cp "$here/sectum-ai.yaml" "$out/sectum-ai.yaml"

echo "==> 1/4  Seed the marker substrate (4 synthetic tenants, canary markers)"
sectum-ai seed --workdir "$out" --config "$out/sectum-ai.yaml"

echo
echo "==> 2/4  Probe Class 7 from the agent-framework end"
echo "         (the leaky in-memory FakeAgent stands in for any agent caller;"
echo "         swap it for a live backend via the factories.py wiring in"
echo "         examples/agent-tool-hijack/)"
# 'sectum-ai probe' exits 2 when it confirms cross-tenant leaks - expected on the
# leaky demo agent, so tolerate the non-zero exit.
rc=0; sectum-ai probe --workdir "$out" --config "$out/sectum-ai.yaml" --probe agent-framework-hijack || rc=$?
if [ "$rc" -ne 2 ]; then
  echo "FAIL: expected confirmed cross-tenant leaks (exit 2), got $rc" >&2
  exit 1
fi

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum-ai report --workdir "$out" --config "$out/sectum-ai.yaml"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum-ai verify "$out/evidence.json" --allow-unanchored --allow-synthetic

echo
echo "Artifacts written to: $out"
echo
echo "The PDF's Findings section itemises each confirmed Class 7 leak via the"
echo "agent-framework surface. To swap the agent caller to a live backend, see"
echo "examples/agent-tool-hijack/factories.py - the probe stays the same; only"
echo "the agent.kind in sectum-ai.yaml changes."
