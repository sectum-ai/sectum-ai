"""Does a model still reproduce a phrase - as recall, not as a guess.

Shared by the Class 11 canary scan and the A3 subject check. A real
autoregressive model continues a prompt rather than echoing it, so the whole
phrase never comes back; the signal is the phrase's trailing part regurgitated
after its leading part. That signal has two control arms:

- the same model with a same-shaped prefix that names nobody (``scramble``):
  a completion any prefix of that shape produces - ``@example.com`` after a
  local part, ``Smith`` after ``John`` - is a generic continuation;
- for a model that routes per tenant, the same prefix as a tenant that trained
  nothing: a completion the base weights already produce - ``Hussein Obama``
  after ``Barack`` - is world knowledge, not the tenant's residual.

A phrase whose trailing part is too short to be evidence, or whose prefix has no
scrambled form (it must differ), is *unverifiable*: the caller reports it as not
checked rather than as a verdict a guess could produce.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sectum_ai.adapters import Capability, ModelAdapter

# "Smith" for "John", "@example.com" for a local part: any base model produces
# those, so a phrase whose trailing part is shorter than this is not checked.
MIN_CONTINUATION_CHARS = 6

# The similarity page a marker/fingerprint scan reads. A marker still stored but
# ranked past the page is invisible to `query`, so a SHORT page without it is
# absence and a FULL one is only "not in the top k" - the caller must treat that
# as inconclusive. Class 11 and the A3 subject probe both scan a vector store for
# the same thing; they kept separate copies of this number, one moved to 50 and
# the other stayed at 10, and the run that read a full page as absence signed
# ERASURE VERIFIED over a canary the store still returned.
FINGERPRINT_QUERY_K = 50


def continuation_split(phrase: str) -> tuple[str, str] | None:
    """The (prefix, casefolded suffix) a prefix-continuation check prompts with.

    ``None`` when the phrase's trailing part is shorter than
    ``MIN_CONTINUATION_CHARS``, or when its prefix cannot be scrambled.
    """
    tokens = phrase.split()
    if len(tokens) >= 2:
        cut = max(1, len(tokens) // 2)
        prefix, suffix = " ".join(tokens[:cut]), " ".join(tokens[cut:])
    elif "@" in phrase:
        # An email: cut inside the local part, so the suffix carries the
        # subject-specific characters and not just the domain every address shares.
        local, domain = phrase.split("@", 1)
        cut = max(1, len(local) // 3)
        prefix, suffix = local[:cut], f"{local[cut:]}@{domain}"
    else:
        # A single token (an account number, a national id): the leading third.
        cut = max(1, len(phrase) // 3)
        prefix, suffix = phrase[:cut], phrase[cut:]
    if len(suffix.strip()) < MIN_CONTINUATION_CHARS or scramble(prefix) is None:
        return None
    return prefix, suffix.casefold()


def scramble(prefix: str) -> str | None:
    """A same-shaped prefix that identifies nobody, or ``None`` when none exists.

    ASCII letters rotate by 13, decimal digits by 5, and every other letter
    (any script) is replaced by the next such letter in the prefix, so a
    Cyrillic or CJK prefix changes too - the ASCII-only rotation left those
    identical to the subject's prefix, and the control arm then vetoed every
    genuine recall. A prefix the transform leaves unchanged has no control.
    """
    others = [ch for ch in prefix if ch.isalpha() and not ch.isascii()]
    rotated = others[1:] + others[:1]
    out: list[str] = []
    for ch in prefix:
        if ch.isascii() and ch.isalpha():
            base = ord("A") if ch.isupper() else ord("a")
            out.append(chr(base + (ord(ch) - base + 13) % 26))
        elif ch.isascii() and ch.isdecimal():
            out.append(str((int(ch) + 5) % 10))
        elif ch.isalpha():
            out.append(rotated.pop(0))
        else:
            out.append(ch)
    control = "".join(out)
    return None if control == prefix else control


def has_base_control(model: ModelAdapter) -> bool:
    """Whether a recall from ``model`` can be told apart from base knowledge.

    The control is the same prompt as a tenant that trained nothing. A model that
    merges every tenant's weights (``SHARED_WEIGHTS``) has no such tenant, so a
    completion the base already knew - "Hussein Obama" after "Barack" - cannot be
    attributed to the subject's data. Its fingerprints are unverifiable, not
    residual: the alternative was a CONFIRMED HIGH finding at confidence 1.0 in a
    DSR attestation for a model that trained nothing.
    """
    return model.supports(Capability.PER_TENANT_ADAPTER) and not model.supports(
        Capability.SHARED_WEIGHTS
    )


def content_recalled(model: ModelAdapter, target: UUID, phrase: str) -> bool:
    """Whether ``model`` still reproduces ``phrase`` for ``target``, controls applied."""
    if _reproduced(model, target, phrase, phrase.casefold()):
        return True
    split = continuation_split(phrase)
    if split is None:
        return False
    prefix, suffix = split
    return _reproduced(model, target, prefix, suffix)


def _reproduced(model: ModelAdapter, target: UUID, prompt: str, needle: str) -> bool:
    """``needle`` in the completion of ``prompt`` - and not for the controls.

    The whole-phrase echo branch used to count with no control at all: a chatty
    base model that restates the prompt ("I have no record matching 'John
    Smith'") signed a RESIDUAL for a tenant that trained nothing, and a hard
    delete then read as an erasure failure.
    """
    if needle not in model.infer(target, prompt).casefold():
        return False
    control = scramble(prompt)
    if control is None:
        # A prompt with no scrambled form has no control: not evidence either way.
        return False
    control_completion = model.infer(target, control).casefold()
    if needle in control_completion:
        return False
    if prompt.casefold() == needle and control.casefold() in control_completion:
        # The model restates its prompt (the scrambled one came back too): a
        # whole-phrase echo is not recall, on shared weights included, where the
        # base-tenant control below cannot tell.
        return False
    if model.supports(Capability.PER_TENANT_ADAPTER) and not model.supports(
        Capability.SHARED_WEIGHTS
    ):
        # A tenant that trained nothing answers from the base weights.
        return needle not in model.infer(uuid4(), prompt).casefold()
    return True
