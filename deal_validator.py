from __future__ import annotations

import asyncio
import sqlite3
import re
from typing import Optional

from deal_models import Offer, Evidence, Evaluation, Verdict
from deal_sources import (
    canonical_url,
    gather_evidence,
    resolve_url,
    store_for,
)
from deal_engine import evaluate


def parse_price_to_float(val) -> Optional[float]:
    """Helper to clean price strings like '₹9,657' or '₹1,499.00' into floats."""
    if not val or val in {"-", "N/A", "Not Found ❌"}:
        return None
    try:
        cleaned = re.sub(r'[^\d.]', '', str(val))
        return float(cleaned) if cleaned else None
    except Exception:
        return None


def get_db_historical_evidence(canonical_url: str) -> list[dict]:
    """Queries local SQLite database for past recorded prices of this URL."""
    db_evidence = []
    try:
        conn = sqlite3.connect("loot_history.db")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT price, min_price, timestamp 
            FROM historical_deals 
            WHERE url = ? 
            ORDER BY timestamp DESC 
            LIMIT 5
        """, (canonical_url,))
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            price_str, min_price_str, timestamp = row
            p_val = parse_price_to_float(price_str)
            m_val = parse_price_to_float(min_price_str)

            if p_val and p_val > 100:
                db_evidence.append({
                    "provider": "local_sqlite_history",
                    "kind": "past_recorded_deal",
                    "price": p_val,
                    "historical_low": m_val if (m_val and m_val > 100) else p_val,
                    "confidence": 0.85
                })
    except Exception as e:
        print(f"Local DB history lookup error: {e}")
    return db_evidence


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
            offer=Offer(
                title=title,
                price=price,
                url=original,
                source=source,
            ),
            evidence=[],
            canonical_url=None,
            store=None,
        )

    store = store_for(final)

    if not store:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="URL does not resolve to a supported retailer.",
            offer=Offer(
                title=title,
                price=price,
                url=original,
                source=source,
            ),
            evidence=[],
            canonical_url=None,
            store=None,
        )

    canonical = canonical_url(final)

    if not canonical:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason=(
                "Supported retailer detected, "
                "but product URL could not be canonicalized."
            ),
            offer=Offer(
                title=title,
                price=price,
                url=original,
                source=source,
            ),
            evidence=[],
            canonical_url=None,
            store=store,
        )

    if price is None or price <= 0:
        return Evaluation(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            score=None,
            reason="Telegram payable price could not be extracted.",
            offer=Offer(
                title=title,
                price=None,
                url=original,
                source=source,
            ),
            evidence=[],
            canonical_url=canonical,
            store=store,
        )

    # 1. Fetch external evidence from providers
    raw = await gather_evidence(canonical)

    # 2. Fetch past recorded prices from our own local SQLite database
    db_raw = await asyncio.to_thread(get_db_historical_evidence, canonical)

    # Combine external and local database evidence
    combined_raw = raw + db_raw

    evidence = [
        Evidence(
            provider=item.get("provider", "unknown"),
            kind=item.get("kind", "unknown"),
            price=item.get("price"),
            historical_low=item.get("historical_low"),
            url=item.get("url"),
            confidence=item.get("confidence", 0.0),
        )
        for item in combined_raw
    ]

    # Valid reference price check (> ₹100)
    valid_evidence = [
        e for e in evidence 
        if (e.price and e.price > 100) or (e.historical_low and e.historical_low > 100)
    ]

    if not valid_evidence:
        # Agar external aur local DB dono mein koi history nahi hai, toh ise NAYA DEAL maan kar PASS kar do 
        # taaki yeh database mein save ho sake aur next time compare ho sake.
        return Evaluation(
            verdict=Verdict.DEAL,
            confidence=0.7,
            score=None,
            reason="New product deal registered into database for future price comparisons.",
            offer=Offer(
                title=title,
                price=price,
                url=original,
                source=source,
            ),
            evidence=evidence,
            canonical_url=canonical,
            store=store,
        )

    # Evaluate using combined evidence (External + Local SQLite History)
    result = evaluate(
        Offer(
            title=title,
            price=price,
            url=original,
            source=source,
        ),
        evidence,
    )

    result.canonical_url = canonical
    result.store = store

    return result