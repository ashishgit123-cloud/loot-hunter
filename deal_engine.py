from __future__ import annotations

from statistics import median
from typing import Optional

from deal_models import Offer, Evidence, Evaluation, Verdict


def evaluate(
    offer: Offer,
    evidence: list[Evidence],
    *,
    minimum_confidence: float = 0.55,
) -> Evaluation:
    """
    Evidence-first evaluator.

    Never calls an unverified Telegram claim a deal.
    Historical low alone is not sufficient proof of a deal.
    """
    warnings = []

    if not offer.price or offer.price <= 0:
        return Evaluation(
            Verdict.UNKNOWN, 0.0, None,
            "Current payable price is unknown.",
            offer, evidence, ["No reliable current price."],
        )

    current = offer.price
    current_refs = [
        e.price for e in evidence
        if e.price and e.price > 0
    ]
    lows = [
        e.historical_low for e in evidence
        if e.historical_low and e.historical_low > 0
    ]

    # Same-store current price is useful, but a single scraped price
    # is not enough to declare a deal.
    if current_refs:
        ref = median(current_refs)
        delta = (ref - current) / ref
    else:
        ref = None
        delta = None

    if lows:
        low = min(lows)
        above_low = (current - low) / low
    else:
        low = None
        above_low = None

    # Manipulation / extraction warning:
    # A "historical low" dramatically below the current offer can be
    # stale, coupon-only, marketplace-specific, or parser noise.
    if low and current >= 5000 and low < current * 0.85:
        warnings.append("Historical low is materially below the current offer; it is not treated as proof of a deal.")

    # Stronger case: current price beats a verified current reference.
    if delta is not None and delta >= 0.08:
        score = min(100.0, 70 + delta * 250)
        confidence = min(
            0.95,
            0.50 + 0.12 * len(current_refs) + 0.10 * len(lows)
        )
        if confidence >= minimum_confidence:
            return Evaluation(
                Verdict.DEAL, confidence, score,
                f"Current price is about {delta * 100:.1f}% below the available current reference price.",
                offer, evidence, warnings,
            )

    # Near historical low is only a possible deal unless current-market
    # corroboration also exists.
    if low is not None and current <= low * 1.03:
        confidence = min(0.80, 0.42 + 0.12 * len(lows) + 0.10 * len(current_refs))
        if current_refs and delta is not None and delta >= 0.03:
            confidence += 0.08
        if confidence >= minimum_confidence:
            return Evaluation(
                Verdict.POSSIBLE_DEAL, confidence,
                60 + min(30, max(0, (0.03 - above_low) * 500)),
                "Price is at/near an observed historical low, but historical data alone is not sufficient for a high-confidence verdict.",
                offer, evidence, warnings,
            )

    if current_refs and delta is not None and delta <= -0.03:
        return Evaluation(
            Verdict.REJECT,
            min(0.90, 0.55 + 0.08 * len(current_refs)),
            max(0.0, 50 + delta * 100),
            f"Current price is about {abs(delta) * 100:.1f}% above the available current reference price.",
            offer, evidence, warnings,
        )

    return Evaluation(
        Verdict.UNKNOWN,
        min(0.75, 0.35 + 0.10 * len(evidence)),
        None,
        "Insufficient independent evidence to verify the Telegram claim.",
        offer, evidence, warnings,
    )
