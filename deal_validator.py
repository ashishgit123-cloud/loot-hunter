import re
import requests
from urllib.parse import quote
from bs4 import BeautifulSoup


MIN_PRICE = 1000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# CATEGORY
# ============================================================

ALLOWED = {
    "electronics": [
        "iphone", "ipad", "macbook", "laptop", "tablet",
        "mobile", "smartphone", "samsung", "oneplus", "pixel",
        "xiaomi", "realme", "motorola", "nothing phone",
        "tv", "television", "monitor", "camera",
        "headphone", "earbuds", "airpods", "speaker",
        "soundbar", "gaming", "playstation", "xbox",
        "graphics card", "gpu", "processor", "ssd", "hard disk",
        "refrigerator", "washing machine", "air conditioner",
        "ac ", "microwave", "air fryer", "vacuum cleaner"
    ],

    "furniture": [
        "sofa", "bed", "wardrobe", "almirah", "mattress",
        "dining table", "dining chair", "office chair",
        "study table", "coffee table", "recliner",
        "bookshelf", "cabinet", "tv unit", "shoe rack"
    ],

    "sports": [
        "running shoes", "running shoe", "sports shoes",
        "sports shoe", "football shoes", "cricket shoes",
        "basketball shoes", "training shoes", "gym shoes",
        "badminton shoes", "tennis shoes", "sports equipment",
        "treadmill", "dumbbell", "exercise bike"
    ]
}


EXCLUDED = [
    "shirt", "t-shirt", "tshirt", "jeans", "trouser",
    "kurta", "dress", "saree", "jacket", "hoodie",
    "watch", "wrist watch", "smart band",
    "bracelet", "jewellery", "jewelry",
    "mobile cover", "phone cover", "back cover",
    "case only", "screen protector", "tempered glass",
    "camera lens protector", "charging cable",
    "usb cable", "data cable", "watch strap",
    "replacement screen", "replacement display"
]


def classify_product(title):
    text = (title or "").lower()

    for word in EXCLUDED:
        if word in text:
            return "excluded"

    for category, words in ALLOWED.items():
        for word in words:
            if word in text:
                return category

    return "other"


# ============================================================
# PRICE
# ============================================================

def clean_price(value):
    try:
        value = str(value)
        value = value.replace(",", "")
        value = value.replace("₹", "")
        return float(
            re.search(r"\d+(?:\.\d+)?", value).group()
        )
    except Exception:
        return None


# ============================================================
# URL
# ============================================================

def resolve_url(url):
    try:
        response = session.get(
            url,
            allow_redirects=True,
            timeout=12,
            stream=True
        )

        return response.url or url

    except Exception:
        return url


# ============================================================
# PRICEHISTORY
# ============================================================

def pricehistory_lookup(product_name, product_url):

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

        result = {
            "lowest": None,
            "current": None
        }

        patterns = {
            "lowest": [
                r"Historic(?:al)? Lowest[^₹0-9]*₹?\s*([\d,]+)",
                r"Lowest Ever[^₹0-9]*₹?\s*([\d,]+)",
                r"All[- ]time Low[^₹0-9]*₹?\s*([\d,]+)"
            ],

            "current": [
                r"Current Price[^₹0-9]*₹?\s*([\d,]+)",
                r"Current Lowest[^₹0-9]*₹?\s*([\d,]+)",
                r"Offer Price[^₹0-9]*₹?\s*([\d,]+)"
            ]
        }

        for key, regexes in patterns.items():

            for pattern in regexes:

                match = re.search(
                    pattern,
                    text,
                    re.I
                )

                if match:
                    result[key] = clean_price(
                        match.group(1)
                    )
                    break

        if result["lowest"] is None:
            return None

        return result

    except Exception as e:

        print(
            f"⚠️ PriceHistory error: {e}"
        )

        return None


# ============================================================
# LOWEST PRICE DECISION
# ============================================================

def compare_price(deal_price, lowest):

    if not lowest:
        return "UNKNOWN"

    # suspicious history
    if lowest <= 100:
        return "SUSPICIOUS_HISTORY"

    # genuine new all-time low
    if deal_price < lowest:
        return "NEW_LOW"

    # within 3%
    tolerance = max(
        50,
        lowest * 0.03
    )

    if deal_price <= lowest + tolerance:
        return "NEAR_LOW"

    return "NOT_LOW"


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_deal(
    product_name,
    product_url,
    deal_price
):

    result = {
        "status": "UNKNOWN",
        "category": None,
        "lowest_price": None,
        "resolved_url": product_url
    }

    if not deal_price:
        result["status"] = "NO_PRICE"
        return result

    if deal_price <= MIN_PRICE:
        result["status"] = "LOW_PRICE"
        return result

    category = classify_product(
        product_name
    )

    result["category"] = category

    if category == "excluded":
        result["status"] = "EXCLUDED_CATEGORY"
        return result

    # We only want these categories for now.
    if category == "other":
        result["status"] = "OTHER_CATEGORY"
        return result

    resolved = resolve_url(
        product_url
    )

    result["resolved_url"] = resolved

    history = pricehistory_lookup(
        product_name,
        resolved
    )

    if not history:
        result["status"] = "NO_HISTORY"
        return result

    lowest = history.get(
        "lowest"
    )

    result["lowest_price"] = lowest

    decision = compare_price(
        deal_price,
        lowest
    )

    # New LOW and Near LOW both qualify.
    if decision == "NEW_LOW":
        result["status"] = "NEW_LOW"
        return result

    if decision == "NEAR_LOW":
        result["status"] = "NEAR_LOW"
        return result

    if decision == "SUSPICIOUS_HISTORY":
        result["status"] = "SUSPICIOUS_HISTORY"
        return result

    result["status"] = "NOT_LOW"

    return result