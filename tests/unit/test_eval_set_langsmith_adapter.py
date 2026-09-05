"""Mock-backed contract tests for the live LangSmith eval-set adapter.

LangSmith is a hosted service, so the adapter's add/search/delete logic is verified
here against an in-memory stand-in for the LangSmith client (the engineering spec,
section 13). The live path is exercised by
``tests/integration/test_eval_set_langsmith.py``.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability, EvalSetAdapter
from sectum_ai.adapters.eval_set.langsmith import LangSmithEvalSet

_PREFIX = "sectum-ai-eval"
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


def _dataset(tenant: UUID) -> str:
    return f"{_PREFIX}-{tenant.hex}"


class _FakeLangSmith:
    """In-memory stand-in for a LangSmith ``Client`` (per-dataset examples)."""

    def __init__(self) -> None:
        self._datasets: dict[str, list[SimpleNamespace]] = {}

    def create_dataset(self, *, dataset_name: str, **_: Any) -> SimpleNamespace:
        self._datasets.setdefault(dataset_name, [])
        return SimpleNamespace(name=dataset_name, id=dataset_name)

    def create_example(self, *, inputs: dict[str, Any], dataset_name: str, **_: Any) -> None:
        self._datasets.setdefault(dataset_name, []).append(SimpleNamespace(inputs=inputs))

    def list_datasets(self, **_: Any) -> Iterator[SimpleNamespace]:
        return iter(SimpleNamespace(name=name, id=name) for name in self._datasets)

    def list_examples(
        self, *, dataset_name: str | None = None, limit: int | None = None, **_: Any
    ) -> Iterator[SimpleNamespace]:
        examples = self._datasets.get(dataset_name or "", [])
        return iter(examples[:limit] if limit is not None else examples)

    def delete_dataset(self, *, dataset_name: str) -> None:
        self._datasets.pop(dataset_name, None)


def test_langsmith_eval_set_conforms_and_reports_text_search() -> None:
    adapter = LangSmithEvalSet(_FakeLangSmith())
    assert isinstance(adapter, EvalSetAdapter)
    assert adapter.supports(Capability.TEXT_SEARCH)


def test_langsmith_eval_set_add_creates_the_dataset_on_first_fixture() -> None:
    client = _FakeLangSmith()
    adapter = LangSmithEvalSet(client)
    adapter.add(_TENANT_A, "fixture mentioning SECTUM-CANARY-AAA")
    # the tenant's dataset now exists and holds the fixture
    assert _dataset(_TENANT_A) in {d.name for d in client.list_datasets()}
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-AAA")


def test_langsmith_eval_set_search_is_scoped_to_a_tenants_dataset() -> None:
    client = _FakeLangSmith()
    adapter = LangSmithEvalSet(client)
    adapter.add(_TENANT_A, "fixture mentioning SECTUM-CANARY-AAA")
    hits = adapter.search(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits and "SECTUM-CANARY-AAA" in hits[0]
    # tenant B has no dataset, so the marker never surfaces in B's scope
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-AAA") == []


def test_langsmith_eval_set_search_returns_nothing_when_the_marker_is_absent() -> None:
    client = _FakeLangSmith()
    adapter = LangSmithEvalSet(client)
    adapter.add(_TENANT_A, "a benign fixture")
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-AAA") == []


def test_langsmith_eval_set_delete_clears_a_tenants_dataset() -> None:
    client = _FakeLangSmith()
    adapter = LangSmithEvalSet(client)
    adapter.add(_TENANT_A, "SECTUM-CANARY-DEL")
    adapter.add(_TENANT_B, "SECTUM-CANARY-KEEP")
    adapter.delete(_TENANT_A)
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-DEL") == []
    # another tenant's dataset is untouched
    assert adapter.search(_TENANT_B, "SECTUM-CANARY-KEEP")


def test_langsmith_eval_set_delete_is_idempotent_when_no_dataset_exists() -> None:
    adapter = LangSmithEvalSet(_FakeLangSmith())
    adapter.delete(_TENANT_A)  # must not raise when the tenant has no dataset
    assert adapter.search(_TENANT_A, "anything") == []


def test_langsmith_eval_set_soft_delete_leaves_the_fixtures() -> None:
    # A soft-delete eval set acknowledges the request but keeps the dataset - the
    # Class 11 residue, matching the fake and the S3 backup.
    client = _FakeLangSmith()
    adapter = LangSmithEvalSet(client, soft_delete=True)
    adapter.add(_TENANT_A, "SECTUM-CANARY-SOFT")
    adapter.delete(_TENANT_A)
    assert adapter.supports(Capability.SOFT_DELETE)
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-SOFT")  # the residue survives


def test_langsmith_eval_set_search_tolerates_an_example_without_the_text_key() -> None:
    client = _FakeLangSmith()
    # an example whose inputs omit "text" must not crash; its str form is scanned
    client.create_dataset(dataset_name=_dataset(_TENANT_A))
    client.create_example(inputs={"other": "SECTUM-CANARY-AAA"}, dataset_name=_dataset(_TENANT_A))
    assert LangSmithEvalSet(client).search(_TENANT_A, "SECTUM-CANARY-AAA")


def test_langsmith_eval_set_refuses_a_listing_that_hit_its_cap() -> None:
    from sectum_ai.spec import AdapterError

    client = _FakeLangSmith()
    adapter = LangSmithEvalSet(client)
    for index in range(1000):
        adapter.add(_TENANT_A, f"fixture number {index}")
    # A MISS on a full page is what cannot be told from an erased fixture; a hit
    # on the same page is a definite residual and is reported (see below).
    with pytest.raises(AdapterError, match="listing cap"):
        adapter.search(_TENANT_A, "SECTUM-CANARY-ABSENT")


def test_langsmith_eval_set_reports_a_fixture_found_on_a_full_page() -> None:
    # A fixture FOUND on a capped page already answers the question; refusing it
    # would lose a real residual rather than prevent a false clean.
    client = _FakeLangSmith()
    adapter = LangSmithEvalSet(client)
    adapter.add(_TENANT_A, "fixture SECTUM-CANARY-AAA")
    for index in range(999):
        adapter.add(_TENANT_A, f"fixture number {index}")
    assert adapter.search(_TENANT_A, "SECTUM-CANARY-AAA")


def test_a_token_overlap_hit_does_not_suppress_the_cap_refusal() -> None:
    # The adapter reports hits by token OVERLAP; the Class 11 probe counts an
    # exact substring. Every hard canary shares the tokens "sectum" and "canary",
    # so one other canary among the page-filling rows made the adapter report a
    # "hit" the probe would not count - which suppressed the refusal, and the
    # target marker sitting past the cap then read as absent. The surface attested
    # ERASED off a listing that was never complete.
    from sectum_ai.spec import AdapterError

    client = _FakeLangSmith()
    adapter = LangSmithEvalSet(client)
    adapter.add(_TENANT_A, "fixture SECTUM-CANARY-OTHERAAAAAAAAAAAAAAA")
    for index in range(999):
        adapter.add(_TENANT_A, f"fixture number {index}")
    with pytest.raises(AdapterError, match="listing cap"):
        adapter.search(_TENANT_A, "SECTUM-CANARY-TARGETBBBBBBBBBBBBBBB")
