"""Structured logging for Sectum AI (the engineering spec, section 16).

Sectum is a security product, so its logs must never leak secrets or raw tenant
content. This module configures :mod:`structlog` so that:

- logs render as JSON (machine-readable, SIEM-friendly) to **stderr** — stdout is
  reserved for a command's own output (for example ``probe --output json``);
- ``DEBUG`` is suppressed by default (section 16: "DEBUG must be off by default");
- a redaction processor drops secret-bearing keys and raw tenant content from
  every event emitted above ``DEBUG``.

Libraries obtain a logger with :func:`get_logger` and never configure logging
themselves; the application entry point (the CLI) calls :func:`configure_logging`
once at start-up. The test suite configures it through a fixture so output is
deterministic and stdout stays clean.
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.types import EventDict, FilteringBoundLogger, Processor, WrappedLogger

# Keys whose values are secrets or canary plaintext: never emitted above DEBUG.
_SECRET_KEYS = frozenset(
    {
        "secret",
        "token",
        "password",
        "passphrase",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "plaintext",
        "canary",
        "marker_plaintext",
    }
)
# Keys carrying raw tenant content: never emitted above DEBUG (section 16).
_TENANT_CONTENT_KEYS = frozenset(
    {"content", "raw_response", "answer", "query", "prompt", "text", "evidence_span"}
)
_SENSITIVE_KEYS = _SECRET_KEYS | _TENANT_CONTENT_KEYS
_REDACTED = "<redacted>"


def redact_sensitive(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Drop secret-bearing keys and raw tenant content from non-DEBUG events.

    DEBUG is opt-in and off by default, so verbose local troubleshooting may see
    raw values; everything at INFO and above is redacted (the engineering spec,
    section 16: "never log secrets or raw tenant content above DEBUG"). Requires
    ``add_log_level`` to run first so ``level`` is present in the event dict.
    """
    if event_dict.get("level") == "debug":
        return event_dict
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(*, debug: bool = False, json_output: bool = True) -> None:
    """Configure process-wide structured logging. Call once, from the entry point.

    ``debug`` enables DEBUG-level events (off by default, per section 16);
    ``json_output`` selects the JSON renderer (the default) over a plain console
    renderer. Logs are always written to stderr so stdout stays reserved for a
    command's own output.
    """
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return a structured logger; the binding name is by convention ``__name__``."""
    # structlog.get_logger is typed -> Any (it returns a lazy proxy); the bound
    # logger is a FilteringBoundLogger once configure_logging has run.
    return cast(FilteringBoundLogger, structlog.get_logger(name))
