from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import requests
from bs4 import BeautifulSoup


TIMEOUT = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


AMAZON = {
    "amazon.in",
    "amazon.com",
}

FLIPKART = {
    "flipkart.com",
}

SHORT_AMAZON = {
    "amzn.to",
}

SHORT_FLIPKART = {
    "fkrt.co",
    "fkrt.cc",
    "fkrt.it",
}

SHORT_DOMAINS = SHORT_AMAZON | SHORT_FLIPKART


# ---------------------------------------------------------
# URL helpers
# ---------------------------------------------------------

def domain(url: str) -> str:
    try:
        d = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]

        if d.startswith("www."):
            d = d[4:]

        return d
    except Exception:
        return ""


def store_for(url: str) -> Optional[str]:
    d = domain(url)

    if d in AMAZON or any(d.endswith("." + x) for x in AMAZON):
        return "amazon"

    if d in FLIPKART or any(d.endswith("." + x) for x in FLIPKART):
        return "flipkart"

    return None


def is_short_url(url: str) -> bool:
    d = domain(url)
    return d in SHORT_DOMAINS


def _remove_tracking_parameters(url: str) -> str:
    try:
        parsed = urlparse(url)

        if not parsed.query:
            return url

        tracking_prefixes = (
            "utm_",
            "fbclid",
            "gclid",
            "aff_",
            "affiliate",
            "ref_",
            "tag",
            "ascsubtag",
            "affid",
            "affid",
            "irclickid",
            "irgwc",
            "psc",
            "pd_rd_",
        )

        tracking_exact = {
            "ref",
            "linkCode",
            "camp",
            "creative",
            "creativeASIN",
            "sprefix",
            "qid",
        }

        clean = []

        for key, value in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        ):
            lower_key = key.lower()

            if key in tracking_exact:
                continue

            if any(
                lower_key.startswith(prefix.lower())
                for prefix in tracking_prefixes
            ):
                continue

            clean.append((key, value))

        query = urlencode(clean)

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


# ---------------------------------------------------------
# URL resolution
# ---------------------------------------------------------

def _meta_refresh_url(
    html: str,
    base_url: str,
) -> Optional[str]:

    if not html:
        return None

    try:
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        meta = soup.find(
            "meta",
            attrs={
                "http-equiv": re.compile(
                    r"refresh",
                    re.I,
                )
            },
        )

        if not meta:
            return None

        content = meta.get(
            "content",
            "",
        )

        m = re.search(
            r"url\s*=\s*(.+)",
            content,
            re.I,
        )

        if not m:
            return None

        target = m.group(1).strip(
            " '\""
        )

        return urljoin(
            base_url,
            target,
        )

    except Exception:
        return None


def _canonical_link_from_html(
    html: str,
    base_url: str,
) -> Optional[str]:

    if not html:
        return None

    try:
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        link = soup.find(
            "link",
            attrs={
                "rel": lambda value: (
                    value
                    and (
                        "canonical"
                        in (
                            value
                            if isinstance(value, list)
                            else [value]
                        )
                    )
                )
            },
        )

        if not link:
            return None

        href = link.get("href")

        if not href:
            return None

        return urljoin(
            base_url,
            href,
        )

    except Exception:
        return None


def resolve_url(url: str) -> Optional[str]:
    if not url:
        return None

    current = url.strip()

    if not current:
        return None

    seen = set()

    for _ in range(8):
        if not current:
            return None

        if current in seen:
            break

        seen.add(current)

        # Already a supported retailer URL.
        if store_for(current):
            return current

        try:
            response = requests.get(
                current,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )

            final = response.url or current

            # Redirect already landed on retailer.
            if store_for(final):
                return final

            # Try canonical link.
            canonical = _canonical_link_from_html(
                response.text or "",
                final,
            )

            if canonical and store_for(canonical):
                return canonical

            # Try meta refresh.
            meta_url = _meta_refresh_url(
                response.text or "",
                final,
            )

            if meta_url:
                if meta_url in seen:
                    break

                current = meta_url
                continue

            # Some affiliate pages expose the retailer URL
            # directly in the HTML.
            html = response.text or ""

            retailer_candidates = re.findall(
                r'https?://[^\s"\'<>]+',
                html,
            )

            found_retailer = None

            for candidate in retailer_candidates:
                candidate = candidate.rstrip(
                    ".,);]}"
                )

                if store_for(candidate):
                    found_retailer = candidate
                    break

            if found_retailer:
                return found_retailer

            return final

        except requests.RequestException:
            return current

        except Exception:
            return current

    if store_for(current):
        return current

    return None


# ---------------------------------------------------------
# Canonical product URLs
# ---------------------------------------------------------

def canonical_url(url: str) -> Optional[str]:
    if not url:
        return None

    store = store_for(url)

    if store == "amazon":
        m = re.search(
            r"/(?:dp|gp/product)/([A-Z0-9]{8,20})",
            url,
            re.I,
        )

        if m:
            return (
                "https://www.amazon.in/dp/"
                + m.group(1).upper()
            )

        return _remove_tracking_parameters(
            url
        )

    if store == "flipkart":
        parsed = urlparse(url)

        if not parsed.path:
            return url

        clean = urlunparse(
            (
                "https",
                "www.flipkart.com",
                parsed.path,
                "",
                parsed.query,
                "",
            )
        )

        return _remove_tracking_parameters(
            clean
        )

    return _remove_tracking_parameters(
        url
    )


# ---------------------------------------------------------
# Price helpers
# ---------------------------------------------------------

def clean_price(value: Any) -> Optional[float]:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            price = float(value)

            if price > 0:
                return price
        except Exception:
            return None

        return None

    text = str(value).strip()

    if not text:
        return None

    text = (
        text.replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
        .replace(",", "")
        .strip()
    )

    m = re.search(
        r"\d+(?:\.\d+)?",
        text,
    )

    if not m:
        return None

    try:
        price = float(m.group(0))

        if price > 0:
            return price

    except ValueError:
        pass

    return None


def _walk_json_prices(
    obj: Any,
) -> List[float]:

    prices: List[float] = []

    if isinstance(obj, dict):

        for key, value in obj.items():

            key_lower = str(key).lower()

            if any(
                token in key_lower
                for token in (
                    "price",
                    "saleprice",
                    "currentprice",
                    "offerprice",
                    "dealprice",
                    "sellingprice",
                    "finalprice",
                    "buyingprice",
                    "minprice",
                )
            ):
                price = clean_price(value)

                if price is not None:
                    prices.append(price)

            prices.extend(
                _walk_json_prices(value)
            )

    elif isinstance(obj, list):

        for item in obj:
            prices.extend(
                _walk_json_prices(item)
            )

    return prices


# ---------------------------------------------------------
# Product page price extraction
# ---------------------------------------------------------

def extract_page_price(
    html: str,
    store: Optional[str] = None,
) -> Optional[float]:

    if not html:
        return None

    candidates: List[float] = []

    # -----------------------------------------------------
    # JSON-LD
    # -----------------------------------------------------

    try:
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        scripts = soup.find_all(
            "script",
            attrs={
                "type": re.compile(
                    r"application/ld\+json",
                    re.I,
                )
            },
        )

        for script in scripts:
            raw = script.string or script.get_text()

            if not raw:
                continue

            try:
                data = json.loads(raw)

                candidates.extend(
                    _walk_json_prices(data)
                )

            except Exception:
                continue

    except Exception:
        pass

    # -----------------------------------------------------
    # Generic HTML price patterns
    # -----------------------------------------------------

    patterns = [
        r'"(?:price|salePrice|currentPrice|offerPrice|dealPrice|sellingPrice|finalPrice|buyingPrice|minPrice|min_price)"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)',
        r'"(?:price|salePrice|currentPrice|offerPrice|dealPrice|sellingPrice|finalPrice|buyingPrice|minPrice|min_price)"\s*:\s*([\d,]+(?:\.\d+)?)',
        r'(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)',
        r'([\d,]+(?:\.\d+)?)\s*(?:₹|Rs\.?|INR)',
    ]

    for pattern in patterns:

        try:
            matches = re.findall(
                pattern,
                html,
                re.I,
            )

            for value in matches:
                price = clean_price(value)

                if price is not None:
                    candidates.append(price)

        except Exception:
            continue

    # -----------------------------------------------------
    # Store-specific hints
    # -----------------------------------------------------

    if store == "flipkart":

        flipkart_patterns = [
            r'"sellingPrice"\s*:\s*([\d,]+(?:\.\d+)?)',
            r'"selling_price"\s*:\s*([\d,]+(?:\.\d+)?)',
            r'"finalPrice"\s*:\s*([\d,]+(?:\.\d+)?)',
            r'"final_price"\s*:\s*([\d,]+(?:\.\d+)?)',
            r'"price"\s*:\s*([\d,]+(?:\.\d+)?)',
        ]

        for pattern in flipkart_patterns:

            matches = re.findall(
                pattern,
                html,
                re.I,
            )

            for value in matches:
                price = clean_price(value)

                if price is not None:
                    candidates.append(price)

    if store == "amazon":

        amazon_patterns = [
            r'"priceToPay"\s*:\s*\{.*?"price"\s*:\s*([\d,]+(?:\.\d+)?)',
            r'"displayPrice"\s*:\s*"₹\s*([\d,]+(?:\.\d+)?)',
            r'"priceAmount"\s*:\s*([\d,]+(?:\.\d+)?)',
        ]

        for pattern in amazon_patterns:

            matches = re.findall(
                pattern,
                html,
                re.I | re.S,
            )

            for value in matches:
                price = clean_price(value)

                if price is not None:
                    candidates.append(price)

    if not candidates:
        return None

    # Remove obviously invalid values.
    candidates = [
        p
        for p in candidates
        if p > 0
    ]

    if not candidates:
        return None

    # Prefer the lowest realistic positive price.
    return min(candidates)


def fetch_product_price(
    url: str,
) -> Optional[float]:

    if not url:
        return None

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return None

        final_url = response.url or url

        store = store_for(final_url)

        return extract_page_price(
            response.text or "",
            store,
        )

    except requests.RequestException:
        return None

    except Exception:
        return None


# ---------------------------------------------------------
# Price history
# ---------------------------------------------------------

def pricehistory_url(
    url: str,
) -> Optional[str]:

    if not url:
        return None

    parsed = urlparse(url)

    if not parsed.netloc:
        return None

    store = store_for(url)

    if store == "amazon":
        return (
            "https://pricehistory.app/"
            + url
        )

    if store == "flipkart":
        return (
            "https://pricehistory.app/"
            + url
        )

    return None


def extract_history(
    html: str,
) -> Dict[str, Optional[float]]:

    result: Dict[str, Optional[float]] = {
        "historical_low": None,
        "current_price": None,
    }

    if not html:
        return result

    candidates: List[float] = []

    patterns = [
        r'"(?:lowest|lowestPrice|allTimeLow|historicalLow|minPrice|min_price)"\s*:\s*"?([\d,]+(?:\.\d+)?)',
        r'"(?:currentPrice|current_price|price)"\s*:\s*"?([\d,]+(?:\.\d+)?)',
        r'(?:lowest|all[- ]time low|historical low|minimum price)[^₹\d]{0,30}(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)',
        r'(?:current price|current price is)[^₹\d]{0,30}(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)',
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.I,
        )

        for value in matches:
            price = clean_price(value)

            if price is not None:
                candidates.append(price)

    if candidates:
        result["historical_low"] = min(
            candidates
        )

    return result


def fetch_pricehistory(
    url: str,
) -> Dict[str, Optional[float]]:

    history_url = pricehistory_url(
        url
    )

    if not history_url:
        return {
            "historical_low": None,
            "current_price": None,
        }

    try:
        response = requests.get(
            history_url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return {
                "historical_low": None,
                "current_price": None,
            }

        return extract_history(
            response.text or ""
        )

    except requests.RequestException:
        return {
            "historical_low": None,
            "current_price": None,
        }

    except Exception:
        return {
            "historical_low": None,
            "current_price": None,
        }


# ---------------------------------------------------------
# Evidence gathering
# ---------------------------------------------------------

async def gather_evidence(
    url: str,
) -> List[Dict[str, Any]]:

    import asyncio

    evidence: List[Dict[str, Any]] = []

    if not url:
        return evidence

    canonical = canonical_url(
        url
    )

    if not canonical:
        return evidence

    store = store_for(
        canonical
    )

    # -----------------------------------------------------
    # Retailer product page
    # -----------------------------------------------------

    try:
        page_price = await asyncio.to_thread(
            fetch_product_price,
            canonical,
        )

        if page_price is not None:

            evidence.append(
                {
                    "provider": store or "retailer",
                    "kind": "current_price",
                    "price": page_price,
                    "historical_low": None,
                    "url": canonical,
                    "confidence": 0.90,
                }
            )

    except Exception:
        pass

    # -----------------------------------------------------
    # Price history
    # -----------------------------------------------------

    try:
        history = await asyncio.to_thread(
            fetch_pricehistory,
            canonical,
        )

        historical_low = history.get(
            "historical_low"
        )

        current_price = history.get(
            "current_price"
        )

        if (
            historical_low is not None
            or current_price is not None
        ):

            evidence.append(
                {
                    "provider": "pricehistory",
                    "kind": "price_history",
                    "price": current_price,
                    "historical_low": historical_low,
                    "url": pricehistory_url(
                        canonical
                    ),
                    "confidence": 0.70,
                }
            )

    except Exception:
        pass

    return evidence