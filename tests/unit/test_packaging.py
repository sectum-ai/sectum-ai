"""Packaging invariants: a published package declares the cross-package and
third-party dependencies it imports, so a standalone `pip install` works (ADR-0004,
the engineering spec, section 13). The dev uv workspace installs every package, so
these gaps are invisible to import-time checks - hence this static guard."""

import tomllib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _declared_names(package: str) -> set[str]:
    data = tomllib.loads((_REPO / "packages" / package / "pyproject.toml").read_text())
    names: set[str] = set()
    for dep in data["project"]["dependencies"]:
        head = dep.split(";", 1)[0].strip()
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " "):
            head = head.split(sep, 1)[0]
        names.add(head.strip())
    return names


def test_probes_declares_the_adapters_dependency_it_imports() -> None:
    # erasure/probe.py and kv_cache_timing/probe.py import sectum.adapters at module
    # load (eagerly via probes/__init__), so a published sectum-ai-probes must
    # declare sectum-ai-adapters or `pip install sectum-ai-probes` + `import
    # sectum.probes` raises ModuleNotFoundError.
    assert "sectum-ai-adapters" in _declared_names("probes")


def test_core_declares_pydantic_it_imports_directly() -> None:
    # config.py and cli/app.py import pydantic directly; do not rely on the
    # transitive edge via sectum-ai-spec.
    assert "pydantic" in _declared_names("core")


def test_adapters_declares_pydantic_it_imports_directly() -> None:
    assert "pydantic" in _declared_names("adapters")
