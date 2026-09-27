# deal_validator.py
# VERSION: 3.0
#
# FLOW:
# Deal text
#   -> price from message
#   -> resolve URL
#   -> price from product page if needed
#   -> PriceHistory lookup using RESOLVED PRODUCT URL
#   -> historical low
#   -> compare
#
# IMPORTANT:
# PriceHistory lookup is URL based.
# Product title is NOT used for PriceHistory search.

import json
import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


VERSION = "3.0"

MIN_PRICE = 1000
NEAR_LOW_PERCENT = 0.03
NEAR_LOW_MAX_RUPEES = 50
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


# ============================================================
# REQUEST SESSION
# ============================================================

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ============================================================
# PRICE CLEANING
# ============================================================

def clean_price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            number = float(value)
            return number if number > 0 else None
        except Exception:
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
        return number if number > 0 else None
    except Exception:
        return None


# ============================================================
# PRICE EXTRACTION FROM TEXT
# ============================================================

def extract_price(text):
    if not text:
        return None

    text = str(text)

    patterns = [
        # Deal Price / Deal at
        r"(?:deal\s*price|deal\s*at)"
        r"\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Offer Price / Offer
        r"(?:offer\s*price|offer)"
        r"\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Sale Price
        r"(?:sale\s*price)"
        r"\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Current Price
        r"(?:current\s*price)"
        r"\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Buy at / Now at
        r"(?:buy\s*at|now\s*at)"
        r"\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Explicit currency
        r"(?:₹|rs\.?|inr)"
        r"\s*"
        r"([\d,]+(?:\.\d+)?)",

        # @ 52999
        r"@\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # 52999/-
        r"\b([\d,]+(?:\.\d+)?)\s*/-",

        # 52999 only
        r"\b([\d,]+(?:\.\d+)?)\s+only\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if not match:
            continue

        price = clean_price(match.group(1))

        if price is not None:
            return price

    return None


# ============================================================
# PRODUCT PAGE PRICE EXTRACTION
# ============================================================

def extract_product_page_price(html):
    if not html:
        return None

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    scripts = soup.find_all(
        "script",
        type="application/ld+json",
    )

    for script in scripts:
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        prices = find_prices_in_json(data)

        for price in prices:
            if price > MIN_PRICE:
                return price

    # --------------------------------------------------------
    # Common Amazon / Flipkart price patterns
    # --------------------------------------------------------

    patterns = [
        # priceAmount
        r'"priceAmount"\s*:\s*"?([\d,.]+)"?',

        # current price
        r'"currentPrice"\s*:\s*"?([\d,.]+)"?',

        # selling price
        r'"sellingPrice"\s*:\s*"?([\d,.]+)"?',

        # final price
        r'"finalPrice"\s*:\s*"?([\d,.]+)"?',

        # price
        r'"price"\s*:\s*"?([\d,.]+)"?',

        # ₹24,999
        r"₹\s*([\d,]+(?:\.\d+)?)",

        # Rs. 24,999
        r"(?:Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:
        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE,
        )

        for value in matches:
            price = clean_price(value)

            if price is not None and price > MIN_PRICE:
                return price

    return None


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

    except requests.RequestException:
        return None

    except Exception:
        return None


# ============================================================
# URL RESOLUTION
# ============================================================

def resolve_url(url):
    if not url:
        return None

    try:
        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        final_url = response.url

        if final_url:
            return final_url

        return url

    except requests.RequestException:
        return url

    except Exception:
        return url


# ============================================================
# STORE / PRODUCT URL DETECTION
# ============================================================

def is_amazon_url(url):
    if not url:
        return False

    value = url.lower()

    return (
        "amazon.in" in value
        or "amazon.com" in value
        or "amzn.to" in value
    )


def is_flipkart_url(url):
    if not url:
        return False

    value = url.lower()

    return (
        "flipkart.com" in value
        or "fkrt.co" in value
    )


def identify_store(url):
    if is_amazon_url(url):
        return "amazon"

    if is_flipkart_url(url):
        return "flipkart"

    return None


# ============================================================
# NORMALIZE PRODUCT URL
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


def normalize_amazon_url(url):
    """
    Keep the canonical Amazon product path where possible.
    """

    match = re.search(
        r"/(?:dp|gp/product)/([A-Z0-9]{8,20})",
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


def normalize_flipkart_url(url):
    """
    Remove tracking/query parameters from Flipkart URL
    while keeping the product URL.
    """

    match = re.search(
        r"(https?://[^/]*flipkart\.com/[^?]+)",
        url,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return url


# ============================================================
# PRICEHISTORY URL
# ============================================================

def build_pricehistory_url(product_url):
    """
    PriceHistory lookup is based on the resolved product URL.

    We intentionally DO NOT search by product title.
    """

    if not product_url:
        return None

    encoded_url = quote(
        product_url,
        safe="",
    )

    return (
        "https://pricehistory.app/"
        f"?url={encoded_url}"
    )


# ============================================================
# PRICEHISTORY LOOKUP
# ============================================================

def pricehistory_lookup(product_url):
    """
    Open PriceHistory using the resolved Amazon/Flipkart URL.

    Returns:
        {
            "url": ...,
            "html": ...,
        }

    or None
    """

    if not product_url:
        return None

    store = identify_store(product_url)

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
            "url": response.url or lookup_url,
            "html": response.text,
        }

    except requests.RequestException:
        return None

    except Exception:
        return None


# ============================================================
# HISTORICAL LOW EXTRACTION
# ============================================================

def extract_historical_low(html):
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
            r"lowest\s*recorded)"
            r"\s*[:\-]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),
        (
            r"(?:record\s*low|"
            r"all\s*time\s*minimum)"
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
    # Raw HTML / JSON
    # --------------------------------------------------------

    raw_patterns = [
        r'"lowestPrice"\s*:\s*"?([\d,.]+)"?',
        r'"lowest_price"\s*:\s*"?([\d,.]+)"?',
        r'"historicalLow"\s*:\s*"?([\d,.]+)"?',
        r'"historical_low"\s*:\s*"?([\d,.]+)"?',
        r'"allTimeLow"\s*:\s*"?([\d,.]+)"?',
        r'"all_time_low"\s*:\s*"?([\d,.]+)"?',
        r'"minPrice"\s*:\s*"?([\d,.]+)"?',
        r'"min_price"\s*:\s*"?([\d,.]+)"?',
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
        r'data-low(?:est)?-price=["\']([\d,.]+)',
        r'data-historical-low=["\']([\d,.]+)',
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

    # Ignore impossible zero/negative values.
    values = [
        value
        for value in values
        if value > 0
    ]

    if not values:
        return None

    return min(values)


# ============================================================
# SUSPICIOUS HISTORICAL LOW
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
        if historical_low < current_price * 0.08:
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
                "Current deal price could not "
                "be determined"
            ),
        }

    if historical_low is None:
        return {
            "status": "HISTORICAL_LOW_UNKNOWN",
            "reason": (
                "Historical low could not be "
                "verified from PriceHistory"
            ),
        }

    if current_price <= historical_low:
        return {
            "status": "NEW_LOW",
            "reason": (
                f"Current price ₹{current_price:.0f} "
                f"is at or below historical low "
                f"₹{historical_low:.0f}"
            ),
        }

    tolerance = max(
        NEAR_LOW_MAX_RUPEES,
        historical_low * NEAR_LOW_PERCENT,
    )

    difference = (
        current_price - historical_low
    )

    if difference <= tolerance:
        return {
            "status": "NEAR_LOW",
            "reason": (
                f"Current price ₹{current_price:.0f} "
                f"is within ₹{tolerance:.0f} "
                f"of historical low "
                f"₹{historical_low:.0f}"
            ),
        }

    return {
        "status": "NOT_LOW",
        "reason": (
            f"Current price ₹{current_price:.0f} "
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
        title = (title or "").strip()
        text = (text or "").strip()

        if not title:
            title = "Unknown Product"

        # ----------------------------------------------------
        # 1. PRICE FROM MESSAGE
        # ----------------------------------------------------

        current_price = clean_price(price)

        if current_price is None:
            current_price = extract_price(text)

        # ----------------------------------------------------
        # 2. RESOLVE URL
        # ----------------------------------------------------

        original_url = url
        final_url = resolve_url(url)

        if not final_url:
            return {
                "status": "URL_UNKNOWN",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    "Product URL could not be resolved"
                ),
                "source": source,
                "url": original_url,
            }

        # ----------------------------------------------------
        # 3. NORMALIZE AMAZON / FLIPKART URL
        # ----------------------------------------------------

        product_url = normalize_product_url(
            final_url
        )

        store = identify_store(
            product_url
        )

        # ----------------------------------------------------
        # 4. RECOVER PRICE FROM PRODUCT PAGE
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
        # 5. PRICE STILL UNKNOWN
        # ----------------------------------------------------

        if current_price is None:
            return {
                "status": "PRICE_UNKNOWN",
                "historical_low": None,
                "current_price": None,
                "category": None,
                "reason": (
                    "Deal price could not be extracted "
                    "from deal text or product page"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
            }

        # ----------------------------------------------------
        # 6. MINIMUM PRICE
        #
        # IMPORTANT:
        # No PriceHistory request for <= ₹1000.
        # This saves time.
        # ----------------------------------------------------

        if current_price <= MIN_PRICE:
            return {
                "status": "PRICE_REJECT",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    f"Deal price ₹{current_price:.0f} "
                    f"is not above minimum price "
                    f"₹{MIN_PRICE}"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
            }

        # ----------------------------------------------------
        # 7. ONLY AMAZON / FLIPKART FOR PRICEHISTORY
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
                    "Resolved URL is not a supported "
                    "Amazon or Flipkart product URL"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
            }

        # ----------------------------------------------------
        # 8. PRICEHISTORY LOOKUP USING URL
        # ----------------------------------------------------

        history_result = pricehistory_lookup(
            product_url
        )

        if not history_result:
            return {
                "status": "HISTORICAL_LOW_UNKNOWN",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    "PriceHistory lookup failed for "
                    "resolved product URL"
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
        # 9. EXTRACT HISTORICAL LOW
        # ----------------------------------------------------

        historical_low = (
            extract_historical_low(
                history_result.get("html")
            )
        )

        if historical_low is None:
            return {
                "status": "HISTORICAL_LOW_UNKNOWN",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    "PriceHistory page opened but "
                    "historical low could not be extracted"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
                "pricehistory_url": (
                    history_result.get("url")
                ),
            }

        # ----------------------------------------------------
        # 10. SUSPICIOUS LOW
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
                    f"Historical low ₹{historical_low:.0f} "
                    f"appears suspicious against "
                    f"current price ₹{current_price:.0f}"
                ),
                "source": source,
                "url": product_url,
                "original_url": original_url,
                "store": store,
                "pricehistory_url": (
                    history_result.get("url")
                ),
            }

        # ----------------------------------------------------
        # 11. COMPARE
        # ----------------------------------------------------

        comparison = compare_price(
            current_price,
            historical_low,
        )

        return {
            "status": comparison["status"],
            "historical_low": historical_low,
            "current_price": current_price,
            "category": None,
            "reason": comparison["reason"],
            "source": source,
            "url": product_url,
            "original_url": original_url,
            "store": store,
            "pricehistory_url": (
                history_result.get("url")
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

    for text in price_tests:
        price = extract_price(text)

        print(
            f"{text:45} -> "
            f"₹{price if price is not None else 'N/A'}"
        )

    # --------------------------------------------------------
    # URL TESTS
    # --------------------------------------------------------

    url_tests = [
        "https://www.amazon.in/dp/B0F8Q96N8G",
        "https://www.flipkart.com/product/example",
        "https://fkrt.co/0eVemO",
        "https://amzn.to/example",
    ]

    print("\nURL TESTS")
    print("-" * 70)

    for url in url_tests:
        print(
            f"URL: {url}"
        )
        print(
            f"STORE: {identify_store(url)}"
        )
        print(
            f"NORMALIZED: "
            f"{normalize_product_url(url)}"
        )
        print()

    print("=" * 70)
    print("VALIDATOR TEST COMPLETE")
    print("=" * 70)
