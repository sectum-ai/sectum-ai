# ADR-0017: weasyprint is an optional audit-pack engine; reportlab stays the default

- Status: Accepted
- Date: 2026-05-30
- Deciders: Dmitry Maranik

## Context

The audit pack is the auditor-/DPO-facing deliverable (the engineering spec,
sections 8.3 and 18). The spec's technology table (section 13) lists both
`reportlab` and `weasyprint` and notes a preference for weasyprint "for
templating"; section 21 recorded the engine choice as an open decision
("prototype weasyprint first"). This ADR resolves it.

The two engines trade off cleanly:

- **reportlab** is pure Python with no system libraries. It is always
  installable, keeps the base install and CI light, and already renders a
  complete, audit-ready pack (summary, scope/methodology, findings with control
  mappings and evidence spans, integrity digests).
- **weasyprint** renders HTML/CSS to PDF, giving a richer, templated layout
  (severity badges, typographic tables, page footers with page numbers). It
  needs the pango/cairo/gdk-pixbuf system libraries, which complicate
  installation and CI on some platforms.

Forcing weasyprint into the base install would bloat the dependency tree and add
system-library friction for the many users who never need the fancier layout —
the same reasoning that makes RFC 3161 timestamping and Rekor anchoring
optional extras (`sectum-ai-evidence[rfc3161]`, `[rekor]`). The renderer was already
designed to be theme-pluggable ([ADR-0002](0002-evidence-layer-oss-boundary.md)).

## Decision

Ship **both** engines behind a selector, with **reportlab as the default**.

- `render_audit_pack(pack, output, *, engine=PdfEngine.REPORTLAB)` dispatches on
  a `PdfEngine` enum (`reportlab` | `weasyprint`).
- weasyprint is an **optional extra**: `pip install "sectum-ai[weasyprint]"`
  (wired as `sectum-ai-evidence[weasyprint]`). It is imported lazily, only when
  selected, so the base install never pulls it in. Selecting `weasyprint`
  without the extra raises a typed `EvidenceError` with the install hint.
- The HTML document is produced by a pure `build_audit_html(pack)` with no
  weasyprint dependency, so the template logic is fully unit-tested without the
  system libraries; only the thin HTML→PDF binding needs the extra (its test
  `importorskip`s).
- Both engines render the **same content** — the methodology narrative, control
  formatting, and coverage disclaimer are shared — so a pack asserts identical
  facts whichever engine produced it. The `sectum report --pdf-engine` flag
  selects the engine at the CLI.

## Consequences

- The default `sectum report` and CI stay pure-Python and light; nothing about
  the base install changes.
- Users who want the richer auditor layout opt in with one extra and the
  `--pdf-engine weasyprint` flag (or `engine=` in the API).
- Two renderers must be kept content-equivalent. The shared content helpers and
  the parallel test suites (`test_pdf.py`, `test_pdf_weasyprint.py`) guard
  against drift; a new section must be added to both.
- The section-21 "PDF engine" open decision is now resolved. If weasyprint's
  layout proves decisively better in front of real auditors, a future ADR may
  revisit the default — but not the optional-extra boundary.
