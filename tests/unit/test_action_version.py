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
