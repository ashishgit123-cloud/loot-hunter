
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional
from urllib.parse import quote, urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup


TIMEOUT = 12

# This is NOT a price-extraction threshold.
# Use it later if you want to filter which deals get forwarded.
MIN_PRICE = 1000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

# Actual supported retailers.
AMAZON = {
    "amazon.in",
    "amazon.com",
}

FLIPKART = {
    "flipkart.com",
}

# Redirect/short-link domains.
# These must NOT be treated as final retailers.
SHORT_AMAZON = {
    "amzn.to",
}

SHORT_FLIPKART = {
    "fkrt.co",
    "fkrt.cc",
    "fkrt.it",
}

SHORT_DOMAINS = SHORT_AMAZON | SHORT_FLIPKART


def domain(url: str) -> str:
    """
    Return normalized hostname without www./port.
    """
    try:
        parsed = urlparse(url.strip())
        host = parsed.hostname or ""
        return host.lower().lstrip("www.")
    except Exception:
        return ""


def store_for(url: str) -> Optional[str]:
    """
    Identify only final supported retailer URLs.

    Short/redirect domains are intentionally NOT returned as retailers.
    """
    d = domain(url)

    if d in AMAZON or any(d.endswith("." + x) for x in AMAZON):
        return "amazon"

    if d in FLIPKART or any(d.endswith("." + x) for x in FLIPKART):
        return "flipkart"

    return None


def is_short_url(url: str) -> bool:
    """
    Return True when URL belongs to a known retailer short-link domain.
    """
    d = domain(url)
    return (
        d in SHORT_DOMAINS
        or any(d.endswith("." + x) for x in SHORT_DOMAINS)
    )


def clean_price(value) -> Optional[float]:
    """
    Extract a positive numeric price.

    IMPORTANT:
    This function does NOT apply MIN_PRICE.
    """
    if value is None:
        return None

    text = str(value).replace("₹", "").replace("INR", "").strip()

    # Handles:
    # 1,299
    # 12,999
    # 1299
    # 1299.50
    m = re.search(
        r"\d+(?:,\d{2,3})*(?:\.\d+)?",
        text,
    )

    if not m:
        return None

    try:
        price = float(m.group(0).replace(",", ""))
        return price if price > 0 else None
    except (ValueError, TypeError):
        return None


def _meta_refresh_url(html: str, base_url: str) -> Optional[str]:
    """
    Extract a meta-refresh redirect if present.
    """
    if not html:
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")

        meta = soup.find(
            "meta",
            attrs={"http-equiv": re.compile(r"refresh", re.I)},
        )

        if not meta:
            return None

        content = meta.get("content", "")

        match = re.search(
            r"url\s*=\s*(.+)",
            content,
            re.I,
        )

        if not match:
            return None

        target = match.group(1).strip(" '\"")

        return urljoin(base_url, target)

    except Exception:
        return None


def resolve_url(url: str) -> Optional[str]:
    """
    Resolve Telegram deal URLs to the final supported retailer URL.

    Flow:

        fkrt.it / fkrt.co / amzn.to
                    ↓
             HTTP redirect
                    ↓
          final retailer URL
                    ↓
          Flipkart / Amazon

    A short URL is never returned as a successfully resolved retailer URL.
    """
    if not url:
        return None

    current = url.strip()
    seen: set[str] = set()

    for _ in range(8):
        if not current:
            return None

        if current in seen:
            break

        seen.add(current)

        # If this is already a final supported retailer URL,
        # we're finished.
        retailer = store_for(current)

        if retailer:
            return current

        try:
            response = requests.get(
                current,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )

            final = response.url or current

            # requests followed HTTP redirects.
            retailer = store_for(final)

            if retailer:
                return final

            # Some affiliate/short links use meta refresh.
            meta_target = _meta_refresh_url(
                response.text or "",
                final,
            )

            if meta_target and meta_target not in seen:
                current = meta_target
                continue

            # Some pages contain canonical URLs.
            try:
                soup = BeautifulSoup(
                    response.text or "",
                    "html.parser",
                )

                canonical_tag = soup.find(
                    "link",
                    rel=lambda value: (
                        value
                        and "canonical" in value
                    ),
                )

                if canonical_tag:
                    canonical_href = canonical_tag.get("href")

                    if canonical_href:
                        canonical_target = urljoin(
                            final,
                            canonical_href,
                        )

                        if (
                            canonical_target not in seen
                            and store_for(canonical_target)
                        ):
                            return canonical_target

            except Exception:
                pass

            # We reached a URL but it isn't a supported retailer.
            return None

        except requests.RequestException:
            return None

    return None


def _remove_tracking_parameters(url: str) -> str:
    """
    Remove common affiliate/tracking query parameters.

    Product-identifying path is retained.
    """
    try:
        parsed = urlparse(url)

        if not parsed.query:
            return url

        keep = []

        tracking_prefixes = (
            "utm_",
            "fbclid",
            "gclid",
            "ref",
            "aff",
            "affiliate",
            "affid",
            "tag",
            "irclickid",
            "mc_",
        )

        for key, value in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        ):
            key_lower = key.lower()

            if any(
                key_lower == prefix
                or key_lower.startswith(prefix)
                for prefix in tracking_prefixes
            ):
                continue

            keep.append((key, value))

        query = urlencode(keep)

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                query,
                "",
            )
        )

    except Exception:
        return url


def canonical_url(url: str) -> Optional[str]:
    """
    Convert supported retailer URLs into a stable product URL.
    """
    if not url:
        return None

    store = store_for(url)

    if not store:
        return None

    url = _remove_tracking_parameters(url)

    if store == "amazon":
        match = re.search(
            r"/(?:dp|gp/product)/([A-Z0-9]{8,20})",
            url,
            re.I,
        )

        if match:
            return (
                "https://www.amazon.in/dp/"
                f"{match.group(1).upper()}"
            )

        parsed = urlparse(url)

        return urlunparse(
            (
                "https",
                parsed.netloc or "www.amazon.in",
                parsed.path,
                "",
                parsed.query,
                "",
            )
        )

    if store == "flipkart":
        parsed = urlparse(url)

        if not parsed.path:
            return "https://www.flipkart.com"

        return urlunparse(
            (
                "https",
                "www.flipkart.com",
                parsed.path,
                "",
                parsed.query,
                "",
            )
        )

    return url


def _walk_json_prices(data, candidates: list[float]) -> None:
    """
    Recursively search JSON-LD for price-like fields.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = str(key).lower()

            if key_lower in {
                "price",
                "priceamount",
                "lowprice",
                "sellingprice",
                "currentprice",
                "finalprice",
                "saleprice",
                "offerprice",
            }:
                price = clean_price(value)

                if price:
                    candidates.append(price)

            else:
                _walk_json_prices(value, candidates)

    elif isinstance(data, list):
        for item in data:
            _walk_json_prices(item, candidates)


def extract_page_price(html: str) -> Optional[float]:
    """
    Extract current price from retailer HTML.

    No MIN_PRICE filtering is performed here.
    """
    if not html:
        return None

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    candidates: list[float] = []

    # ---------------------------------------------------------
    # 1. JSON-LD structured data
    # ---------------------------------------------------------

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        _walk_json_prices(
            data,
            candidates,
        )

    if candidates:
        return min(candidates)

    # ---------------------------------------------------------
    # 2. Common retailer JSON patterns
    # ---------------------------------------------------------

    patterns = [
        r'"(?:currentPrice|sellingPrice|finalPrice|salePrice|offerPrice)"'
        r'\s*:\s*"?(?P<p>[\d,.]+)',

        r'"(?:selling_price|sellingPrice|selling_price_value)"'
        r'\s*:\s*"?(?P<p>[\d,.]+)',

        r'"price"\s*:\s*"?(?P<p>[\d,.]+)',
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            html,
            re.I,
        ):
            price = clean_price(
                match.group("p")
            )

            if price:
                candidates.append(price)

    if candidates:
        return min(candidates)

    # ---------------------------------------------------------
    # 3. Visible ₹ / Rs / INR prices
    # ---------------------------------------------------------

    for pattern in [
        r"(?:₹|Rs\.?|INR)\s*(?P<p>[\d,]+(?:\.\d+)?)",
    ]:
        for match in re.finditer(
            pattern,
            html,
            re.I,
        ):
            price = clean_price(
                match.group("p")
            )

            if price:
                candidates.append(price)

    return min(candidates) if candidates else None


def fetch_product_price(url: str) -> Optional[float]:
    """
    Fetch current retailer page price.
    """
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return None

        return extract_page_price(
            response.text
        )

    except requests.RequestException:
        return None


def pricehistory_url(product_url: str) -> str:
    return (
        "https://pricehistory.app/?url="
        f"{quote(product_url, safe='')}"
    )


def extract_history(html: str) -> dict:
    """
    Best-effort historical-price parser.

    Missing/ambiguous data is UNKNOWN, never a deal.
    """
    if not html:
        return {}

    values: list[float] = []

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    patterns = [
        (
            r"(?:all[-\s]*time\s*low|"
            r"historical\s*low|"
            r"lowest\s*price)"
            r"\s*[:\-]?\s*"
            r"(?:₹|Rs\.?|INR)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),
        (
            r'"(?:lowestPrice|lowest_price|'
            r"historicalLow|historical_low|"
            r"allTimeLow|all_time_low|"
            r"minPrice|min_price)"
            r'\s*:\s*"?(?P<p>[\d,.]+)'
        ),
    ]

    combined = text + "\n" + html

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            combined,
            re.I,
        ):
            raw_price = (
                match.groupdict().get("p")
                if match.groupdict()
                else match.group(1)
            )

            price = clean_price(raw_price)

            if price:
                values.append(price)

    if not values:
        return {}

    return {
        "historical_low": min(values)
    }


def fetch_pricehistory(
    product_url: str,
) -> dict:
    try:
        response = requests.get(
            pricehistory_url(product_url),
            headers={
                **HEADERS,
                "Referer": product_url,
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return {}

        data = extract_history(
            response.text
        )

        if data:
            data["url"] = response.url

        return data

    except requests.RequestException:
        return {}


async def gather_evidence(
    product_url: str,
) -> list[dict]:
    """
    Parallel evidence collection.

    Providers supply evidence.
    deal_engine.evaluate() decides the verdict.
    """

    tasks = [
        asyncio.to_thread(
            fetch_product_price,
            product_url,
        ),
        asyncio.to_thread(
            fetch_pricehistory,
            product_url,
        ),
    ]

    page_price, history = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    out: list[dict] = []

    if isinstance(
        page_price,
        (int, float),
    ) and page_price > 0:

        out.append(
            {
                "provider": "retailer_page",
                "kind": "current_price",
                "price": float(page_price),
                "confidence": 0.70,
            }
        )

    if (
        isinstance(history, dict)
        and history.get("historical_low")
    ):
        out.append(
            {
                "provider": "pricehistory",
                "kind": "historical",
                "historical_low": float(
                    history["historical_low"]
                ),
                "url": history.get("url"),
                "confidence": 0.65,
            }
        )

    return out