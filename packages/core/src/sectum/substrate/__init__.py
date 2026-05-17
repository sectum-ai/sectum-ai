"""The Sectum AI marker substrate: synthetic tenants, corpora, markers, detection.

This is part of the ``sectum`` core distribution (the engineering spec, section 6).
"""

from sectum.substrate.build import build_substrate
from sectum.substrate.detect import (
    DetectionPipeline,
    EmbeddingProvider,
    FakeEmbeddingProvider,
    FakeJudge,
    Judge,
    JudgeVerdict,
    confirmed_findings,
)
from sectum.substrate.scenario import default_scenario

__all__ = [
    "DetectionPipeline",
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "FakeJudge",
    "Judge",
    "JudgeVerdict",
    "build_substrate",
    "confirmed_findings",
    "default_scenario",
]
