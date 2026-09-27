# deal_validator.py
# VERSION: 3.0

import re
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin


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
}


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize(text):
    if not text:
        return ""

    text = str(text).lower()

    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = text.replace("-", " ")

    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# PRICE CLEANING
# ============================================================

def clean_price(value):
    if value is None:
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
        price = float(match.group())

        if price <= 0:
            return None

        return price

    except Exception:
        return None


# ============================================================
# PRICE EXTRACTION
# ============================================================

def extract_price(text):
    if not text:
        return None

    text = str(text)

    patterns = [
        (
            r"(?:deal\s*price|deal\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        (
            r"(?:offer\s*price|offer)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        (
            r"(?:sale\s*price)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        (
            r"(?:current\s*price)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        (
            r"(?:buy\s*at|now\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        (
            r"@\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        (
            r"(?:₹|rs\.?|inr)"
            r"\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        (
            r"\b([\d,]+(?:\.\d+)?)\s*/-"
        ),

        (
            r"\b([\d,]+(?:\.\d+)?)\s+only\b"
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
# URL RESOLUTION
# ============================================================

def resolve_url(url):
    if not url:
        return None

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        final_url = response.url

        if final_url:
            return final_url

    except Exception:
        pass

    return url


# ============================================================
# STORE DETECTION
# ============================================================

def detect_store(url):
    if not url:
        return None

    url_lower = url.lower()

    if (
        "amazon.in" in url_lower
        or "amazon.com" in url_lower
    ):
        return "amazon"

    if (
        "flipkart.com" in url_lower
    ):
        return "flipkart"

    return None


# ============================================================
# PRODUCT ID EXTRACTION
# ============================================================

def extract_product_id(url):
    if not url:
        return None

    # Amazon ASIN
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/product/([A-Z0-9]{10})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            url,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return None


# ============================================================
# PRICEHISTORY SEARCH
# ============================================================

def pricehistory_search(
    product_url=None,
    product_title=None,
):
    """
    Search PriceHistory.

    Priority:
        1. Resolved Amazon/Flipkart URL
        2. Product title

    This is intentionally URL-first because the exact
    product URL gives PriceHistory a much better chance
    of finding the correct product.
    """

    queries = []

    if product_url:
        queries.append(product_url)

    if product_title:
        queries.append(product_title)

    endpoints = [
        "https://pricehistory.app/search?q={}",
        "https://pricehistoryapp.com/search?q={}",
    ]

    for query in queries:

        if not query:
            continue

        encoded = quote(
            query,
            safe="",
        )

        for endpoint in endpoints:

            search_url = endpoint.format(
                encoded
            )

            try:

                response = requests.get(
                    search_url,
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )

                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(
                    response.text,
                    "html.parser",
                )

                candidates = []

                for link in soup.find_all(
                    "a",
                    href=True,
                ):

                    href = (
                        link.get(
                            "href",
                            "",
                        )
                        .strip()
                    )

                    link_text = (
                        link.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if not href:
                        continue

                    full_url = urljoin(
                        search_url,
                        href,
                    )

                    if (
                        "pricehistory"
                        not in full_url.lower()
                    ):
                        continue

                    if full_url.rstrip("/") == search_url.rstrip("/"):
                        continue

                    candidates.append(
                        {
                            "title": link_text,
                            "url": full_url,
                        }
                    )

                # Prefer candidates that contain
                # recognizable product identifiers.
                if candidates:

                    if product_url:

                        product_id = (
                            extract_product_id(
                                product_url
                            )
                        )

                        if product_id:

                            for candidate in candidates:

                                if product_id.lower() in (
                                    candidate["url"].lower()
                                ):
                                    return candidate

                    return candidates[0]

            except Exception:
                continue

    return None


# ============================================================
# FETCH PAGE
# ============================================================

def fetch_page(url):
    if not url:
        return None

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return None

        return response.text

    except Exception:
        return None


# ============================================================
# CURRENT PRICE FROM PRODUCT PAGE
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

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):

        try:

            data = script.string

            if not data:
                continue

            objects = json_safe_loads(data)

            for obj in objects:

                price = find_price_in_json(
                    obj
                )

                if price is not None:
                    return price

        except Exception:
            continue

    # --------------------------------------------------------
    # Common HTML attributes
    # --------------------------------------------------------

    selectors = [
        "[itemprop='price']",
        ".a-price-whole",
        ".a-offscreen",
        "[data-price]",
        "[data-asin-price]",
    ]

    for selector in selectors:

        try:

            elements = soup.select(
                selector
            )

            for element in elements:

                value = (
                    element.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not value:
                    value = (
                        element.get(
                            "content"
                        )
                        or element.get(
                            "data-price"
                        )
                    )

                price = clean_price(
                    value
                )

                if price is not None:
                    return price

        except Exception:
            continue

    # --------------------------------------------------------
    # Visible text
    # --------------------------------------------------------

    text = soup.get_text(
        " ",
        strip=True,
    )

    patterns = [
        r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            price = clean_price(
                match.group(1)
            )

            if price is not None:
                return price

    return None


def json_safe_loads(data):
    import json

    parsed = json.loads(data)

    if isinstance(parsed, list):
        return parsed

    return [parsed]


def find_price_in_json(obj):

    if isinstance(obj, dict):

        offers = obj.get("offers")

        if offers:

            if isinstance(
                offers,
                list,
            ):
                for offer in offers:

                    price = find_price_in_json(
                        offer
                    )

                    if price is not None:
                        return price

            elif isinstance(
                offers,
                dict,
            ):
                price = clean_price(
                    offers.get("price")
                )

                if price is not None:
                    return price

        for key in (
            "price",
            "lowPrice",
        ):

            if key in obj:

                price = clean_price(
                    obj.get(key)
                )

                if price is not None:
                    return price

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
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE,
        ):

            value = clean_price(
                match.group(1)
            )

            if value is not None:
                values.append(value)

    raw_patterns = [
        r'"lowestPrice"\s*:\s*"?([\d,.]+)"?',
        r'"lowest_price"\s*:\s*"?([\d,.]+)"?',
        r'"historicalLow"\s*:\s*"?([\d,.]+)"?',
        r'"historical_low"\s*:\s*"?([\d,.]+)"?',
    ]

    for pattern in raw_patterns:

        for match in re.finditer(
            pattern,
            html,
            re.IGNORECASE,
        ):

            value = clean_price(
                match.group(1)
            )

            if value is not None:
                values.append(value)

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
                "Current deal price "
                "could not be determined"
            ),
        }

    if historical_low is None:

        return {
            "status": "HISTORICAL_LOW_UNKNOWN",
            "reason": (
                "Verified historical low "
                "could not be found"
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
        # LOCAL PRICE
        # ----------------------------------------------------

        current_price = clean_price(
            price
        )

        if current_price is None:
            current_price = extract_price(
                text
            )

        # ----------------------------------------------------
        # RESOLVE URL FIRST
        # ----------------------------------------------------

        final_url = resolve_url(
            url
        )

        store = detect_store(
            final_url
        )

        # ----------------------------------------------------
        # PRODUCT PAGE PRICE
        # ----------------------------------------------------

        if current_price is None and final_url:

            product_html = fetch_page(
                final_url
            )

            if product_html:

                current_price = (
                    extract_product_page_price(
                        product_html
                    )
                )

        # ----------------------------------------------------
        # MIN PRICE
        # ----------------------------------------------------

        if (
            current_price is not None
            and current_price <= MIN_PRICE
        ):

            return {
                "status": "PRICE_REJECT",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    f"Deal price ₹{current_price:.0f} "
                    f"is not above minimum "
                    f"price ₹{MIN_PRICE}"
                ),
                "source": source,
                "url": final_url,
            }

        # ----------------------------------------------------
        # PRICEHISTORY
        #
        # IMPORTANT:
        # Resolved URL is searched FIRST.
        # Title is only fallback.
        # ----------------------------------------------------

        result = pricehistory_search(
            product_url=final_url,
            product_title=title,
        )

        historical_low = None
        pricehistory_url = None
        pricehistory_title = ""

        if result:

            pricehistory_url = result.get(
                "url"
            )

            pricehistory_title = result.get(
                "title",
                "",
            )

            html = fetch_page(
                pricehistory_url
            )

            if html:

                historical_low = (
                    extract_historical_low(
                        html
                    )
                )

        # ----------------------------------------------------
        # NO HISTORICAL LOW
        # ----------------------------------------------------

        if historical_low is None:

            return {
                "status": "HISTORICAL_LOW_UNKNOWN",
                "historical_low": None,
                "current_price": current_price,
                "category": None,
                "reason": (
                    "Historical low could not "
                    "be verified from PriceHistory"
                ),
                "source": source,
                "url": final_url,
                "store": store,
                "pricehistory_url": pricehistory_url,
                "pricehistory_title": pricehistory_title,
            }

        # ----------------------------------------------------
        # PRICE STILL UNKNOWN
        # ----------------------------------------------------

        if current_price is None:

            return {
                "status": "PRICE_UNKNOWN",
                "historical_low": historical_low,
                "current_price": None,
                "category": None,
                "reason": (
                    "Deal price could not be "
                    "extracted from deal text "
                    "or product page"
                ),
                "source": source,
                "url": final_url,
                "store": store,
                "pricehistory_url": pricehistory_url,
                "pricehistory_title": pricehistory_title,
            }

        # ----------------------------------------------------
        # SUSPICIOUS LOW
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
                "url": final_url,
                "store": store,
                "pricehistory_url": pricehistory_url,
                "pricehistory_title": pricehistory_title,
            }

        # ----------------------------------------------------
        # COMPARE
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
            "url": final_url,
            "store": store,
            "pricehistory_url": pricehistory_url,
            "pricehistory_title": pricehistory_title,
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

    print("=" * 60)
    print("DEAL VALIDATOR")
    print("VERSION:", VERSION)
    print("=" * 60)

    tests = [
        "ASUS Dual GeForce RTX 5060 8GB GDDR7 OC Edition "
        "Video Card DUAL-RTX5060-O8G @52,999",
        "Laptop Deal Price: ₹24,999",
        "Wireless Headphones @12,999",
        "Samsung Refrigerator Rs. 34,999",
    ]

    print("\nPRICE TESTS")
    print("-" * 60)

    for text in tests:

        price = extract_price(text)

        print(
            f"{text[:45]:45} -> ₹{price}"
        )

    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
