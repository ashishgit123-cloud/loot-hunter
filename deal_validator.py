# deal_validator.py
# VERSION: 2.5
#
# Minimal-diff production validator
# - Categories read only from product_categories.txt
# - No brand/model hardcoding
# - Price > ₹1,000 required
# - Historical-low equal = NEW_LOW
# - Within 3% / ₹50 = NEAR_LOW
# - Exclusions supported
# - Suspicious historical lows rejected
# - Existing listener-compatible validate_deal() API preserved

import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin


VERSION = "2.5"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATEGORY_FILE = os.path.join(BASE_DIR, "product_categories.txt")

MIN_PRICE = 1000
NEAR_LOW_PERCENT = 0.03
NEAR_LOW_MAX_RUPEES = 50

REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}


# ============================================================
# CATEGORY FILE
# ============================================================

def load_categories():
    """
    Reads product_categories.txt.

    Everything before:
        EXCLUDE / DO NOT TARGET

    is treated as a category.

    Everything after that and before:
        MINIMUM DEAL PRICE

    is treated as an exclusion.
    """

    if not os.path.exists(CATEGORY_FILE):
        raise FileNotFoundError(
            f"Category file not found: {CATEGORY_FILE}"
        )

    categories = []
    exclusions = []

    section = "categories"

    with open(CATEGORY_FILE, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()

            if not line:
                continue

            upper = line.upper()

            # Ignore title/version/section decoration
            if upper.startswith("DEAL BOT PRODUCT CATEGORY"):
                continue

            if upper.startswith("VERSION:"):
                continue

            if upper.startswith("="):
                continue

            # Switch to exclusions
            if upper.startswith("EXCLUDE / DO NOT TARGET"):
                section = "exclusions"
                continue

            # Stop after minimum price section
            if upper.startswith("MINIMUM DEAL PRICE"):
                break

            # Ignore numbered section headings
            if re.match(r"^\d+\.\s+", line):
                continue

            # Only list entries matter
            if line.startswith("-"):
                value = line[1:].strip()

                if not value:
                    continue

                if section == "exclusions":
                    exclusions.append(value)
                else:
                    categories.append(value)

    if not categories:
        raise ValueError(
            "product_categories.txt loaded but no categories were found"
        )

    return categories, exclusions


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize(text):
    if not text:
        return ""

    text = text.lower()

    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = text.replace("-", " ")

    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def tokens(text):
    return set(normalize(text).split())


# ============================================================
# CATEGORY MATCHING
# ============================================================

def category_match(product_text, category):
    """
    Generic category matching.

    Example:
        Wireless Headphones
        Headphones

    -> MATCH

    No brand/model list is used.
    """

    product = normalize(product_text)
    cat = normalize(category)

    if not product or not cat:
        return False

    # Exact phrase
    if cat in product:
        return True

    # Token based fallback
    product_tokens = tokens(product)
    category_tokens = tokens(cat)

    if not category_tokens:
        return False

    matched = product_tokens.intersection(category_tokens)

    # Single-word category:
    # Headphones -> Wireless Headphones
    if len(category_tokens) == 1:
        return len(matched) == 1

    # Multi-word category:
    # Require all category words
    return matched == category_tokens


def classify_product(title, extra_text=""):
    categories, exclusions = load_categories()

    combined = f"{title} {extra_text}".strip()

    normalized_product = normalize(combined)

    # --------------------------------------------------------
    # EXCLUSIONS FIRST
    # --------------------------------------------------------

    for exclusion in exclusions:
        if category_match(normalized_product, exclusion):
            return {
                "matched": False,
                "category": None,
                "reason": f"Excluded product type: {exclusion}",
            }

    # --------------------------------------------------------
    # CATEGORY MATCH
    # --------------------------------------------------------

    for category in categories:
        if category_match(normalized_product, category):
            return {
                "matched": True,
                "category": category,
                "reason": f"Matched category: {category}",
            }

    return {
        "matched": False,
        "category": None,
        "reason": "Product category is outside configured deal categories",
    }


# ============================================================
# PRICE HELPERS
# ============================================================

def clean_price(value):
    if value is None:
        return None

    value = str(value)

    value = value.replace(",", "")
    value = value.replace("₹", "")
    value = value.replace("Rs.", "")
    value = value.replace("Rs", "")
    value = value.replace("INR", "")

    match = re.search(r"\d+(?:\.\d+)?", value)

    if not match:
        return None

    try:
        return float(match.group())
    except Exception:
        return None


def extract_price(text):
    if not text:
        return None

    patterns = [
        r"(?:deal\s*price|deal\s*at|offer\s*price|offer|sale\s*price|current\s*price|buy\s*at|now\s*at)"
        r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",

        r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            price = clean_price(match.group(1))

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

        if response.url:
            return response.url

    except Exception:
        pass

    return url


# ============================================================
# PRICEHISTORY
# ============================================================

def pricehistory_search(query):
    """
    Attempts PriceHistory search.

    Returns:
        {
            title,
            url,
            html
        }
    """

    encoded = quote(query)

    search_urls = [
        f"https://pricehistory.app/search?q={encoded}",
        f"https://pricehistoryapp.com/search?q={encoded}",
    ]

    for search_url in search_urls:

        try:
            response = requests.get(
                search_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                continue

            html = response.text

            soup = BeautifulSoup(html, "html.parser")

            # Look for product links
            links = soup.find_all("a", href=True)

            for link in links:

                href = link.get("href", "").strip()

                if not href:
                    continue

                text = link.get_text(" ", strip=True)

                if not text:
                    continue

                full_url = urljoin(search_url, href)

                lower_href = full_url.lower()

                if (
                    "pricehistory" in lower_href
                    or "price-history" in lower_href
                ):
                    return {
                        "title": text,
                        "url": full_url,
                        "html": None,
                    }

        except Exception:
            continue

    return None


def fetch_page(url):
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
# HISTORICAL LOW EXTRACTION
# ============================================================

def extract_historical_low(html):
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text(" ", strip=True)

    patterns = [
        r"(?:all[\s\-]*time\s*low|lowest\s*price|historical\s*low)"
        r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",

        r"(?:lowest)"
        r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",

        r'"(?:lowestPrice|lowest_price|historicalLow|historical_low)"'
        r'\s*:\s*"?(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)',
    ]

    values = []

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = clean_price(match.group(1))

            if value is not None:
                values.append(value)

    # Raw HTML can contain structured data
    raw_patterns = [
        r'"lowestPrice"\s*:\s*"?([\d,.]+)',
        r'"lowest_price"\s*:\s*"?([\d,.]+)',
        r'"historicalLow"\s*:\s*"?([\d,.]+)',
        r'"historical_low"\s*:\s*"?([\d,.]+)',
    ]

    for pattern in raw_patterns:
        for match in re.finditer(pattern, html, re.I):
            value = clean_price(match.group(1))

            if value is not None:
                values.append(value)

    if not values:
        return None

    return min(values)


# ============================================================
# SUSPICIOUS LOW CHECK
# ============================================================

def suspicious_historical_low(current_price, historical_low):
    if current_price is None or historical_low is None:
        return False

    # Historical low cannot be absurdly tiny compared with
    # the current price for normal physical products.
    #
    # Example:
    # Current ₹26,499
    # Historical ₹99
    #
    # This is suspicious and should not automatically qualify.

    if current_price >= 5000 and historical_low < current_price * 0.08:
        return True

    if current_price >= 2000 and historical_low < 100:
        return True

    return False


# ============================================================
# PRICE COMPARISON
# ============================================================

def compare_price(current_price, historical_low):

    if current_price is None:
        return {
            "status": "PRICE_UNKNOWN",
            "reason": "Current price could not be determined",
        }

    if historical_low is None:
        return {
            "status": "HISTORICAL_LOW_UNKNOWN",
            "reason": "Historical low could not be found",
        }

    # IMPORTANT:
    # Equal historical low is ACCEPTED.
    if current_price <= historical_low:
        return {
            "status": "NEW_LOW",
            "reason": (
                f"Current price ₹{current_price:.0f} is at or below "
                f"historical low ₹{historical_low:.0f}"
            ),
        }

    tolerance = max(
        NEAR_LOW_MAX_RUPEES,
        historical_low * NEAR_LOW_PERCENT,
    )

    difference = current_price - historical_low

    if difference <= tolerance:
        return {
            "status": "NEAR_LOW",
            "reason": (
                f"Current price ₹{current_price:.0f} is within "
                f"₹{tolerance:.0f} of historical low ₹{historical_low:.0f}"
            ),
        }

    return {
        "status": "NOT_LOW",
        "reason": (
            f"Current price ₹{current_price:.0f} is above "
            f"historical low ₹{historical_low:.0f}"
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
    """
    Listener-compatible public function.

    Returns a dictionary containing:
        status
        historical_low
        category
        reason
        source
        url
    """

    try:

        # ----------------------------------------------------
        # BASIC INPUT
        # ----------------------------------------------------

        title = (title or "").strip()
        text = (text or "").strip()
        source = source or ""

        if not title:
            return {
                "status": "INVALID",
                "historical_low": None,
                "category": None,
                "reason": "Product title is empty",
                "source": source,
                "url": url,
            }

        # ----------------------------------------------------
        # PRICE
        # ----------------------------------------------------

        current_price = clean_price(price)

        if current_price is None and text:
            current_price = extract_price(text)

        if current_price is None:
            return {
                "status": "PRICE_UNKNOWN",
                "historical_low": None,
                "category": None,
                "reason": "Current price could not be determined",
                "source": source,
                "url": url,
            }

        # STRICTLY GREATER THAN ₹1,000
        if current_price <= MIN_PRICE:
            return {
                "status": "PRICE_REJECT",
                "historical_low": None,
                "category": None,
                "reason": (
                    f"Product price ₹{current_price:.0f} is not above "
                    f"minimum deal price ₹{MIN_PRICE}"
                ),
                "source": source,
                "url": url,
            }

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        category_result = classify_product(
            title,
            text,
        )

        if not category_result["matched"]:
            return {
                "status": "CATEGORY_REJECT",
                "historical_low": None,
                "category": None,
                "reason": category_result["reason"],
                "source": source,
                "url": url,
            }

        category = category_result["category"]

        # ----------------------------------------------------
        # RESOLVE URL
        # ----------------------------------------------------

        final_url = resolve_url(url)

        # ----------------------------------------------------
        # PRICEHISTORY SEARCH
        # ----------------------------------------------------

        search_query = title

        result = pricehistory_search(search_query)

        historical_low = None
        pricehistory_title = ""
        pricehistory_url = None

        if result:

            pricehistory_title = result.get("title", "")
            pricehistory_url = result.get("url")

            page_url = pricehistory_url

            if page_url:
                page_html = fetch_page(page_url)

                if page_html:
                    historical_low = extract_historical_low(page_html)

        # ----------------------------------------------------
        # NO HISTORICAL LOW
        # ----------------------------------------------------

        if historical_low is None:

            return {
                "status": "HISTORICAL_LOW_UNKNOWN",
                "historical_low": None,
                "category": category,
                "reason": (
                    "PriceHistory historical low could not be verified"
                ),
                "source": source,
                "url": final_url,
            }

        # ----------------------------------------------------
        # SUSPICIOUS HISTORICAL LOW
        # ----------------------------------------------------

        if suspicious_historical_low(
            current_price,
            historical_low,
        ):

            return {
                "status": "SUSPICIOUS_LOW",
                "historical_low": historical_low,
                "category": category,
                "reason": (
                    f"Historical low ₹{historical_low:.0f} appears "
                    f"suspicious against current price "
                    f"₹{current_price:.0f}"
                ),
                "source": source,
                "url": final_url,
            }

        # ----------------------------------------------------
        # PRICE COMPARISON
        # ----------------------------------------------------

        comparison = compare_price(
            current_price,
            historical_low,
        )

        return {
            "status": comparison["status"],
            "historical_low": historical_low,
            "category": category,
            "reason": comparison["reason"],
            "source": source,
            "url": final_url,
            "pricehistory_url": pricehistory_url,
            "pricehistory_title": pricehistory_title,
        }

    except Exception as e:

        return {
            "status": "VALIDATOR_ERROR",
            "historical_low": None,
            "category": None,
            "reason": f"{type(e).__name__}: {e}",
            "source": source,
            "url": url,
        }


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 40)
    print("DEAL VALIDATOR")
    print("VERSION:", VERSION)
    print("=" * 40)

    try:
        categories, exclusions = load_categories()

        print("Category file:", CATEGORY_FILE)
        print("Categories loaded:", len(categories))
        print("Exclusions loaded:", len(exclusions))

        print()
        print("Category test:")

        test_products = [
            "Wireless Headphones",
            "Running Shoes",
            "Office Chair",
            "Samsung Refrigerator",
            "Phone Cover",
            "Tempered Glass",
            "Laptop",
        ]

        for product in test_products:
            result = classify_product(product)
            print(
                f"{product:30} -> "
                f"{result['matched']} | "
                f"{result['category']} | "
                f"{result['reason']}"
            )

    except Exception as e:
        print("ERROR:", type(e).__name__, e)

    print("=" * 40)
    print("VALIDATOR TEST COMPLETE")
    print("=" * 40)