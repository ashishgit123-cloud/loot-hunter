from __future__ import annotations

import asyncio
from typing import Optional

from deal_models import Offer, Evidence, Evaluation, Verdict
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
    final = await asyncio.to_thread(resolve_url, url)

    if not final:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="Product URL could not be resolved.",
            offer=Offer(title, price, original, source, text),
            evidence=[],
        )

    canonical = canonical_url(final)
    store = store_for(canonical or final)

    if not store:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="URL does not resolve to a supported retailer.",
            offer=Offer(title, price, original, source, text),
            evidence=[],
            canonical_url=canonical,
            store=None,
        )

    if not price:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="Telegram payable price could not be extracted.",
            offer=Offer(title, None, original, source, text),
            evidence=[],
            canonical_url=canonical,
            store=store,
        )

    raw = await gather_evidence(canonical)
    evidence = [
        Evidence(
            provider=x["provider"],
            kind=x["kind"],
            price=x.get("price"),
            historical_low=x.get("historical_low"),
            url=x.get("url"),
            confidence=x.get("confidence", 0),
        )
        for x in raw
    ]

    result = evaluate(
        Offer(title, price, original, source, text),
        evidence,
    )
    result.canonical_url = canonical
    result.store = store
    return result
