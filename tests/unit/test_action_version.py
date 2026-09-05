"""Standing guard: the GitHub Action installs the version this repo ships.

``action.yml`` pins a ``version`` input whose default is passed straight to
``pip install "sectum-ai==${SECTUM_AI_VERSION}"``, so a caller who does not
override it gets exactly that version. Nothing tied it to the packages' own
version, and ``docs/RELEASING.md`` listed only the five ``pyproject.toml`` files,
so six consecutive releases (v0.7.0 through v0.8.3) shipped while the Action kept
installing 0.6.0.

That is worse than a stale docs string: the Action is how a customer runs Sectum
in CI, and 0.6.0 predates every correctness fix in 0.8.0 - the false ERASED
verdicts, the judge-vetoed verbatim leaks, the KV-cache findings manufactured
from machine drift. The Action was quietly handing out the versions those fixes
exist to replace.

Version drift is invisible by construction: the stale value is a well-formed
version string that no reader would think to question. So it gets a test rather
than a line in a runbook.
"""

import re
import tomllib
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]


def _package_version() -> str:
    data = tomllib.loads((_ROOT / "packages" / "core" / "pyproject.toml").read_text())
    version: str = data["project"]["version"]
    return version


def _action_default() -> str:
    data = yaml.safe_load((_ROOT / "action.yml").read_text())
    default: str = data["inputs"]["version"]["default"]
    return default


def _readme_status_version() -> str | None:
    readme = (_ROOT / "README.md").read_text()
    match = re.search(r"\*\*Status:\s*v(\d+\.\d+\.\d+)", readme)
    return match.group(1) if match else None


def test_the_action_default_matches_the_shipped_version() -> None:
    # A release that bumps the packages but not the Action leaves every default
    # run of the Action installing the previous release.
    assert _action_default() == _package_version(), (
        f"action.yml pins sectum-ai=={_action_default()} but this repo ships "
        f"{_package_version()}; bump the `version` input default in action.yml "
        "(and the two references in docs/github-action.md) as part of the release"
    )


def test_the_action_docs_quote_the_same_version() -> None:
    # The docs table states the default and the prose shows a pin example; both
    # are read as authoritative, so both drift silently when only action.yml moves.
    docs = (_ROOT / "docs" / "github-action.md").read_text()
    shipped = _package_version()
    table = re.search(r"^\|\s*`version`\s*\|\s*`([^`]+)`\s*\|", docs, re.MULTILINE)
    assert table is not None, "docs/github-action.md has no `version` row in the inputs table"
    assert table.group(1) == shipped, (
        f"docs/github-action.md documents the default as {table.group(1)}, "
        f"but this repo ships {shipped}"
    )
    pins = set(re.findall(r"sectum-ai/sectum-ai@v(\d+\.\d+\.\d+)", docs))
    assert pins <= {shipped}, (
        f"docs/github-action.md pins sectum-ai/sectum-ai@v{sorted(pins - {shipped})} "
        f"in an example, but this repo ships {shipped}"
    )


def test_the_readme_status_matches_the_shipped_version() -> None:
    # The README status line states the shipped version in prose but was tied to
    # nothing, so it sat at v0.8.1 while the repo shipped 0.10.0 (two releases
    # stale) - a wrong version string in the storefront of a "verify, don't trust
    # us" product. Guard it like the Action default.
    shipped = _package_version()
    status = _readme_status_version()
    assert status is not None, "README.md has no `**Status: vX.Y.Z**` line"
    assert status == shipped, (
        f"README.md status line says v{status}, but this repo ships {shipped}; "
        "bump the `**Status: vX.Y.Z**` line in README.md as part of the release"
    )


def test_the_docs_landing_page_states_the_shipped_version() -> None:
    # docs/index.md is the docs site's front page and states the version in prose.
    # RELEASING.md listed it with "unguarded by the test below, so check it by
    # hand" - the same arrangement that let the Action sit six releases stale.
    shipped = _package_version()
    match = re.search(
        r"Sectum AI is at v(\d+\.\d+\.\d+)", (_ROOT / "docs" / "index.md").read_text()
    )
    assert match is not None, "docs/index.md has no `Sectum AI is at vX.Y.Z` line"
    assert match.group(1) == shipped, (
        f"docs/index.md says v{match.group(1)}, but this repo ships {shipped}; "
        "bump it as part of the release"
    )


def test_the_security_policy_supports_the_shipped_minor() -> None:
    # SECURITY.md tells a reporter which versions get fixes. Left stale it points
    # them at a minor that is no longer current - and it was in neither the
    # release recipe nor a test.
    shipped = _package_version()
    text = (_ROOT / "SECURITY.md").read_text()
    match = re.search(r"currently `(\d+\.\d+)\.x`", text)
    assert match is not None, "SECURITY.md has no ``currently `X.Y.x` `` supported-versions row"
    minor = ".".join(shipped.split(".")[:2])
    assert match.group(1) == minor, (
        f"SECURITY.md says the supported minor is {match.group(1)}.x, but this repo "
        f"ships {shipped}; bump the supported-versions table as part of the release"
    )
