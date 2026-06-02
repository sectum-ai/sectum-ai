"""Shared pytest fixtures for the Sectum AI test suite."""

import pytest
import structlog

from sectum.spec import configure_logging


@pytest.fixture(autouse=True)
def _configure_logging() -> None:
    """Give every test deterministic structured logging.

    structlog's *unconfigured* default writes to stdout, which would corrupt the
    tests that assert on a command's stdout (for example ``probe --output json``).
    Resetting first guarantees isolation if a test reconfigures logging itself;
    INFO level keeps DEBUG-only raw content out of captured output.
    """
    structlog.reset_defaults()
    configure_logging(debug=False, json_output=True)
