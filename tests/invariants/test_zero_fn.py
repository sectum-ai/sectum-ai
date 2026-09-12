"""Invariant: every planted marker that surfaces cross-principal is detected.

The zero-false-*negative* complement to the zero-FP control (the engineering
spec, section 6.4). Each marker type has its own detection path - HARD via the
exact scan, SECRET via the credential-format pass, ENTITY via semantic
similarity + judge - and a foreign marker appearing verbatim in an observation
must always become a confirmed leak, from whichever field it was planted in.
"""

import json
import tempfile
from pathlib import Path

from sectum_ai.probes import DetectionPipeline, confirmed_findings
from sectum_ai.spec import MarkerType, Substrate, Surface
from sectum_ai.substrate import build_substrate, default_scenario


def _substrate() -> Substrate:
    return build_substrate(default_scenario(seed=271828))


def test_every_foreign_marker_surfacing_is_a_confirmed_leak() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    observer = substrate.tenants[1].tenant_id
    exercised: dict[MarkerType, int] = dict.fromkeys(MarkerType, 0)
    for marker in substrate.manifest.markers:
        if marker.owner_tenant_id == observer:
            continue
        text = f"retrieved cross-tenant content: {marker.plaintext} (end of chunk)"
        found = confirmed_findings(pipeline.detect(observer, text, Surface.VECTOR_DB))
        assert any(finding.marker_id == marker.marker_id for finding in found), (
            f"missed {marker.marker_type.value} {marker.marker_id}"
        )
        exercised[marker.marker_type] += 1
    # All three marker types were actually exercised (not a vacuous pass).
    assert all(count > 0 for count in exercised.values()), exercised


def test_marker_is_detected_from_each_planted_field() -> None:
    # A marker carried in a document's title or metadata - not only its body -
    # is still a confirmed leak when that single field surfaces cross-tenant.
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate)
    documents = {doc.doc_id: doc for doc in substrate.documents}
    observer = substrate.tenants[1].tenant_id
    seen_fields: set[str] = set()
    for marker in substrate.manifest.markers:
        if marker.owner_tenant_id == observer:
            continue
        for location in marker.planted_locations:
            document = documents[location.doc_id]
            field_text = {
                "title": document.title,
                "body": document.content,
                "metadata": " ".join(document.metadata.values()),
            }[location.field]
            found = confirmed_findings(pipeline.detect(observer, field_text, Surface.VECTOR_DB))
            assert any(finding.marker_id == marker.marker_id for finding in found), (
                f"{marker.marker_id} not detected from its {location.field} field"
            )
            seen_fields.add(location.field)
    assert seen_fields == {"body", "title", "metadata"}


def test_every_by_id_read_flags_the_200_empty_ambiguity() -> None:
    """Class 1's deny-semantics rule belongs to all three by-id reads, not one.

    ``AccessOutcome.DENIED`` is produced by no code path - the runner emits only
    RETURNED or EMPTY - so "nothing came back" can never mean "the deny was
    enforced". The vector fetch recorded that and its two structural siblings, a
    foreign ``cache.get`` and a foreign ``mcp.invoke`` of another principal's
    resource key, threw the identical ``str | None`` away: on an isolated stack
    Classes 4 and 7 passed with an empty note over exactly Class 1's evidence.
    """
    from collections import Counter

    from typer.testing import CliRunner

    from sectum_ai.cli.app import app

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as raw:
        workdir = Path(raw)
        config = workdir / "isolated.yaml"
        config.write_text("adapters:\n  vector_store: {kind: fake, shared_index: false}\n")
        assert (
            runner.invoke(
                app, ["seed", "--workdir", str(workdir), "--config", str(config)]
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(
                app, ["probe", "--workdir", str(workdir), "--config", str(config)]
            ).exit_code
            == 0
        )
        run = json.loads((workdir / "run.json").read_text())

    caveated = Counter(
        finding["probe_id"] for finding in run["findings"] if "-empty-" in finding["finding_id"]
    )
    assert set(caveated) == {
        "tenant-boundary-fetch",
        "semantic-cache-contamination",
        "agent-tool-hijack",
        # The fourth by-id read. `lookup <marker_id>` across a principal boundary
        # is one, and this class passed with no note over exactly Class 1's
        # evidence. Its caveat is unconditional rather than gated on
        # `AccessOutcome.EMPTY`: an agent framework answers in prose whichever way
        # its tool went, so no output establishes a deny.
        "agent-framework-hijack",
    }, caveated
    # Informational only: an unverified finding must never flip a class - that is
    # the false-positive control the whole detector rests on.
    assert {
        finding["status"] for finding in run["findings"] if "-empty-" in finding["finding_id"]
    } == {"unverified"}
