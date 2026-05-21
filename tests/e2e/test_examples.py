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
_EXAMPLES = ("retrieval-pivot", "erasure-attestation", "mcp-tenant-boundary")


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
