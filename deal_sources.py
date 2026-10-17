
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional
from urllib.parse import (
    parse_qsl,
    quote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import requests
from bs4 import BeautifulSoup


# Keep requests short so a slow retailer does not stall processing.
CONNECT_TIMEOUT = 3.05
READ_TIMEOUT = 5
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)
MAX_REDIRECTS = 6
MAX_HTML_BYTES = 1_200_000
MIN_PRICE = 1000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Connection": "close",
}

AMAZON = {"amazon.in", "amazon.com"}
FLIPKART = {"flipkart.com"}

SHORT_AMAZON = {"amzn.to"}
SHORT_FLIPKART = {"fkrt.co", "fkrt.cc", "fkrt.it"}
SHORT_DOMAINS = SHORT_AMAZON | SHORT_FLIPKART


def domain(url: str) -> str:
    try:
        host = urlparse((url or "").strip()).hostname or ""
        return host.lower().removeprefix("www.")
    except (ValueError, AttributeError):
        return ""


def store_for(url: str) -> Optional[str]:
    host = domain(url)

    if host in AMAZON or any(host.endswith("." + d) for d in AMAZON):
        return "amazon"

    if host in FLIPKART or any(host.endswith("." + d) for d in FLIPKART):
        return "flipkart"

    return None


def is_short_url(url: str) -> bool:
    host = domain(url)
    return host in SHORT_DOMAINS or any(
        host.endswith("." + d) for d in SHORT_DOMAINS
    )


def _valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except (ValueError, AttributeError):
        return False


def _request_html(url: str, headers: Optional[dict] = None):
    """
    Fetch a limited amount of HTML.

    Returns (final_url, status_code, html).
    Network calls must run in a worker thread when called by async code.
    """
    if not _valid_http_url(url):
        return url, 0, ""

    response = None

    try:
        response = requests.get(
            url,
            headers=headers or HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
            stream=True,
        )

        final_url = response.url or url
        status = response.status_code

        if not _valid_http_url(final_url):
            return url, status, ""

        content_type = response.headers.get("Content-Type", "").lower()

        if content_type and not any(
            kind in content_type
            for kind in ("text/html", "application/xhtml+xml", "text/plain")
        ):
            return final_url, status, ""

        chunks = []
        size = 0

        for chunk in response.iter_content(chunk_size=16_384):
            if not chunk:
                continue

            remaining = MAX_HTML_BYTES - size
            if remaining <= 0:
                break

            chunk = chunk[:remaining]
            chunks.append(chunk)
            size += len(chunk)

            if size >= MAX_HTML_BYTES:
                break

        raw = b"".join(chunks)
        encoding = response.encoding or "utf-8"

        try:
            html = raw.decode(encoding, errors="replace")
        except LookupError:
            html = raw.decode("utf-8", errors="replace")

        return final_url, status, html

    except requests.RequestException:
        return url, 0, ""

    finally:
        if response is not None:
            response.close()


def clean_price(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None

    text = str(value).replace("₹", "").replace("INR", "").strip()
    match = re.search(r"(?<!\d)\d[\d,]*(?:\.\d{1,2})?(?!\d)", text)

    if not match:
        return None

    try:
        price = float(match.group(0).replace(",", ""))
        return price if 50 < price < 100_000_000 else None
    except (ValueError, TypeError):
        return None


def extract_price_from_text(text: str) -> Optional[float]:
    """
    Prefer explicit selling-price formats from a Telegram post.
    Ignore discount percentages and common cash-discount phrases.
    """
    if not text:
        return None

    cleaned = text

    # Remove common discount percentages.
    cleaned = re.sub(
        r"\b(?:upto|up to|flat|save|extra)?\s*\d+(?:\.\d+)?\s*%"
        r"(?:\s*(?:off|discount))?\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Remove cash-discount amounts so they are not mistaken for selling prices.
    cleaned = re.sub(
        r"\b(?:save|saving|cashback|discount|off)\b"
        r"[^,\n.!|]{0,24}(?:₹|Rs\.?|INR)?\s*[\d,]+(?:\.\d+)?",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?"
        r"\s*(?:off|discount|cashback|saving)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    patterns = [
        r"(?:₹|Rs\.?|INR)\s*(?P<p>\d[\d,]*(?:\.\d{1,2})?)",
        r"@\s*(?P<p>\d[\d,]*(?:\.\d{1,2})?)",
        r"(?P<p>\d[\d,]*(?:\.\d{1,2})?)\s*/-",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, cleaned, re.IGNORECASE):
            price = clean_price(match.group("p"))
            if price:
                return price

    return None


def _meta_refresh_url(html: str, base_url: str) -> Optional[str]:
    if not html:
        return None

    try:
        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find(
            "meta",
            attrs={"http-equiv": re.compile(r"^refresh$", re.I)},
        )

        if not meta:
            return None

        content = meta.get("content", "")
        match = re.search(r"url\s*=\s*['\"]?(.+?)['\"]?\s*$", content, re.I)

        if not match:
            return None

        target = match.group(1).strip().strip("'\"")
        return urljoin(base_url, target)

    except Exception:
        return None


def _redirect_parameter(html: str, base_url: str) -> Optional[str]:
    """
    Inspect only explicit redirect parameters.
    Do not select arbitrary product links from a page.
    """
    try:
        parsed = urlparse(base_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))

        keys = {
            "url", "u", "target", "dest", "destination",
            "redirect", "redirect_url", "redirect_uri",
        }

        for key, value in params.items():
            if key.lower() not in keys or not value:
                continue

            target = urljoin(base_url, value)

            if _valid_http_url(target) and store_for(target):
                return target

        return None
    except Exception:
        return None


def resolve_url(url: str) -> Optional[str]:
    """
    Resolve HTTP redirects, meta refresh and supported canonical URLs.
    JavaScript-only redirects may not be resolvable with requests.
    """
    if not url:
        return None

    current = url.strip()
    seen: set[str] = set()

    for _ in range(MAX_REDIRECTS):
        if not _valid_http_url(current) or current in seen:
            return None

        seen.add(current)

        if store_for(current):
            return current

        final_url, status, html = _request_html(current)

        if final_url in seen and final_url != current:
            if store_for(final_url):
                return final_url
            return None

        if store_for(final_url):
            return final_url

        if not html or status < 200 or status >= 400:
            return None

        meta_target = _meta_refresh_url(html, final_url)

        if meta_target and meta_target not in seen:
            current = meta_target
            continue

        param_target = _redirect_parameter(html, final_url)

        if param_target and param_target not in seen:
            current = param_target
            continue

        try:
            soup = BeautifulSoup(html, "html.parser")
            canonical = soup.find(
                "link",
                rel=lambda value: (
                    value
                    and "canonical" in (
                        value if isinstance(value, list) else value.split()
                    )
                ),
            )

            if canonical and canonical.get("href"):
                target = urljoin(final_url, canonical["href"].strip())

                if store_for(target):
                    return target
        except Exception:
            pass

        return None

    return None


def _remove_tracking_parameters(url: str) -> str:
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url

        tracking_prefixes = (
            "utm_", "fbclid", "gclid", "ref", "aff",
            "affiliate", "affid", "tag", "irclickid", "mc_",
        )

        kept = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lowered = key.lower()

            if any(
                lowered == prefix or lowered.startswith(prefix)
                for prefix in tracking_prefixes
            ):
                continue

            kept.append((key, value))

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(kept),
                "",
            )
        )
    except Exception:
        return url


def canonical_url(url: str) -> Optional[str]:
    if not url:
        return None

    retailer = store_for(url)
    if not retailer:
        return None

    url = _remove_tracking_parameters(url)
    parsed = urlparse(url)

    if retailer == "amazon":
        match = re.search(
            r"/(?:dp|gp/product)/([A-Z0-9]{8,20})",
            parsed.path,
            re.I,
        )

        if match:
            return f"https://www.amazon.in/dp/{match.group(1).upper()}"

        host = parsed.hostname or "www.amazon.in"
        return urlunparse(
            ("https", host, parsed.path, "", parsed.query, "")
        )

    if retailer == "flipkart":
        return urlunparse(
            ("https", "www.flipkart.com", parsed.path, "", parsed.query, "")
        )

    return url


def _walk_json_prices(data, candidates: list[float]) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in {
                "price", "priceamount", "lowprice", "sellingprice",
                "currentprice", "finalprice", "saleprice", "offerprice",
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
    Prefer product-specific structured data and retailer selectors.
    Avoid blindly returning the smallest number found in the entire page.
    """
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # OpenGraph product price.
    for selector in (
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
    ):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            price = clean_price(tag["content"])
            if price:
                return price

    # Product JSON-LD: inspect Product offers first.
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        objects = data if isinstance(data, list) else [data]

        for obj in objects:
            if not isinstance(obj, dict):
                continue

            kind = obj.get("@type", "")
            kinds = kind if isinstance(kind, list) else [kind]

            if "Product" not in kinds:
                continue

            offers = obj.get("offers", [])
            offers = offers if isinstance(offers, list) else [offers]

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                price = clean_price(
                    offer.get("price")
                    or offer.get("lowPrice")
                    or offer.get("priceSpecification", {}).get("price")
                    if isinstance(offer.get("priceSpecification", {}), dict)
                    else offer.get("price") or offer.get("lowPrice")
                )

                if price:
                    return price

    # Retailer-specific page selectors.
    selectors = (
        "span.a-price .a-offscreen",
        ".apexPriceToPay span.a-offscreen",
        "#priceblock_dealprice",
        "#priceblock_ourprice",
        "div.Nx9bqj",
        "div._30jeq3",
        "div._25b18c div._30jeq3",
        "div._1vC4OE",
    )

    for selector in selectors:
        try:
            element = soup.select_one(selector)
            if element:
                price = clean_price(element.get_text(" ", strip=True))
                if price:
                    return price
        except Exception:
            continue

    # Conservative fallback: price-like metadata only.
    for tag in soup.find_all("meta"):
        key = (
            tag.get("itemprop")
            or tag.get("property")
            or tag.get("name")
            or ""
        ).lower()

        if key in {"price", "product:price:amount", "twitter:data2"}:
            price = clean_price(tag.get("content"))
            if price:
                return price

    return None


def fetch_product_price(url: str) -> Optional[float]:
    if not store_for(url):
        return None

    final_url, status, html = _request_html(url)

    if status != 200 or not html or not store_for(final_url):
        return None

    return extract_page_price(html)


def get_offer_price(text: str, url: Optional[str] = None) -> Optional[float]:
    """
    Prefer a price stated in the Telegram post.
    Page scraping is a fallback and should be called via asyncio.to_thread.
    """
    price = extract_price_from_text(text or "")

    if price:
        return price

    if url:
        resolved = resolve_url(url)
        if resolved:
            canonical = canonical_url(resolved) or resolved
            return fetch_product_price(canonical)

    return None


def pricehistory_url(product_url: str) -> str:
    return f"https://pricehistory.app/?url={quote(product_url, safe='')}"


def extract_history(html: str) -> dict:
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    combined = text + "\n" + html

    patterns = [
        r"(?:all[-\s]time low|historical low|lowest price)"
        r"\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)",
        r'"(?:lowestPrice|lowest_price|historicalLow|historical_low|'
        r'allTimeLow|all_time_low|minPrice|min_price)"\s*:\s*"?(?P<p>[\d,.]+)',
    ]

    values = []

    for pattern in patterns:
        for match in re.finditer(pattern, combined, re.I):
            raw = match.groupdict().get("p") or match.group(1)
            price = clean_price(raw)

            if price:
                values.append(price)

    if not values:
        return {}

    # This is only a heuristic; the page may contain unrelated prices.
    return {"historical_low": min(values)}


def fetch_pricehistory(product_url: str) -> dict:
    try:
        _, status, html = _request_html(
            pricehistory_url(product_url),
            headers={
                **HEADERS,
                "Referer": product_url,
            },
        )

        if status != 200 or not html:
            return {}

        return extract_history(html)

    except Exception:
        return {}


async def gather_evidence(product_url: str) -> list[dict]:
    """
    Run all network work in threads so it does not block the asyncio loop.
    Each operation has a timeout and returns no evidence on failure.
    """
    tasks = [
        asyncio.to_thread(fetch_product_price, product_url),
        asyncio.to_thread(fetch_pricehistory, product_url),
    ]

    page_price, history = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    evidence: list[dict] = []

    if isinstance(page_price, (int, float)) and page_price > 50:
        evidence.append(
            {
                "provider": "retailer_page",
                "kind": "current_price",
                "price": float(page_price),
                "confidence": 0.70,
            }
        )

    if isinstance(history, dict) and history.get("historical_low"):
        evidence.append(
            {
                "provider": "pricehistory",
                "kind": "historical",
                "historical_low": float(history["historical_low"]),
                "confidence": 0.65,
                "url": pricehistory_url(product_url),
            }
        )

    return evidence
