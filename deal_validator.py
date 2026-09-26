# deal_validator.py
# VERSION: 2.4

import os
import re
import html
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote


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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
    )
}


# ============================================================
# CATEGORY FILE
# ============================================================

def load_category_file():
    categories = []
    excluded = []

    if not os.path.isfile(CATEGORY_FILE):
        raise FileNotFoundError(
            f"CATEGORY FILE NOT FOUND: {CATEGORY_FILE}"
        )

    with open(
        CATEGORY_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        lines = f.readlines()

    in_exclude = False

    for raw in lines:

        line = raw.strip()

        if not line:
            continue

        upper = line.upper()

        if "EXCLUDE / DO NOT TARGET" in upper:
            in_exclude = True
            continue

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

        if re.match(r"^\d+\.\s+", line):
            continue

        if not line.startswith("-"):
            continue

        value = line[1:].strip()

        if not value:
            continue

        value = re.sub(
            r"\s+",
            " ",
            value
        )

        if in_exclude:
            excluded.append(value)
        else:
            categories.append(value)

    if not categories:
        raise ValueError(
            "CATEGORY FILE LOADED BUT NO CATEGORIES FOUND"
        )

    return categories, excluded


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = text.lower()

    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = text.replace("\\", " ")
    text = text.replace("-", " ")
    text = text.replace("_", " ")

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def tokenize(text):
    text = normalize_text(text)

    if not text:
        return set()

    return set(text.split())


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
    return {
        token
        for token in tokenize(text)
        if token not in STOP_WORDS
        and len(token) >= 2
    }


# ============================================================
# CATEGORY MATCHING
# ============================================================

def category_variants(category):
    variants = []

    parts = re.split(
        r"/|,",
        category
    )

    for part in parts:

        part = normalize_text(part)

        if not part:
            continue

        variants.append(part)

        words = part.split()
        singular = []

        for word in words:

            if word.endswith("ies") and len(word) > 4:
                singular.append(
                    word[:-3] + "y"
                )

            elif (
                word.endswith("s")
                and not word.endswith("ss")
            ):
                singular.append(
                    word[:-1]
                )

            else:
                singular.append(word)

        singular_text = " ".join(
            singular
        )

        if singular_text != part:
            variants.append(
                singular_text
            )

    return list(
        dict.fromkeys(variants)
    )


def category_matches(
    product_text,
    category
):
    if not product_text or not category:
        return False

    product_normalized = normalize_text(
        product_text
    )

    product_tokens = useful_tokens(
        product_text
    )

    for variant in category_variants(
        category
    ):

        if variant in product_normalized:
            return True

        category_tokens = useful_tokens(
            variant
        )

        if not category_tokens:
            continue

        if category_tokens.issubset(
            product_tokens
        ):
            return True

        if len(category_tokens) == 1:

            token = next(
                iter(category_tokens)
            )

            if token in product_tokens:
                return True

    return False


# ============================================================
# PRODUCT CLASSIFICATION
# ============================================================

def classify_product(
    product_title,
    extra_text=""
):
    categories, excluded = load_category_file()

    combined = " ".join(
        x for x in [
            product_title,
            extra_text
        ]
        if x
    )

    for item in excluded:

        if category_matches(
            combined,
            item
        ):
            return {
                "accepted": False,
                "category": None,
                "reason": (
                    "Product matches excluded "
                    f"category: {item}"
                )
            }

    for category in categories:

        if category_matches(
            combined,
            category
        ):
            return {
                "accepted": True,
                "category": category,
                "reason": (
                    "Matched category: "
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
# URL
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

        return response.url or url

    except Exception:
        return url


# ============================================================
# HTTP
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
# PRICE
# ============================================================

def parse_price(value):
    if value is None:
        return None

    text = str(value)

    text = (
        text
        .replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
    )

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
# HISTORICAL LOW
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
# PAGE TITLE
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
            return soup.title.get_text(
                " ",
                strip=True
            )

    except Exception:
        pass

    return ""


# ============================================================
# PRICEHISTORY METADATA
# ============================================================

def extract_metadata(html_text):
    if not html_text:
        return ""

    try:

        soup = BeautifulSoup(
            html_text,
            "html.parser"
        )

        pieces = []

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

        return " ".join(
            pieces
        )[:5000]

    except Exception:
        return ""


# ============================================================
# PRICEHISTORY SEARCH
# ============================================================

def search_pricehistory(
    product_title
):
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

        try:

            soup = BeautifulSoup(
                html_text,
                "html.parser"
            )

            links = []

            for anchor in soup.find_all(
                "a",
                href=True
            ):

                href = anchor.get(
                    "href",
                    ""
                )

                text = anchor.get_text(
                    " ",
                    strip=True
                )

                if href.startswith("/"):
                    href = (
                        "https://pricehistory.app"
                        + href
                    )

                if href:
                    links.append(
                        (href, text)
                    )

        except Exception:
            links = []

        seen = set()

        for href, anchor_text in links[:10]:

            if href in seen:
                continue

            seen.add(href)

            page = fetch_page(
                href
            )

            if not page:
                continue

            low = extract_historical_low(
                page
            )

            if low is None:
                continue

            return {
                "title": extract_page_title(
                    page
                ),
                "url": href,
                "historical_low": low,
                "category": extract_metadata(
                    page
                ),
            }

    return None


# ============================================================
# HISTORY VALIDATION
# ============================================================

def suspicious_historical_low(
    current_price,
    historical_low
):
    if (
        current_price is None
        or historical_low is None
    ):
        return False

    if historical_low <= 0:
        return True

    if (
        current_price >= 5000
        and historical_low
        < current_price * 0.05
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
    if (
        current_price is None
        or historical_low is None
    ):
        return (
            "NOT_LOW",
            "Historical low price unavailable"
        )

    if current_price <= historical_low:
        return (
            "NEW_LOW",
            "Current price is at or below historical low"
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
            "Current price is near historical low"
        )

    return (
        "NOT_LOW",
        "Current price is above historical low"
    )


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_deal(
    product_title,
    current_price,
    url="",
    source=""
):

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

    if current_price <= MIN_PRICE:

        return {
            "status": "PRICE_REJECT",
            "historical_low": None,
            "reason": (
                f"Product price ₹{current_price:.0f} "
                f"is not above ₹{MIN_PRICE}"
            ),
            "category": None,
        }

    resolved_url = resolve_url(
        url
    ) if url else ""

    classification = classify_product(
        product_title
    )

    pricehistory = search_pricehistory(
        product_title
    )

    historical_low = None
    ph_title = ""
    ph_category = ""
    ph_url = ""

    if pricehistory:

        historical_low = pricehistory.get(
            "historical_low"
        )

        ph_title = pricehistory.get(
            "title",
            ""
        )

        ph_category = pricehistory.get(
            "category",
            ""
        )

        ph_url = pricehistory.get(
            "url",
            ""
        )

    if not classification["accepted"]:

        metadata = " ".join(
            x for x in [
                product_title,
                ph_title,
                ph_category
            ]
            if x
        )

        classification = classify_product(
            metadata
        )

    if not classification["accepted"]:

        return {
            "status": "CATEGORY_REJECT",
            "historical_low": historical_low,
            "reason": classification["reason"],
            "category": None,
            "source": source,
            "url": (
                resolved_url
                or ph_url
            ),
        }

    if historical_low is None:

        return {
            "status": "NOT_LOW",
            "historical_low": None,
            "reason": (
                "Historical low price "
                "could not be determined"
            ),
            "category": classification.get(
                "category"
            ),
            "source": source,
            "url": (
                resolved_url
                or ph_url
            ),
        }

    if suspicious_historical_low(
        current_price,
        historical_low
    ):

        return {
            "status": "SUSPICIOUS_HISTORY",
            "historical_low": historical_low,
            "reason": (
                "Historical low appears "
                "unrealistically low"
            ),
            "category": classification.get(
                "category"
            ),
            "source": source,
            "url": (
                resolved_url
                or ph_url
            ),
        }

    status, reason = compare_price(
        current_price,
        historical_low
    )

    return {
        "status": status,
        "historical_low": historical_low,
        "reason": reason,
        "category": classification.get(
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
        "========== VALIDATOR TEST =========="
    )

    try:

        categories, excluded = load_category_file()

        print(
            "CATEGORY FILE:",
            CATEGORY_FILE
        )

        print(
            "CATEGORIES LOADED:",
            len(categories)
        )

        print(
            "EXCLUSIONS LOADED:",
            len(excluded)
        )

        test = classify_product(
            "Wireless Headphones"
        )

        print(
            "TEST PRODUCT:",
            "Wireless Headphones"
        )

        print(
            "CATEGORY TEST:",
            test
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

    except Exception as e:

        print(
            "ERROR:",
            str(e)
        )

    print(
        "===================================="
    )