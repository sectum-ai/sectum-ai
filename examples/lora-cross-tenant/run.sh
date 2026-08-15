#!/usr/bin/env bash
#
# examples/lora-cross-tenant/run.sh
#
# Reproduces Attack Class 9 - cross-tenant LoRA / adapter influence - end to
# end (the engineering spec, section 7). The probe trains each tenant's
# adapter on a corpus containing a memorisable HARD_CANARY, then queries
# every foreign tenant; on a mis-routed or weight-bled stack the
# memorised canary surfaces in the wrong tenant's inference, which is the
# leak the audit pack itemises.
#
# Today the demo runs against the in-memory FakeModel with
# `adapter_bleed=true` (the leaky weight-bleed condition the substrate is
# built to catch). The same probe drives the new live
# `HuggingFaceLoraModel` adapter when an operator points `kind:
# huggingface` at a real base model + `adapters_dir` (see README.md).
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
echo "==> 2/4  Probe the LoRA stack (per-tenant train + cross-tenant inference)"
# 'sectum-ai probe' exits 2 when it confirms cross-tenant leaks - expected on the
# leaky-bleed fake model in the demo config, so tolerate the non-zero exit.
rc=0; sectum-ai probe --workdir "$out" --probe lora-cross-tenant || rc=$?
if [ "$rc" -ne 2 ]; then
  echo "FAIL: expected confirmed cross-tenant leaks (exit 2), got $rc" >&2
  exit 1
fi

echo
echo "==> 3/4  Assemble the tamper-evident evidence pack (JSON + PDF)"
sectum-ai report --workdir "$out"

echo
echo "==> 4/4  Independently verify the evidence pack"
sectum-ai verify "$out/evidence.json" --allow-unanchored --allow-synthetic

echo
echo "Artifacts written to: $out"
echo
echo "Swap the in-memory model for a real one by pointing the model adapter"
echo "at the new live HuggingFaceLoraModel via sectum-ai.yaml - see README.md."
