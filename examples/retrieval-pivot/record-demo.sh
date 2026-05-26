#!/usr/bin/env bash
# Record the flagship Sectum AI demo end-to-end as an asciinema cast.
#
# This script drives the same workflow the README quickstart promises:
#
#   sectum seed   --workdir .sectum --config sectum.yaml
#   sectum probe  --workdir .sectum --config sectum.yaml --output json
#   sectum report --workdir .sectum --config sectum.yaml
#   sectum verify .sectum/evidence.json
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
# Determinism: the script wipes .sectum/ first, sets a fixed
# substrate seed in sectum.yaml, and runs everything offline so the
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
rm -rf .sectum

# Use a fixed seed so the demo is reproducible across runs.
config=$(mktemp)
cat > "$config" <<'YAML'
scenario:
  seed: 2026
  corpus_profile: demo
workdir: .sectum
# Default leaky-fakes substrate; the cast is supposed to show real
# findings, not a clean run.
YAML

# The narrative script asciinema records. Each line lands as a typed
# command in the cast. Comments are visible to the viewer; commands
# are run via the asciinema-recorded shell.
cast=demo.cast
asciinema rec --overwrite --title "Sectum AI — 95% leakage in 90 seconds" --command "bash -c '
  # === 1. Seed a 4-tenant marker substrate (Acme, Globex, Initech, Hooli)
  sectum seed --workdir .sectum --config $config
  echo
  # === 2. Run the cross-tenant probe suite. The default substrate is
  #        deliberately leaky so the headline RPR shows real findings.
  sectum probe --workdir .sectum --config $config --output json
  echo
  # === 3. Build the tamper-evident evidence pack (JSON + PDF + in-toto envelope).
  sectum report --workdir .sectum --config $config
  echo
  # === 4. Independently verify the pack with no Sectum installation trust.
  sectum verify .sectum/evidence.json
  echo
  # === 5. Inspect what landed on disk.
  ls -lh .sectum/*.json .sectum/*.pdf
'" "$cast"

# Tidy.
rm -f "$config"

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
