"""End-to-end tests that run the example walkthroughs (the engineering spec, section 14).

Opt-in: set ``SECTUM_RUN_E2E=1`` (CI sets it on a dedicated step). Each example's
``run.sh`` seeds a substrate, probes the demo stack, assembles a tamper-evident
evidence pack, and verifies it via the ``sectum`` CLI - so a non-zero exit means
the published demo broke. These shell out to ``uv run sectum`` and are slower
than the in-process CLI tests, hence the opt-in gate.
"""

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("SECTUM_RUN_E2E"),
        reason="set SECTUM_RUN_E2E=1 to run the example walkthroughs",
    ),
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = (
    "retrieval-pivot",
    "erasure-attestation",
    "mcp-tenant-boundary",
    "agent-tool-hijack",
    "memory-contamination",
    "lora-cross-tenant",
    "kv-cache-timing",
)


@pytest.mark.parametrize("example", _EXAMPLES)
def test_example_walkthrough_runs_and_verifies(example: str) -> None:
    run_sh = _REPO_ROOT / "examples" / example / "run.sh"
    result = subprocess.run(
        ["bash", str(run_sh)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]
    out = _REPO_ROOT / "examples" / example / "out"
    assert list(out.glob("*.json")), f"no artifacts written to {out}"


def _sectum(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``uv run sectum <args>`` from ``cwd`` and return the completed process."""
    return subprocess.run(
        ["uv", "run", "--quiet", "--project", str(_REPO_ROOT), "sectum", *args],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        cwd=str(cwd),
    )


def test_tampered_evidence_pack_makes_sectum_verify_exit_4(tmp_path: Path) -> None:
    """Mutating the evidence pack must make ``sectum verify`` exit 4.

    The tamper-evident property is the OSS evidence layer's core promise (the
    engineering spec, §8). The example walkthroughs above only confirm the
    happy path: build → verify PASS. This test closes the loop on the
    failure path: build → mutate → verify FAIL (exit 4).
    """
    # Use the retrieval-pivot scenario - it is the cheapest of the three to
    # set up (no MCP provisioning, no erasure window) and produces a real
    # evidence.json plus an attestation envelope in one go.
    workdir = tmp_path / "out"
    workdir.mkdir()

    seed = _sectum("seed", "--workdir", str(workdir), cwd=tmp_path)
    assert seed.returncode == 0, (seed.stdout + seed.stderr)[-2000:]

    # `sectum probe` exits 2 when it confirms leaks. Tolerate that here -
    # the demo substrate is deliberately leaky and the probe is supposed
    # to detect it, so the non-zero exit IS the success signal at this step.
    probe = _sectum("probe", "--workdir", str(workdir), cwd=tmp_path)
    assert probe.returncode in (0, 2), (probe.stdout + probe.stderr)[-2000:]

    report = _sectum("report", "--workdir", str(workdir), cwd=tmp_path)
    assert report.returncode == 0, (report.stdout + report.stderr)[-2000:]

    pack_path = workdir / "evidence.json"
    assert pack_path.exists(), f"sectum report did not write {pack_path}"

    # Baseline: a freshly built pack verifies (exit 0).
    verify = _sectum("verify", str(pack_path), cwd=tmp_path)
    assert verify.returncode == 0, (verify.stdout + verify.stderr)[-2000:]

    # Mutate the pack: change a single field VALUE inside the canonical run
    # JSON. The pack still validates as an EvidencePack (the schema is
    # unchanged) but the run digest no longer matches what the TSA token
    # attests to; verify must catch the mismatch and exit 4 with a "[FAIL]"
    # line. Mutating a key instead would trip the schema check first and
    # exit 3 (a different failure mode covered elsewhere).
    original = pack_path.read_text(encoding="utf-8")
    tampered = original.replace(
        '"run_id": "run-sectum-demo-2026"',
        '"run_id": "run-sectum-demo-XXXX"',
        1,
    )
    assert tampered != original, "tamper pattern did not match the pack contents"
    pack_path.write_text(tampered, encoding="utf-8")

    verify_tampered = _sectum("verify", str(pack_path), cwd=tmp_path)
    assert verify_tampered.returncode == 4, (
        f"expected exit 4 (verification failure), got {verify_tampered.returncode}\n"
        + (verify_tampered.stdout + verify_tampered.stderr)[-2000:]
    )
    # The CLI's stdout should carry a recognisable failure marker so an
    # operator parsing the output (CI step, audit-pack reviewer) can spot it.
    combined = verify_tampered.stdout + verify_tampered.stderr
    assert "[FAIL]" in combined or "VERIFICATION FAILED" in combined.upper(), combined[-1000:]


def test_sectum_probe_filter_runs_only_the_named_probe(tmp_path: Path) -> None:
    """``sectum probe --probe <id>`` must run only that probe.

    The run.json's per-probe finding counts have a single non-zero entry under
    the named probe, with the others either absent or zero. Catches a class
    of regression where the suite filter silently degrades to "run everything".
    """
    workdir = tmp_path / "out"
    workdir.mkdir()
    seed = _sectum("seed", "--workdir", str(workdir), cwd=tmp_path)
    assert seed.returncode == 0, (seed.stdout + seed.stderr)[-2000:]

    probe = _sectum(
        "probe",
        "--workdir",
        str(workdir),
        "--probe",
        "tenant-boundary-fetch",
        cwd=tmp_path,
    )
    assert probe.returncode in (0, 2), (probe.stdout + probe.stderr)[-2000:]

    run_json = workdir / "run.json"
    assert run_json.exists(), f"sectum probe did not write {run_json}"
    import json

    data = json.loads(run_json.read_text(encoding="utf-8"))
    # The leaky default substrate produces hits for tenant-boundary-fetch on
    # every run; a filtered probe records findings under that probe_id ONLY.
    # We pin the filter via the findings list (each finding carries its
    # probe_id) rather than `probe_versions`: the CLI today only includes
    # probes that ran in `probe_versions`, but a refactor that padded that
    # map (e.g., to record every shipped probe even on a filtered run)
    # would silently defeat a versions-only check. Findings are the ground
    # truth — only probes that actually executed can have produced one.
    finding_probes = {f["probe_id"] for f in data.get("findings", [])}
    assert finding_probes, "the leaky default substrate should have produced findings; got empty"
    other = finding_probes - {"tenant-boundary-fetch"}
    assert not other, f"filter leaked other probes into findings: {other}"
