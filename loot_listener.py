import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urlparse


# ============================================================
# CONFIG
# ============================================================

REQUEST_TIMEOUT = 15

# Product categories we want
ALLOWED_CATEGORIES = [
    "electronics",
    "mobile",
    "smartphone",
    "laptop",
    "tablet",
    "monitor",
    "tv",
    "television",
    "headphone",
    "earphone",
    "earbuds",
    "speaker",
    "camera",
    "printer",
    "router",
    "ssd",
    "hard disk",
    "keyboard",
    "mouse",
    "gaming",
    "furniture",
    "chair",
    "office chair",
    "sofa",
    "bed",
    "mattress",
    "table",
    "desk",
    "cabinet",
    "sports",
    "running shoe",
    "running shoes",
    "sports shoe",
    "sports shoes",
    "sneaker",
    "sneakers",
    "football",
    "cricket",
    "badminton",
    "fitness",
    "gym",
    "treadmill",
]

# Things we do NOT want
EXCLUDED_KEYWORDS = [
    "phone cover",
    "mobile cover",
    "back cover",
    "case for",
    "flip cover",
    "silicon cover",
    "silicone cover",
    "tempered glass",
    "screen protector",
    "screen guard",
    "charging cable",
    "data cable",
    "usb cable",
    "type c cable",
    "lightning cable",
    "aux cable",
    "watch strap",
    "watch band",
    "smart band",
    "fitness band",
    "bangle",
    "bracelet",
    "jewellery",
    "jewelry",
    "earring",
    "necklace",
    "ring",
    "socks",
    "innerwear",
    "underwear",
    "t-shirt",
    "shirt",
    "kurta",
    "jeans",
    "trouser",
    "trousers",
    "dress",
    "saree",
    "sandal",
    "slipper",
    "belt",
    "wallet",
    "small accessory",
    "replacement part",
    "spare part",
]


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
})


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", str(text))
    return text.strip()


def normalize_title(title):
    title = clean_text(title).lower()

    # Remove common noise
    title = re.sub(r"\([^)]*\)", " ", title)
    title = re.sub(r"\[[^\]]*\]", " ", title)

    # Remove special characters
    title = re.sub(r"[^a-z0-9\s]", " ", title)

    # Common useless words
    stop_words = {
        "buy",
        "best",
        "deal",
        "offer",
        "sale",
        "discount",
        "price",
        "online",
        "india",
        "amazon",
        "flipkart",
        "new",
        "latest",
        "original",
        "free",
    }

    words = []

    for word in title.split():
        if word not in stop_words:
            words.append(word)

    return " ".join(words)


def title_tokens(title):
    normalized = normalize_title(title)

    if not normalized:
        return set()

    return set(normalized.split())


def title_similarity(title1, title2):
    """
    Basic token based similarity.
    Used only as a safety check so unrelated PriceHistory
    products are not accepted.
    """

    a = title_tokens(title1)
    b = title_tokens(title2)

    if not a or not b:
        return 0.0

    common = a.intersection(b)

    return len(common) / max(len(a), len(b))


# ============================================================
# PRICE HELPERS
# ============================================================

def parse_price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        value = float(value)

        if value <= 0:
            return None

        return value

    text = str(value)

    # Remove commas etc.
    text = text.replace(",", "")

    match = re.search(
        r"(?:₹|Rs\.?|INR)?\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE
    )

    if not match:
        return None

    try:
        price = float(match.group(1))

        if price <= 0:
            return None

        return price

    except Exception:
        return None


def extract_prices(text):
    """
    Extract all prices from text.
    """

    if not text:
        return []

    patterns = [
        r"₹\s*[\d,]+(?:\.\d+)?",
        r"\bRs\.?\s*[\d,]+(?:\.\d+)?",
        r"\bINR\s*[\d,]+(?:\.\d+)?",
    ]

    found = []

    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            price = parse_price(match)

            if price is not None:
                found.append(price)

    return found


# ============================================================
# PRODUCT CLASSIFICATION
# ============================================================

def classify_product(title):
    if not title:
        return {
            "allowed": False,
            "category": None,
            "reason": "Product title is empty"
        }

    text = title.lower()

    # First reject obvious junk/accessories
    for keyword in EXCLUDED_KEYWORDS:

        if keyword in text:
            return {
                "allowed": False,
                "category": "excluded",
                "reason": f"Excluded product type: {keyword}"
            }

    # Then find allowed category
    for keyword in ALLOWED_CATEGORIES:

        if keyword in text:
            return {
                "allowed": True,
                "category": keyword,
                "reason": f"Allowed category: {keyword}"
            }

    return {
        "allowed": False,
        "category": None,
        "reason": "Product category is outside configured deal categories"
    }


# ============================================================
# URL RESOLUTION
# ============================================================

def resolve_url(url):
    """
    Resolve short URLs such as:
      fkrt.co/xxxxx
      amzn.in/xxxxx
      amzn.to/xxxxx

    Returns:
      resolved_url, error
    """

    if not url:
        return None, "URL is empty"

    url = url.strip()

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        final_url = response.url

        if not final_url:
            return None, "URL resolution returned empty URL"

        return final_url, None

    except requests.RequestException as exc:
        return None, f"URL resolution failed: {exc}"


# ============================================================
# DOMAIN DETECTION
# ============================================================

def get_domain(url):
    if not url:
        return ""

    try:
        hostname = urlparse(url).hostname or ""
        return hostname.lower()
    except Exception:
        return ""


def normalize_domain(domain):
    domain = domain.lower()

    if domain.startswith("www."):
        domain = domain[4:]

    return domain


# ============================================================
# PRICEHISTORY SEARCH
# ============================================================

def build_pricehistory_queries(title):
    """
    Creates multiple search queries.

    We intentionally use the actual product title rather than
    hardcoding Samsung/iPhone/etc.
    """

    title = clean_text(title)

    queries = []

    if title:
        queries.append(title)

    normalized = normalize_title(title)

    if normalized and normalized != title.lower():
        queries.append(normalized)

    # Remove very long titles
    words = normalized.split()

    if len(words) > 8:
        queries.append(" ".join(words[:8]))

    return list(dict.fromkeys(queries))


def fetch_pricehistory_search(query):
    """
    Search PriceHistory website.

    If their search endpoint changes, this function fails safely
    instead of pretending that a product was found.
    """

    search_url = (
        "https://pricehistory.app/search"
        "?q=" + quote_plus(query)
    )

    try:
        response = SESSION.get(
            search_url,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return []

        return parse_pricehistory_results(
            response.text,
            query
        )

    except requests.RequestException:
        return []


def parse_pricehistory_results(html, query):
    """
    Parse possible PriceHistory result cards.

    We deliberately collect candidate information and validate
    title similarity before accepting anything.
    """

    soup = BeautifulSoup(html, "html.parser")

    candidates = []

    # Links are the most reliable anchor for a product result.
    for anchor in soup.find_all("a", href=True):

        href = anchor.get("href", "").strip()

        if not href:
            continue

        text = clean_text(anchor.get_text(" ", strip=True))

        if not text:
            continue

        # Look for product-ish text
        prices = extract_prices(text)

        if not prices:
            # Try parent card
            parent = anchor

            for _ in range(4):

                parent = parent.parent

                if not parent:
                    break

                parent_text = clean_text(
                    parent.get_text(" ", strip=True)
                )

                prices = extract_prices(parent_text)

                if prices:
                    text = parent_text
                    break

        if not prices:
            continue

        absolute_url = href

        if href.startswith("/"):
            absolute_url = "https://pricehistory.app" + href
        elif href.startswith("//"):
            absolute_url = "https:" + href

        candidates.append({
            "title": text,
            "url": absolute_url,
            "prices": prices,
        })

    return candidates


# ============================================================
# PRICEHISTORY PRODUCT PAGE
# ============================================================

def fetch_pricehistory_product(url):
    """
    Open a PriceHistory product page and try to extract
    historical minimum.
    """

    if not url:
        return None

    try:
        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        page_text = clean_text(
            soup.get_text(" ", strip=True)
        )

        # ----------------------------------------------------
        # Explicit historical-low labels
        # ----------------------------------------------------

        historical_patterns = [
            r"all[\s\-]*time\s+low[^₹0-9]{0,50}₹?\s*([\d,]+)",
            r"lowest\s+price[^₹0-9]{0,50}₹?\s*([\d,]+)",
            r"lowest\s+ever[^₹0-9]{0,50}₹?\s*([\d,]+)",
            r"historical\s+low[^₹0-9]{0,50}₹?\s*([\d,]+)",
            r"lowest[^₹0-9]{0,50}₹?\s*([\d,]+)",
        ]

        for pattern in historical_patterns:

            match = re.search(
                pattern,
                page_text,
                re.IGNORECASE
            )

            if match:

                price = parse_price(
                    match.group(1)
                )

                if price:
                    return {
                        "historical_low": price,
                        "page_title": clean_text(
                            soup.title.get_text()
                            if soup.title
                            else ""
                        ),
                        "source_url": url,
                    }

        # ----------------------------------------------------
        # JSON-LD / script fallback
        # ----------------------------------------------------

        script_text = " ".join(
            script.get_text(" ", strip=True)
            for script in soup.find_all("script")
        )

        patterns = [
            r'"lowestPrice"\s*:\s*"?(?:₹)?([\d,.]+)',
            r'"lowest_price"\s*:\s*"?(?:₹)?([\d,.]+)',
            r'"allTimeLow"\s*:\s*"?(?:₹)?([\d,.]+)',
            r'"all_time_low"\s*:\s*"?(?:₹)?([\d,.]+)',
            r'"minPrice"\s*:\s*"?(?:₹)?([\d,.]+)',
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                script_text,
                re.IGNORECASE
            )

            if match:

                price = parse_price(
                    match.group(1)
                )

                if price:
                    return {
                        "historical_low": price,
                        "page_title": clean_text(
                            soup.title.get_text()
                            if soup.title
                            else ""
                        ),
                        "source_url": url,
                    }

        return None

    except requests.RequestException:
        return None


# ============================================================
# PRICEHISTORY LOOKUP
# ============================================================

def pricehistory_lookup(product_title, merchant_url=None):
    """
    Returns the best matching PriceHistory record.

    IMPORTANT:
    We do not accept the first random search result.
    Product title similarity is checked.
    """

    queries = build_pricehistory_queries(
        product_title
    )

    all_candidates = []

    for query in queries:

        results = fetch_pricehistory_search(
            query
        )

        all_candidates.extend(results)

        if all_candidates:
            break

    if not all_candidates:
        return {
            "found": False,
            "reason": "No PriceHistory product found"
        }

    best_candidate = None
    best_similarity = 0.0

    for candidate in all_candidates:

        candidate_title = candidate.get(
            "title",
            ""
        )

        similarity = title_similarity(
            product_title,
            candidate_title
        )

        if similarity > best_similarity:

            best_similarity = similarity
            best_candidate = candidate

    # Safety threshold
    if not best_candidate or best_similarity < 0.35:

        return {
            "found": False,
            "reason": (
                "PriceHistory result found but product "
                "title did not match sufficiently"
            ),
            "similarity": best_similarity,
        }

    history = fetch_pricehistory_product(
        best_candidate.get("url")
    )

    if not history:

        return {
            "found": False,
            "reason": (
                "Matching PriceHistory product found, "
                "but historical low could not be extracted"
            ),
            "matched_title": best_candidate.get(
                "title",
                ""
            ),
            "similarity": best_similarity,
        }

    history["found"] = True

    history["matched_title"] = best_candidate.get(
        "title",
        ""
    )

    history["similarity"] = best_similarity

    return history


# ============================================================
# SUSPICIOUS HISTORY CHECK
# ============================================================

def suspicious_historical_low(
    product_title,
    current_price,
    historical_low
):
    """
    Prevent obviously bad historical records from creating
    fake loot alerts.

    Example:
      Samsung S23 current = ₹26,499
      history = ₹99

    ₹99 is suspicious and should not automatically be treated
    as a genuine historical low.
    """

    if not historical_low:
        return False, ""

    if historical_low <= 0:
        return True, "Historical low is zero or negative"

    # Extremely low history for normally expensive products
    high_value_keywords = [
        "iphone",
        "samsung galaxy",
        "pixel",
        "oneplus",
        "ipad",
        "macbook",
        "laptop",
        "television",
        "tv",
        "monitor",
        "camera",
        "washing machine",
        "refrigerator",
        "sofa",
        "bed",
        "office chair",
    ]

    title = product_title.lower()

    high_value_product = any(
        keyword in title
        for keyword in high_value_keywords
    )

    if high_value_product:

        if historical_low < 500:
            return (
                True,
                "Historical low looks suspiciously low for this product"
            )

    # If current price is very high and historical low is
    # unrealistically tiny, flag it.
    if current_price >= 5000:

        if historical_low < current_price * 0.03:
            return (
                True,
                "Historical low is below 3% of current price and may be invalid"
            )

    return False, ""


# ============================================================
# PRICE COMPARISON
# ============================================================

def compare_price(current_price, historical_low):
    """
    IMPORTANT LOGIC

    current <= historical low
        -> NEW_LOW

    current is within 3% OR ₹50 of historical low
        -> NEAR_LOW

    otherwise
        -> NOT_LOW
    """

    if current_price is None:
        return {
            "status": "INVALID_PRICE",
            "reason": "Current price could not be determined"
        }

    if historical_low is None:
        return {
            "status": "PRICE_HISTORY_NOT_FOUND",
            "reason": "Historical low is unavailable"
        }

    # --------------------------------------------------------
    # EXACT EQUAL ALSO COUNTS AS NEW LOW
    # --------------------------------------------------------

    if current_price <= historical_low:

        return {
            "status": "NEW_LOW",
            "historical_low": historical_low,
            "reason": (
                f"Current price ₹{current_price:,.0f} is "
                f"equal to or below historical low "
                f"₹{historical_low:,.0f}"
            ),
        }

    # --------------------------------------------------------
    # NEAR LOW
    # 3% OR ₹50 tolerance
    # --------------------------------------------------------

    tolerance = max(
        50,
        historical_low * 0.03
    )

    if current_price <= historical_low + tolerance:

        difference = current_price - historical_low

        return {
            "status": "NEAR_LOW",
            "historical_low": historical_low,
            "reason": (
                f"Current price ₹{current_price:,.0f} is "
                f"₹{difference:,.0f} above historical low "
                f"₹{historical_low:,.0f}, within allowed "
                f"3%/₹50 tolerance"
            ),
        }

    # --------------------------------------------------------
    # NOT LOW
    # --------------------------------------------------------

    difference = current_price - historical_low

    return {
        "status": "NOT_LOW",
        "historical_low": historical_low,
        "reason": (
            f"Current price ₹{current_price:,.0f} is "
            f"₹{difference:,.0f} above historical low "
            f"₹{historical_low:,.0f}"
        ),
    }


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_deal(
    product_title,
    deal_price,
    url=None,
    source=None,
):
    """
    Main function called by loot_listener.py.

    Returns a structured dictionary:

    {
        status,
        historical_low,
        reason
    }
    """

    try:

        # ----------------------------------------------------
        # INPUT CHECK
        # ----------------------------------------------------

        product_title = clean_text(
            product_title
        )

        deal_price = parse_price(
            deal_price
        )

        if not product_title:

            return {
                "status": "INVALID_PRODUCT",
                "historical_low": None,
                "reason": "Product title is empty",
            }

        if deal_price is None:

            return {
                "status": "INVALID_PRICE",
                "historical_low": None,
                "reason": "Deal price could not be parsed",
            }

        # ----------------------------------------------------
        # MINIMUM DEAL PRICE
        # Strictly greater than ₹1,000
        # ----------------------------------------------------

        if deal_price <= 1000:

            return {
                "status": "PRICE_TOO_LOW",
                "historical_low": None,
                "reason": (
                    f"Product price ₹{deal_price:,.0f} "
                    f"is at or below minimum allowed price ₹1,000"
                ),
            }

        # ----------------------------------------------------
        # CATEGORY CHECK
        # ----------------------------------------------------

        category = classify_product(
            product_title
        )

        if not category["allowed"]:

            return {
                "status": "CATEGORY_REJECT",
                "historical_low": None,
                "reason": category["reason"],
            }

        # ----------------------------------------------------
        # RESOLVE SHORT URL
        # ----------------------------------------------------

        resolved_url = url

        if url:

            resolved, resolve_error = resolve_url(
                url
            )

            if resolved:

                resolved_url = resolved

            else:

                # Do not fail the entire deal solely because
                # a short URL could not be resolved.
                #
                # But make the reason explicit if history lookup
                # subsequently fails.
                resolved_url = url

        # ----------------------------------------------------
        # PRICEHISTORY LOOKUP
        # ----------------------------------------------------

        history = pricehistory_lookup(
            product_title,
            merchant_url=resolved_url
        )

        if not history.get("found"):

            return {
                "status": "PRICE_HISTORY_NOT_FOUND",
                "historical_low": None,
                "reason": history.get(
                    "reason",
                    "Could not verify historical price"
                ),
            }

        historical_low = parse_price(
            history.get("historical_low")
        )

        if historical_low is None:

            return {
                "status": "PRICE_HISTORY_NOT_FOUND",
                "historical_low": None,
                "reason": (
                    "PriceHistory record found but "
                    "historical low is invalid"
                ),
            }

        # ----------------------------------------------------
        # PRODUCT MATCH SAFETY
        # ----------------------------------------------------

        similarity = history.get(
            "similarity",
            0
        )

        if similarity < 0.35:

            return {
                "status": "PRODUCT_MISMATCH",
                "historical_low": historical_low,
                "reason": (
                    "PriceHistory product does not match "
                    "the deal product sufficiently"
                ),
            }

        # ----------------------------------------------------
        # SUSPICIOUS HISTORY SAFETY
        # ----------------------------------------------------

        suspicious, suspicious_reason = (
            suspicious_historical_low(
                product_title,
                deal_price,
                historical_low
            )
        )

        if suspicious:

            return {
                "status": "SUSPICIOUS_HISTORY",
                "historical_low": historical_low,
                "reason": suspicious_reason,
            }

        # ----------------------------------------------------
        # FINAL PRICE COMPARISON
        # ----------------------------------------------------

        result = compare_price(
            deal_price,
            historical_low
        )

        # Add useful metadata
        result["product_title"] = product_title
        result["deal_price"] = deal_price
        result["source"] = source
        result["url"] = resolved_url
        result["matched_title"] = history.get(
            "matched_title"
        )
        result["similarity"] = similarity

        return result

    except Exception as exc:

        return {
            "status": "VALIDATOR_ERROR",
            "historical_low": None,
            "reason": (
                f"Validator exception: "
                f"{type(exc).__name__}: {exc}"
            ),
        }


# ============================================================
# OPTIONAL TEST
# ============================================================

if __name__ == "__main__":

    test = validate_deal(
        product_title=(
            "Samsung Galaxy S23 5G "
            "(Cream, 256 GB) (8 GB RAM)"
        ),
        deal_price=26499,
        url="https://fkrt.co/SjusKq",
        source="@vaasutechdeals",
    )

    print("\n========== VALIDATOR TEST ==========")

    for key, value in test.items():
        print(f"{key}: {value}")

    print("====================================\n")