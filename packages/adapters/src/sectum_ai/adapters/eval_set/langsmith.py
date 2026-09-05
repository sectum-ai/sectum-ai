"""Live LangSmith adapter: a golden eval set backed by LangSmith Datasets.

A LangSmith Dataset *is* a curated eval / golden test-fixture set - the fourth of
the spec's "ten hiding places" - so each tenant maps to its own dataset named
``{prefix}-{tenant.hex}``. A fixture is a dataset example, a search scans the
dataset's examples for the marker, and erasure deletes the tenant's dataset. The
public LangSmith SDK exposes per-dataset create/list/delete and per-example
create/list, which makes the per-dataset model the clean fit (like the LangSmith
observability adapter's per-project model).

The ``langsmith`` package is imported only on the live ``connect`` path, so the
adapter and its mock-backed test need no dependency. The live path requires the
``langsmith`` optional dependency: ``pip install sectum-ai-adapters[langsmith]``.
"""

import re
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, EvalSetAdapter
from sectum_ai.spec import AdapterError

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_EXAMPLE_LIMIT = 1000
"""How many of a dataset's examples to scan when searching for a marker."""


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class LangSmithEvalSet(EvalSetAdapter):
    """A golden eval set backed by LangSmith Datasets, one dataset per tenant."""

    def __init__(
        self,
        client: Any,
        *,
        name: str = "langsmith-eval",
        prefix: str = "sectum-ai-eval",
        soft_delete: bool = False,
    ) -> None:
        capabilities = {Capability.TEXT_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._client = client
        self._prefix = prefix
        self._soft_delete = soft_delete

    @classmethod
    def connect(
        cls,
        api_key: str,
        api_url: str | None = None,
        *,
        name: str = "langsmith-eval",
        prefix: str = "sectum-ai-eval",
        soft_delete: bool = False,
    ) -> Self:
        """Open a LangSmith client and return the adapter.

        The ``langsmith`` package is imported here, on the live path only, so the
        adapter module and its mock-backed test do not require it.
        """
        from langsmith import Client

        client = Client(api_url=api_url, api_key=api_key)
        return cls(client, name=name, prefix=prefix, soft_delete=soft_delete)

    def _dataset_name(self, tenant: UUID) -> str:
        return f"{self._prefix}-{tenant.hex}"

    def _dataset_names(self) -> set[str]:
        return {str(dataset.name) for dataset in self._client.list_datasets()}

    @staticmethod
    def _text(example: Any) -> str:
        # A fixture is stored under the ``text`` input; read defensively (the whole
        # inputs dict carries the marker even if the key ever changes).
        inputs = getattr(example, "inputs", None) or {}
        if isinstance(inputs, dict) and "text" in inputs:
            return str(inputs["text"])
        return str(inputs)

    def add(self, tenant: UUID, text: str) -> None:
        dataset = self._dataset_name(tenant)
        if dataset not in self._dataset_names():
            self._client.create_dataset(dataset_name=dataset)
        self._client.create_example(inputs={"text": text}, dataset_name=dataset)

    def search(self, tenant: UUID, query: str) -> list[str]:
        dataset = self._dataset_name(tenant)
        if dataset not in self._dataset_names():
            return []
        query_tokens = _tokens(query)
        hits: list[str] = []
        seen = 0
        for example in self._client.list_examples(dataset_name=dataset, limit=_EXAMPLE_LIMIT):
            seen += 1
            text = self._text(example)
            if query_tokens & _tokens(text):
                hits.append(text)
        if seen >= _EXAMPLE_LIMIT:
            # A truncated page is not a scan: a fixture past it read as absent.
            raise AdapterError(
                f"LangSmith dataset {dataset} holds at least {_EXAMPLE_LIMIT} examples, the "
                "listing cap, so the eval-set scan would be incomplete"
            )
        return hits

    def delete(self, tenant: UUID) -> None:
        # A soft-delete eval set acknowledges the request but keeps the dataset - the
        # residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        dataset = self._dataset_name(tenant)
        if dataset in self._dataset_names():
            self._client.delete_dataset(dataset_name=dataset)
