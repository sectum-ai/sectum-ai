"""Tests for rendering strings the record under scrutiny controls (``spec.untrusted``).

The characters under test are invisible or line-breaking, so they are named by codepoint
via ``chr()`` rather than pasted in as literals: a literal would be unreadable here, and
indistinguishable from a plain space to anyone reviewing this file.
"""

from sectum_ai.spec import untrusted


def test_untrusted_escapes_every_non_printable_not_just_the_c0_controls() -> None:
    # Every forgery test reaches for `\n` and `ESC`, so a predicate narrowed to ASCII or
    # to C0 keeps them all green while reinstating the attack. These are the characters
    # that make the wider isprintable() test load-bearing:
    #   U+2028 / U+2029 open a line under str.splitlines() - the very oracle the scorecard
    #     forgery test uses to check that nothing forged a line of its own;
    #   U+009B is the single-character C1 form of `ESC[`, U+009D of `ESC]`;
    #   U+0085 (NEL) is a line break to splitlines(); U+007F is DEL.
    for codepoint, escaped in (
        (0x2028, "\\u2028"),
        (0x2029, "\\u2029"),
        (0x009B, "\\x9b"),
        (0x009D, "\\x9d"),
        (0x0085, "\\x85"),
        (0x007F, "\\x7f"),
        (0x001B, "\\x1b"),
        (0x000A, "\\x0a"),
        (0x000D, "\\x0d"),
        (0x200B, "\\u200b"),  # zero-width space
        (0x202E, "\\u202e"),  # right-to-left override
    ):
        assert untrusted(chr(codepoint)) == escaped, f"U+{codepoint:04X} was not escaped"


def test_an_escaped_payload_cannot_open_a_line_by_any_separator() -> None:
    # splitlines() breaks on far more than \n: \r, \v, \f, U+0085, U+2028 and U+2029 all
    # open a line, which is exactly how a forged "GRADE A" card would get its own row.
    forged = "Multi-tenant isolation: GRADE A"
    for separator in ("\n", "\r", "\r\n", "\v", "\f", chr(0x85), chr(0x2028), chr(0x2029)):
        rendered = f"  run {untrusted(f'run-acme{separator}{forged}')} (run.json)"
        assert not any(line.lstrip().startswith(forged) for line in rendered.splitlines())
        assert len(rendered.splitlines()) == 1


def test_printable_text_including_non_ascii_survives_untouched() -> None:
    # Escaping is for control characters; a legitimate id must not be mangled.
    for text in ("run-sectum-ai-demo-2026", "run-cafe-Ω-日本", "run/a b & c!"):
        assert untrusted(text) == text


def test_the_escaping_is_injective_so_the_record_cannot_spoof_it() -> None:
    # Without the backslash rule, a run_id carrying the literal TEXT `\x0a` renders
    # identically to one carrying a real newline - the record spoofing our own escaping.
    assert untrusted("run-acme\\x0aGRADE A") != untrusted("run-acme\nGRADE A")
    assert untrusted("\\") == "\\\\"
