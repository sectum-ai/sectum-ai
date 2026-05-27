#!/usr/bin/env bash
#
# examples/kv-cache-timing/run.sh
#
# Reproduces Attack Class 5 - the KV-cache timing side channel - end to end
# (the engineering spec, section 7). A shared inference infrastructure with
# a KV prefix cache returns a prompt faster when its prefix was recently
# processed by another tenant; this script seeds a substrate against a fake
# model with the prefix cache deliberately turned on, runs the timing probe
# (24 trials per condition with a Cohen's-d effect-size gate), assembles a
# tamper-evident evidence pack, and verifies it.
#
# Class 5 is a statistical workflow rather than a plan/detect probe: the
# probe times paired primed-vs-control prompts and reports a per-tenant
# timing signal. A large enough effect size becomes a confirmed Side-Channel
# finding; the audit-pack PDF carries the effect sizes + confidence
# intervals so an auditor can review the statistical strength themselves.
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
echo "==> 2/4  Probe the KV cache (paired primed-vs-control timing trials)"
# 'sectum probe' exits 2 when it confirms cross-tenant leaks - expected on
# the leaky-cache fake model in the demo config, so tolerate the non-zero
# exit. The statistical run reports per-tenant-pair effect sizes; a
# confirmed Class 5 finding is one whose Cohen's d crosses the 0.8 boundary
# the probe pins.
sectum probe --workdir "$out" --probe kv-cache-timing || true

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum verify "$out/evidence.json"

echo
echo "Artifacts written to: $out"
echo
echo "The audit pack's findings carry the per-pair effect sizes; a large"
echo "effect (~5.0+) is a side channel an attacker could exploit, while a"
echo "moderate one (0.8-5.0) is enough to flag and re-test under load."
