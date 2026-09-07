"""The machine-readable modes emit a document on stdout and nothing else.

`sectum-ai <cmd> --output json > report.json` has to parse, however noisy the run
was. Two warnings on the `probe` path omitted `err=True`, so the JSON report began

    warning: fake-deterministic excluded from the embedding-model gradient ...
    warning: no embedding-model gradient recorded ...
    {

and `jq` read nothing from it. That is the shipped GitHub Action's own pipeline:
`action.yml` redirects `probe`'s stdout into the report file and reads
`confirmed-findings`, `confirmed-on-live-surfaces` and `retrieval-pivot-rate` out
of it, so all three outputs went empty and the step summary printed "unknown" for
a run that confirmed findings - while the gate step's own emptiness guard passed,
because the file was not empty.

Two tests, deliberately: one drives the CLI end to end, and one sweeps the module
so a warning added tomorrow on a path no test exercises cannot reinstate it.
"""

import ast
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sectum_ai.cli import app as app_module
from sectum_ai.cli.app import app

_runner = CliRunner()
_SOURCE = Path(app_module.__file__)


def test_every_cli_warning_is_written_to_stderr() -> None:
    source = _SOURCE.read_text()
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "echo"
        ):
            continue
        text = ast.get_source_segment(source, node) or ""
        if "warning:" in text and not any(keyword.arg == "err" for keyword in node.keywords):
            offenders.append(f"{_SOURCE.name}:{node.lineno}")
    assert not offenders, f"warning(s) written to stdout: {offenders}"


@pytest.mark.parametrize("output", ["json", "sarif", "oscal"])
def test_a_probe_report_parses_even_when_the_run_warns(tmp_path: Path, output: str) -> None:
    # Two real warnings fire here: one embedding model is modelled-only and so is
    # excluded from the gradient, and the one that remains is not a gradient. Both
    # used to land in the document.
    seeded = _runner.invoke(
        app,
        [
            "seed",
            "--workdir",
            str(tmp_path),
            "--embedding-model",
            "hash-64",
            "--embedding-model",
            "fake-deterministic",
        ],
    )
    assert seeded.exit_code == 0, seeded.output

    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", output])
    assert result.exit_code == 2, result.output
    assert "warning:" in result.stderr, result.stderr
    assert "warning:" not in result.stdout, result.stdout
    # Parses, and is the report - not a fragment that happens to be valid JSON.
    payload = json.loads(result.stdout)
    assert payload, result.stdout
