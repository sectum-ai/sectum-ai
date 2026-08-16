"""An adapter family this build cannot resolve is rejected, not ignored.

Every resolver reads its family with ``config.adapters.get(name, fake)``, so an
unrecognised key was never looked up at all: the family fell back to the built-in
in-memory fake and the run proceeded as though configured. ``vector:`` instead of
``vector_store:`` is the whole failure - one character short of a real backend,
written by an operator who then believed they had probed production.

v0.9.0 made that visible after the fact (the run records the surface as
SYNTHETIC). This closes it before the fact: a misspelled key is never intentional,
so the honest moment to say so is config load, before anything is seeded.
"""

import re
from pathlib import Path

import pytest

from sectum_ai.config import ADAPTER_FAMILIES, AdapterConfig, SectumConfig, load_config
from sectum_ai.spec import ConfigError

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _error_text(excinfo: pytest.ExceptionInfo[Exception]) -> str:
    return str(excinfo.value)


def test_the_family_set_matches_every_key_the_resolvers_read() -> None:
    """The declared set must equal what the code actually looks up.

    A family added to a resolver but not here becomes silently un-configurable -
    the validator would reject the very key the resolver expects. The reverse (a
    name here that nothing reads) is just as bad: the config would accept a block
    that never takes effect, which is the failure this module exists to prevent.
    """
    read: set[str] = set()
    for path in (_REPO_ROOT / "packages").rglob("*.py"):
        read |= set(re.findall(r'adapters\.get\(\s*"([a-z_]+)"', path.read_text()))
    assert read, "found no adapters.get call sites - the introspection broke"
    assert read == set(ADAPTER_FAMILIES), (
        f"declared but never read: {sorted(set(ADAPTER_FAMILIES) - read)}; "
        f"read but not declared: {sorted(read - set(ADAPTER_FAMILIES))}"
    )


@pytest.mark.parametrize("family", sorted(ADAPTER_FAMILIES))
def test_every_declared_family_is_accepted(family: str) -> None:
    config = SectumConfig(adapters={family: AdapterConfig(kind="fake")})
    assert family in config.adapters


def test_an_empty_adapters_block_is_still_valid() -> None:
    # Configuring nothing is legitimate (the quickstart does it); only a key that
    # cannot resolve is an error.
    assert SectumConfig(adapters={}).adapters == {}


def test_the_original_typo_is_rejected_with_the_family_it_meant() -> None:
    with pytest.raises(ValueError) as excinfo:
        SectumConfig(adapters={"vector": AdapterConfig(kind="pgvector")})
    message = _error_text(excinfo)
    assert "'vector'" in message
    assert "did you mean 'vector_store'?" in message


@pytest.mark.parametrize(
    "typo,expected",
    [
        ("vectorstore", "vector_store"),
        ("observabilty", "observability"),
        ("momery", "memory"),
        ("aget", "agent"),
    ],
)
def test_near_misses_suggest_the_intended_family(typo: str, expected: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        SectumConfig(adapters={typo: AdapterConfig(kind="fake")})
    assert f"did you mean {expected!r}?" in _error_text(excinfo)


def test_an_unrecognisable_key_still_errors_clearly() -> None:
    # No near match to offer; the message must still name the key and the valid set
    # rather than failing with a bare suggestion-less shrug.
    with pytest.raises(ValueError) as excinfo:
        SectumConfig(adapters={"zzzzzz": AdapterConfig(kind="fake")})
    message = _error_text(excinfo)
    assert "'zzzzzz'" in message
    assert "vector_store" in message  # the valid set is listed


def test_every_unknown_family_is_named_not_just_the_first() -> None:
    with pytest.raises(ValueError) as excinfo:
        SectumConfig(
            adapters={
                "vector": AdapterConfig(kind="fake"),
                "observabilty": AdapterConfig(kind="fake"),
                "cache": AdapterConfig(kind="fake"),
            }
        )
    message = _error_text(excinfo)
    assert "'vector'" in message
    assert "'observabilty'" in message
    assert "families" in message  # plural


def test_the_message_explains_the_consequence_not_just_the_rule() -> None:
    # The operator's mental model is "I configured pgvector". Saying "unknown key"
    # alone leaves them to guess why that mattered.
    with pytest.raises(ValueError) as excinfo:
        SectumConfig(adapters={"vector": AdapterConfig(kind="pgvector")})
    assert "synthetic" in _error_text(excinfo)


def test_a_typo_in_a_real_config_file_names_the_file(tmp_path: Path) -> None:
    # Through load_config the ValidationError becomes a ConfigError carrying the
    # path, which is what the CLI prints.
    config = tmp_path / "sectum-ai.yaml"
    config.write_text("adapters:\n  vector:\n    kind: pgvector\n    dsn_env: SECTUM_DSN\n")
    with pytest.raises(ConfigError) as excinfo:
        load_config(config)
    message = str(excinfo.value)
    assert str(config) in message
    assert "did you mean 'vector_store'?" in message
