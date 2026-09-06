"""Direct unit coverage for the canary plaintext generators (spec section 6.3).

These pin the *generators themselves* (`sectum_ai.substrate.markers`), which were
previously exercised only indirectly through `build_substrate`. The focus is the
entity-canary codename (review round 7): a codename must be a distinctive single
token so the detection FP-control backstop (spec section 6.4) cannot be defeated
by a benign mention of a bare dictionary codeword. The hard/secret shape guards
pin the claim that the round-7 change left those generators untouched.
"""

import random
import re
import string

from sectum_ai.spec import tokenize
from sectum_ai.substrate.markers import (
    _HARD_PREFIX,
    _MARKER_CODENAMES,
    _b32,
    _entity_plaintext,
    _hard_plaintext,
    _secret_aws,
    _secret_openai,
    _secret_ssn,
)

_BASE32_ALPHABET = set(string.ascii_uppercase + "234567")


def _split_entity(plaintext: str) -> tuple[str, str, str]:
    """Return (base codeword, fused codename token, serial) of an entity plaintext."""
    assert plaintext.startswith("Project "), plaintext
    head, sep, serial = plaintext.rpartition("-")
    assert sep == "-", plaintext
    codename = head[len("Project ") :]
    base = next(b for b in _MARKER_CODENAMES if codename.startswith(b))
    return base, tokenize(codename)[0], serial


# --- the entity-canary codename (the round-7 change) ----------------------------


def test_entity_plaintext_is_deterministic_for_a_fixed_rng_and_sequence() -> None:
    # The reproducibility contract (spec section 6.5): generation is a pure
    # function of the rng state and the sequence.
    assert _entity_plaintext(random.Random(7), 3) == _entity_plaintext(random.Random(7), 3)


def test_entity_plaintext_has_the_documented_shape() -> None:
    # "Project <Codeword><base32>-<NNNNN>" - codeword fused with a base32 segment.
    text = _entity_plaintext(random.Random(1), 42)
    assert re.fullmatch(r"Project [A-Z][a-z]+[A-Z2-7]{5}-\d{5}", text), text
    base, _token, _serial = _split_entity(text)
    assert base in _MARKER_CODENAMES
    entropy = text[len("Project ") + len(base) :].rpartition("-")[0]
    assert len(entropy) == 5  # base32 of 3 bytes (24 bits), padding stripped
    assert set(entropy) <= _BASE32_ALPHABET


def test_entity_plaintext_serial_is_the_zero_padded_sequence() -> None:
    assert _entity_plaintext(random.Random(5), 0).endswith("-00000")
    assert _entity_plaintext(random.Random(5), 7).endswith("-00007")
    assert _entity_plaintext(random.Random(5), 99999).endswith("-99999")


def test_entity_codename_fuses_entropy_into_a_single_token() -> None:
    # No separator between codeword and entropy: `tokenize` ([a-z0-9]+) must see
    # exactly one token, so a benign mention of the bare codeword cannot match it.
    base, token, _serial = _split_entity(_entity_plaintext(random.Random(2), 1))
    assert tokenize(_entity_plaintext(random.Random(2), 1)) == ["project", token, "00001"]
    assert token.startswith(base.lower())  # legible: still begins with the codeword
    assert len(token) == len(base) + 5  # ... but strictly longer (entropy fused on)


def test_entity_codename_is_never_the_bare_codeword() -> None:
    bare = {c.lower() for c in _MARKER_CODENAMES}
    rng = random.Random(99)
    for seq in range(60):
        _base, token, _serial = _split_entity(_entity_plaintext(rng, seq))
        assert token not in bare, token


def test_entity_codenames_are_unique_even_when_the_codeword_repeats() -> None:
    # Distinctiveness: the entropy disambiguates two canaries that happen to draw
    # the same base codeword - the property the detection backstop relies on.
    rng = random.Random(2026)
    pairs = [_split_entity(_entity_plaintext(rng, seq))[:2] for seq in range(80)]
    bases = [base for base, _token in pairs]
    tokens = [token for _base, token in pairs]
    # The draw actually exercises the collision case (some codeword recurs)...
    assert len(set(bases)) < len(bases), "test did not exercise a repeated codeword"
    # ... yet every fused codename token is still globally unique.
    assert len(set(tokens)) == len(tokens)


def test_entity_codeword_stays_legible() -> None:
    # The demo-readability contract: the human-facing prefix is preserved.
    text = _entity_plaintext(random.Random(11), 5)
    assert text.startswith("Project ")
    assert any(text[len("Project ") :].startswith(c) for c in _MARKER_CODENAMES)


# --- hard / secret generators are untouched by the round-7 change ---------------


def test_hard_plaintext_shape_is_unchanged() -> None:
    text = _hard_plaintext(random.Random(3))
    assert text.startswith(_HARD_PREFIX)
    body = text[len(_HARD_PREFIX) :]
    assert len(body) == 26  # base32 of 16 bytes (128 bits), padding stripped
    assert set(body) <= _BASE32_ALPHABET


def test_secret_generators_keep_their_credential_shapes() -> None:
    assert re.fullmatch(r"sk-[A-Za-z0-9]{48}", _secret_openai(random.Random(4)))
    assert re.fullmatch(r"AKIA[A-Z0-9]{16}", _secret_aws(random.Random(4)))
    # A US SSN *shape* whose 9xx area the SSA never issues (non-issuable).
    assert re.fullmatch(r"9\d{2}-\d{2}-\d{4}", _secret_ssn(random.Random(4)))


def test_b32_strips_padding_and_stays_in_alphabet() -> None:
    for n in (1, 3, 8, 16):
        out = _b32(random.Random(1), n)
        assert "=" not in out
        assert set(out) <= _BASE32_ALPHABET
