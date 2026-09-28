from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Verdict(str, Enum):
    DEAL = "DEAL"
    POSSIBLE_DEAL = "POSSIBLE_DEAL"
    UNKNOWN = "UNKNOWN"
    REJECT = "REJECT"


@dataclass
class Offer:
    title: str
    price: Optional[float]
    url: str
    source: str
    raw_text: str = ""
    currency: str = "INR"


@dataclass
class Evidence:
    provider: str
    kind: str
    price: Optional[float] = None
    historical_low: Optional[float] = None
    typical_price: Optional[float] = None
    url: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: float = 0.0
    notes: str = ""


@dataclass
class Evaluation:
    verdict: Verdict
    confidence: float
    score: Optional[float]
    reason: str
    offer: Offer
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    canonical_url: Optional[str] = None
    store: Optional[str] = None
