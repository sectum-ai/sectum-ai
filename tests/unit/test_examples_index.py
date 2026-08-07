"""Standing guard: the examples index matches the examples on disk.

Enumeration drift is this repo's recurring documentation failure. Adding an example (or
a class, or a CLI command) silently falsifies every page that enumerates them, and the
stale page contains no string anyone would think to grep for - so the drift is invisible
until a reader follows the index and finds a gap. Nothing compared ``examples/README.md``
to the directory, and Class 13's demo duly shipped unlisted while the CHANGELOG and
``docs/skus.md`` pointed readers straight at it.
"""

import re
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def _listed() -> set[str]:
    readme = (_EXAMPLES_DIR / "README.md").read_text(encoding="utf-8")
    return set(re.findall(r"\[`([a-z0-9-]+)/`\]", readme))


def _on_disk() -> set[str]:
    return {
        path.name
        for path in _EXAMPLES_DIR.iterdir()
        if path.is_dir() and not path.name.startswith((".", "__"))
    }


def test_the_examples_index_lists_every_example() -> None:
    listed, on_disk = _listed(), _on_disk()
    assert not on_disk - listed, f"examples/README.md never lists: {sorted(on_disk - listed)}"
    assert not listed - on_disk, f"examples/README.md lists absent: {sorted(listed - on_disk)}"


# The runner's shape varies, and the index says so: most examples ship a top-level
# run.sh, the two analytical sweeps ship run.py, and open-webui-run drives a Docker
# stack from scripts/run.sh. An example with no single entry point at all - an operator
# workflow its README walks through - goes in _WITHOUT_A_RUNNER; none currently do.
_RUNNERS = ("run.sh", "run.py", "scripts/run.sh")
_WITHOUT_A_RUNNER: set[str] = set()


def test_every_example_ships_a_readme_and_a_runner() -> None:
    for name in sorted(_on_disk()):
        example = _EXAMPLES_DIR / name
        assert (example / "README.md").exists(), f"{name} has no README.md"
        if name in _WITHOUT_A_RUNNER:
            continue
        assert any((example / runner).exists() for runner in _RUNNERS), (
            f"{name} ships no runner ({', '.join(_RUNNERS)})"
        )
