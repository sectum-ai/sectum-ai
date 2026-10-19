"""Split a corpus write into requests a hosted store accepts.

Pinecone, Azure AI Search and Qdrant cap one write request by size (Qdrant by a
server setting, 32 MB by default), Pinecone and Azure also at 1000 records. A real
embedding model's vectors can pass a size cap at the default corpus size: at 384
dimensions a 500-document corpus computes to about 4 MB, twice Pinecone's 2 MB.
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
