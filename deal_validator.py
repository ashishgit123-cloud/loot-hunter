from __future__ import annotations

import asyncio
from typing import Optional

from deal_models import (
    Offer,
    Evidence,
    Evaluation,
    Verdict,
)

from deal_sources import (
    canonical_url,
    gather_evidence,
    resolve_url,
    store_for,
)

from deal_engine import evaluate


async def validate_deal(
    title: str,
    price: Optional[float],
    url: str,
    source: str,
    text: str = "",
) -> Evaluation:

    original = url

    # ---------------------------------------------------------
    # Resolve Telegram/affiliate/short URL
    # ---------------------------------------------------------

    final = await asyncio.to_thread(
        resolve_url,
        url,
    )

    if not final:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="Product URL could not be resolved.",
            offer=Offer(
                title,
                price,
                original,
                source,
                text,
            ),
            evidence=[],
        )

    # ---------------------------------------------------------
    # Identify retailer
    # ---------------------------------------------------------

    store = store_for(final)

    if not store:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="URL does not resolve to a supported retailer.",
            offer=Offer(
                title,
                price,
                original,
                source,
                text,
            ),
            evidence=[],
            canonical_url=None,
            store=None,
        )

    # ---------------------------------------------------------
    # Canonical product URL
    # ---------------------------------------------------------

    canonical = canonical_url(final)

    if not canonical:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="Supported retailer detected, but product URL could not be canonicalized.",
            offer=Offer(
                title,
                price,
                original,
                source,
                text,
            ),
            evidence=[],
            canonical_url=None,
            store=store,
        )

    # ---------------------------------------------------------
    # Telegram price
    # ---------------------------------------------------------

    if price is None or price <= 0:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="Telegram payable price could not be extracted.",
            offer=Offer(
                title,
                None,
                original,
                source,
                text,
            ),
            evidence=[],
            canonical_url=canonical,
            store=store,
        )

    # ---------------------------------------------------------
    # Gather independent evidence
    # ---------------------------------------------------------

    raw = await gather_evidence(
        canonical
    )

    evidence = []

    for item in raw:
        evidence.append(
            Evidence(
                provider=item["provider"],
                kind=item["kind"],
                price=item.get("price"),
                historical_low=item.get(
                    "historical_low"
                ),
                url=item.get("url"),
                confidence=item.get(
                    "confidence",
                    0,
                ),
            )
        )

    # ---------------------------------------------------------
    # Evaluate
    # ---------------------------------------------------------

    result = evaluate(
        Offer(
            title,
            price,
            original,
            source,
            text,
        ),
        evidence,
    )

    result.canonical_url = canonical
    result.store = store

    return result