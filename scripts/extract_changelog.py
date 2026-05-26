#!/usr/bin/env python3
"""Extract a single release's section from CHANGELOG.md.

The release workflow uses this to build the GitHub Release body from the
project's `Keep a Changelog`-formatted CHANGELOG. The output is just the
section body (Added / Changed / Fixed / Notes...), without the header line.

Behaviour:
    - For a final tag (`v0.1.0`), look up `## [0.1.0]`.
    - For a pre-release tag (`v0.1.0-rc.1`), look up `## [0.1.0-rc.1]` first
      and fall back to `## [Unreleased]` so a release candidate can ship
      while the version's final section is still being drafted.
    - If neither is found, exit non-zero so the workflow fails before
      publishing an empty release.

Usage:
    python scripts/extract_changelog.py v0.1.0 > release-notes.md
    python scripts/extract_changelog.py v0.1.0-rc.1 > release-notes.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
_SECTION_RE = re.compile(r"^## \[(?P<label>[^\]]+)\](?:\s|$)")
_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:[-.](?:a|b|rc|alpha|beta)\.?\d+)?)$")


def _is_prerelease(version: str) -> bool:
    return any(token in version for token in ("a", "b", "rc", "alpha", "beta"))


def _read_section(text: str, label: str) -> str | None:
    """Return the body under `## [label]`, or None if the section is absent.

    The body runs from the line after the header to the next `## ` heading
    (or the end of the file). Trailing reference-link lines like
    `[0.1.0]: https://...` are left in place by design - they belong to the
    section and reading them in the release body is fine.
    """
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if match and match.group("label").lower() == label.lower():
            start = index + 1
            break
    if start is None:
        return None

    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break

    return "\n".join(lines[start:end]).strip()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: extract_changelog.py <tag>")
    tag = argv[1]
    match = _TAG_RE.match(tag)
    if match is None:
        raise SystemExit(f"unrecognised release tag: {tag!r}")
    version = match.group("version")

    text = _CHANGELOG.read_text(encoding="utf-8")

    # A final release section is mandatory; a pre-release may use Unreleased.
    body = _read_section(text, version)
    if body is None and _is_prerelease(version):
        body = _read_section(text, "Unreleased")
        if body is not None:
            body = (
                f"_Release notes for `{tag}` (pre-release) are drawn from the "
                "`Unreleased` section of CHANGELOG.md._\n\n" + body
            )
    if body is None:
        raise SystemExit(
            f"refusing to release: CHANGELOG.md has no `## [{version}]` "
            "section (and no Unreleased fallback was eligible). Add the "
            "section and re-tag."
        )

    print(body)
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main(sys.argv))
