"""Rendering strings that came out of the record under scrutiny."""


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
        "\\\\"
        if char == "\\"
        else char
        if char.isprintable()
        else (f"\\x{ord(char):02x}" if ord(char) < 0x100 else f"\\u{ord(char):04x}")
        for char in text
    )
