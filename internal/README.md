# internal/

Internal planning artifacts — product specs, design decisions, and roadmap notes
that are **not** part of the published documentation site (`docs/`, served at
docs.sectum.ai) and carry no build or test gate. This is for work that is planned
or on hold, ahead of any public commitment.

- `specs/` — product specs / PRDs for planned features.
- `adr/` — internal architecture decision records, numbered **separately** from
  the public `docs/adr/` sequence. Promote one into `docs/adr/` (renumbering to
  the next public number and adding it to the mkdocs nav) if and when the feature
  ships and the decision becomes public.

Nothing here is imported by the packages or referenced by mkdocs, so it never
affects the release artifacts.
