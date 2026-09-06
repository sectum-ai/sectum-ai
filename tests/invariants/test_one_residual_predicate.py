"""One predicate answers "is this canary still there" - everywhere it is asked.

Two code paths ask that question about the same bytes: the Class 11 scans that
COUNT residue, and the capped-listing adapters that decide whether an incomplete
page needs refusing. When the two disagree, the disagreement is a fail-open in
one specific direction: an adapter whose suppression is LOOSER than the caller's
count says "found it, no need to refuse" over a hit the caller will not count, so
the marker sitting past the cap reads as absent and the surface is signed ERASED.

That is not hypothetical - it shipped. The scans tested a raw case-sensitive
``in`` while the adapters guarding them suppressed on a casefolded hit, and a
search index still returning a re-cased copy of the tenant's canary attested
clean. The fix is not "casefold the scans too": matching the two predicates by
hand is what failed, and a third normalization (zero-width, NFKC) would split
them again. There is one function, and these tests pin that there is one.
"""

from sectum_ai.adapters import fakes
from sectum_ai.adapters.eval_set import langsmith
from sectum_ai.adapters.memory import mem0
from sectum_ai.adapters.observability import datadog, helicone, langfuse, otel, phoenix
from sectum_ai.adapters.observability import langsmith as trace_langsmith
from sectum_ai.adapters.search_index import opensearch
from sectum_ai.probes import _recall
from sectum_ai.probes.erasure import probe as erasure_probe
from sectum_ai.probes.subject_erasure import probe as subject_probe
from sectum_ai.spec import residual_present


def test_every_residual_question_resolves_to_the_same_function() -> None:
    # `is`, not an equality of behaviour: two lookalikes that agree today are
    # exactly what drifted apart before, and only identity survives the next
    # normalization someone adds to one of them.
    # `_recall` is the sixth, and it was missed by the first pass at this: the
    # MODEL surface asks the same question through `content_recalled`, and a
    # canary the model re-rendered read as "not recalled" - ERASED - one commit
    # after the other five were unified. That is why this is a sweep, not a list.
    for module in (
        erasure_probe,
        subject_probe,
        _recall,
        langsmith,
        mem0,
        opensearch,
        # The TRACING family, the seventh through thirteenth: `c99bf33` unified
        # three adapter families and skipped this one, and `_scan_observability`
        # applies no predicate of its own - it trusts the adapter's already
        # filtered list, so the adapter's `in` WAS the residue test.
        helicone,
        datadog,
        langfuse,
        trace_langsmith,
        phoenix,
        otel,
        fakes,
    ):
        assert module.residual_present is residual_present, module.__name__


def test_residual_present_sees_every_rendering_a_backend_can_apply() -> None:
    canary = "SECTUM-CANARY-UURK6HUSUBK7RGQ42MLR2ZMN5U"
    for label, haystack in (
        ("verbatim", f"row mentioning {canary}"),
        ("re-cased", f"row mentioning {canary.lower()}"),
        # U+200B ZERO WIDTH SPACE, U+FF33 FULLWIDTH LATIN CAPITAL S: spelled by
        # codepoint so this file stays ASCII.
        ("zero-width split", f"row mentioning {canary[:6]}\u200b{canary[6:]}"),
        ("full-width", f"row mentioning \uff33{canary[1:]}"),
    ):
        assert residual_present(canary, haystack), label

    assert not residual_present(canary, "a row mentioning nothing of the sort")
    # An empty-plaintext marker would otherwise substring-match every observation
    # and confirm a leak on all of them.
    assert not residual_present("", "any text at all")


def test_no_module_asks_the_residue_question_with_a_raw_substring_test() -> None:
    # The identity check above is a LIST, so it structurally cannot see a sibling
    # that never imported the predicate at all - which is exactly how the tracing
    # family stayed on a raw `in` through the commit that unified the other three,
    # and through twelve review cycles. This is the sweep: it walks the source and
    # fails on any `<marker-ish> in <text>` comparison, whether or not the module
    # has ever heard of `residual_present`.
    import ast
    from pathlib import Path

    # Names that mean "the thing we are looking for" on the left of an `in`.
    needles = {"marker", "needle", "query", "plaintext", "phrase", "canary", "secret"}
    # Membership tests that are NOT the residue question: the right-hand side is
    # already normalized by the shared normalizer, so the comparison is the shared
    # predicate spelled out. Named by VARIABLE, not by file: excluding a whole
    # file would be the same hole this test exists to close, one level up.
    normalized = {"haystack", "shaped"}

    roots = [Path("packages/adapters/src"), Path("packages/probes/src")]
    offenders: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare) or len(node.ops) != 1:
                    continue
                if not isinstance(node.ops[0], ast.In | ast.NotIn):
                    continue
                # `<marker-ish> in <text>`. The left side is a Name (`needle`)
                # OR an Attribute (`marker.plaintext`) - the shape every Class 11
                # scan uses, and the one the first version of this sweep could not
                # see, so it caught the adapter family it was calibrated on and
                # missed all six probe-side residue tests.
                left = node.left
                name = (
                    left.id
                    if isinstance(left, ast.Name)
                    else left.attr
                    if isinstance(left, ast.Attribute)
                    else ""
                )
                if name.lower() in needles:
                    right = node.comparators[0]
                    if isinstance(right, ast.Set | ast.Dict | ast.Tuple | ast.List):
                        continue
                    if isinstance(right, ast.Name) and right.id in normalized:
                        continue
                    offenders.append(f"{path}:{node.lineno}")

    assert not offenders, (
        "these ask 'is this canary still there' with a raw substring test instead of "
        f"`residual_present`, so they will disagree with every other caller: {offenders}"
    )


def test_the_shared_predicate_answers_the_detector_s_question() -> None:
    # The predicate was shared across seven modules and was still WEAKER than the
    # detector it was meant to agree with: `residual_present` tested a substring
    # where every detection tier tests a substring OR the marker's tokens
    # contiguous and in order. So a trace holding a re-punctuated canary was a
    # CONFIRMED CRITICAL leak on one path and absent on the other - and the
    # erasure scan, reading the second, signed "Erasure ... verified" over it.
    canary = "SECTUM-CANARY-UURK6HUSUBK7RGQ42MLR2ZMN5U"
    for label, separator in (
        ("verbatim", "-"),
        ("space", " "),
        # U+2011 NON-BREAKING HYPHEN and U+2013 EN DASH, by codepoint.
        ("non-breaking hyphen", "\u2011"),
        ("en dash", "\u2013"),
    ):
        rendered = canary.replace("-", separator)
        assert residual_present(canary, f'{{"prompt": "lookup {rendered}"}}'), label

    # And the arm costs nothing on the other side: the tokens must be contiguous
    # and in order, so none of these is the canary.
    for label, text in (
        ("out of order", " ".join(reversed(canary.split("-")))),
        ("one token wrong", canary.replace("-", " ")[:-4] + "ZZZZ"),
        ("a token interposed", canary.replace("-", " X ", 1)),
        ("unrelated", "an ordinary trace with nothing in it"),
    ):
        assert not residual_present(canary, text), label
