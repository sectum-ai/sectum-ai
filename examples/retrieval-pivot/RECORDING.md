> **Status:** the committed `demo.cast` predates the `sectum_ai` rename and the
> current verifier — it shows a `.sectum/` workdir, a `VERIFIED: the evidence pack
> is intact` verdict the CLI no longer prints, and two verify checks where today
> there are seven. Re-record it with the steps below before linking it anywhere.
> A `demo.gif` is not committed.

# Recording the demo

The flagship demo is a 90-second walkthrough of the Class 2 organic-
entity-bleed RAG probe — the one that reproduces the Retrieval Pivot
research finding (81.2% benign-query cross-tenant leakage on the demo
substrate; the 2026 research reported 95.4%). It is meant to be the
first thing a visitor sees; nothing links it yet.

This directory ships [`record-demo.sh`](./record-demo.sh) — a one-
shot script that wraps `asciinema rec` around the demo workflow and
emits a `demo.cast` file. The cast is small (a few KB), deterministic,
and embeddable as a JS player on any page.

## Why a recording at all

Engineers who land on a security product's page click "watch demo"
before they read docs. A 90-second asciinema cast is the lowest-
friction proof that the headline number (81.2% RPR) is reproducible
on a real machine. It's also the only piece of the website that
shows actual command output rather than prose.

## Quickstart

```sh
# One-time setup
pip install sectum-ai asciinema

cd examples/retrieval-pivot
./record-demo.sh                # writes demo.cast in $PWD
./record-demo.sh --gif          # also renders demo.gif via agg
./record-demo.sh --upload       # also uploads to asciinema.org
```

The script:

1. Wipes `.sectum-ai/` to start from a clean substrate.
2. Runs against the CLI's built-in demo stack (no config file — the
   script deliberately passes none, so the substrate is the default one).
3. Drives the four-command workflow inside `asciinema rec`:
   `seed` → `probe --output json` → `report` → `verify --allow-unanchored
   --allow-synthetic` (a demo pack is refused without both flags).
4. Writes `demo.cast` to the current directory.

## Embedding on the website

The website renders the cast via the asciinema-player JS embed:

```html
<link rel="stylesheet" type="text/css"
  href="https://cdn.jsdelivr.net/npm/asciinema-player@3/dist/bundle/asciinema-player.css" />
<script src="https://cdn.jsdelivr.net/npm/asciinema-player@3/dist/bundle/asciinema-player.min.js"></script>
<div id="demo"></div>
<script>
  AsciinemaPlayer.create('/demo.cast', document.getElementById('demo'), {
    autoPlay: false,
    preload: true,
    cols: 100,
    rows: 24,
  });
</script>
```

For the GitHub README the GIF (`./record-demo.sh --gif`) renders
inline without a JS embed — embed it with a standard
`![demo](./examples/retrieval-pivot/demo.gif)`.

## Re-recording cadence

Re-record on:

- A new release of the OSS that changes the CLI output shape (the
  command outputs would visibly differ in the cast).
- A change to the default substrate that changes the headline RPR.
- A new attack class being added to the suite (worth showing more
  probes in the cast).

The script is deterministic, so a re-recording produces a
near-identical cast modulo timestamps. The diff at review time
should be small.

## Out of scope

- A full video walkthrough (presenter-narrated). That's a separate
  artifact; this is the terminal-only mechanical proof.
- A live web demo at sectum.ai/demo. That'd require a sandboxed
  Sectum runner; out of scope until the Sectum Cloud platform
  ships the customer-onboarding pipeline.
