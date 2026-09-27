# deal_validator.py
# VERSION: 3.1

import json
import re
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup


VERSION = "3.1"

MIN_PRICE = 1000
NEAR_LOW_PERCENT = 0.03
NEAR_LOW_MAX_RUPEES = 50
REQUEST_TIMEOUT = 15
MAX_REDIRECTS = 10


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Connection": "keep-alive",
}


SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ============================================================
# DOMAIN HELPERS
# ============================================================

AMAZON_DOMAINS = {
    "amazon.in",
    "amazon.com",
    "amazon.co.uk",
    "amazon.de",
    "amazon.fr",
    "amazon.it",
    "amazon.es",
    "amazon.ca",
    "amazon.com.au",
}

FLIPKART_DOMAINS = {
    "flipkart.com",
}

AMAZON_SHORT_DOMAINS = {
    "amzn.to",
}

FLIPKART_SHORT_DOMAINS = {
    "fkrt.co",
    "fkrt.cc",
}


def normalize_domain(url):
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        domain = (
            parsed.netloc
            or ""
        ).lower()

        if domain.startswith("www."):
            domain = domain[4:]

        return domain

    except Exception:
        return ""


def domain_matches(domain, domains):
    if not domain:
        return False

    for item in domains:
        if (
            domain == item
            or domain.endswith("." + item)
        ):
            return True

    return False


def is_amazon_domain(url):
    domain = normalize_domain(url)

    return domain_matches(
        domain,
        AMAZON_DOMAINS,
    )


def is_flipkart_domain(url):
    domain = normalize_domain(url)

    return domain_matches(
        domain,
        FLIPKART_DOMAINS,
    )


def is_amazon_short_url(url):
    domain = normalize_domain(url)

    return domain_matches(
        domain,
        AMAZON_SHORT_DOMAINS,
    )


def is_flipkart_short_url(url):
    domain = normalize_domain(url)

    return domain_matches(
        domain,
        FLIPKART_SHORT_DOMAINS,
    )


def identify_store(url):
    if not url:
        return None

    if is_amazon_domain(url):
        return "amazon"

    if is_flipkart_domain(url):
        return "flipkart"

    return None


def is_supported_short_url(url):
    return (
        is_amazon_short_url(url)
        or is_flipkart_short_url(url)
    )


# ============================================================
# PRICE CLEANING
# ============================================================

def clean_price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            number = float(value)

            if number > 0:
                return number

        except Exception:
            pass

        return None

    value = str(value).strip()

    value = value.replace(",", "")
    value = value.replace("₹", "")

    value = re.sub(
        r"\bRs\.?\b",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\bINR\b",
        "",
        value,
        flags=re.IGNORECASE,
    )

    match = re.search(
        r"\d+(?:\.\d+)?",
        value,
    )

    if not match:
        return None

    try:
        number = float(match.group())

        if number > 0:
            return number

    except Exception:
        pass

    return None


# ============================================================
# DEAL PRICE EXTRACTION
# ============================================================

def extract_price(text):
    if not text:
        return None

    text = str(text)

    patterns = [
        # Deal Price: ₹52,999
        (
            r"(?:deal\s*price|deal\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Offer Price: ₹52,999
        (
            r"(?:offer\s*price|offer)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Sale Price
        (
            r"(?:sale\s*price)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Current Price
        (
            r"(?:current\s*price)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Buy at / Now at
        (
            r"(?:buy\s*at|now\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # @52,999
        (
            r"@\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # ₹52,999
        (
            r"(?:₹|rs\.?|inr)"
            r"\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # 52999/-
        (
            r"\b"
            r"([\d,]+(?:\.\d+)?)"
            r"\s*/-"
        ),

        # 52999 only
        (
            r"\b"
            r"([\d,]+(?:\.\d+)?)"
            r"\s+only\b"
        ),
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if not match:
            continue

        price = clean_price(
            match.group(1)
        )

        if price is not None:
            return price

    return None


# ============================================================
# JSON PRICE EXTRACTION
# ============================================================

def find_prices_in_json(data):
    prices = []

    if isinstance(data, dict):

        for key, value in data.items():

            key_lower = str(key).lower()

            if key_lower in {
                "price",
                "priceamount",
                "currentprice",
                "sellingprice",
                "finalprice",
                "saleprice",
                "lowprice",
            }:

                price = clean_price(value)

                if price is not None:
                    prices.append(price)

            else:
                prices.extend(
                    find_prices_in_json(value)
                )

    elif isinstance(data, list):

        for item in data:

            prices.extend(
                find_prices_in_json(item)
            )

    return prices


# ============================================================
# FETCH PAGE
# ============================================================

def fetch_page(url):
    if not url:
        return None

    try:

        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return None

        return response.text

    except Exception:
        return None


# ============================================================
# RESOLVE URL
# ============================================================

def resolve_url(url):
    """
    Follow short-link and redirect chains.

    Examples:

        fkrt.cc
        -> fkrt.co
        -> flipkart.com/product/...

        amzn.to
        -> amazon.in/dp/...

    Returns final URL whenever possible.
    """

    if not url:
        return None

    current_url = url.strip()

    visited = set()

    for _ in range(MAX_REDIRECTS):

        if not current_url:
            break

        if current_url in visited:
            break

        visited.add(current_url)

        # Already reached a real store domain.
        if (
            is_amazon_domain(current_url)
            or is_flipkart_domain(current_url)
        ):
            return current_url

        try:

            response = SESSION.get(
                current_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )

        except Exception:
            break

        location = response.headers.get(
            "Location"
        )

        if location:

            next_url = requests.compat.urljoin(
                current_url,
                location,
            )

            current_url = next_url

            continue

        # No HTTP Location.
        # Try normal request to allow requests
        # to follow JS/meta redirects.
        try:

            response = SESSION.get(
                current_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            final_url = (
                response.url
                or current_url
            )

            if (
                is_amazon_domain(final_url)
                or is_flipkart_domain(final_url)
            ):
                return final_url

            # ------------------------------------------------
            # Meta refresh
            # ------------------------------------------------

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

            meta = soup.find(
                "meta",
                attrs={
                    "http-equiv": re.compile(
                        r"refresh",
                        re.IGNORECASE,
                    )
                },
            )

            if meta:

                content = meta.get(
                    "content",
                    "",
                )

                match = re.search(
                    r"url\s*=\s*(.+)",
                    content,
                    re.IGNORECASE,
                )

                if match:

                    next_url = requests.compat.urljoin(
                        final_url,
                        match.group(1).strip(
                            " '\""
                        ),
                    )

                    current_url = next_url

                    continue

            return final_url

        except Exception:
            break

    return current_url or url


# ============================================================
# AMAZON URL NORMALIZATION
# ============================================================

def normalize_amazon_url(url):
    if not url:
        return None

    match = re.search(
        r"/(?:dp|gp/product)/"
        r"([A-Z0-9]{8,20})",
        url,
        re.IGNORECASE,
    )

    if match:

        asin = match.group(1)

        return (
            "https://www.amazon.in/dp/"
            f"{asin}"
        )

    return url


# ============================================================
# FLIPKART URL NORMALIZATION
# ============================================================

def normalize_flipkart_url(url):
    if not url:
        return None

    parsed = urlparse(url)

    if not parsed.netloc:
        return url

    domain = parsed.netloc

    if not domain:
        domain = "www.flipkart.com"

    path = parsed.path or "/"

    return (
        "https://"
        f"{domain}"
        f"{path}"
    )


# ============================================================
# PRODUCT URL NORMALIZATION
# ============================================================

def normalize_product_url(url):
    if not url:
        return None

    store = identify_store(url)

    if store == "amazon":
        return normalize_amazon_url(url)

    if store == "flipkart":
        return normalize_flipkart_url(url)

    return url


# ============================================================
# PRICE FROM PRODUCT PAGE
# ============================================================

def extract_product_page_price(html):
    if not html:
        return None

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    scripts = soup.find_all(
        "script",
        type="application/ld+json",
    )

    for script in scripts:

        raw = (
            script.string
            or script.get_text()
        )

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        prices = find_prices_in_json(
            data
        )

        valid_prices = [
            price
            for price in prices
            if price > MIN_PRICE
        ]

        if valid_prices:

            # Prefer the lowest valid price
            # from structured product data.
            return min(valid_prices)

    # --------------------------------------------------------
    # Common product-page JSON
    # --------------------------------------------------------

    patterns = [

        r'"priceAmount"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"currentPrice"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"sellingPrice"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"finalPrice"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"salePrice"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'₹\s*([\d,]+(?:\.\d+)?)',

        r'(?:Rs\.?|INR)\s*'
        r'([\d,]+(?:\.\d+)?)',
    ]

    candidates = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE,
        )

        for value in matches:

            price = clean_price(
                value
            )

            if (
                price is not None
                and price > MIN_PRICE
            ):
                candidates.append(price)

    if candidates:
        return min(candidates)

    return None


# ============================================================
# PRICEHISTORY LOOKUP URL
# ============================================================

def build_pricehistory_url(
    product_url
):
    """
    Build PriceHistory URL from PRODUCT URL.

    No title search is performed.
    """

    if not product_url:
        return None

    encoded = quote(
        product_url,
        safe="",
    )

    return (
        "https://pricehistory.app/"
        f"?url={encoded}"
    )


# ============================================================
# PRICEHISTORY LOOKUP
# ============================================================

def pricehistory_lookup(
    product_url
):
    """
    Lookup PriceHistory using the resolved
    Amazon/Flipkart product URL.
    """

    if not product_url:
        return None

    store = identify_store(
        product_url
    )

    if store not in {
        "amazon",
        "flipkart",
    }:
        return None

    lookup_url = build_pricehistory_url(
        product_url
    )

    if not lookup_url:
        return None

    try:

        response = SESSION.get(
            lookup_url,
            headers={
                **HEADERS,
                "Referer": product_url,
            },
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return None

        return {
            "url": (
                response.url
                or lookup_url
            ),
            "html": response.text,
        }

    except Exception:
        return None


# ============================================================
# HISTORICAL LOW EXTRACTION
# ============================================================

def extract_historical_low(
    html
):
    if not html:
        return None

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    text = soup.get_text(
        " ",
        strip=True,
    )

    values = []

    # --------------------------------------------------------
    # Visible text
    # --------------------------------------------------------

    patterns = [

        (
            r"(?:all[\s\-]*time\s*low|"
            r"historical\s*low|"
            r"lowest\s*price)"
            r"\s*[:\-]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        (
            r"(?:lowest\s*ever|"
            r"lowest\s*recorded|"
            r"record\s*low)"
            r"\s*[:\-]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE,
        ):

            price = clean_price(
                match.group(1)
            )

            if price is not None:
                values.append(price)

    # --------------------------------------------------------
    # Raw JSON / HTML
    # --------------------------------------------------------

    raw_patterns = [

        r'"lowestPrice"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"lowest_price"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"historicalLow"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"historical_low"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"allTimeLow"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"all_time_low"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"minPrice"\s*:\s*"?'
        r"([\d,.]+)" r'"?',

        r'"min_price"\s*:\s*"?'
        r"([\d,.]+)" r'"?',
    ]

    for pattern in raw_patterns:

        for match in re.finditer(
            pattern,
            html,
            re.IGNORECASE,
        ):

            price = clean_price(
                match.group(1)
            )

            if price is not None:
                values.append(price)

    # --------------------------------------------------------
    # Data attributes
    # --------------------------------------------------------

    attribute_patterns = [

        r'data-low(?:est)?-price=["\']'
        r'([\d,.]+)',

        r'data-historical-low=["\']'
        r'([\d,.]+)',
    ]

    for pattern in attribute_patterns:

        for match in re.finditer(
            pattern,
            html,
            re.IGNORECASE,
        ):

            price = clean_price(
                match.group(1)
            )

            if price is not None:
                values.append(price)

    if not values:
        return None

    values = [
        value
        for value in values
        if value > 0
    ]

    if not values:
        return None

    return min(values)


# ============================================================
# SUSPICIOUS LOW
# ============================================================

def suspicious_historical_low(
    current_price,
    historical_low,
):
    if (
        current_price is None
        or historical_low is None
    ):
        return False

    if current_price >= 5000:

        if historical_low < (
            current_price * 0.08
        ):
            return True

    if current_price >= 2000:

        if historical_low < 100:
            return True

    return False


# ============================================================
# PRICE COMPARISON
# ============================================================

def compare_price(
    current_price,
    historical_low,
):
    if current_price is None:

        return {
            "status": "PRICE_UNKNOWN",
            "reason": (
                "Current deal price could "
                "not be determined"
            ),
        }

    if historical_low is None:

        return {
            "status": "HISTORICAL_LOW_UNKNOWN",
            "reason": (
                "Historical low could not "
                "be verified from PriceHistory"
            ),
        }

    # --------------------------------------------------------
    # New low
    # --------------------------------------------------------

    if current_price <= historical_low:

        return {
            "status": "NEW_LOW",
            "reason": (
                f"Current price "
                f"₹{current_price:.0f} "
                f"is at or below historical "
                f"low ₹{historical_low:.0f}"
            ),
        }

    # --------------------------------------------------------
    # Near low
    # --------------------------------------------------------

    tolerance = max(
        NEAR_LOW_MAX_RUPEES,
        historical_low * NEAR_LOW_PERCENT,
    )

    difference = (
        current_price
        - historical_low
    )

    if difference <= tolerance:

        return {
            "status": "NEAR_LOW",
            "reason": (
                f"Current price "
                f"₹{current_price:.0f} "
                f"is within ₹{tolerance:.0f} "
                f"of historical low "
                f"₹{historical_low:.0f}"
            ),
        }

    # --------------------------------------------------------
    # Not low
    # --------------------------------------------------------

    return {
        "status": "NOT_LOW",
        "reason": (
            f"Current price "
            f"₹{current_price:.0f} "
            f"is above historical low "
            f"₹{historical_low:.0f}"
        ),
    }


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_deal(
    title,
    price=None,
    url=None,
    source=None,
    text=None,
):
    try:

        title = (
            title or ""
        ).strip()

        text = (
            text or ""
        ).strip()

        # ----------------------------------------------------
        # 1. PRICE FROM DEAL MESSAGE
        # ----------------------------------------------------

        current_price = clean_price(
            price
        )

        if current_price is None:

            current_price = extract_price(
                text
            )

        # ----------------------------------------------------
        # 2. RESOLVE URL
        # ----------------------------------------------------

        original_url = url

        final_url = resolve_url(
            url
        )

        if not final_url:

            return {
                "status": "URL_UNKNOWN",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    "Product URL could "
                    "not be resolved"
                ),
                "source": source,
                "url": original_url,
            }

        # ----------------------------------------------------
        # 3. DETECT STORE AFTER REDIRECT
        # ----------------------------------------------------

        store = identify_store(
            final_url
        )

        # ----------------------------------------------------
        # 4. NORMALIZE PRODUCT URL
        # ----------------------------------------------------

        product_url = normalize_product_url(
            final_url
        )

        # Re-check after normalization.
        store = identify_store(
            product_url
        )

        # ----------------------------------------------------
        # 5. PRICE FROM PRODUCT PAGE
        # ----------------------------------------------------

        if current_price is None:

            product_html = fetch_page(
                product_url
            )

            if product_html:

                current_price = (
                    extract_product_page_price(
                        product_html
                    )
                )

        # ----------------------------------------------------
        # 6. PRICE UNKNOWN
        # ----------------------------------------------------

        if current_price is None:

            return {
                "status": "PRICE_UNKNOWN",
                "historical_low": None,
                "current_price": None,
                "category": None,
                "reason": (
                    "Deal price could not be "
                    "extracted from deal text "
                    "or product page"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
            }

        # ----------------------------------------------------
        # 7. FAST MINIMUM PRICE REJECT
        #
        # No PriceHistory request.
        # ----------------------------------------------------

        if current_price <= MIN_PRICE:

            return {
                "status": "PRICE_REJECT",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    f"Deal price "
                    f"₹{current_price:.0f} "
                    f"is not above minimum "
                    f"price ₹{MIN_PRICE}"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
            }

        # ----------------------------------------------------
        # 8. STORE CHECK
        # ----------------------------------------------------

        if store not in {
            "amazon",
            "flipkart",
        }:

            return {
                "status": "PRICEHISTORY_UNSUPPORTED",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    "Resolved URL is not an "
                    "Amazon or Flipkart "
                    "product URL"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
            }

        # ----------------------------------------------------
        # 9. PRICEHISTORY URL LOOKUP
        #
        # IMPORTANT:
        # URL based only.
        # No title search.
        # ----------------------------------------------------

        history_result = (
            pricehistory_lookup(
                product_url
            )
        )

        if not history_result:

            return {
                "status": "HISTORICAL_LOW_UNKNOWN",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    "PriceHistory lookup "
                    "failed for resolved "
                    "product URL"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
                "pricehistory_url": (
                    build_pricehistory_url(
                        product_url
                    )
                ),
            }

        # ----------------------------------------------------
        # 10. HISTORICAL LOW
        # ----------------------------------------------------

        historical_low = (
            extract_historical_low(
                history_result.get(
                    "html"
                )
            )
        )

        if historical_low is None:

            return {
                "status": "HISTORICAL_LOW_UNKNOWN",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    "PriceHistory page opened "
                    "but historical low could "
                    "not be extracted"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
                "pricehistory_url": (
                    history_result.get(
                        "url"
                    )
                ),
            }

        # ----------------------------------------------------
        # 11. SUSPICIOUS LOW
        # ----------------------------------------------------

        if suspicious_historical_low(
            current_price,
            historical_low,
        ):

            return {
                "status": "SUSPICIOUS_LOW",
                "historical_low": historical_low,
                "current_price": current_price,
                "category": None,
                "reason": (
                    f"Historical low "
                    f"₹{historical_low:.0f} "
                    f"appears suspicious "
                    f"against current price "
                    f"₹{current_price:.0f}"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
                "pricehistory_url": (
                    history_result.get(
                        "url"
                    )
                ),
            }

        # ----------------------------------------------------
        # 12. COMPARE
        # ----------------------------------------------------

        comparison = compare_price(
            current_price,
            historical_low,
        )

        return {
            "status": comparison[
                "status"
            ],
            "historical_low": historical_low,
            "current_price": current_price,
            "category": None,
            "reason": comparison[
                "reason"
            ],
            "source": source,
            "url": product_url,
            "original_url": original_url,
            "store": store,
            "pricehistory_url": (
                history_result.get(
                    "url"
                )
            ),
        }

    except Exception as e:

        return {
            "status": "VALIDATOR_ERROR",
            "historical_low": None,
            "current_price": None,
            "category": None,
            "reason": (
                f"{type(e).__name__}: {e}"
            ),
            "source": source,
            "url": url,
        }


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 70)
    print("DEAL VALIDATOR")
    print("VERSION:", VERSION)
    print("=" * 70)

    # --------------------------------------------------------
    # PRICE TESTS
    # --------------------------------------------------------

    price_tests = [
        "Deal Price: ₹24,999",
        "🔥 Deal at Rs 18,999",
        "Offer Price ₹34,999",
        "Now at ₹12,499",
        "Buy at INR 25,999",
        "₹49,999 only",
        "24999/-",
        "Deal Price - 24999",
        "Deal @ ₹12,999",
        "Current Price: Rs. 14,999",
        "Sale Price: INR 19,999",
        "ASUS RTX 5060 @52,999",
    ]

    print("\nPRICE TESTS")
    print("-" * 70)

    for item in price_tests:

        price = extract_price(
            item
        )

        print(
            f"{item:45} -> "
            f"₹{price if price is not None else 'N/A'}"
        )

    # --------------------------------------------------------
    # URL TESTS
    # --------------------------------------------------------

    url_tests = [
        "https://www.amazon.in/dp/B0F8Q96N8G",
        "https://amzn.to/example",
        "https://www.flipkart.com/example/p/abc",
        "https://fkrt.co/example",
        "https://fkrt.cc/example",
    ]

    print("\nURL TESTS")
    print("-" * 70)

    for item in url_tests:

        print(
            "URL:",
            item,
        )

        print(
            "STORE:",
            identify_store(item),
        )

        print(
            "SHORT:",
            is_supported_short_url(item),
        )

        print(
            "NORMALIZED:",
            normalize_product_url(item),
        )

        print()

    print("=" * 70)
    print("VALIDATOR TEST COMPLETE")
    print("=" * 70)
