# ============================================================
# DEAL VALIDATOR
# Version: 2.1
#
# Changes from v2.0:
# - Product categories are now loaded from product_categories.txt
# - Exclusion list is also loaded from the same file
# - Minimum price is read from the category file
# - Existing PriceHistory validation retained
# - NEW_LOW includes current price == historical low
# - NEAR_LOW = within 3% or ₹50 of historical low
# ============================================================

import os
import re
import requests
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATEGORY_FILE = os.path.join(BASE_DIR, "product_categories.txt")

DEFAULT_MIN_PRICE = 1000
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
# CATEGORY MASTER LOADER
# ============================================================

def load_category_master():
    """
    Reads product_categories.txt.

    Returns:
        {
            "allowed": [...],
            "excluded": [...],
            "min_price": 1000
        }
    """

    if not os.path.exists(CATEGORY_FILE):
        print(
            f"⚠️ Category file not found: {CATEGORY_FILE}. "
            f"Using safe fallback."
        )

        return {
            "allowed": [
                "mobile",
                "smartphone",
                "laptop",
                "macbook",
                "tablet",
                "tv",
                "monitor",
                "headphones",
                "earphones",
                "tws",
                "speaker",
                "camera",
                "gaming",
                "keyboard",
                "mouse",
                "printer",
                "router",
                "ssd",
                "hdd",
                "furniture",
                "sofa",
                "bed",
                "mattress",
                "chair",
                "table",
                "cabinet",
                "sports",
                "running shoes",
                "sports shoes",
                "football",
                "cricket",
                "badminton",
                "basketball",
                "gym",
                "treadmill",
                "fitness",
                "cycling",
            ],
            "excluded": [
                "phone cover",
                "phone case",
                "tempered glass",
                "screen protector",
                "cable",
                "jewellery",
                "clothes",
                "fashion",
                "small accessory",
                "smart band",
                "watch strap",
            ],
            "min_price": DEFAULT_MIN_PRICE,
        }

    allowed = []
    excluded = []
    min_price = DEFAULT_MIN_PRICE

    current_section = None

    try:
        with open(CATEGORY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for raw_line in lines:
            line = raw_line.strip()

            if not line:
                continue

            # Version / comments
            if line.startswith("#"):
                continue

            # Section detection
            upper = line.upper()

            if upper.startswith("EXCLUDE / DO NOT TARGET"):
                current_section = "excluded"
                continue

            if upper.startswith("MINIMUM DEAL PRICE"):
                current_section = "minimum"
                continue

            # Any numbered category:
            # 1. ELECTRONICS
            # 2. FURNITURE
            if re.match(r"^\d+\.\s+", line):
                current_section = "allowed"
                continue

            # Minimum price
            if current_section == "minimum":
                numbers = re.findall(r"\d[\d,]*", line)

                if numbers:
                    try:
                        value = int(numbers[0].replace(",", ""))

                        if value > 0:
                            min_price = value
                    except ValueError:
                        pass

                continue

            # Bullet item
            if line.startswith("-"):
                item = line[1:].strip()

                if not item:
                    continue

                # Remove trailing comments if any
                item = item.split("#", 1)[0].strip()

                if current_section == "excluded":
                    excluded.append(item.lower())

                elif current_section == "allowed":
                    allowed.append(item.lower())

        return {
            "allowed": allowed,
            "excluded": excluded,
            "min_price": min_price,
        }

    except Exception as e:
        print(f"⚠️ Category file read error: {e}")

        return {
            "allowed": [],
            "excluded": [],
            "min_price": DEFAULT_MIN_PRICE,
        }


CATEGORY_MASTER = load_category_master()

ALLOWED_CATEGORIES = CATEGORY_MASTER["allowed"]
EXCLUDED_KEYWORDS = CATEGORY_MASTER["excluded"]
MIN_PRICE = CATEGORY_MASTER["min_price"]


# ============================================================
# PRODUCT CLASSIFICATION
# ============================================================

def normalize_text(text):
    if not text:
        return ""

    text = text.lower()
    text = text.replace("/", " ")
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9₹ ]+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def classify_product(title):
    """
    Returns:
        {
            "accepted": True/False,
            "reason": "...",
            "matched_category": "..."
        }
    """

    if not title:
        return {
            "accepted": False,
            "reason": "Product title missing",
            "matched_category": None,
        }

    normalized = normalize_text(title)

    # --------------------------------------------------------
    # EXCLUSIONS FIRST
    # --------------------------------------------------------

    for keyword in EXCLUDED_KEYWORDS:
        keyword_normalized = normalize_text(keyword)

        if keyword_normalized and keyword_normalized in normalized:
            return {
                "accepted": False,
                "reason": f"Excluded product type: {keyword}",
                "matched_category": None,
            }

    # --------------------------------------------------------
    # ALLOWED CATEGORY CHECK
    # --------------------------------------------------------

    for category in ALLOWED_CATEGORIES:
        category_normalized = normalize_text(category)

        if not category_normalized:
            continue

        # Exact phrase
        if category_normalized in normalized:
            return {
                "accepted": True,
                "reason": f"Matched category: {category}",
                "matched_category": category,
            }

        # Handle slash-separated category names
        parts = [
            p.strip()
            for p in re.split(r"[/|]", category_normalized)
            if p.strip()
        ]

        for part in parts:
            if len(part) >= 4 and part in normalized:
                return {
                    "accepted": True,
                    "reason": f"Matched category: {category}",
                    "matched_category": category,
                }

    return {
        "accepted": False,
        "reason": "Product category not in category master list",
        "matched_category": None,
    }


# ============================================================
# URL RESOLUTION
# ============================================================

def resolve_url(url):
    """
    Resolves Flipkart/Amazon short URLs such as fkrt.co.
    """

    if not url:
        return ""

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

    except Exception as e:
        print(f"⚠️ URL resolve failed: {e}")

    return url


# ============================================================
# PRICE HISTORY HELPERS
# ============================================================

def normalize_price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)

    text = text.replace(",", "")
    text = text.replace("₹", "")
    text = text.replace("Rs.", "")
    text = text.replace("Rs", "")
    text = text.replace("INR", "")

    numbers = re.findall(r"\d+(?:\.\d+)?", text)

    if not numbers:
        return None

    try:
        return float(numbers[0])
    except ValueError:
        return None


def title_similarity(title1, title2):
    """
    Simple token similarity.
    """

    if not title1 or not title2:
        return 0.0

    a = set(normalize_text(title1).split())
    b = set(normalize_text(title2).split())

    if not a or not b:
        return 0.0

    intersection = len(a.intersection(b))
    union = len(a.union(b))

    if union == 0:
        return 0.0

    return intersection / union


# ============================================================
# PRICEHISTORY SEARCH
# ============================================================

def build_pricehistory_queries(title):
    """
    Creates multiple search queries without hardcoding brands.
    """

    normalized = normalize_text(title)

    queries = []

    if normalized:
        queries.append(normalized)

    # Remove common deal/variant noise
    cleaned = re.sub(
        r"\b\d+\s*gb\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\b\d+\s*tb\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\b\d+\s*ram\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\b\d+\s*inch\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()

    if cleaned and cleaned not in queries:
        queries.append(cleaned)

    # First 8 useful words
    words = cleaned.split()

    if len(words) > 8:
        short_query = " ".join(words[:8])

        if short_query not in queries:
            queries.append(short_query)

    return queries[:3]


def fetch_pricehistory_search(query):
    """
    Search PriceHistory.

    This intentionally keeps the request isolated so that if
    PriceHistory changes its frontend/search structure, only this
    function needs adjustment.
    """

    search_urls = [
        f"https://pricehistory.app/search?q={quote(query)}",
        f"https://pricehistoryapp.com/search?q={quote(query)}",
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

            return response.text, response.url

        except Exception as e:
            print(
                f"⚠️ PriceHistory search error "
                f"for '{query}': {e}"
            )

    return None, None


def parse_pricehistory_results(html, original_title):
    """
    Extract possible PriceHistory product URLs/titles.
    """

    if not html:
        return []

    results = []

    try:
        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):

            href = a.get("href", "").strip()

            text = a.get_text(" ", strip=True)

            if not href or not text:
                continue

            if href.startswith("/"):
                href = urljoin(
                    "https://pricehistory.app",
                    href,
                )

            href_lower = href.lower()

            if "pricehistory" not in href_lower:
                continue

            similarity = title_similarity(
                original_title,
                text,
            )

            if similarity >= 0.20:
                results.append(
                    {
                        "title": text,
                        "url": href,
                        "similarity": similarity,
                    }
                )

        results.sort(
            key=lambda x: x["similarity"],
            reverse=True,
        )

        return results[:10]

    except Exception as e:
        print(
            f"⚠️ PriceHistory result parse error: {e}"
        )

        return []


# ============================================================
# PRICEHISTORY PRODUCT PAGE
# ============================================================

def fetch_pricehistory_product(url):
    """
    Fetch a PriceHistory product page and attempt to extract
    historical low values.
    """

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return None

        html = response.text

        soup = BeautifulSoup(html, "html.parser")

        page_text = soup.get_text(
            " ",
            strip=True,
        )

        historical_low = None

        # Common labels
        patterns = [
            r"all[\s\-]*time[\s\-]*low[^₹0-9]{0,80}₹?\s*([\d,]+)",
            r"lowest[\s\-]*price[^₹0-9]{0,80}₹?\s*([\d,]+)",
            r"historical[\s\-]*low[^₹0-9]{0,80}₹?\s*([\d,]+)",
            r"lowest[^₹0-9]{0,80}₹?\s*([\d,]+)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                page_text,
                flags=re.IGNORECASE,
            )

            if match:
                historical_low = normalize_price(
                    match.group(1)
                )

                if historical_low is not None:
                    break

        # Search page scripts / raw HTML as fallback
        if historical_low is None:

            raw_patterns = [
                r'"lowestPrice"\s*:\s*"?([\d.]+)"?',
                r'"lowest_price"\s*:\s*"?([\d.]+)"?',
                r'"historicalLow"\s*:\s*"?([\d.]+)"?',
                r'"allTimeLow"\s*:\s*"?([\d.]+)"?',
            ]

            for pattern in raw_patterns:

                match = re.search(
                    pattern,
                    html,
                    flags=re.IGNORECASE,
                )

                if match:
                    historical_low = normalize_price(
                        match.group(1)
                    )

                    if historical_low is not None:
                        break

        if historical_low is None:
            return None

        return {
            "historical_low": historical_low,
            "url": response.url,
        }

    except Exception as e:
        print(
            f"⚠️ PriceHistory product error: {e}"
        )

        return None


# ============================================================
# PRICEHISTORY LOOKUP
# ============================================================

def pricehistory_lookup(title, deal_url=None):
    """
    Main PriceHistory lookup.

    Returns:
        {
            "historical_low": ...,
            "matched_title": ...,
            "pricehistory_url": ...,
            "similarity": ...
        }

    or None
    """

    # --------------------------------------------------------
    # 1. Try resolved product URL first
    # --------------------------------------------------------

    resolved_url = resolve_url(deal_url)

    # Currently we use title search as the reliable generic
    # fallback because marketplaces do not expose a uniform
    # product-ID mapping.
    # --------------------------------------------------------

    queries = build_pricehistory_queries(title)

    best_match = None

    for query in queries:

        html, search_url = fetch_pricehistory_search(
            query
        )

        if not html:
            continue

        results = parse_pricehistory_results(
            html,
            title,
        )

        for result in results:

            if (
                best_match is None
                or result["similarity"]
                > best_match["similarity"]
            ):
                best_match = result

        # Good enough match
        if (
            best_match
            and best_match["similarity"] >= 0.60
        ):
            break

    if not best_match:
        return None

    product_data = fetch_pricehistory_product(
        best_match["url"]
    )

    if not product_data:
        return None

    return {
        "historical_low": product_data["historical_low"],
        "matched_title": best_match["title"],
        "pricehistory_url": product_data["url"],
        "similarity": best_match["similarity"],
        "resolved_deal_url": resolved_url,
    }


# ============================================================
# SUSPICIOUS HISTORICAL LOW CHECK
# ============================================================

def suspicious_historical_low(
    current_price,
    historical_low,
    title,
):
    """
    Prevent obviously broken history values such as:

    Phone current = ₹26,499
    Historical low = ₹99

    Such values should not automatically become deals.
    """

    if not current_price or not historical_low:
        return False

    ratio = historical_low / current_price

    normalized = normalize_text(title)

    high_value_keywords = [
        "iphone",
        "galaxy",
        "pixel",
        "oneplus",
        "laptop",
        "macbook",
        "tv",
        "monitor",
        "camera",
        "console",
        "refrigerator",
        "washing machine",
        "air conditioner",
        "ac",
        "sofa",
        "bed",
        "treadmill",
    ]

    is_high_value_product = any(
        keyword in normalized
        for keyword in high_value_keywords
    )

    if is_high_value_product and ratio < 0.02:
        return True

    if current_price >= 10000 and historical_low < 100:
        return True

    if current_price >= 20000 and historical_low < 200:
        return True

    return False


# ============================================================
# PRICE COMPARISON
# ============================================================

def compare_price(
    current_price,
    historical_low,
):
    """
    Rules:

    current <= historical_low
        => NEW_LOW

    otherwise if within 3% OR ₹50
        => NEAR_LOW

    otherwise
        => NOT_LOW
    """

    current_price = normalize_price(current_price)
    historical_low = normalize_price(historical_low)

    if current_price is None:
        return {
            "status": "NOT_LOW",
            "reason": "Current price could not be parsed",
        }

    if historical_low is None:
        return {
            "status": "NOT_LOW",
            "reason": "Historical low could not be parsed",
        }

    # IMPORTANT:
    # Equal historical low is a valid NEW_LOW.
    if current_price <= historical_low:
        return {
            "status": "NEW_LOW",
            "reason": (
                f"Current price ₹{current_price:,.0f} "
                f"is at/below historical low "
                f"₹{historical_low:,.0f}"
            ),
            "historical_low": historical_low,
        }

    difference = current_price - historical_low

    allowed_difference = max(
        historical_low * NEAR_LOW_PERCENT,
        NEAR_LOW_MAX_RUPEES,
    )

    if difference <= allowed_difference:
        return {
            "status": "NEAR_LOW",
            "reason": (
                f"Current price ₹{current_price:,.0f} "
                f"is within ₹{allowed_difference:,.0f} "
                f"of historical low "
                f"₹{historical_low:,.0f}"
            ),
            "historical_low": historical_low,
        }

    return {
        "status": "NOT_LOW",
        "reason": (
            f"Current price ₹{current_price:,.0f} "
            f"is ₹{difference:,.0f} above historical low "
            f"₹{historical_low:,.0f}"
        ),
        "historical_low": historical_low,
    }


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_deal(
    title,
    price,
    url=None,
    source=None,
):
    """
    Main validator.

    Returns a structured dictionary which loot_listener.py
    can consume directly.
    """

    try:

        # ----------------------------------------------------
        # BASIC VALIDATION
        # ----------------------------------------------------

        if not title:
            return {
                "status": "REJECT",
                "reason": "Product title missing",
                "source": source,
            }

        current_price = normalize_price(price)

        if current_price is None:
            return {
                "status": "REJECT",
                "reason": "Current price could not be parsed",
                "source": source,
            }

        # ----------------------------------------------------
        # MINIMUM PRICE
        # Strictly greater than ₹1,000
        # ----------------------------------------------------

        if current_price <= MIN_PRICE:
            return {
                "status": "REJECT",
                "reason": (
                    f"Price ₹{current_price:,.0f} "
                    f"is not above minimum deal price "
                    f"₹{MIN_PRICE:,.0f}"
                ),
                "source": source,
                "price": current_price,
            }

        # ----------------------------------------------------
        # PRODUCT CATEGORY
        # ----------------------------------------------------

        category_result = classify_product(title)

        if not category_result["accepted"]:
            return {
                "status": "REJECT",
                "reason": category_result["reason"],
                "source": source,
                "price": current_price,
            }

        matched_category = category_result[
            "matched_category"
        ]

        # ----------------------------------------------------
        # PRICEHISTORY
        # ----------------------------------------------------

        history = pricehistory_lookup(
            title=title,
            deal_url=url,
        )

        if not history:
            return {
                "status": "NOT_LOW",
                "reason": (
                    "PriceHistory product match/history "
                    "could not be verified"
                ),
                "source": source,
                "price": current_price,
                "category": matched_category,
            }

        historical_low = normalize_price(
            history.get("historical_low")
        )

        if historical_low is None:
            return {
                "status": "NOT_LOW",
                "reason": (
                    "PriceHistory returned no valid "
                    "historical low"
                ),
                "source": source,
                "price": current_price,
                "category": matched_category,
            }

        # ----------------------------------------------------
        # SUSPICIOUS HISTORY
        # ----------------------------------------------------

        if suspicious_historical_low(
            current_price,
            historical_low,
            title,
        ):
            return {
                "status": "NOT_LOW",
                "reason": (
                    f"Suspicious PriceHistory low "
                    f"₹{historical_low:,.0f}; "
                    f"possible bad/mismatched history"
                ),
                "source": source,
                "price": current_price,
                "historical_low": historical_low,
                "category": matched_category,
                "pricehistory_url": history.get(
                    "pricehistory_url"
                ),
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
            "reason": comparison.get("reason"),
            "source": source,
            "product": title,
            "price": current_price,
            "historical_low": historical_low,
            "category": matched_category,
            "pricehistory_url": history.get(
                "pricehistory_url"
            ),
            "match_similarity": history.get(
                "similarity"
            ),
        }

    except Exception as e:

        return {
            "status": "ERROR",
            "reason": f"Validator error: {e}",
            "source": source,
        }


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    print("========================================")
    print("DEAL VALIDATOR v2.1")
    print("========================================")
    print(
        f"Category file: {CATEGORY_FILE}"
    )
    print(
        f"Allowed category entries: "
        f"{len(ALLOWED_CATEGORIES)}"
    )
    print(
        f"Excluded entries: "
        f"{len(EXCLUDED_KEYWORDS)}"
    )
    print(
        f"Minimum price: ₹{MIN_PRICE}"
    )
    print("========================================")

    test_title = (
        "Samsung Galaxy S23 5G "
        "(Cream, 256 GB) (8 GB RAM)"
    )

    result = validate_deal(
        title=test_title,
        price=26499,
        url="https://fkrt.co/SjusKq",
        source="@vaasutechdeals",
    )

    print("\nTEST RESULT:")
    print(result)