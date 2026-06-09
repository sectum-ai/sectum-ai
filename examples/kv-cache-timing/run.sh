#!/usr/bin/env bash
#
# examples/kv-cache-timing/run.sh
#
# Reproduces Attack Class 5 - the KV-cache timing side channel - end to end
# (the engineering spec, section 7). A shared inference infrastructure with
# a KV prefix cache returns a prompt faster when its prefix was recently
# processed by another tenant; this script seeds a substrate against a fake
# model with the prefix cache deliberately turned on, runs the timing probe
# (24 paired trials per condition, gated by a Welch t-test), assembles a
# tamper-evident evidence pack, and verifies it.
#
# Class 5 is a statistical workflow rather than a plan/detect probe: the
# probe times paired primed-vs-control prompts and runs a Welch t-test on
# the two latency distributions. A finding is confirmed only when the gap is
# significant (p < 0.01), large (Cohen's d >= 0.8), and directional; the
# audit-pack PDF carries the t-statistic, p-value, CI, and effect size so an
# auditor can review the statistical strength themselves.
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
echo "==> 2/4  Probe the KV cache (paired primed-vs-control timing trials)"
# 'sectum-ai probe' exits 2 when it confirms cross-tenant leaks - expected on
# the leaky-cache fake model in the demo config, so tolerate the non-zero
# exit. The statistical run gates each tenant pair on a Welch t-test; a
# confirmed Class 5 finding is one whose gap is significant (p < 0.01),
# large (Cohen's d >= 0.8), and directional (primed faster).
rc=0; sectum-ai probe --workdir "$out" --probe kv-cache-timing || rc=$?
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
echo "The audit pack's findings carry the per-pair Welch t-test result; a"
echo "very large effect (Cohen's d ~5.0+) is a side channel an attacker could"
echo "exploit, while a smaller-but-significant one is enough to flag and"
echo "re-test under load."
