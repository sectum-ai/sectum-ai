"""Tests for the OSCAL 1.1.x assessment-results export (``sectum_ai.evidence.oscal``)."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sectum_ai.evidence import OSCAL_VERSION, run_to_oscal
from sectum_ai.evidence.controls import COVERAGE_DISCLAIMER, control_mappings
from sectum_ai.spec import (
    Finding,
    FindingStatus,
    RunMetrics,
    RunResult,
    Severity,
    Surface,
)

_OWNER = UUID(int=0xB)
_OBSERVED = UUID(int=0xA)


def _finding(
    finding_id: str,
    *,
    probe_id: str = "rag-entity-bleed",
    severity: Severity = Severity.CRITICAL,
    status: FindingStatus = FindingStatus.CONFIRMED,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        probe_id=probe_id,
        severity=severity,
        confidence=1.0,
        status=status,
        owner_tenant_id=_OWNER,
        observed_in_tenant_id=_OBSERVED,
        surface=Surface.VECTOR_DB,
        marker_id="marker-1",
        evidence_span="canary surfaced in the wrong tenant",
        owasp_llm="LLM08:2025",
        atlas=("AML.T0024",),
        nist=("MEASURE 2.7",),
    )


def _run(*findings: Finding, run_id: str = "run-1") -> RunResult:
    moment = datetime(2026, 5, 18, 12, 30, tzinfo=UTC)
    return RunResult(
        run_id=run_id,
        scenario_hash="scenario-hash",
        manifest_hash="manifest-hash",
        started_at=moment,
        finished_at=moment,
        findings=tuple(findings),
        metrics=RunMetrics(),
        # A real run always records which probes ran and what they ran against;
        # the control mappings are gated on that evidence (a live surface), so a
        # fixture without it would assert nothing.
        probe_versions={"tenant-boundary-fetch": "0.7.1"},
        surface_provenance={"vector_db": "LIVE"},
    )


def _doc(run: RunResult) -> dict[str, Any]:
    result: dict[str, Any] = run_to_oscal(run)["assessment-results"]
    return result


def test_emits_a_valid_assessment_results_envelope() -> None:
    doc = run_to_oscal(_run(_finding("f-1")), tool_version="9.9.9")
    assert OSCAL_VERSION == "1.1.2"
    ar = doc["assessment-results"]
    # Top-level required fields of an OSCAL assessment-results document:
    # uuid, metadata, import-ap, results are ALL required by the schema.
    assert UUID(ar["uuid"])  # parseable UUID
    assert ar["import-ap"]["href"]  # import-ap is required, with an href
    metadata = ar["metadata"]
    assert metadata["oscal-version"] == "1.1.2"
    assert metadata["version"] == "9.9.9"
    assert metadata["last-modified"] == "2026-05-18T12:30:00+00:00"
    assert "run-1" in metadata["title"]
    # Exactly one results entry, carrying the required result fields
    # (reviewed-controls is required on every OSCAL result).
    (result,) = ar["results"]
    for key in (
        "uuid",
        "title",
        "description",
        "start",
        "reviewed-controls",
        "observations",
        "findings",
    ):
        assert key in result, key
    assert result["start"] == "2026-05-18T12:30:00+00:00"
    # reviewed-controls names the controls the assessment spoke to.
    selections = result["reviewed-controls"]["control-selections"]
    reviewed = {c["control-id"] for sel in selections for c in sel.get("include-controls", [])}
    assert "CC6.1" in reviewed  # the controls from control_mappings() are listed


def test_coverage_disclaimer_is_embedded_in_metadata_remarks() -> None:
    # The OSCAL consumer must see the same caveat the audit PDF carries: the
    # mappings are test-coverage assertions, not legal certification.
    metadata = _doc(_run(_finding("f-1")))["metadata"]
    assert metadata["remarks"] == COVERAGE_DISCLAIMER


def test_one_observation_per_finding_with_marker_grounded_evidence() -> None:
    findings = (_finding("f-1"), _finding("f-2", probe_id="tenant-boundary-fetch"))
    (result,) = _doc(_run(*findings))["results"]
    observations = result["observations"]
    assert len(observations) == 2
    first = observations[0]
    # An observation records that Sectum TESTED and what it saw.
    assert first["methods"] == ["TEST"]
    assert "canary surfaced in the wrong tenant" in first["description"]
    # The Sectum finding id is carried so the OSCAL evidence is traceable back to
    # the signed evidence.json record.
    props = {(p["name"], p["value"]) for p in first["props"]}
    assert ("sectum-finding-id", "f-1") in props
    assert ("sectum-surface", "vector_db") in props
    assert ("sectum-status", "confirmed") in props


def test_findings_cover_every_mapped_control_and_link_observations() -> None:
    (result,) = _doc(_run(_finding("f-1")))["results"]
    findings = result["findings"]
    # One OSCAL finding per (framework, control id) the RUN's evidence supports.
    expected = sum(len(m.control_ids) for m in control_mappings(_run(_finding("f-1"))))
    assert len(findings) == expected
    target_ids = {f["target"]["target-id"] for f in findings}
    assert "CC6.1" in target_ids  # SOC 2
    assert "Article 25" in target_ids  # GDPR isolation
    # The deletion controls are NOT asserted: this run carries no erasure evidence.
    assert "Article 17" not in target_ids
    assert "1798.105" not in target_ids
    # Every control finding links back to the lone observation.
    observation_uuid = result["observations"][0]["uuid"]
    for finding in findings:
        linked = {ref["observation-uuid"] for ref in finding["related-observations"]}
        assert observation_uuid in linked
        assert finding["target"]["type"] == "objective-id"


def test_confirmed_leak_marks_controls_not_satisfied() -> None:
    (result,) = _doc(_run(_finding("f-1", status=FindingStatus.CONFIRMED)))["results"]
    states = {f["target"]["status"]["state"] for f in result["findings"]}
    assert states == {"not-satisfied"}


def test_unverified_candidate_does_not_flip_a_control_to_failed() -> None:
    # An UNVERIFIED Sectum candidate is recorded as evidence (an observation) but
    # must never on its own present as a confirmed control failure - the
    # anti-over-claim guarantee.
    (result,) = _doc(_run(_finding("f-1", status=FindingStatus.UNVERIFIED)))["results"]
    # The candidate is still observed (evidence is not lost)...
    props = {(p["name"], p["value"]) for p in result["observations"][0]["props"]}
    assert ("sectum-status", "unverified") in props
    # ...but every control reads satisfied because nothing was *confirmed*.
    states = {f["target"]["status"]["state"] for f in result["findings"]}
    assert states == {"satisfied"}


def test_zero_findings_run_is_a_valid_tested_clean_attestation() -> None:
    # A run with no confirmed leaks must be a valid AR reading "tested, no
    # confirmed cross-tenant leakage", not an empty/ambiguous document.
    (result,) = _doc(_run())["results"]
    assert result["observations"] == []
    # Controls are still present (the run tested them) and read satisfied.
    assert len(result["findings"]) == sum(len(m.control_ids) for m in control_mappings(_run()))
    states = {f["target"]["status"]["state"] for f in result["findings"]}
    assert states == {"satisfied"}
    assert "no cross-principal leakage was confirmed" in result["description"].lower()


def test_uuids_are_deterministic_from_run_id_not_random() -> None:
    # Same run -> byte-identical document (no uuid4); different run id -> different
    # document uuid. Determinism is required by the reproducibility contract.
    first = run_to_oscal(_run(_finding("f-1")), tool_version="1.0.0")
    again = run_to_oscal(_run(_finding("f-1")), tool_version="1.0.0")
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)
    other = run_to_oscal(_run(_finding("f-1"), run_id="run-2"), tool_version="1.0.0")
    assert other["assessment-results"]["uuid"] != first["assessment-results"]["uuid"]


def test_document_is_json_serialisable() -> None:
    # The CLI dispatch json.dumps() the document; a stray datetime would break it.
    doc = run_to_oscal(_run(_finding("f-1")), tool_version="1.0.0")
    reloaded = json.loads(json.dumps(doc))
    assert reloaded["assessment-results"]["metadata"]["oscal-version"] == "1.1.2"


def test_a_synthetic_only_run_states_no_control_finding() -> None:
    # Every control rendered `satisfied` for a run whose every surface was the
    # built-in fake - a production result a demo cannot support. The observations
    # still ship; the control findings do not, and the result says why. A run
    # with NO provenance block is the same case, not "not synthetic".
    for provenance in ({"vector_db": "SYNTHETIC"}, {}):
        run = _run().model_copy(update={"surface_provenance": provenance})
        result = run_to_oscal(run)["assessment-results"]["results"][0]
        assert result["findings"] == [], provenance
        assert "no control objective was assessed" in result["description"]
    live = _run().model_copy(update={"surface_provenance": {"vector_db": "LIVE"}})
    assert run_to_oscal(live)["assessment-results"]["results"][0]["findings"]


def test_a_confirmed_leak_on_a_fake_surface_moves_no_control() -> None:
    # On a mixed run a confirmed finding from the semantic-cache FAKE flipped all
    # twenty control findings to not-satisfied - the finding `score` says
    # "describes that fake, not your stack".
    fake_leak = _finding("f").model_copy(update={"surface": Surface.SEMANTIC_CACHE})
    run = _run(fake_leak).model_copy(
        update={"surface_provenance": {"vector_db": "LIVE", "semantic_cache": "SYNTHETIC"}}
    )
    result = run_to_oscal(run)["assessment-results"]["results"][0]
    assert result["findings"]
    assert {f["target"]["status"]["state"] for f in result["findings"]} == {"satisfied"}
    assert "excluded from every control verdict: semantic_cache" in result["description"]
    # the same finding on the live surface does move them
    live_leak = _finding("f")
    moved = run_to_oscal(_run(live_leak))["assessment-results"]["results"][0]
    assert {f["target"]["status"]["state"] for f in moved["findings"]} == {"not-satisfied"}


def test_a_residual_after_erasure_is_not_a_cross_tenant_leak() -> None:
    # A live erasure run with residual markers said "confirmed at least one
    # manifest-grounded cross-tenant leak; the tested isolation objective is not
    # satisfied" under a title of "tenant isolation" - for GDPR Article 17.
    residual = _finding("r", probe_id="gdpr-erasure-verification").model_copy(
        update={"observed_in_tenant_id": _OWNER}
    )
    run = _run(residual).model_copy(
        update={
            "probe_versions": {"gdpr-erasure-verification": "1"},
            "metrics": RunMetrics(erasure_coverage={"vector_db": "RESIDUAL"}),
        }
    )
    result = run_to_oscal(run)["assessment-results"]["results"][0]
    titles = {f["title"] for f in result["findings"]}
    assert titles == {
        "GDPR Article 17 — erasure verification",
        "CCPA/CPRA 1798.105 — erasure verification",
    }
    verdicts = {f["target"]["description"] for f in result["findings"]}
    assert all("markers remaining" in v and "cross" not in v for v in verdicts)
    assert {f["target"]["status"]["state"] for f in result["findings"]} == {"not-satisfied"}
    assert "presumed retained, on vector_db" in result["description"]


def test_metadata_carries_the_surface_provenance() -> None:
    run = _run().model_copy(update={"surface_provenance": {"vector_db": "LIVE"}})
    props = run_to_oscal(run)["assessment-results"]["metadata"]["props"]
    assert ("sectum-surface-provenance-vector_db", "LIVE") in {
        (p["name"], p["value"]) for p in props
    }


def test_observations_label_a_residual_finding_as_such() -> None:
    residual = _finding("r").model_copy(update={"observed_in_tenant_id": _OWNER})
    observation = run_to_oscal(_run(residual))["assessment-results"]["results"][0]["observations"][
        0
    ]
    assert "residual-data finding" in observation["description"]
    assert "cross-tenant" not in observation["description"]


def test_a_caveat_surface_does_not_verify_the_erasure() -> None:
    # The erasure verdict counted CONFIRMED findings only; a caveat surface (no
    # per-tenant erasure API, data presumed retained) emits UNVERIFIED ones, so
    # "verified the erasure on every live surface" rendered over three markers
    # presumed retained, and the result carried the isolation narrative.
    run = _run().model_copy(
        update={
            "probe_versions": {"gdpr-erasure-verification": "1"},
            "surface_provenance": {"vector_db": "LIVE", "backup": "LIVE"},
            "metrics": RunMetrics(
                erasure_coverage={"vector_db": "ERASED", "backup": "ATTESTABLE_WITH_CAVEAT"},
                erasure_caveats={"backup": 3},
            ),
        }
    )
    result = run_to_oscal(run)["assessment-results"]["results"][0]
    assert {f["target"]["status"]["state"] for f in result["findings"]} == {"not-satisfied"}
    assert all("presumed retained" in f["target"]["description"] for f in result["findings"])
    assert "scanned an erasure" in result["description"]
    assert "verified an erasure" not in result["description"]
    assert "presumed retained, on backup" in result["description"]
    assert "cross-principal" not in result["description"]


def test_a_control_about_the_vector_surface_needs_a_live_vector_surface() -> None:
    # The OWASP LLM08 row ("vector and embedding weaknesses") was asserted on a
    # run whose only live surface was MCP and whose vector store was the leaking
    # fake - twenty satisfied controls over 213 findings the scorecard withholds.
    run = _run().model_copy(
        update={
            "probe_versions": {"tenant-boundary-fetch": "1", "agent-tool-hijack": "1"},
            "surface_provenance": {"vector_db": "SYNTHETIC", "mcp": "LIVE"},
        }
    )
    findings = run_to_oscal(run)["assessment-results"]["results"][0]["findings"]
    titles = {f["title"] for f in findings}
    assert not any("LLM08" in t for t in titles), titles
    assert titles, "the generic rows still speak for the live MCP surface"
    assert all("Live surfaces: mcp." in f["description"] for f in findings)


def test_a_kv_cache_finding_counts_against_the_live_model_adapter() -> None:
    # KV-cache findings name the cache surface while provenance is keyed by the
    # model adapter that ran, so every live-surface gate dropped them: OSCAL said
    # `satisfied` over twelve confirmed side channels on the only live surface.
    kv = _finding("kv", probe_id="kv-cache-timing").model_copy(update={"surface": Surface.KV_CACHE})
    run = _run(kv).model_copy(
        update={
            "probe_versions": {"kv-cache-timing": "1"},
            "surface_provenance": {"model_adapter": "LIVE"},
        }
    )
    result = run_to_oscal(run)["assessment-results"]["results"][0]
    assert result["findings"]
    assert {f["target"]["status"]["state"] for f in result["findings"]} == {"not-satisfied"}


def test_the_live_surface_suffix_and_the_erasure_verdict_agree() -> None:
    # The "Live surfaces:" suffix kept ERASED/RESIDUAL surfaces while the verdict
    # kept caveat surfaces too, so one description named a surface its own
    # verdict then contradicted.
    run = _run().model_copy(
        update={
            "probe_versions": {"gdpr-erasure-verification": "1"},
            "surface_provenance": {"vector_db": "LIVE", "tracing": "LIVE"},
            "metrics": RunMetrics(
                erasure_coverage={"vector_db": "ERASED", "tracing": "ATTESTABLE_WITH_CAVEAT"}
            ),
        }
    )
    finding = run_to_oscal(run)["assessment-results"]["results"][0]["findings"][0]
    assert "Live surfaces: tracing, vector_db." in finding["description"]
    assert "presumed retained, after the erasure on tracing" in finding["target"]["description"]


def test_every_observation_says_which_stack_it_describes() -> None:
    # OSCAL states provenance once for the run and gates its CONTROL findings on
    # it, but a GRC platform tabulates the observations - and a row from the
    # built-in fake tabulated identically to one from production. The SARIF
    # projection carries it per result for the same reason.
    doc = _doc(
        _run(_finding("f-1")).model_copy(update={"surface_provenance": {"vector_db": "SYNTHETIC"}})
    )
    observation = doc["results"][0]["observations"][0]
    props = {p["name"]: p["value"] for p in observation["props"]}
    assert props["sectum-surface-provenance"] == "SYNTHETIC"
    assert props["sectum-backing-surface"] == "vector_db"
    assert observation["description"].startswith("[synthetic surface")

    live = _doc(
        _run(_finding("f-1")).model_copy(update={"surface_provenance": {"vector_db": "LIVE"}})
    )
    live_observation = live["results"][0]["observations"][0]
    live_props = {p["name"]: p["value"] for p in live_observation["props"]}
    assert live_props["sectum-surface-provenance"] == "LIVE"
    assert not live_observation["description"].startswith("[synthetic surface")

    # A surface the record does not describe reads UNRECORDED, not SYNTHETIC.
    unstated = _doc(_run(_finding("f-1")).model_copy(update={"surface_provenance": {}}))
    unstated_props = {
        p["name"]: p["value"] for p in unstated["results"][0]["observations"][0]["props"]
    }
    assert unstated_props["sectum-surface-provenance"] == "UNRECORDED"


def test_an_unrecorded_surface_observation_is_not_told_it_describes_a_fake() -> None:
    # Same two-valued prose beside a three-valued property, in the projection a
    # GRC platform tabulates.
    doc = _doc(_run(_finding("f-1")).model_copy(update={"surface_provenance": {}}))
    description = doc["results"][0]["observations"][0]["description"]
    assert description.startswith("[surface provenance not recorded"), description
    assert "built-in fake" not in description
