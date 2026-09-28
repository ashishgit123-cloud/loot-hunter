"""
Price/evidence providers.

Important:
- Providers return evidence; they do NOT decide whether a Telegram post is a deal.
- Add licensed APIs here when available.
- Do not depend on undocumented/private endpoints.
"""

from __future__ import annotations
import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup

TIMEOUT = 12
MIN_PRICE = 1000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

AMAZON = {"amazon.in", "amazon.com"}
FLIPKART = {"flipkart.com"}
SHORT_AMAZON = {"amzn.to"}
SHORT_FLIPKART = {"fkrt.co", "fkrt.cc"}


def domain(url: str) -> str:
    try:
        d = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def store_for(url: str) -> Optional[str]:
    d = domain(url)
    if d in AMAZON or any(d.endswith("." + x) for x in AMAZON):
        return "amazon"
    if d in FLIPKART or any(d.endswith("." + x) for x in FLIPKART):
        return "flipkart"
    return None


def clean_price(value) -> Optional[float]:
    if value is None:
        return None
    m = re.search(r"\d+(?:,\d{2,3})*(?:\.\d+)?", str(value).replace("₹", ""))
    if not m:
        return None
    try:
        p = float(m.group(0).replace(",", ""))
        return p if p > 0 else None
    except ValueError:
        return None


def resolve_url(url: str) -> Optional[str]:
    if not url:
        return None
    current = url.strip()
    seen = set()

    for _ in range(8):
        if not current or current in seen:
            break
        seen.add(current)

        if store_for(current):
            return current

        try:
            r = requests.get(
                current, headers=HEADERS, timeout=TIMEOUT,
                allow_redirects=True,
            )
            final = r.url or current
            if store_for(final):
                return final

            # Only accept meta refresh if it points somewhere useful.
            soup = BeautifulSoup(r.text or "", "html.parser")
            meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
            if meta:
                m = re.search(r"url\s*=\s*(.+)", meta.get("content", ""), re.I)
                if m:
                    current = requests.compat.urljoin(final, m.group(1).strip(" '\""))
                    continue
            return final
        except requests.RequestException:
            return current

    return current


def canonical_url(url: str) -> Optional[str]:
    if not url:
        return None
    store = store_for(url)
    if store == "amazon":
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{8,20})", url, re.I)
        if m:
            return f"https://www.amazon.in/dp/{m.group(1).upper()}"
    if store == "flipkart":
        p = urlparse(url)
        return f"https://www.flipkart.com{p.path}" if p.path else url
    return url


def extract_page_price(html: str) -> Optional[float]:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    # Prefer product structured data.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue

        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if str(k).lower() in {
                        "price", "priceamount", "lowprice", "sellingprice",
                        "currentprice", "finalprice", "saleprice"
                    }:
                        p = clean_price(v)
                        if p and p >= MIN_PRICE:
                            candidates.append(p)
                    else:
                        walk(v)
            elif isinstance(x, list):
                for y in x:
                    walk(y)

        walk(data)

    if candidates:
        return min(candidates)

    # Fallback is intentionally conservative.
    for pat in [
        r'"(?:currentPrice|sellingPrice|finalPrice|salePrice)"\s*:\s*"?(?P<p>[\d,.]+)',
        r'(?:₹|Rs\.?|INR)\s*(?P<p>[\d,]+(?:\.\d+)?)',
    ]:
        for m in re.finditer(pat, html, re.I):
            p = clean_price(m.group("p"))
            if p and p >= MIN_PRICE:
                candidates.append(p)

    return min(candidates) if candidates else None


def fetch_product_price(url: str) -> Optional[float]:
    try:
        r = requests.get(
            url, headers=HEADERS, timeout=TIMEOUT,
            allow_redirects=True,
        )
        if r.status_code != 200:
            return None
        return extract_page_price(r.text)
    except requests.RequestException:
        return None


def pricehistory_url(product_url: str) -> str:
    return f"https://pricehistory.app/?url={quote(product_url, safe='')}"


def extract_history(html: str) -> dict:
    """
    Best-effort parser. Missing/ambiguous data is UNKNOWN, never a deal.
    """
    if not html:
        return {}

    values = []
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

    patterns = [
        r"(?:all[-\s]*time\s*low|historical\s*low|lowest\s*price)\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)",
        r'"(?:lowestPrice|lowest_price|historicalLow|historical_low|allTimeLow|all_time_low|minPrice|min_price)"\s*:\s*"?([\d,.]+)',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text + "\n" + html, re.I):
            p = clean_price(m.group(1))
            if p and p >= MIN_PRICE:
                values.append(p)

    if not values:
        return {}
    return {"historical_low": min(values)}


def fetch_pricehistory(product_url: str) -> dict:
    try:
        r = requests.get(
            pricehistory_url(product_url),
            headers={**HEADERS, "Referer": product_url},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if r.status_code != 200:
            return {}
        data = extract_history(r.text)
        if data:
            data["url"] = r.url
        return data
    except requests.RequestException:
        return {}


async def gather_evidence(product_url: str) -> list[dict]:
    """
    Parallel evidence collection. PriceHistory is one provider, not truth.
    """
    tasks = [
        asyncio.to_thread(fetch_product_price, product_url),
        asyncio.to_thread(fetch_pricehistory, product_url),
    ]
    page_price, history = await asyncio.gather(*tasks, return_exceptions=True)
    out = []

    if isinstance(page_price, (int, float)) and page_price >= MIN_PRICE:
        out.append({
            "provider": "retailer_page",
            "kind": "current_price",
            "price": float(page_price),
            "confidence": 0.70,
        })

    if isinstance(history, dict) and history.get("historical_low"):
        out.append({
            "provider": "pricehistory",
            "kind": "historical",
            "historical_low": float(history["historical_low"]),
            "url": history.get("url"),
            "confidence": 0.65,
        })

    return out
