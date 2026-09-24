"""The composite action's CLI invocations still exist in the CLI.

`action.yml` shells out to `sectum-ai seed` and `sectum-ai probe` with a fixed
set of flags, and to a fixed set of `--output` values. Nothing tied any of that
to the Typer app: the self-test workflow that would catch a break runs only when
`action.yml` itself changes (`paths:` filter), so a PR that renamed a CLI flag
would go green and ship an action that fails on the user's first run - the same
shape as the version drift `test_action_version.py` exists to stop.
"""

import re
from pathlib import Path

import yaml
from typer.main import get_command

from sectum_ai.cli.app import app

_ROOT = Path(__file__).resolve().parents[2]


def _action_shell() -> str:
    steps = yaml.safe_load((_ROOT / "action.yml").read_text())["runs"]["steps"]
    return "\n".join(str(step.get("run", "")) for step in steps)


def _options(command_name: str) -> set[str]:
    command = get_command(app).commands[command_name]  # type: ignore[attr-defined]
    names: set[str] = set()
    for param in command.params:
        names.update(opt for opt in getattr(param, "opts", []) if opt.startswith("--"))
    return names


def test_every_flag_the_action_passes_exists_on_its_command() -> None:
    shell = _action_shell()
    for command_name in ("seed", "probe"):
        # `args=(--workdir "..." --output "...")` and `args+=(--config "...")`
        block = re.findall(rf"args[+]?=\(([^)]*)\)(?=[\s\S]*?sectum-ai {command_name})", shell)
        flags = {flag for chunk in block for flag in re.findall(r"--[a-z][a-z-]*", chunk)}
        assert flags, f"no flags parsed for `sectum-ai {command_name}` in action.yml"
        missing = flags - _options(command_name)
        assert not missing, (
            f"action.yml passes {sorted(missing)} to `sectum-ai {command_name}`, which the "
            "CLI does not define; the action would fail on the user's first run"
        )


def test_the_output_formats_the_action_accepts_are_the_cli_s() -> None:
    # action.yml validates `output` up front so an invalid value is a clear error
    # rather than colliding with the probe's exit 2. That allow-list is a second
    # copy of the CLI's OutputFormat enum.
    from sectum_ai.cli.app import OutputFormat

    shell = _action_shell()
    match = re.search(r"^\s*(text\|[a-z|]+)\)\s*;;", shell, re.MULTILINE)
    assert match is not None, "action.yml has no `text|...)` output allow-list"
    assert set(match.group(1).split("|")) == {member.value for member in OutputFormat}


def test_the_commands_the_action_runs_exist() -> None:
    shell = _action_shell()
    # Only invocations at the start of a line (prose in an ::error:: message
    # mentions the CLI too).
    invoked = set(re.findall(r"^\s*sectum-ai ([a-z][a-z-]*)", shell, re.MULTILINE))
    known = set(get_command(app).commands)  # type: ignore[attr-defined]
    assert invoked, "no `sectum-ai <command>` invocation found in action.yml"
    assert invoked <= known, f"action.yml runs unknown commands: {sorted(invoked - known)}"


def test_every_json_path_the_action_reads_is_a_key_of_the_probe_report() -> None:
    # `action.yml` derives three of its outputs with `jq -r '.<field>'` over the
    # probe's JSON report. The only job that asserts those outputs installs from
    # PyPI (`action-selftest.yml`: "install the latest published sectum-ai"), and
    # the one job that runs THIS checkout's CLI asserts only the exit code and
    # that the report is non-empty - so renaming a report field in a PR shipped an
    # action whose outputs are all empty strings, silently, on the user's first
    # run. `jq` on a missing key emits `null`, and the `// ""` fallback beside it
    # turns that into an empty output rather than an error.
    from sectum_ai.spec import RunMetrics

    paths = set(re.findall(r"jq -r '\.([a-z_]+)", _action_shell()))
    assert paths, "the action no longer reads any JSON path - update this test"
    # The probe report is the metrics block plus the two live-surface counts the
    # CLI adds; both are optional in the JSON, so membership is what matters.
    report_keys = set(RunMetrics.model_fields) | {"confirmed_on_live_surfaces"}
    assert paths <= report_keys, f"not keys of the probe report: {sorted(paths - report_keys)}"
