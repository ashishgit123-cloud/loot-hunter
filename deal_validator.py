# ============================================================
# DEAL VALIDATOR v2.3
# ============================================================
# Purpose:
# - Read product categories from product_categories.txt
# - No brand/model hardcoding
# - Generic product/category matching
# - PriceHistory validation
# - NEW_LOW when current price <= historical low
# - NEAR_LOW when within configured tolerance
# - Reject products <= ₹1,000
# ============================================================

import os
import re
import html
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CATEGORY_FILE = os.path.join(
    BASE_DIR,
    "product_categories.txt"
)

MIN_PRICE = 1000

NEAR_LOW_PERCENT = 3.0
NEAR_LOW_MAX_RUPEES = 50

REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}


# ============================================================
# CATEGORY FILE
# ============================================================

def load_category_file():
    """
    Reads product_categories.txt.

    Returns:
        {
            "categories": [...],
            "excluded": [...]
        }
    """

    categories = []
    excluded = []

    if not os.path.exists(CATEGORY_FILE):
        return categories, excluded

    try:
        with open(
            CATEGORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            lines = f.readlines()

    except Exception:
        return categories, excluded

    in_exclude_section = False

    for raw_line in lines:

        line = raw_line.strip()

        if not line:
            continue

        upper = line.upper()

        # ----------------------------------------------------
        # Detect exclude section
        # ----------------------------------------------------

        if (
            "EXCLUDE / DO NOT TARGET" in upper
            or "EXCLUDE" == upper
        ):
            in_exclude_section = True
            continue

        # ----------------------------------------------------
        # Ignore headers / separators / comments
        # ----------------------------------------------------

        if line.startswith("="):
            continue

        if line.startswith("#"):
            continue

        if upper.startswith("DEAL BOT"):
            continue

        if upper.startswith("VERSION:"):
            continue

        if upper.startswith("PURPOSE:"):
            continue

        if upper.startswith("SOURCE-OF-TRUTH"):
            continue

        if upper.startswith("MINIMUM DEAL PRICE"):
            continue

        # ----------------------------------------------------
        # Ignore numbered section headings
        # Example:
        # 1. ELECTRONICS & COMPUTING
        # ----------------------------------------------------

        if re.match(r"^\d+\.\s+", line):
            continue

        # ----------------------------------------------------
        # Only process bullet lines
        # ----------------------------------------------------

        if not line.startswith("-"):
            continue

        value = line[1:].strip()

        if not value:
            continue

        # Remove accidental duplicate spaces
        value = re.sub(r"\s+", " ", value)

        if in_exclude_section:
            excluded.append(value)
        else:
            categories.append(value)

    return categories, excluded


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):
    if not text:
        return ""

    text = html.unescape(str(text))

    text = text.lower()

    # Normalize common separators
    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = text.replace("\\", " ")
    text = text.replace("-", " ")
    text = text.replace("_", " ")

    # Remove punctuation
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def tokenize(text):
    normalized = normalize_text(text)

    if not normalized:
        return set()

    return set(normalized.split())


# ============================================================
# TOKEN HELPERS
# ============================================================

STOP_WORDS = {
    "the",
    "and",
    "with",
    "for",
    "from",
    "new",
    "latest",
    "original",
    "official",
    "best",
    "premium",
    "pro",
    "plus",
    "edition",
    "model",
    "product",
    "online",
    "sale",
    "offer",
    "offers",
    "deal",
    "deals",
}


def useful_tokens(text):
    tokens = tokenize(text)

    return {
        token
        for token in tokens
        if token not in STOP_WORDS
        and len(token) >= 2
    }


# ============================================================
# GENERIC CATEGORY MATCHING
# ============================================================

def category_variants(category):
    """
    Creates generic matching variants from a category.

    Example:
        Headphones
        -> headphones

        Smartphones / Mobile Phones
        -> smartphones mobile phones
        -> smartphone mobile phone
    """

    variants = []

    raw = category.strip()

    if not raw:
        return variants

    variants.append(raw)

    # Split slash alternatives
    parts = re.split(r"/|,", raw)

    for part in parts:

        part = part.strip()

        if not part:
            continue

        variants.append(part)

        words = part.split()

        # Singular/plural generic normalization
        singular_words = []

        for word in words:

            if word.endswith("ies") and len(word) > 4:
                singular_words.append(
                    word[:-3] + "y"
                )

            elif word.endswith("s") and not word.endswith("ss"):
                singular_words.append(
                    word[:-1]
                )

            else:
                singular_words.append(word)

        variants.append(
            " ".join(singular_words)
        )

    # Deduplicate
    output = []

    seen = set()

    for item in variants:

        normalized = normalize_text(item)

        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)

    return output


def phrase_match(product_text, category_variant):
    """
    Strong generic phrase match.

    Example:
        "wireless headphones bluetooth"
        matches
        "headphones"
    """

    product_normalized = normalize_text(product_text)
    category_normalized = normalize_text(category_variant)

    if not product_normalized or not category_normalized:
        return False

    # Exact phrase
    if category_normalized in product_normalized:
        return True

    return False


def category_matches(product_text, category):
    """
    Generic category matching.

    No brands/models are used.

    Matching order:
    1. Exact category phrase
    2. Category alternative phrase
    3. Generic token matching
    """

    if not product_text or not category:
        return False

    product_normalized = normalize_text(product_text)

    product_tokens = useful_tokens(product_text)

    for variant in category_variants(category):

        # ----------------------------------------------------
        # Exact phrase match
        # ----------------------------------------------------

        if phrase_match(
            product_normalized,
            variant
        ):
            return True

        # ----------------------------------------------------
        # Token match
        # ----------------------------------------------------

        category_tokens = useful_tokens(variant)

        if not category_tokens:
            continue

        # All category words present
        if category_tokens.issubset(product_tokens):
            return True

        # Single-word category
        if len(category_tokens) == 1:

            token = next(iter(category_tokens))

            if token in product_tokens:
                return True

    return False


# ============================================================
# EXCLUSION MATCHING
# ============================================================

def is_excluded(product_text, excluded):
    """
    Checks excluded generic categories/items.

    Does NOT use brands/models.
    """

    if not product_text:
        return False, None

    for item in excluded:

        if category_matches(
            product_text,
            item
        ):
            return True, item

    return False, None


# ============================================================
# PRODUCT CATEGORY CLASSIFICATION
# ============================================================

def classify_product(product_title, extra_text=""):
    """
    Generic classification using:
        product title
        extra metadata

    Returns:
        {
            "accepted": bool,
            "category": str|None,
            "reason": str
        }
    """

    categories, excluded = load_category_file()

    combined_text = " ".join(
        x for x in [
            product_title,
            extra_text
        ]
        if x
    )

    # --------------------------------------------------------
    # Exclusions FIRST
    # --------------------------------------------------------

    excluded_match, excluded_item = is_excluded(
        combined_text,
        excluded
    )

    if excluded_match:

        return {
            "accepted": False,
            "category": None,
            "reason": (
                "Product matches excluded category: "
                f"{excluded_item}"
            )
        }

    # --------------------------------------------------------
    # Category matching
    # --------------------------------------------------------

    for category in categories:

        if category_matches(
            combined_text,
            category
        ):

            return {
                "accepted": True,
                "category": category,
                "reason": (
                    "Matched configured category: "
                    f"{category}"
                )
            }

    return {
        "accepted": False,
        "category": None,
        "reason": (
            "Product category is outside "
            "configured deal categories"
        )
    }


# ============================================================
# URL RESOLUTION
# ============================================================

def resolve_url(url):
    """
    Resolves short URLs such as fkrt.co.
    """

    if not url:
        return ""

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )

        return response.url or url

    except Exception:
        return url


# ============================================================
# HTTP FETCH
# ============================================================

def fetch_page(url):
    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )

        if response.status_code >= 400:
            return ""

        return response.text

    except Exception:
        return ""


# ============================================================
# PRICE PARSING
# ============================================================

def parse_price(value):
    if value is None:
        return None

    text = str(value)

    text = text.replace(",", "")
    text = text.replace("₹", "")
    text = text.replace("Rs.", "")
    text = text.replace("Rs", "")
    text = text.replace("INR", "")

    match = re.search(
        r"(\d+(?:\.\d+)?)",
        text
    )

    if not match:
        return None

    try:
        return float(match.group(1))
    except Exception:
        return None


# ============================================================
# HISTORICAL LOW EXTRACTION
# ============================================================

def extract_historical_low(text):
    if not text:
        return None

    patterns = [

        r"all[\s\-]*time[\s\-]*low"
        r".{0,120}?"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        r"historical[\s\-]*low"
        r".{0,120}?"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        r"lowest[\s\-]*price"
        r".{0,120}?"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        r"lowest[\s\-]*ever"
        r".{0,120}?"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        r"lowest"
        r".{0,80}?"
        r"(?:₹|rs\.?|inr)\s*"
        r"([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I | re.S
        )

        if match:

            price = parse_price(
                match.group(1)
            )

            if price is not None:
                return price

    # --------------------------------------------------------
    # JSON-like / HTML keys
    # --------------------------------------------------------

    key_patterns = [

        r'"lowestPrice"\s*:\s*"?([\d,.]+)',
        r'"lowest_price"\s*:\s*"?([\d,.]+)',
        r'"historicalLow"\s*:\s*"?([\d,.]+)',
        r'"historical_low"\s*:\s*"?([\d,.]+)',
        r'"allTimeLow"\s*:\s*"?([\d,.]+)',
        r'"all_time_low"\s*:\s*"?([\d,.]+)',
    ]

    for pattern in key_patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            price = parse_price(
                match.group(1)
            )

            if price is not None:
                return price

    return None


# ============================================================
# TITLE EXTRACTION
# ============================================================

def extract_page_title(html_text):
    if not html_text:
        return ""

    try:

        soup = BeautifulSoup(
            html_text,
            "html.parser"
        )

        if soup.title:

            title = soup.title.get_text(
                " ",
                strip=True
            )

            return title

    except Exception:
        pass

    return ""


# ============================================================
# CATEGORY METADATA EXTRACTION
# ============================================================

def extract_category_metadata(html_text):
    """
    Extracts generic category information from page.

    No brand/model assumptions.
    """

    if not html_text:
        return ""

    try:

        soup = BeautifulSoup(
            html_text,
            "html.parser"
        )

        pieces = []

        # Breadcrumbs
        for element in soup.select(
            "[class*='breadcrumb'], "
            "[class*='category'], "
            "[class*='Category']"
        ):

            text = element.get_text(
                " ",
                strip=True
            )

            if text:
                pieces.append(text)

        # Meta keywords
        for meta in soup.find_all(
            "meta"
        ):

            name = (
                meta.get("name")
                or meta.get("property")
                or ""
            ).lower()

            if name in {
                "keywords",
                "category",
                "product:category"
            }:

                content = meta.get(
                    "content",
                    ""
                )

                if content:
                    pieces.append(content)

        # Limit size
        return " ".join(
            pieces
        )[:5000]

    except Exception:
        return ""


# ============================================================
# PRICEHISTORY SEARCH
# ============================================================

def search_pricehistory(product_title):
    """
    Attempts generic PriceHistory search.

    Returns:
        {
            "title": ...,
            "url": ...,
            "historical_low": ...,
            "category": ...,
            "raw": ...
        }

    If unavailable, returns None.
    """

    if not product_title:
        return None

    query = quote(
        product_title[:180]
    )

    search_urls = [

        f"https://pricehistory.app/search?q={query}",

        f"https://pricehistoryapp.com/search?q={query}",
    ]

    for search_url in search_urls:

        html_text = fetch_page(
            search_url
        )

        if not html_text:
            continue

        # ----------------------------------------------------
        # Extract possible product URLs
        # ----------------------------------------------------

        links = []

        try:

            soup = BeautifulSoup(
                html_text,
                "html.parser"
            )

            for anchor in soup.find_all(
                "a",
                href=True
            ):

                href = anchor.get(
                    "href",
                    ""
                )

                anchor_text = anchor.get_text(
                    " ",
                    strip=True
                )

                if (
                    "pricehistory" in href
                    or "pricehistory" in search_url
                ):

                    if href.startswith("/"):
                        href = (
                            "https://pricehistory.app"
                            + href
                        )

                    links.append(
                        (
                            href,
                            anchor_text
                        )
                    )

        except Exception:
            links = []

        # ----------------------------------------------------
        # Try result pages
        # ----------------------------------------------------

        candidates = []

        for href, anchor_text in links:

            combined = (
                anchor_text
                + " "
                + href
            )

            if product_title.lower() in combined.lower():

                candidates.insert(
                    0,
                    href
                )

            else:
                candidates.append(
                    href
                )

        # Remove duplicates
        unique_candidates = []

        seen = set()

        for url in candidates:

            if url in seen:
                continue

            seen.add(url)
            unique_candidates.append(url)

        # Limit requests
        for product_url in unique_candidates[:5]:

            page = fetch_page(
                product_url
            )

            if not page:
                continue

            low = extract_historical_low(
                page
            )

            page_title = extract_page_title(
                page
            )

            metadata = extract_category_metadata(
                page
            )

            if low is not None:

                return {
                    "title": page_title,
                    "url": product_url,
                    "historical_low": low,
                    "category": metadata,
                    "raw": page
                }

        # ----------------------------------------------------
        # Search page itself may contain low
        # ----------------------------------------------------

        low = extract_historical_low(
            html_text
        )

        if low is not None:

            return {
                "title": "",
                "url": search_url,
                "historical_low": low,
                "category": "",
                "raw": html_text
            }

    return None


# ============================================================
# SUSPICIOUS HISTORICAL LOW CHECK
# ============================================================

def suspicious_historical_low(
    current_price,
    historical_low
):
    """
    Prevent obviously broken history values.

    Example:
        Current = ₹25,000
        Historical = ₹99

    Such a value is suspicious and should not
    automatically qualify the deal.
    """

    if current_price is None:
        return False

    if historical_low is None:
        return False

    if historical_low <= 0:
        return True

    # Extremely low relative to current price
    if (
        current_price >= 5000
        and historical_low < current_price * 0.05
    ):
        return True

    return False


# ============================================================
# PRICE COMPARISON
# ============================================================

def compare_price(
    current_price,
    historical_low
):
    """
    Returns:

        NEW_LOW
            Current price <= historical low

        NEAR_LOW
            Within 3% OR ₹50

        NOT_LOW
            Otherwise
    """

    if (
        current_price is None
        or historical_low is None
    ):
        return (
            "NOT_LOW",
            "Historical low price unavailable"
        )

    # --------------------------------------------------------
    # Equal historical low IS accepted
    # --------------------------------------------------------

    if current_price <= historical_low:

        return (
            "NEW_LOW",
            (
                "Current price is at or below "
                "historical low"
            )
        )

    difference = (
        current_price
        - historical_low
    )

    tolerance = max(
        NEAR_LOW_MAX_RUPEES,
        historical_low
        * NEAR_LOW_PERCENT
        / 100
    )

    if difference <= tolerance:

        return (
            "NEAR_LOW",
            (
                "Current price is within "
                f"{NEAR_LOW_PERCENT}% / "
                f"₹{NEAR_LOW_MAX_RUPEES} "
                "of historical low"
            )
        )

    return (
        "NOT_LOW",
        "Current price is above historical low"
    )


# ============================================================
# VALIDATE DEAL
# ============================================================

def validate_deal(
    product_title,
    current_price,
    url="",
    source=""
):

    # --------------------------------------------------------
    # Basic validation
    # --------------------------------------------------------

    if not product_title:

        return {
            "status": "REJECT",
            "historical_low": None,
            "reason": "Product title is empty",
            "category": None,
        }

    try:
        current_price = float(
            current_price
        )
    except Exception:

        return {
            "status": "REJECT",
            "historical_low": None,
            "reason": "Invalid current price",
            "category": None,
        }

    # --------------------------------------------------------
    # Minimum price
    # --------------------------------------------------------

    if current_price <= MIN_PRICE:

        return {
            "status": "PRICE_REJECT",
            "historical_low": None,
            "reason": (
                f"Product price ₹{current_price:.0f} "
                f"is not above minimum ₹{MIN_PRICE}"
            ),
            "category": None,
        }

    # --------------------------------------------------------
    # Resolve URL
    # --------------------------------------------------------

    resolved_url = resolve_url(
        url
    ) if url else ""

    # --------------------------------------------------------
    # FIRST: try title classification
    # --------------------------------------------------------

    classification = classify_product(
        product_title
    )

    category_result = classification

    # --------------------------------------------------------
    # PriceHistory lookup
    #
    # Important:
    # Even if title classification fails,
    # we STILL continue to PriceHistory.
    #
    # This prevents model-only titles such as:
    # "Samsung Galaxy S23 5G..."
    # from being rejected before metadata lookup.
    # --------------------------------------------------------

    pricehistory = search_pricehistory(
        product_title
    )

    historical_low = None
    ph_category = ""
    ph_title = ""
    ph_url = ""

    if pricehistory:

        historical_low = pricehistory.get(
            "historical_low"
        )

        ph_category = pricehistory.get(
            "category",
            ""
        )

        ph_title = pricehistory.get(
            "title",
            ""
        )

        ph_url = pricehistory.get(
            "url",
            ""
        )

    # --------------------------------------------------------
    # SECOND classification using PriceHistory metadata
    # --------------------------------------------------------

    if not category_result["accepted"]:

        metadata_text = " ".join(
            x for x in [
                product_title,
                ph_title,
                ph_category
            ]
            if x
        )

        category_result = classify_product(
            metadata_text
        )

    # --------------------------------------------------------
    # If still not classified
    # --------------------------------------------------------

    if not category_result["accepted"]:

        return {
            "status": "CATEGORY_REJECT",
            "historical_low": historical_low,
            "reason": category_result["reason"],
            "category": None,
            "source": source,
            "url": (
                resolved_url
                or ph_url
            ),
        }

    # --------------------------------------------------------
    # Historical low unavailable
    # --------------------------------------------------------

    if historical_low is None:

        return {
            "status": "NOT_LOW",
            "historical_low": None,
            "reason": (
                "Historical low price "
                "could not be determined"
            ),
            "category": category_result.get(
                "category"
            ),
            "source": source,
            "url": (
                resolved_url
                or ph_url
            ),
        }

    # --------------------------------------------------------
    # Suspicious historical low
    # --------------------------------------------------------

    if suspicious_historical_low(
        current_price,
        historical_low
    ):

        return {
            "status": "SUSPICIOUS_HISTORY",
            "historical_low": historical_low,
            "reason": (
                "Historical low appears "
                "unrealistically low compared "
                "with current price"
            ),
            "category": category_result.get(
                "category"
            ),
            "source": source,
            "url": (
                resolved_url
                or ph_url
            ),
        }

    # --------------------------------------------------------
    # Compare price
    # --------------------------------------------------------

    status, reason = compare_price(
        current_price,
        historical_low
    )

    # --------------------------------------------------------
    # Final result
    # --------------------------------------------------------

    return {
        "status": status,
        "historical_low": historical_low,
        "reason": reason,
        "category": category_result.get(
            "category"
        ),
        "source": source,
        "url": (
            resolved_url
            or ph_url
        ),
    }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "===================================="
    )

    print(
        "========== VALIDATOR TEST ==========="
    )

    result = validate_deal(
        product_title="Wireless Headphones",
        current_price=2499,
        url="",
        source="TEST"
    )

    print(
        "status:",
        result.get("status")
    )

    print(
        "historical_low:",
        result.get("historical_low")
    )

    print(
        "category:",
        result.get("category")
    )

    print(
        "reason:",
        result.get("reason")
    )

    print(
        "===================================="
    )