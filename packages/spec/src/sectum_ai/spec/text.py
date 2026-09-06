"""Strings that came out of the record under scrutiny: rendering them, and matching them.

Both halves exist because the text Sectum handles is adversarial. :func:`untrusted`
renders a hostile string without letting it forge our output; :func:`residual_present`
decides whether a canary is *still there* in text a backend controls, and is shared
so that no two code paths can answer that question differently.
"""

import unicodedata


def untrusted(text: str) -> str:
    """Neutralize control characters in a string the graded record controls.

    Sectum's whole purpose is to report on a record it does not trust, so every string
    the record carries - ``run_id``, probe ids, finding ids, baseline entry names - is
    hostile input the moment it reaches our output. Rendered raw, a newline forges whole
    lines of Sectum's own reporting (a second, passing scorecard under the real one; an
    ``[ok]`` anchor line inside ``verify``), and an ANSI escape rewrites the reader's
    terminal.

    Escapes rather than strips, so tampering is visible instead of silently vanishing,
    and injectively (``\\xNN`` under U+0100, ``\\uNNNN`` at or above it, and ``\\`` for a
    literal backslash), so the escaped form names exactly one input: without the backslash
    rule a ``run_id`` containing the *text* ``\\x0a`` would render identically to one
    containing a real newline, letting the record spoof our own escaping.

    ``str.isprintable()`` is the right test, and deliberately wider than the C0 controls:
    it is false for Cc, Cf (bidi overrides and zero-width joiners), Cs, Co, Cn, Zl, Zp and
    non-space Zs - every class that can open a line or drive a terminal. That width is
    load-bearing, not incidental. ``U+2028``/``U+2029`` open a line under
    :meth:`str.splitlines`, and ``U+009B`` is the single-character C1 form of ``ESC[``, so
    an ASCII-range or C0-only predicate would reinstate the forgery while every C0 test
    stayed green. Combining marks and homoglyphs do pass through, which is correct: they
    mislead a human reading a name, but cannot forge structure in our output.
    """
    return "".join(
        "\\\\" if char == "\\" else char if char.isprintable() else _escape(char) for char in text
    )


def _escape(char: str) -> str:
    """One escape per non-printable character, injectively.

    ``:04x`` is a MINIMUM width, so an astral codepoint emitted five hex digits
    and collided with a BMP escape followed by a digit (U+E0001 and U+E000 then
    "1" both rendered ``\\ue0001``) - the injectivity this module argues for.
    """
    code = ord(char)
    if code < 0x100:
        return f"\\x{code:02x}"
    if code < 0x10000:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"


def _strip_format_chars(text: str) -> str:
    """Drop Unicode format characters (category ``Cf``): zero-width spaces/joiners.

    A leaked canary split with a zero-width character (``SEC​tum-...``) reads
    identically to a human but evades a raw substring test; removing format
    characters before matching closes that evasion.
    """
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def normalize_for_match(text: str) -> str:
    """Case-, width-, and zero-width-insensitive form for canary substring matching.

    A backend that re-cased, NFKC-normalized (e.g. full-width), or zero-width-split
    a canary would slip past a raw ``in`` test; normalizing the needle and the
    haystack the same way before matching catches it. Used only to decide *whether*
    a canary is present - the original text and the canonical canary are what the
    evidence pack quotes.
    """
    return unicodedata.normalize("NFKC", _strip_format_chars(text)).casefold()


def residual_present(needle: str, haystack: str) -> bool:
    """Whether ``needle`` still appears in ``haystack``, normalization-insensitively.

    THE single answer to "is this canary still there", deliberately shared between
    the probes that count residue and the adapters that decide whether a truncated
    listing needs refusing. Two predicates for one question is a fail-open: the
    erasure scans tested a raw case-sensitive ``in`` while the adapter guarding
    them suppressed its cap refusal on a casefolded hit, so a marker the adapter
    had seen but the scan would not count read as absent - and a surface still
    holding a re-cased copy of the canary was signed ERASED.

    An empty ``needle`` is never present: an empty-plaintext marker would otherwise
    substring-match every observation and confirm a leak on all of them.
    """
    return bool(needle) and normalize_for_match(needle) in normalize_for_match(haystack)
