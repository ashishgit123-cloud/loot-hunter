import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}

MIN_PRICE = 1000

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# BASIC PRICE PARSER
# ============================================================

def clean_price(value):
    if value is None:
        return None

    value = str(value)
    value = value.replace(",", "")
    value = value.replace("₹", "")
    value = value.replace("Rs.", "")
    value = value.replace("Rs", "")

    match = re.search(r"\d+(?:\.\d+)?", value)

    if not match:
        return None

    try:
        return float(match.group())
    except Exception:
        return None


# ============================================================
# URL RESOLVER
# ============================================================

def resolve_url(url):
    """
    amzn.to / bit.ly / fkrt.it etc.
    ko actual URL mein resolve karta hai.
    """

    try:
        response = session.get(
            url,
            allow_redirects=True,
            timeout=12,
            stream=True
        )

        final_url = response.url

        if final_url:
            return final_url

    except Exception as e:
        print(f"⚠️ URL resolve failed: {e}")

    return url


# ============================================================
# PRODUCT NAME CLEANER
# ============================================================

def clean_product_title(title):
    if not title:
        return ""

    title = re.sub(r"https?://\S+", " ", title)

    title = re.sub(
        r"(₹|Rs\.?)\s*[\d,]+(?:\.\d+)?",
        " ",
        title,
        flags=re.I
    )

    title = re.sub(
        r"\b\d{1,3}%\s*(off|discount)?\b",
        " ",
        title,
        flags=re.I
    )

    title = re.sub(r"\s+", " ", title)

    return title.strip()


# ============================================================
# EXTRACT PRICES FROM TEXT
# ============================================================

def extract_prices(text):
    if not text:
        return []

    patterns = [
        r"(?:deal price|offer price|sale price|buy at|now|current price)"
        r"\s*[:\-]?\s*₹?\s*([\d,]+(?:\.\d+)?)",

        r"₹\s*([\d,]+(?:\.\d+)?)",

        r"\bRs\.?\s*([\d,]+(?:\.\d+)?)",
    ]

    prices = []

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            price = clean_price(match)

            if price is not None:
                prices.append(price)

    return prices


def extract_deal_price(text):
    """
    Explicit deal/offer/current price ko priority.
    """

    if not text:
        return None

    priority_patterns = [
        r"(?:deal price|offer price|sale price|current price)"
        r"\s*[:\-]?\s*₹?\s*([\d,]+(?:\.\d+)?)",

        r"(?:buy at|now|today)"
        r"\s*[:\-]?\s*₹?\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in priority_patterns:
        match = re.search(pattern, text, flags=re.I)

        if match:
            price = clean_price(match.group(1))

            if price is not None:
                return price

    prices = extract_prices(text)

    if not prices:
        return None

    return min(prices)


# ============================================================
# SEARCH PRICEHISTORY
# ============================================================

def search_pricehistory(product_name="", product_url=""):
    """
    Product URL/name ko PriceHistory par search karta hai.

    IMPORTANT:
    Ye validation layer hai.
    Future PriceHistory changes yahin karne hain.
    """

    query = product_url or product_name

    if not query:
        return None

    try:
        url = (
            "https://pricehistory.app/"
            "?search=" + quote(query)
        )

        response = session.get(
            url,
            timeout=15
        )

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(
            " ",
            strip=True
        )

        return parse_pricehistory_text(text)

    except Exception as e:
        print(f"⚠️ PriceHistory error: {e}")
        return None


def parse_pricehistory_text(text):
    if not text:
        return None

    result = {
        "lowest": None,
        "current": None,
        "offer": None,
        "average": None,
        "highest": None,
    }

    patterns = {
        "lowest": [
            r"Historic(?:al)? Lowest[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
            r"Lowest Ever[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
            r"\bLowest[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        ],

        "current": [
            r"Current Price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
            r"Price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        ],

        "offer": [
            r"Current Lowest Offer Price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
            r"Current Lowest[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
            r"Offer Price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        ],

        "average": [
            r"Average Price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        ],

        "highest": [
            r"Highest[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        ],
    }

    for key, regexes in patterns.items():
        for pattern in regexes:
            match = re.search(
                pattern,
                text,
                flags=re.I
            )

            if match:
                result[key] = clean_price(match.group(1))
                break

    if not any(result.values()):
        return None

    return result


# ============================================================
# SEARCH PRICETRAIL
# ============================================================

def search_pricetrail(product_name="", product_url=""):
    """
    PriceTrail public search.
    """

    query = product_url or product_name

    if not query:
        return None

    try:
        url = (
            "https://www.pricehistorytracker.in/"
            "?search=" + quote(query)
        )

        response = session.get(
            url,
            timeout=15
        )

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(
            " ",
            strip=True
        )

        return parse_generic_history(text)

    except Exception as e:
        print(f"⚠️ PriceTrail error: {e}")
        return None


# ============================================================
# BUYHATKE
# ============================================================

def search_buyhatke(product_name="", product_url=""):
    """
    Buyhatke public price/deal pages.
    """

    query = product_url or product_name

    if not query:
        return None

    try:
        url = (
            "https://price.buyhatke.com/"
            "?search=" + quote(query)
        )

        response = session.get(
            url,
            timeout=15
        )

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(
            " ",
            strip=True
        )

        return parse_generic_history(text)

    except Exception as e:
        print(f"⚠️ Buyhatke error: {e}")
        return None


# ============================================================
# GENERIC HISTORY PARSER
# ============================================================

def parse_generic_history(text):
    if not text:
        return None

    result = {
        "lowest": None,
        "current": None,
        "average": None,
    }

    lowest_patterns = [
        r"Lowest Ever[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        r"All[- ]time Low[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        r"Lowest[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        r"lowest price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
    ]

    current_patterns = [
        r"Current Price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        r"Offer Price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
        r"Price[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
    ]

    average_patterns = [
        r"average[^₹0-9]*₹?\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in lowest_patterns:
        match = re.search(pattern, text, flags=re.I)

        if match:
            result["lowest"] = clean_price(match.group(1))
            break

    for pattern in current_patterns:
        match = re.search(pattern, text, flags=re.I)

        if match:
            result["current"] = clean_price(match.group(1))
            break

    for pattern in average_patterns:
        match = re.search(pattern, text, flags=re.I)

        if match:
            result["average"] = clean_price(match.group(1))
            break

    if not any(result.values()):
        return None

    return result


# ============================================================
# LOWEST PRICE DECISION
# ============================================================

def compare_with_lowest(deal_price, lowest):
    """
    Central lowest-price decision.

    YAHAN future mein rule change kar sakte ho.
    """

    if not deal_price:
        return "NO_PRICE"

    if deal_price <= MIN_PRICE:
        return "LOW_PRICE"

    if not lowest:
        return "UNKNOWN"

    tolerance = max(
        50,
        lowest * 0.03
    )

    if deal_price <= lowest + tolerance:
        return "LOWEST"

    return "NOT_LOW"


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_deal(
    product_name,
    product_url,
    deal_price
):
    """
    ========================================================
    MAIN VALIDATION CONTROLLER
    ========================================================

    FUTURE VALIDATION CHANGES:
    >>> Mostly ONLY this section / functions below.
    ========================================================
    """

    result = {
        "status": "UNKNOWN",
        "lowest_price": None,
        "pricehistory": None,
        "pricetrail": None,
        "buyhatke": None,
        "resolved_url": product_url,
    }

    if not deal_price:
        result["status"] = "NO_PRICE"
        return result

    if deal_price <= MIN_PRICE:
        result["status"] = "LOW_PRICE"
        return result

    # --------------------------------------------------------
    # STEP 1: resolve short URL
    # --------------------------------------------------------

    resolved_url = resolve_url(product_url)

    result["resolved_url"] = resolved_url

    # --------------------------------------------------------
    # STEP 2: PriceHistory
    # --------------------------------------------------------

    ph = search_pricehistory(
        product_name,
        resolved_url
    )

    result["pricehistory"] = ph

    if ph and ph.get("lowest"):
        result["lowest_price"] = ph["lowest"]

        decision = compare_with_lowest(
            deal_price,
            ph["lowest"]
        )

        if decision == "LOWEST":
            result["status"] = "VALID"
            return result

    # --------------------------------------------------------
    # STEP 3: PriceTrail
    # --------------------------------------------------------

    pt = search_pricetrail(
        product_name,
        resolved_url
    )

    result["pricetrail"] = pt

    if pt and pt.get("lowest"):
        result["lowest_price"] = pt["lowest"]

        decision = compare_with_lowest(
            deal_price,
            pt["lowest"]
        )

        if decision == "LOWEST":
            result["status"] = "VALID"
            return result

    # --------------------------------------------------------
    # STEP 4: Buyhatke
    # --------------------------------------------------------

    bh = search_buyhatke(
        product_name,
        resolved_url
    )

    result["buyhatke"] = bh

    if bh and bh.get("lowest"):
        result["lowest_price"] = bh["lowest"]

        decision = compare_with_lowest(
            deal_price,
            bh["lowest"]
        )

        if decision == "LOWEST":
            result["status"] = "VALID"
            return result

    # --------------------------------------------------------
    # STEP 5: No validator could confirm
    # --------------------------------------------------------

    if (
        ph is None
        and pt is None
        and bh is None
    ):
        result["status"] = "NO_VALIDATION_DATA"
    else:
        result["status"] = "NOT_LOW"

    return result