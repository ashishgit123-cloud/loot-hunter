from __future__ import annotations

import asyncio
import json
import re
from typing import Optional
from urllib.parse import quote, urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup


TIMEOUT = 12

MIN_PRICE = 1000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
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


def domain(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        host = parsed.hostname or ""
        return host.lower().lstrip("www.")
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
    return (
        d in SHORT_DOMAINS
        or any(d.endswith("." + x) for x in SHORT_DOMAINS)
    )


def clean_price(value) -> Optional[float]:
    if value is None:
        return None

    text = str(value).replace("₹", "").replace("INR", "").strip()
    m = re.search(
        r"\d+(?:,\d{2,3})*(?:\.\d+)?",
        text,
    )

    if not m:
        return None

    try:
        price = float(m.group(0).replace(",", ""))
        # Filter out numbers that look like percentages or unrealistically low prices (< 50)
        return price if price > 50 else None
    except (ValueError, TypeError):
        return None


def extract_price_from_text(text: str) -> Optional[float]:
    """
    Extracts deal price from raw Telegram message text or titles.
    - Ignores percentages (e.g., 80% off, upto 50%).
    - Ignores cash discounts/off amounts (e.g., 17,250 off, save ₹5000).
    - Handles currency patterns like ₹629, Rs. 629, @4999, 4,999/-
    """
    if not text:
        return None

    # 1. Clean up percentage discount clauses
    cleaned_text = re.sub(r'\d+\s*%\s*(?:off|discount)?', '', text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r'(?:upto|flat|save|min|max|extra)\s*\d+\s*%', '', cleaned_text, flags=re.IGNORECASE)

    # 2. Clean up cash discount/off phrases so they aren't mistakenly picked as product price
    # e.g., "17,250 off", "save ₹5000", "₹2000 discount", "discount of 500"
    cleaned_text = re.sub(r'(?:off|discount|save|saving|cashback)\b[^,.\n]*?(?:₹|Rs\.?|INR)?\s*[\d,]+(?:\.\d+)?', '', cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r'(?:₹|Rs\.?|INR)?\s*[\d,]+(?:\.\d+)?\b[^,.\n]*?(?:off|discount|saving|cashback)', '', cleaned_text, flags=re.IGNORECASE)

    # 3. Match strict currency/price patterns for actual selling price
    patterns = [
        r"(?:₹|Rs\.?|INR)\s*(?P<p>[\d,]+(?:\.\d+)?)(?=\b|\s|$)",
        r"@\s*(?P<p>[\d,]+(?:\.\d+)?)",
        r"(?P<p>[\d,]+(?:\.\d+)?)\s*/-"
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned_text, re.I)
        if match:
            raw = match.group("p").rstrip(".")
            try:
                price = float(raw.replace(",", ""))
                if price > 50:  # Valid price threshold
                    return price
            except ValueError:
                continue

    return clean_price(cleaned_text)    

def get_offer_price(text: str, url: Optional[str] = None) -> Optional[float]:
    """
    Smart Fallback:
    1. Extracts price from text safely (ignoring percentages).
    2. Fallback to live product page scraping if needed.
    """
    price = extract_price_from_text(text)
    if price and price > 0:
        return price

    if url:
        resolved = resolve_url(url)
        if resolved:
            canonical = canonical_url(resolved) or resolved
            web_price = fetch_product_price(canonical)
            if web_price and web_price > 0:
                return web_price

    return None


def _meta_refresh_url(html: str, base_url: str) -> Optional[str]:
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
        match = re.search(r"url\s*=\s*(.+)", content, re.I)
        if not match:
            return None

        target = match.group(1).strip(" '\"")
        return urljoin(base_url, target)
    except Exception:
        return None


def resolve_url(url: str) -> Optional[str]:
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
            retailer = store_for(final)
            if retailer:
                return final

            meta_target = _meta_refresh_url(response.text or "", final)
            if meta_target and meta_target not in seen:
                current = meta_target
                continue

            try:
                soup = BeautifulSoup(response.text or "", "html.parser")
                canonical_tag = soup.find(
                    "link",
                    rel=lambda value: value and "canonical" in value,
                )
                if canonical_tag and canonical_tag.get("href"):
                    canonical_target = urljoin(final, canonical_tag.get("href"))
                    if canonical_target not in seen and store_for(canonical_target):
                        return canonical_target
            except Exception:
                pass

            return None
        except requests.RequestException:
            return None

    return None


def _remove_tracking_parameters(url: str) -> str:
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url

        keep = []
        tracking_prefixes = (
            "utm_", "fbclid", "gclid", "ref", "aff",
            "affiliate", "affid", "tag", "irclickid", "mc_",
        )

        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            key_lower = key.lower()
            if any(key_lower == p or key_lower.startswith(p) for p in tracking_prefixes):
                continue
            keep.append((key, value))

        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(keep), ""))
    except Exception:
        return url


def canonical_url(url: str) -> Optional[str]:
    if not url:
        return None

    store = store_for(url)
    if not store:
        return None

    url = _remove_tracking_parameters(url)

    if store == "amazon":
        match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{8,20})", url, re.I)
        if match:
            return f"https://www.amazon.in/dp/{match.group(1).upper()}"
        parsed = urlparse(url)
        return urlunparse(("https", parsed.netloc or "www.amazon.in", parsed.path, "", parsed.query, ""))

    if store == "flipkart":
        parsed = urlparse(url)
        if not parsed.path:
            return "https://www.flipkart.com"
        return urlunparse(("https", "www.flipkart.com", parsed.path, "", parsed.query, ""))

    return url


def _walk_json_prices(data, candidates: list[float]) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in {
                "price", "priceamount", "lowprice", "sellingprice",
                "currentprice", "finalprice", "saleprice", "offerprice",
            }:
                price = clean_price(value)
                if price and price > 50:
                    candidates.append(price)
            else:
                _walk_json_prices(value, candidates)
    elif isinstance(data, list):
        for item in data:
            _walk_json_prices(item, candidates)


def extract_page_price(html: str) -> Optional[float]:
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[float] = []

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            _walk_json_prices(data, candidates)
        except (ValueError, TypeError):
            continue

    if candidates:
        return min(candidates)

    patterns = [
        r'"(?:currentPrice|sellingPrice|finalPrice|salePrice|offerPrice)"\s*:\s*"?(?P<p>[\d,.]+)',
        r'"(?:selling_price|sellingPrice|selling_price_value)"\s*:\s*"?(?P<p>[\d,.]+)',
        r'"price"\s*:\s*"?(?P<p>[\d,.]+)',
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, html, re.I):
            price = clean_price(match.group("p"))
            if price and price > 50:
                candidates.append(price)

    if candidates:
        return min(candidates)

    for pattern in [r"(?:₹|Rs\.?|INR)\s*(?P<p>[\d,]+(?:\.\d+)?)"]:
        for match in re.finditer(pattern, html, re.I):
            price = clean_price(match.group("p"))
            if price and price > 50:
                candidates.append(price)

    return min(candidates) if candidates else None


def fetch_product_price(url: str) -> Optional[float]:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        price_val = 0.0

        # 1. Amazon Specific Selectors
        if "amazon" in url.lower():
            amazon_selectors = [
                "span.a-price-whole",
                "span.a-offscreen",
                "#priceblock_ourprice",
                "#priceblock_dealprice",
                ".apexPriceToPay span.a-offscreen"
            ]
            for sel in amazon_selectors:
                element = soup.select_one(sel)
                if element:
                    price_text = element.get_text().strip()
                    clean_price_val = clean_price(price_text)
                    if clean_price_val and clean_price_val > 50:
                        price_val = clean_price_val
                        break

        # 2. Flipkart Specific Selectors
        elif "flipkart" in url.lower():
            flipkart_selectors = [
                "div._30jeq3",
                "div._25b18c div._30jeq3",
                "div.Nx9bqj",
                "div._1vC4OE"
            ]
            for sel in flipkart_selectors:
                element = soup.select_one(sel)
                if element:
                    price_text = element.get_text().strip()
                    clean_price_val = clean_price(price_text)
                    if clean_price_val and clean_price_val > 50:
                        price_val = clean_price_val
                        break

        # 3. Fallback to OpenGraph / Meta tags or general page price extractor if specific selectors miss
        if price_val == 0.0:
            meta_price = soup.find('meta', property='product:price:amount') or soup.find('meta', attrs={'name': 'twitter:data2'})
            if meta_price and meta_price.get('content'):
                try:
                    price_val = float(meta_price['content'].strip())
                except ValueError:
                    pass

        if price_val == 0.0:
            price_val = extract_page_price(resp.text) or 0.0

        return price_val if price_val > 50 else None

    except Exception as e:
        print(f"Fetch price error for {url}: {e}")
        
    return None


def pricehistory_url(product_url: str) -> str:
    return f"https://pricehistory.app/?url={quote(product_url, safe='')}"


def extract_history(html: str) -> dict:
    if not html:
        return {}

    values: list[float] = []
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    patterns = [
        (
            r"(?:all[-\s]*time\s*low|historical\s*low|lowest\s*price)"
            r"\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)"
        ),
        (
            r'"(?:lowestPrice|lowest_price|historicalLow|historical_low|'
            r'allTimeLow|all_time_low|minPrice|min_price)"\s*:\s*"?(?P<p>[\d,.]+)'
        ),
    ]

    combined = text + "\n" + html
    for pattern in patterns:
        for match in re.finditer(pattern, combined, re.I):
            raw_price = match.groupdict().get("p") if match.groupdict() else match.group(1)
            price = clean_price(raw_price)
            if price and price > 50:
                values.append(price)

    if not values:
        return {}

    return {"historical_low": min(values)}


def fetch_pricehistory(product_url: str) -> dict:
    try:
        response = requests.get(
            pricehistory_url(product_url),
            headers={**HEADERS, "Referer": product_url},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code != 200:
            return {}

        data = extract_history(response.text)
        if data:
            data["url"] = response.url
        return data
    except requests.RequestException:
        return {}


async def gather_evidence(product_url: str) -> list[dict]:
    tasks = [
        asyncio.to_thread(fetch_product_price, product_url),
        asyncio.to_thread(fetch_pricehistory, product_url),
    ]

    page_price, history = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[dict] = []

    if isinstance(page_price, (int, float)) and page_price > 50:
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