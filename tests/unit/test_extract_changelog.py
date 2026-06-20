"""Tests for scripts/extract_changelog.py (the release-notes extractor).

The release workflow builds the GitHub Release body from CHANGELOG.md via this
script, so a final tag must yield its populated section and an empty section -
including an empty Unreleased fallback for a pre-release tag - must refuse rather
than silently ship a release with no notes.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

# The script lives under scripts/ (not an importable package), so load it by path.
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "extract_changelog.py"
_spec = importlib.util.spec_from_file_location("extract_changelog", _SCRIPT)
assert _spec is not None and _spec.loader is not None
extract_changelog: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_changelog)

_POPULATED = """\
# Changelog

## [Unreleased]

## [0.1.1] - 2026-06-19

### Added

- A real release entry.

## [0.1.0] - 2026-05-26

### Added

- Initial release.
"""

_EMPTY_UNRELEASED = """\
# Changelog

## [Unreleased]

## [0.1.1] - 2026-06-19

### Added

- A real release entry.
"""


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changelog: str, tag: str) -> int:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(changelog, encoding="utf-8")
    monkeypatch.setattr(extract_changelog, "_CHANGELOG", path)
    return int(extract_changelog.main(["extract_changelog.py", tag]))


def test_final_tag_returns_its_section_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, tmp_path, _POPULATED, "v0.1.1") == 0
    out = capsys.readouterr().out
    assert "A real release entry." in out
    assert "Initial release." not in out  # stops at the next `## ` heading
    assert "drawn from the" not in out  # no pre-release banner for a final tag


def test_prerelease_uses_its_own_section_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changelog = _POPULATED.replace(
        "## [Unreleased]\n",
        "## [Unreleased]\n\n## [0.1.2-rc.1] - 2026-06-20\n\n### Added\n\n- An rc entry.\n",
    )
    assert _run(monkeypatch, tmp_path, changelog, "v0.1.2-rc.1") == 0
    out = capsys.readouterr().out
    assert "An rc entry." in out
    assert "drawn from the" not in out  # used its own section, not the fallback


def test_prerelease_falls_back_to_populated_unreleased(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changelog = _POPULATED.replace(
        "## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- A drafted entry.\n"
    )
    assert _run(monkeypatch, tmp_path, changelog, "v0.1.2-rc.1") == 0
    out = capsys.readouterr().out
    assert "A drafted entry." in out
    assert "drawn from the" in out  # the pre-release fallback banner is prepended


def test_prerelease_with_empty_unreleased_fallback_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The regression: an empty `## [Unreleased]` used to ship a banner-only body
    # at exit 0. It must now fail before publishing an empty release.
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, tmp_path, _EMPTY_UNRELEASED, "v0.1.2-rc.1")
    assert "empty" in str(exc.value)
    assert "Unreleased" in str(exc.value)


def test_final_tag_with_empty_section_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty_final = "# Changelog\n\n## [0.1.1] - 2026-06-19\n\n## [0.1.0] - 2026-05-26\n\n- old\n"
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, tmp_path, empty_final, "v0.1.1")
    assert "empty" in str(exc.value)


def test_missing_section_refuses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, tmp_path, _POPULATED, "v9.9.9")
    assert "no `## [9.9.9]`" in str(exc.value)


def test_malformed_tag_refuses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, tmp_path, _POPULATED, "v1.2")
    assert "unrecognised release tag" in str(exc.value)
