"""Split a corpus write into requests a hosted store accepts.

Pinecone, Azure AI Search and Qdrant cap the size of one write request. The
64-dimension hashing default fit a whole tenant's corpus in one; a real embedding
model's vectors (hundreds to thousands of dimensions) do not.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence


def request_batches[R](
    records: Sequence[R],
    *,
    max_bytes: int,
    size: Callable[[R], int],
    max_records: int | None = None,
) -> Iterator[Sequence[R]]:
    """Consecutive runs of ``records``, each within the caps (a lone oversized record alone)."""
    start, total = 0, 0
    for index, record in enumerate(records):
        length = size(record)
        if index > start and (total + length > max_bytes or index - start == max_records):
            yield records[start:index]
            start, total = index, 0
        total += length
    if start < len(records):
        yield records[start:]
