# ============================================================
# DEAL VALIDATOR
# Version: 2.2
#
# IMPORTANT:
# - NO brand hardcoding
# - NO model hardcoding
# - Categories loaded from product_categories.txt
# - Minimum price loaded from product_categories.txt
# - Equal to historical low = NEW_LOW
# - Within 3% OR ₹50 = NEAR_LOW
# - Suspicious historical lows are rejected
# - PriceHistory used for historical validation
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

CATEGORY_FILE = os.path.join(
    BASE_DIR,
    "product_categories.txt"
)

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
# TEXT HELPERS
# ============================================================

def normalize_text(text):
    if not text:
        return ""

    text = str(text).lower()

    text = text.replace("/", " ")
    text = text.replace("-", " ")
    text = text.replace("_", " ")

    text = re.sub(
        r"[^a-z0-9₹ ]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def tokenize(text):
    normalized = normalize_text(text)

    if not normalized:
        return set()

    return set(
        word
        for word in normalized.split()
        if len(word) >= 3
    )


# ============================================================
# CATEGORY MASTER LOADER
# ============================================================

def load_category_master():

    allowed = []
    excluded = []

    min_price = DEFAULT_MIN_PRICE

    if not os.path.exists(CATEGORY_FILE):

        print(
            f"⚠️ Category file not found: "
            f"{CATEGORY_FILE}"
        )

        return {
            "allowed": [],
            "excluded": [],
            "min_price": DEFAULT_MIN_PRICE,
        }

    current_section = None

    try:

        with open(
            CATEGORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            for raw_line in file:

                line = raw_line.strip()

                if not line:
                    continue

                upper = line.upper()

                # --------------------------------------------
                # Ignore comments
                # --------------------------------------------

                if line.startswith("#"):
                    continue

                # --------------------------------------------
                # EXCLUDE SECTION
                # --------------------------------------------

                if upper.startswith(
                    "EXCLUDE / DO NOT TARGET"
                ):

                    current_section = "excluded"
                    continue

                # --------------------------------------------
                # MINIMUM PRICE SECTION
                # --------------------------------------------

                if upper.startswith(
                    "MINIMUM DEAL PRICE"
                ):

                    current_section = "minimum"
                    continue

                # --------------------------------------------
                # Numbered category section
                # Example:
                # 1. ELECTRONICS
                # --------------------------------------------

                if re.match(
                    r"^\d+\.\s+",
                    line
                ):

                    current_section = "allowed"
                    continue

                # --------------------------------------------
                # Minimum price
                # --------------------------------------------

                if current_section == "minimum":

                    numbers = re.findall(
                        r"\d[\d,]*",
                        line
                    )

                    if numbers:

                        try:

                            value = int(
                                numbers[0]
                                .replace(",", "")
                            )

                            if value > 0:
                                min_price = value

                        except ValueError:
                            pass

                    continue

                # --------------------------------------------
                # Bullet item
                # --------------------------------------------

                if not line.startswith("-"):
                    continue

                item = line[1:].strip()

                if not item:
                    continue

                if current_section == "allowed":

                    allowed.append(item)

                elif current_section == "excluded":

                    excluded.append(item)

        return {
            "allowed": allowed,
            "excluded": excluded,
            "min_price": min_price,
        }

    except Exception as e:

        print(
            f"❌ Category file read error: {e}"
        )

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
# CATEGORY MATCHING
# ============================================================

def category_tokens(category):

    """
    Convert category name into useful tokens.

    Example:

    Mobile / Smartphone
    ->
    mobile, smartphone

    Running Shoes
    ->
    running, shoes
    """

    return tokenize(category)


def category_match_score(text, category):

    """
    Generic category matching.

    No brands.
    No product models.
    No fixed product names.
    """

    text_tokens = tokenize(text)

    category_tokens_set = category_tokens(
        category
    )

    if not text_tokens or not category_tokens_set:
        return 0.0

    matched = (
        text_tokens
        .intersection(category_tokens_set)
    )

    if not matched:
        return 0.0

    return (
        len(matched)
        /
        len(category_tokens_set)
    )


def classify_product(
    title,
    extra_text=""
):

    """
    Classifies product using category master.

    extra_text can contain information extracted
    from PriceHistory/product page.

    NO brand/model list is used.
    """

    combined_text = " ".join(
        [
            title or "",
            extra_text or "",
        ]
    )

    normalized = normalize_text(
        combined_text
    )

    if not normalized:

        return {
            "accepted": False,
            "reason": "Product title/category information missing",
            "matched_category": None,
            "score": 0.0,
        }

    # ========================================================
    # EXCLUSIONS FIRST
    # ========================================================

    for excluded in EXCLUDED_KEYWORDS:

        excluded_normalized = normalize_text(
            excluded
        )

        if not excluded_normalized:
            continue

        if excluded_normalized in normalized:

            return {
                "accepted": False,
                "reason": (
                    f"Excluded product type: "
                    f"{excluded}"
                ),
                "matched_category": None,
                "score": 0.0,
            }

    # ========================================================
    # ALLOWED CATEGORY MATCH
    # ========================================================

    best_category = None
    best_score = 0.0

    for category in ALLOWED_CATEGORIES:

        score = category_match_score(
            combined_text,
            category
        )

        if score > best_score:

            best_score = score
            best_category = category

    # Strong enough category match
    if best_category and best_score >= 0.50:

        return {
            "accepted": True,
            "reason": (
                f"Matched category: "
                f"{best_category}"
            ),
            "matched_category": best_category,
            "score": best_score,
        }

    # Single-token category match
    # Useful for categories such as:
    # Laptop, Monitor, Sofa, Drill etc.
    for category in ALLOWED_CATEGORIES:

        tokens = category_tokens(category)

        if len(tokens) != 1:
            continue

        token = next(iter(tokens))

        if token in tokenize(combined_text):

            return {
                "accepted": True,
                "reason": (
                    f"Matched category: "
                    f"{category}"
                ),
                "matched_category": category,
                "score": 1.0,
            }

    return {
        "accepted": False,
        "reason": (
            "Product category is outside "
            "configured deal categories"
        ),
        "matched_category": None,
        "score": best_score,
    }


# ============================================================
# URL RESOLUTION
# ============================================================

def resolve_url(url):

    if not url:
        return ""

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )

        if response.url:
            return response.url

    except Exception as e:

        print(
            f"⚠️ URL resolve failed: {e}"
        )

    return url


# ============================================================
# PRICE PARSER
# ============================================================

def normalize_price(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):

        return float(value)

    text = str(value)

    text = text.replace(
        ",",
        ""
    )

    text = text.replace(
        "₹",
        ""
    )

    text = text.replace(
        "Rs.",
        ""
    )

    text = text.replace(
        "Rs",
        ""
    )

    text = text.replace(
        "INR",
        ""
    )

    numbers = re.findall(
        r"\d+(?:\.\d+)?",
        text
    )

    if not numbers:
        return None

    try:

        return float(
            numbers[0]
        )

    except ValueError:

        return None


# ============================================================
# TITLE SIMILARITY
# ============================================================

def title_similarity(
    title1,
    title2
):

    if not title1 or not title2:
        return 0.0

    a = tokenize(title1)
    b = tokenize(title2)

    if not a or not b:
        return 0.0

    intersection = len(
        a.intersection(b)
    )

    union = len(
        a.union(b)
    )

    if union == 0:
        return 0.0

    return intersection / union


# ============================================================
# PRICEHISTORY SEARCH QUERIES
# ============================================================

def build_pricehistory_queries(
    title
):

    normalized = normalize_text(
        title
    )

    queries = []

    if normalized:
        queries.append(
            normalized
        )

    # Remove RAM/storage/size noise
    cleaned = re.sub(
        r"\b\d+\s*(gb|tb|mb|inch|inches|ram)\b",
        "",
        normalized,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned
    ).strip()

    if cleaned and cleaned not in queries:

        queries.append(
            cleaned
        )

    words = cleaned.split()

    if len(words) > 8:

        short_query = " ".join(
            words[:8]
        )

        if short_query not in queries:

            queries.append(
                short_query
            )

    return queries[:3]


# ============================================================
# PRICEHISTORY SEARCH
# ============================================================

def fetch_pricehistory_search(
    query
):

    search_urls = [

        (
            "https://pricehistory.app/"
            f"search?q={quote(query)}"
        ),

        (
            "https://pricehistoryapp.com/"
            f"search?q={quote(query)}"
        ),
    ]

    for search_url in search_urls:

        try:

            response = requests.get(
                search_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code != 200:
                continue

            return (
                response.text,
                response.url
            )

        except Exception as e:

            print(
                f"⚠️ PriceHistory search error "
                f"for '{query}': {e}"
            )

    return None, None


# ============================================================
# PRICEHISTORY SEARCH RESULT PARSER
# ============================================================

def parse_pricehistory_results(
    html,
    original_title
):

    if not html:
        return []

    results = []

    try:

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        for a in soup.find_all(
            "a",
            href=True
        ):

            href = a.get(
                "href",
                ""
            ).strip()

            text = a.get_text(
                " ",
                strip=True
            )

            if not href or not text:
                continue

            if href.startswith("/"):

                href = urljoin(
                    "https://pricehistory.app",
                    href
                )

            if (
                "pricehistory"
                not in href.lower()
            ):
                continue

            similarity = title_similarity(
                original_title,
                text
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
            reverse=True
        )

        return results[:10]

    except Exception as e:

        print(
            "⚠️ PriceHistory result parse error:",
            e
        )

        return []


# ============================================================
# PRICEHISTORY PRODUCT PAGE
# ============================================================

def fetch_pricehistory_product(
    url
):

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            return None

        html = response.text

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        page_text = soup.get_text(
            " ",
            strip=True
        )

        # ----------------------------------------------------
        # HISTORICAL LOW
        # ----------------------------------------------------

        historical_low = None

        patterns = [

            (
                r"all[\s\-]*time[\s\-]*low"
                r"[^₹0-9]{0,80}"
                r"₹?\s*([\d,]+)"
            ),

            (
                r"lowest[\s\-]*price"
                r"[^₹0-9]{0,80}"
                r"₹?\s*([\d,]+)"
            ),

            (
                r"historical[\s\-]*low"
                r"[^₹0-9]{0,80}"
                r"₹?\s*([\d,]+)"
            ),

            (
                r"lowest"
                r"[^₹0-9]{0,80}"
                r"₹?\s*([\d,]+)"
            ),
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                page_text,
                flags=re.IGNORECASE
            )

            if match:

                historical_low = normalize_price(
                    match.group(1)
                )

                if historical_low is not None:
                    break

        # ----------------------------------------------------
        # RAW HTML / SCRIPT FALLBACK
        # ----------------------------------------------------

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
                    flags=re.IGNORECASE
                )

                if match:

                    historical_low = normalize_price(
                        match.group(1)
                    )

                    if historical_low is not None:
                        break

        # ----------------------------------------------------
        # CATEGORY / BREADCRUMB EXTRACTION
        # ----------------------------------------------------

        category_text_parts = []

        # Breadcrumb-like elements
        selectors = [
            "nav",
            "[class*='breadcrumb']",
            "[class*='category']",
            "[class*='product-category']",
            "meta[property='product:category']",
        ]

        for selector in selectors:

            try:

                elements = soup.select(
                    selector
                )

                for element in elements:

                    if element.name == "meta":

                        value = element.get(
                            "content",
                            ""
                        )

                    else:

                        value = element.get_text(
                            " ",
                            strip=True
                        )

                    if value:

                        category_text_parts.append(
                            value
                        )

            except Exception:
                continue

        # ----------------------------------------------------
        # PAGE TITLE
        # ----------------------------------------------------

        page_title = ""

        if soup.title:

            page_title = soup.title.get_text(
                " ",
                strip=True
            )

        if page_title:

            category_text_parts.append(
                page_title
            )

        category_text = " ".join(
            category_text_parts
        )

        if (
            historical_low is None
            and not category_text
        ):
            return None

        return {
            "historical_low": historical_low,
            "category_text": category_text,
            "page_title": page_title,
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

def pricehistory_lookup(
    title,
    deal_url=None
):

    resolved_url = resolve_url(
        deal_url
    )

    queries = build_pricehistory_queries(
        title
    )

    best_match = None

    for query in queries:

        html, search_url = (
            fetch_pricehistory_search(
                query
            )
        )

        if not html:
            continue

        results = parse_pricehistory_results(
            html,
            title
        )

        for result in results:

            if (
                best_match is None
                or result["similarity"]
                > best_match["similarity"]
            ):

                best_match = result

        if (
            best_match
            and best_match["similarity"]
            >= 0.60
        ):

            break

    if not best_match:

        return None

    product_data = (
        fetch_pricehistory_product(
            best_match["url"]
        )
    )

    if not product_data:

        return None

    return {
        "historical_low":
            product_data.get(
                "historical_low"
            ),

        "matched_title":
            best_match.get(
                "title"
            ),

        "pricehistory_url":
            product_data.get(
                "url"
            ),

        "similarity":
            best_match.get(
                "similarity"
            ),

        "category_text":
            product_data.get(
                "category_text",
                ""
            ),

        "page_title":
            product_data.get(
                "page_title",
                ""
            ),

        "resolved_deal_url":
            resolved_url,
    }


# ============================================================
# SUSPICIOUS HISTORICAL LOW
# ============================================================

def suspicious_historical_low(
    current_price,
    historical_low
):

    if not current_price:
        return False

    if not historical_low:
        return False

    # Extremely tiny historical value compared
    # with current value is suspicious.
    ratio = (
        historical_low
        /
        current_price
    )

    if (
        current_price >= 10000
        and historical_low < 100
    ):
        return True

    if (
        current_price >= 20000
        and historical_low < 200
    ):
        return True

    if ratio < 0.01:
        return True

    return False


# ============================================================
# PRICE COMPARISON
# ============================================================

def compare_price(
    current_price,
    historical_low
):

    current_price = normalize_price(
        current_price
    )

    historical_low = normalize_price(
        historical_low
    )

    if current_price is None:

        return {
            "status": "NOT_LOW",
            "reason":
                "Current price could not be parsed",
        }

    if historical_low is None:

        return {
            "status": "NOT_LOW",
            "reason":
                "Historical low could not be parsed",
        }

    # ========================================================
    # EQUAL ALSO COUNTS
    # ========================================================

    if current_price <= historical_low:

        return {
            "status": "NEW_LOW",
            "reason": (
                f"Current price "
                f"₹{current_price:,.0f} "
                f"is at/below historical low "
                f"₹{historical_low:,.0f}"
            ),
            "historical_low":
                historical_low,
        }

    difference = (
        current_price
        -
        historical_low
    )

    allowed_difference = max(
        historical_low
        *
        NEAR_LOW_PERCENT,

        NEAR_LOW_MAX_RUPEES
    )

    if difference <= allowed_difference:

        return {
            "status": "NEAR_LOW",
            "reason": (
                f"Current price "
                f"₹{current_price:,.0f} "
                f"is within "
                f"₹{allowed_difference:,.0f} "
                f"of historical low "
                f"₹{historical_low:,.0f}"
            ),
            "historical_low":
                historical_low,
        }

    return {
        "status": "NOT_LOW",
        "reason": (
            f"Current price "
            f"₹{current_price:,.0f} "
            f"is ₹{difference:,.0f} "
            f"above historical low "
            f"₹{historical_low:,.0f}"
        ),
        "historical_low":
            historical_low,
    }


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_deal(
    title,
    price,
    url=None,
    source=None
):

    try:

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        if not title:

            return {
                "status":
                    "CATEGORY_REJECT",

                "reason":
                    "Product title missing",

                "historical_low":
                    None,

                "source":
                    source,
            }

        # ----------------------------------------------------
        # PRICE
        # ----------------------------------------------------

        current_price = normalize_price(
            price
        )

        if current_price is None:

            return {
                "status":
                    "REJECT",

                "reason":
                    "Current price could not be parsed",

                "historical_low":
                    None,

                "source":
                    source,
            }

        # ----------------------------------------------------
        # MINIMUM PRICE
        # ----------------------------------------------------

        if current_price <= MIN_PRICE:

            return {
                "status":
                    "REJECT",

                "reason": (
                    f"Price "
                    f"₹{current_price:,.0f} "
                    f"is not above minimum "
                    f"₹{MIN_PRICE:,.0f}"
                ),

                "historical_low":
                    None,

                "source":
                    source,

                "price":
                    current_price,
            }

        # ----------------------------------------------------
        # INITIAL CATEGORY CHECK
        # ----------------------------------------------------

        category_result = classify_product(
            title
        )

        # ----------------------------------------------------
        # PRICEHISTORY LOOKUP
        # ----------------------------------------------------

        history = pricehistory_lookup(
            title=title,
            deal_url=url
        )

        # ----------------------------------------------------
        # IF CATEGORY IS UNKNOWN:
        # Try PriceHistory page/category information
        # before rejecting.
        # ----------------------------------------------------

        if not category_result["accepted"]:

            if history:

                extra_text = " ".join(
                    [
                        history.get(
                            "matched_title",
                            ""
                        ),

                        history.get(
                            "category_text",
                            ""
                        ),

                        history.get(
                            "page_title",
                            ""
                        ),
                    ]
                )

                category_result = classify_product(
                    title,
                    extra_text
                )

        # ----------------------------------------------------
        # CATEGORY FINAL CHECK
        # ----------------------------------------------------

        if not category_result["accepted"]:

            return {
                "status":
                    "CATEGORY_REJECT",

                "reason":
                    category_result["reason"],

                "historical_low":
                    None,

                "source":
                    source,

                "price":
                    current_price,
            }

        matched_category = (
            category_result[
                "matched_category"
            ]
        )

        # ----------------------------------------------------
        # PRICEHISTORY NOT FOUND
        # ----------------------------------------------------

        if not history:

            return {
                "status":
                    "NOT_LOW",

                "reason":
                    (
                        "PriceHistory product "
                        "match/history could not "
                        "be verified"
                    ),

                "historical_low":
                    None,

                "source":
                    source,

                "price":
                    current_price,

                "category":
                    matched_category,
            }

        # ----------------------------------------------------
        # HISTORICAL LOW
        # ----------------------------------------------------

        historical_low = normalize_price(
            history.get(
                "historical_low"
            )
        )

        if historical_low is None:

            return {
                "status":
                    "NOT_LOW",

                "reason":
                    (
                        "PriceHistory returned "
                        "no valid historical low"
                    ),

                "historical_low":
                    None,

                "source":
                    source,

                "price":
                    current_price,

                "category":
                    matched_category,
            }

        # ----------------------------------------------------
        # SUSPICIOUS HISTORY
        # ----------------------------------------------------

        if suspicious_historical_low(
            current_price,
            historical_low
        ):

            return {
                "status":
                    "NOT_LOW",

                "reason": (
                    "Suspicious PriceHistory "
                    f"low ₹{historical_low:,.0f}; "
                    "possible bad/mismatched history"
                ),

                "historical_low":
                    historical_low,

                "source":
                    source,

                "price":
                    current_price,

                "category":
                    matched_category,

                "pricehistory_url":
                    history.get(
                        "pricehistory_url"
                    ),
            }

        # ----------------------------------------------------
        # PRICE COMPARISON
        # ----------------------------------------------------

        comparison = compare_price(
            current_price,
            historical_low
        )

        return {
            "status":
                comparison["status"],

            "reason":
                comparison.get(
                    "reason"
                ),

            "source":
                source,

            "product":
                title,

            "price":
                current_price,

            "historical_low":
                historical_low,

            "category":
                matched_category,

            "pricehistory_url":
                history.get(
                    "pricehistory_url"
                ),

            "match_similarity":
                history.get(
                    "similarity"
                ),
        }

    except Exception as e:

        return {
            "status":
                "ERROR",

            "reason":
                f"Validator error: {e}",

            "historical_low":
                None,

            "source":
                source,
        }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "===================================="
    )

    print(
        "========== VALIDATOR TEST =========="
    )

    print(
        f"Version: 2.2"
    )

    print(
        f"Category file: "
        f"{CATEGORY_FILE}"
    )

    print(
        f"Allowed categories loaded: "
        f"{len(ALLOWED_CATEGORIES)}"
    )

    print(
        f"Excluded categories loaded: "
        f"{len(EXCLUDED_KEYWORDS)}"
    )

    print(
        f"Minimum price: "
        f"₹{MIN_PRICE}"
    )

    print(
        "===================================="
    )

    # Generic test only.
    # NO brand/model is required by the validator.
    test_title = "Wireless Headphones"

    result = validate_deal(
        title=test_title,
        price=2499,
        url="",
        source="TEST"
    )

    print(
        "STATUS:",
        result.get("status")
    )

    print(
        "HISTORICAL LOW:",
        result.get("historical_low")
    )

    print(
        "REASON:",
        result.get("reason")
    )

    print(
        "CATEGORY:",
        result.get("category")
    )

    print(
        "===================================="
    )