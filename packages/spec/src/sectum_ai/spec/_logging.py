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
import re
import sys
from typing import TextIO, cast

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
# Exact membership missed every key that CONTAINS a secret word - `secret_key`,
# `tsa_token`, `db_dsn`, `application_key` - while the config redactor, which
# answers the same question about the same shapes, matched them by a word
# boundary. Two redactors disagreeing about what a secret is means one of them is
# wrong; this is the config redactor's rule, so the answer no longer depends on
# which path the value took. (Tenant-content keys stay exact: they are specific
# field names, not a family of spellings.)
SECRET_KEY_RE = re.compile(
    r"(?:api_?key|dsn|password|passphrase|token|secret|credential|credentials"
    r"|application_key|authorization)"
    r"(?![A-Za-z0-9])"
)
_REDACTED = "<redacted>"


def _is_sensitive_key(name: str) -> bool:
    lowered = name.lower()
    if lowered in _SENSITIVE_KEYS:
        return True
    # `*_env` names an environment VARIABLE, not the secret itself.
    return not lowered.endswith("_env") and SECRET_KEY_RE.search(lowered) is not None


# Canary/secret value shapes, scrubbed wherever they appear (nested under a benign
# key, inside the event message, or in an exception's text) so a future careless
# call site cannot leak one even without using a sensitive key name. The shapes
# mirror ``sectum_ai.substrate.markers``: the HARD canary's branded prefix and the
# three secret-canary credential formats. Entity canaries are ordinary-looking
# text, so they are covered by the key-name pass (``plaintext``/``canary``/…), not
# value-scrubbed, to avoid false positives on legitimate prose. The ``sk-``/``AKIA``
# shapes are anchored at a non-alphanumeric boundary so they match a standalone
# token, not a substring of a benign identifier (``task-``/``disk-`` + a long id,
# ``…AKIA…`` mid-word); an underscore still counts as a boundary so ``api_sk-…``
# is caught.
_SECRET_VALUE_RE = re.compile(
    r"SECTUM-CANARY-[A-Z2-7]+"  # HARD canary (branded high-entropy token)
    r"|(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,}"  # OpenAI-style API key
    r"|(?<![A-Za-z0-9])AKIA[A-Z0-9]{16}"  # AWS access-key id
    r"|\b9\d{2}-\d{2}-\d{4}\b"  # non-issuable 9xx US SSN shape
)


def _scrub_text(text: str) -> str:
    """Replace any embedded canary/secret-shaped token with the redaction marker."""
    return _SECRET_VALUE_RE.sub(_REDACTED, text)


def _redact_value(value: object) -> object:
    """Recursively redact sensitive keys and scrub secret-shaped strings.

    Walks nested mappings/sequences so a sensitive key or a secret-shaped value is
    caught at any depth, not just at the top level. A sensitive key is dropped
    wholesale; strings (including the event message) and the text of exception
    values are scrubbed for embedded secret shapes. Other scalars pass through.
    """
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED if isinstance(key, str) and _is_sensitive_key(key) else _redact_value(val)
            )
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, BaseException):
        return _scrub_text(f"{type(value).__name__}: {value}")
    return value


def redact_sensitive(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Drop secret-bearing keys and raw tenant content from non-DEBUG events.

    DEBUG is opt-in and off by default, so verbose local troubleshooting may see
    raw values; everything at INFO and above is redacted (the engineering spec,
    section 16: "never log secrets or raw tenant content above DEBUG"). Requires
    ``add_log_level`` to run first so ``level`` is present in the event dict.

    Redaction is recursive and value-aware (defense in depth): a sensitive key is
    dropped at any nesting depth, and a canary/secret-shaped token is scrubbed
    wherever it appears — nested under a benign key, embedded in the event
    message, or carried in an exception's text — so a careless call site cannot
    leak one. Today every production call site logs only operational metadata
    (IDs, counts, model names, digests); this is the backstop for the future.
    """
    if event_dict.get("level") == "debug":
        return event_dict
    return cast(EventDict, _redact_value(event_dict))


class _LiveStderr:
    """A ``sys.stderr`` proxy that resolves the stream at write time.

    structlog's ``PrintLogger`` (with ``cache_logger_on_first_use``) binds its
    output stream once, so capturing ``sys.stderr`` directly pins the cached logger
    to one object. A Typer/Click ``CliRunner`` (typer >= 0.26) swaps and then closes
    the ``sys.stderr`` it captured between in-process invocations, so the next log
    on the pinned stream raises ``ValueError: I/O operation on closed file``.
    Forwarding to the current ``sys.stderr`` on every call keeps logging robust to
    that without giving up logger caching. No production path closes stderr; this
    just makes the test harness (and any embedder of the CLI) safe.
    """

    def write(self, message: str) -> int:
        return sys.stderr.write(message)

    def flush(self) -> None:
        sys.stderr.flush()


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
        logger_factory=structlog.PrintLoggerFactory(file=cast(TextIO, _LiveStderr())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return a structured logger; the binding name is by convention ``__name__``."""
    # structlog.get_logger is typed -> Any (it returns a lazy proxy); the bound
    # logger is a FilteringBoundLogger once configure_logging has run.
    return cast(FilteringBoundLogger, structlog.get_logger(name))
