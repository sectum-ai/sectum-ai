#!/usr/bin/env python3
"""Verify the workspace's package versions match a release tag.

A signed release is only honest if every distribution carries the version a
human approved. This script reads the tag (`v0.1.0` or `v0.1.0-rc.1`), strips
the leading `v`, and asserts that every `packages/*/pyproject.toml` declares
the same version under `[project] version`. Mismatch is a release blocker.

Usage:
    python scripts/check_release_version.py v0.1.0
    python scripts/check_release_version.py "$GITHUB_REF_NAME"

Exit codes:
    0   every package is at the tagged version
    1   any package is at a different version, or the tag is malformed
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

# A pragmatic PEP 440-ish tag: `v` + the version that goes into pyproject.
# Accepts `v0.1.0`, `v1.2.3`, `v0.1.0-rc.1`, `v0.1.0-alpha.2`, `v0.1.0-beta.1`.
# Final and pre-release tags are both allowed; everything else is rejected.
_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:[-.](?:a|b|rc|alpha|beta)\.?\d+)?)$")

# The five publishable distributions; the release workflow assumes this set.
_PACKAGES = (
    "packages/core",
    "packages/spec",
    "packages/probes",
    "packages/adapters",
    "packages/evidence",
)


def _tag_to_version(tag: str) -> str:
    """Strip the leading `v` and normalise a tag's pre-release segment.

    PyPI uses PEP 440 (`0.1.0rc1`); the tag carries the human-friendly
    `v0.1.0-rc.1`. Both round-trip to the same release; the canonical form
    used inside `pyproject.toml` is the PEP 440 spelling.
    """
    match = _TAG_RE.match(tag)
    if match is None:
        raise SystemExit(
            f"refusing to release: tag {tag!r} is not a recognised release tag. "
            "Expected forms: v0.1.0, v1.2.3, v0.1.0-rc.1, v0.1.0-alpha.2."
        )
    version = match.group("version")
    # Normalise `0.1.0-rc.1` -> `0.1.0rc1`, `0.1.0-alpha.2` -> `0.1.0a2`,
    # `0.1.0-beta.1` -> `0.1.0b1` (the canonical PEP 440 spellings).
    pep440 = {"alpha": "a", "beta": "b"}
    return re.sub(
        r"-(a|b|rc|alpha|beta)\.?(\d+)",
        lambda m: f"{pep440.get(m.group(1), m.group(1))}{m.group(2)}",
        version,
    )


def _package_version(package_dir: Path) -> str:
    """Read the `[project] version` from a package's `pyproject.toml`."""
    pyproject = package_dir / "pyproject.toml"
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    try:
        return str(data["project"]["version"])
    except KeyError as exc:  # pragma: no cover - misconfigured packaging metadata
        raise SystemExit(f"{pyproject}: missing [project] version") from exc


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: check_release_version.py <tag>")
    tag = argv[1]
    expected = _tag_to_version(tag)

    repo_root = Path(__file__).resolve().parent.parent
    mismatches: list[tuple[str, str]] = []
    for package in _PACKAGES:
        actual = _package_version(repo_root / package)
        if actual != expected:
            mismatches.append((package, actual))

    if mismatches:
        lines = [
            f"refusing to release: tag {tag} resolves to version {expected}, "
            "but these packages declare a different version:"
        ]
        lines.extend(f"  {pkg}: {ver}" for pkg, ver in mismatches)
        lines.append(
            "Bump every package's [project] version in pyproject.toml to match "
            "the tag, commit, and re-tag."
        )
        print("\n".join(lines), file=sys.stderr)
        return 1

    print(f"all 5 packages at version {expected} (tag {tag})")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main(sys.argv))
