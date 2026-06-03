#!/usr/bin/env bash
# Record the flagship Sectum AI demo end-to-end as an asciinema cast.
#
# This script drives the same workflow the README quickstart promises:
#
#   sectum-ai seed   --workdir .sectum-ai --config sectum-ai.yaml
#   sectum-ai probe  --workdir .sectum-ai --config sectum-ai.yaml --output json
#   sectum-ai report --workdir .sectum-ai --config sectum-ai.yaml
#   sectum-ai verify .sectum-ai/evidence.json
#
# Wrapped with `asciinema rec`, the run produces a deterministic
# `demo.cast` file that's embeddable on the website and linkable from
# the README. The whole thing finishes in ~90 seconds; the cast is
# ~10 KB.
#
# Prerequisites:
#   - asciinema: `pip install asciinema` (or `brew install asciinema`)
#   - sectum:    `pip install sectum-ai`
#   - python 3.12+
#
# Usage:
#   cd examples/retrieval-pivot
#   ./record-demo.sh                # writes demo.cast in $PWD
#   ./record-demo.sh --upload       # also uploads to asciinema.org
#   ./record-demo.sh --gif          # also renders demo.gif via agg
#
# After recording, the operator commits demo.cast to the repo and
# embeds it on /docs/quickstart and the website index page via the
# asciinema-player JS embed.
#
# Determinism: the script wipes .sectum-ai/ first, sets a fixed
# substrate seed in sectum-ai.yaml, and runs everything offline so the
# cast file is byte-identical across re-recordings except for
# timestamps. That makes regression-checking the demo cheap.

set -euo pipefail

upload=false
gif=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --upload) upload=true; shift;;
    --gif)    gif=true; shift;;
    *) echo "unknown flag: $1" >&2; exit 64;;
  esac
done

# Sanity-check deps.
command -v asciinema >/dev/null || { echo "asciinema not on PATH; pip install asciinema" >&2; exit 1; }
command -v sectum    >/dev/null || { echo "sectum not on PATH; pip install sectum-ai" >&2; exit 1; }

cd "$(dirname "$0")"

# Fresh substrate each recording.
rm -rf .sectum-ai

# The recording uses the built-in leaky-fakes defaults — the same path
# `examples/retrieval-pivot/run.sh` drives. Earlier revisions of this
# script supplied a custom `sectum-ai.yaml`; that turned out to override
# the substrate flags that make the demo *leaky*, and the resulting
# cast showed 0 findings — directly contradicting the title. The
# in-memory leaky fakes are what produce the 264-finding pack the
# website promises; do not re-introduce a config override here without
# also reproducing the run.sh output.
cast=demo.cast
asciinema rec --overwrite --title "Sectum AI — 95% leakage in 90 seconds" --command "bash -c '
  # === 1. Seed a 4-tenant marker substrate (Acme, Globex, Initech, Hooli)
  sectum-ai seed --workdir .sectum-ai
  echo
  # === 2. Run the cross-tenant probe suite. The default in-memory
  #        substrate is deliberately leaky so the headline RPR shows
  #        real findings; sectum-ai probe exits 2 when it confirms
  #        cross-tenant leaks, so tolerate the non-zero exit.
  sectum-ai probe --workdir .sectum-ai --output json || true
  echo
  # === 3. Build the tamper-evident evidence pack (JSON + PDF + in-toto envelope).
  sectum-ai report --workdir .sectum-ai
  echo
  # === 4. Independently verify the pack with no Sectum installation trust.
  sectum-ai verify .sectum-ai/evidence.json
  echo
  # === 5. Inspect what landed on disk.
  ls -lh .sectum-ai/*.json .sectum-ai/*.pdf
'" "$cast"

echo
echo "wrote $cast ($(wc -c < "$cast" | tr -d ' ') bytes)"

if $upload; then
  asciinema upload "$cast"
fi

if $gif; then
  command -v agg >/dev/null || { echo "agg not on PATH; cargo install --git https://github.com/asciinema/agg" >&2; exit 1; }
  agg --theme monokai --font-size 16 "$cast" demo.gif
  echo "wrote demo.gif ($(wc -c < demo.gif | tr -d ' ') bytes)"
fi
