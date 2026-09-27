# deal_validator.py
# VERSION: 2.9

import re
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin


VERSION = "2.9"


# ============================================================
# CONFIG
# ============================================================

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
# CATEGORIES
# ============================================================

ALLOWED_CATEGORIES = [
    "Smartphones",
    "Mobile Phones",
    "Laptops",
    "MacBooks",
    "Tablets",
    "iPads",
    "Desktop Computers",
    "Monitors",
    "TVs",
    "Smart TVs",
    "Projectors",
    "Cameras",
    "Camera Lenses",
    "Gaming Consoles",
    "Graphics Cards",
    "GPU",
    "Processors",
    "CPU",
    "Motherboards",
    "RAM",
    "SSD",
    "HDD",
    "NAS",
    "Printers",
    "Scanners",
    "Routers",
    "Wi-Fi Devices",
    "Networking Equipment",
    "Keyboards",
    "Mice",
    "Webcams",

    "Headphones",
    "Earphones",
    "TWS Earbuds",
    "Bluetooth Speakers",
    "Home Audio Systems",
    "Soundbars",
    "Amplifiers",
    "Microphones",
    "Audio Equipment",

    "Air Conditioners",
    "Refrigerators",
    "Washing Machines",
    "Dishwashers",
    "Microwave Ovens",
    "OTG Ovens",
    "Air Purifiers",
    "Vacuum Cleaners",
    "Water Purifiers",
    "Fans",
    "Room Heaters",
    "Kitchen Appliances",
    "Coffee Machines",
    "Electric Kettles",
    "Induction Cooktops",

    "Smart Home Devices",
    "Smart Lighting",
    "Smart Switches",
    "Smart Plugs",
    "Security Cameras",
    "Smart Doorbells",
    "Home Automation Devices",

    "Sofas",
    "Beds",
    "Mattresses",
    "Office Chairs",
    "Gaming Chairs",
    "Recliners",
    "Study Tables",
    "Office Tables",
    "Dining Tables",
    "Dining Chairs",
    "Wardrobes",
    "Cabinets",
    "Bookshelves",
    "TV Units",
    "Shoe Racks",
    "Coffee Tables",
    "Side Tables",
    "Storage Furniture",

    "Running Shoes",
    "Sports Shoes",
    "Football Shoes",
    "Cricket Bats",
    "Cricket Equipment",
    "Badminton Rackets",
    "Badminton Equipment",
    "Tennis Equipment",
    "Basketball Equipment",
    "Sports Bags",
    "Gym Equipment",
    "Dumbbells",
    "Barbells",
    "Weight Plates",
    "Treadmills",
    "Exercise Bikes",
    "Cross Trainers",
    "Yoga Equipment",
    "Fitness Equipment",
    "Cycling Equipment",
    "Sports Accessories",

    "Car Accessories",
    "Bike Accessories",
    "Car Electronics",
    "Bike Electronics",
    "Dashcams",
    "Car Audio",
    "Tyres",
    "Car Care Equipment",
    "Bike Care Equipment",
    "Automotive Tools",
    "Automotive Equipment",

    "Power Tools",
    "Drills",
    "Grinders",
    "Screwdriver Sets",
    "Tool Kits",
    "Hand Tools",
    "Measuring Tools",
    "Workshop Equipment",
    "Hardware Equipment",
    "Welding Equipment",
    "Professional Tools",

    "Trolley Bags",
    "Suitcases",
    "Backpacks",
    "Duffle Bags",
    "Travel Bags",
    "Travel Gear",
    "Travel Accessories",

    "Tents",
    "Camping Gear",
    "Trekking Equipment",
    "Hiking Equipment",
    "Outdoor Furniture",
    "Outdoor Equipment",

    "Home Utility",
    "Home Organization",
    "Storage Solutions",
    "Cleaning Equipment",
    "Kitchen Storage",
    "Bathroom Utility",
    "Dining & Serving",
    "Home Improvement Equipment",

    "Premium Toys",
    "Building Sets",
    "Construction Sets",
    "Educational Toys",
    "Kids Ride-ons",
    "Kids Equipment",
    "Learning Devices",

    "Pet Beds",
    "Pet Feeders",
    "Pet Grooming Equipment",
    "Pet Travel Equipment",
    "Pet Accessories",

    "Gardening Tools",
    "Garden Equipment",
    "Planters",
    "Outdoor Storage",

    "Books",
    "Educational Equipment",
    "Study Equipment",
    "Educational Devices",

    "Trimmers",
    "Shavers",
    "Hair Dryers",
    "Hair Straighteners",
    "Hair Styling Appliances",
    "Electric Grooming Devices",
    "Electric Personal Care Devices",

    "Professional Equipment",
    "Industrial Equipment",
    "Commercial Equipment",
    "Testing Equipment",
]


# ============================================================
# EXCLUDED KEYWORDS
# ============================================================

EXCLUDED_KEYWORDS = [
    "phone cover",
    "phone case",
    "mobile cover",
    "mobile case",
    "back cover",
    "screen protector",
    "tempered glass",
    "charging cable",
    "usb cable",
    "data cable",
    "aux cable",
    "hdmi cable",
    "charger",
    "adapter",
    "small watch",
    "smart band",
    "fitness band",
    "jewellery",
    "jewelry",
    "clothing",
    "clothes",
    "fashion",
    "saree",
    "shirt",
    "t shirt",
    "jeans",
    "trousers",
    "dress",
    "cosmetic",
    "makeup",
    "grocery",
    "food",
    "daily consumable",
]


# ============================================================
# DEBUG
# ============================================================

def price_debug(message):
    print(f"[PRICE DEBUG] {message}")


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
# CATEGORY MATCH
# ============================================================

def category_match(product_text, category):
    product = normalize(product_text)
    cat = normalize(category)

    if not product or not cat:
        return False

    if cat in product:
        return True

    product_words = set(product.split())
    category_words = set(cat.split())

    if len(category_words) == 1:
        return bool(product_words.intersection(category_words))

    return category_words.issubset(product_words)


# ============================================================
# CLASSIFY PRODUCT
# ============================================================

def classify_product(title, extra_text=""):
    combined = normalize(f"{title} {extra_text}")

    for keyword in EXCLUDED_KEYWORDS:
        if normalize(keyword) in combined:
            return {
                "matched": False,
                "category": None,
                "reason": f"Excluded product type: {keyword}",
            }

    for category in ALLOWED_CATEGORIES:
        if category_match(combined, category):
            return {
                "matched": True,
                "category": category,
                "reason": f"Matched category: {category}",
            }

    return {
        "matched": False,
        "category": None,
        "reason": (
            "Product category is outside "
            "configured deal categories"
        ),
    }


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
        flags=re.I,
    )

    value = re.sub(
        r"\bINR\b",
        "",
        value,
        flags=re.I,
    )

    match = re.search(
        r"\d+(?:\.\d+)?",
        value,
    )

    if not match:
        return None

    try:
        return float(match.group())
    except Exception:
        return None


# ============================================================
# TEXT PRICE EXTRACTION
# ============================================================

def extract_price(text):
    if not text:
        return None

    text = str(text)

    patterns = [
        (
            "deal price",
            r"(?:deal\s*price|deal\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "offer price",
            r"(?:offer\s*price|offer)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "sale price",
            r"(?:sale\s*price)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "current price",
            r"(?:current\s*price)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "buy at",
            r"(?:buy\s*at|now\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "rupee",
            r"(?:₹|rs\.?|inr)\s*"
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "slash price",
            r"\b([\d,]+(?:\.\d+)?)\s*/-",
        ),
        (
            "only price",
            r"\b([\d,]+(?:\.\d+)?)\s+only\b",
        ),
    ]

    for name, pattern in patterns:
        match = re.search(pattern, text, re.I)

        if not match:
            continue

        price = clean_price(match.group(1))

        if price is not None and price > 0:
            price_debug(
                f"TEXT PRICE FOUND | pattern={name} | "
                f"price=₹{price:.0f}"
            )
            return price

    price_debug("TEXT PRICE NOT FOUND")

    return None


# ============================================================
# URL RESOLUTION
# ============================================================

def resolve_url(url):
    if not url:
        return None

    price_debug(f"RESOLVE URL START | {url}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        final_url = response.url or url

        price_debug(
            f"RESOLVE URL DONE | status={response.status_code} | "
            f"final={final_url}"
        )

        return final_url

    except Exception as e:
        price_debug(
            f"RESOLVE URL FAILED | "
            f"{type(e).__name__}: {e}"
        )
        return url


# ============================================================
# FETCH PRODUCT PAGE
# ============================================================

def fetch_page(url):
    if not url:
        price_debug("FETCH PAGE SKIPPED | URL empty")
        return None

    price_debug(f"FETCH PAGE START | {url}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        price_debug(
            f"FETCH PAGE RESPONSE | "
            f"status={response.status_code} | "
            f"content_length={len(response.text)}"
        )

        if response.status_code != 200:
            price_debug("FETCH PAGE FAILED | non-200 response")
            return None

        return response.text

    except Exception as e:
        price_debug(
            f"FETCH PAGE FAILED | "
            f"{type(e).__name__}: {e}"
        )
        return None


# ============================================================
# PRODUCT PAGE PRICE EXTRACTION
# ============================================================

def extract_product_page_price(html):
    if not html:
        price_debug("PRODUCT PAGE PRICE | HTML EMPTY")
        return None

    price_debug(
        f"PRODUCT PAGE PRICE SCAN START | "
        f"html_length={len(html)}"
    )

    candidates = []

    # --------------------------------------------------------
    # JSON-LD / HTML price attributes
    # --------------------------------------------------------

    patterns = [
        (
            "priceCurrency/price",
            r'"price"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "lowPrice",
            r'"lowPrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "currentPrice",
            r'"currentPrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "sellingPrice",
            r'"sellingPrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "salePrice",
            r'"salePrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "productPrice",
            r'"productPrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "price attribute",
            r'data-price=["\']([\d,]+(?:\.\d+)?)',
        ),
    ]

    for name, pattern in patterns:
        for match in re.finditer(
            pattern,
            html,
            re.I,
        ):
            value = clean_price(match.group(1))

            if value is not None and value > 0:
                candidates.append(value)
                price_debug(
                    f"PAGE CANDIDATE | {name} | "
                    f"₹{value:.0f}"
                )

    # --------------------------------------------------------
    # Visible page text
    # --------------------------------------------------------

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tag in soup(
        ["script", "style", "noscript"]
    ):
        tag.extract()

    visible_text = soup.get_text(
        " ",
        strip=True,
    )

    visible_patterns = [
        (
            "visible deal price",
            r"(?:deal\s*price|sale\s*price|"
            r"current\s*price|selling\s*price)"
            r"\s*[:\-]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)",
        ),
        (
            "visible rupee",
            r"(?:₹|rs\.?|inr)\s*"
            r"([\d,]+(?:\.\d+)?)",
        ),
    ]

    for name, pattern in visible_patterns:
        for match in re.finditer(
            pattern,
            visible_text,
            re.I,
        ):
            value = clean_price(match.group(1))

            if value is not None and value > 0:
                candidates.append(value)
                price_debug(
                    f"VISIBLE CANDIDATE | {name} | "
                    f"₹{value:.0f}"
                )

    # --------------------------------------------------------
    # Filter unrealistic values
    # --------------------------------------------------------

    filtered = [
        value
        for value in candidates
        if MIN_PRICE < value < 10000000
    ]

    if not filtered:
        price_debug(
            f"PRODUCT PAGE PRICE NOT FOUND | "
            f"candidates={len(candidates)}"
        )
        return None

    # Prefer smaller realistic selling-price candidate.
    # This is only a fallback when page exposes multiple
    # price fields.
    selected = min(filtered)

    price_debug(
        f"PRODUCT PAGE PRICE SELECTED | "
        f"₹{selected:.0f} | "
        f"candidates={len(filtered)}"
    )

    return selected


# ============================================================
# PRICEHISTORY SEARCH
# ============================================================

def pricehistory_search(query):
    if not query:
        return None

    encoded = quote(query)

    urls = [
        f"https://pricehistory.app/search?q={encoded}",
        f"https://pricehistoryapp.com/search?q={encoded}",
    ]

    for search_url in urls:
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

            for link in soup.find_all(
                "a",
                href=True,
            ):
                href = link.get(
                    "href",
                    "",
                ).strip()

                link_text = link.get_text(
                    " ",
                    strip=True,
                )

                if not href or not link_text:
                    continue

                full_url = urljoin(
                    search_url,
                    href,
                )

                if "pricehistory" in full_url.lower():
                    return {
                        "title": link_text,
                        "url": full_url,
                    }

        except Exception:
            continue

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
            re.I,
        ):
            value = clean_price(
                match.group(1)
            )

            if value is not None:
                values.append(value)

    raw_patterns = [
        r'"lowestPrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*([\d,.]+)',
        r'"lowest_price"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*([\d,.]+)',
        r'"historicalLow"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*([\d,.]+)',
        r'"historical_low"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*([\d,.]+)',
    ]

    for pattern in raw_patterns:
        for match in re.finditer(
            pattern,
            html,
            re.I,
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

    difference = current_price - historical_low

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

        price_debug("=" * 60)
        price_debug(
            f"VALIDATION START | title={title[:120]}"
        )
        price_debug(
            f"INPUT PRICE={price} | URL={url}"
        )

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        if not title:
            return {
                "status": "INVALID",
                "historical_low": None,
                "category": None,
                "reason": (
                    "Product title "
                    "could not be determined"
                ),
                "source": source,
                "url": url,
            }

        # ----------------------------------------------------
        # PRICE FROM INPUT
        # ----------------------------------------------------

        current_price = clean_price(price)

        if current_price is not None:
            price_debug(
                f"INPUT PRICE FOUND | ₹{current_price:.0f}"
            )

        # ----------------------------------------------------
        # PRICE FROM TELEGRAM / DEAL TEXT
        # ----------------------------------------------------

        if current_price is None:
            price_debug(
                "Trying price extraction from deal text..."
            )

            current_price = extract_price(text)

        # ----------------------------------------------------
        # PRICE FROM PRODUCT PAGE
        # ----------------------------------------------------

        final_url = url

        if current_price is None and url:
            price_debug(
                "Deal text has no price. "
                "Trying product URL..."
            )

            final_url = resolve_url(url)

            if final_url:
                html = fetch_page(final_url)

                if html:
                    current_price = (
                        extract_product_page_price(
                            html
                        )
                    )
                else:
                    price_debug(
                        "PRODUCT PAGE UNAVAILABLE"
                    )

        # ----------------------------------------------------
        # PRICE STILL UNKNOWN
        # ----------------------------------------------------

        if current_price is None:
            price_debug(
                "FINAL RESULT: PRICE UNKNOWN"
            )

            return {
                "status": "PRICE_UNKNOWN",
                "historical_low": None,
                "category": None,
                "reason": (
                    "Deal price could not be extracted "
                    "from deal text or product page"
                ),
                "source": source,
                "url": final_url or url,
            }

        price_debug(
            f"FINAL CURRENT PRICE | ₹{current_price:.0f}"
        )

        # ----------------------------------------------------
        # MINIMUM PRICE
        # ----------------------------------------------------

        if current_price <= MIN_PRICE:
            return {
                "status": "PRICE_REJECT",
                "historical_low": None,
                "category": None,
                "reason": (
                    f"Deal price ₹{current_price:.0f} "
                    f"is not above minimum price "
                    f"₹{MIN_PRICE}"
                ),
                "source": source,
                "url": final_url or url,
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
                "url": final_url or url,
            }

        category = category_result["category"]

        # ----------------------------------------------------
        # RESOLVE URL IF NOT ALREADY DONE
        # ----------------------------------------------------

        if not final_url:
            final_url = resolve_url(url)

        # ----------------------------------------------------
        # PRICEHISTORY SEARCH
        # ----------------------------------------------------

        price_debug(
            f"PRICEHISTORY SEARCH | query={title[:120]}"
        )

        result = pricehistory_search(title)

        historical_low = None
        pricehistory_url = None
        pricehistory_title = ""

        if result:
            pricehistory_url = result.get("url")
            pricehistory_title = result.get(
                "title",
                "",
            )

            price_debug(
                f"PRICEHISTORY RESULT | "
                f"{pricehistory_url}"
            )

            html = fetch_page(
                pricehistory_url
            )

            if html:
                historical_low = (
                    extract_historical_low(html)
                )

        else:
            price_debug(
                "PRICEHISTORY RESULT NOT FOUND"
            )

        # ----------------------------------------------------
        # HISTORICAL LOW NOT FOUND
        # ----------------------------------------------------

        if historical_low is None:
            return {
                "status": "HISTORICAL_LOW_UNKNOWN",
                "historical_low": None,
                "category": category,
                "reason": (
                    "Historical low could not "
                    "be verified from PriceHistory"
                ),
                "source": source,
                "url": final_url or url,
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
                "category": category,
                "reason": (
                    f"Historical low ₹{historical_low:.0f} "
                    f"appears suspicious against "
                    f"current price ₹{current_price:.0f}"
                ),
                "source": source,
                "url": final_url or url,
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
            "category": category,
            "reason": comparison["reason"],
            "source": source,
            "url": final_url or url,
            "pricehistory_url": pricehistory_url,
            "pricehistory_title": pricehistory_title,
        }

    except Exception as e:
        price_debug(
            f"VALIDATOR EXCEPTION | "
            f"{type(e).__name__}: {e}"
        )

        return {
            "status": "VALIDATOR_ERROR",
            "historical_low": None,
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
        "Wireless Headphones",
        "Running Shoes",
        "Office Chair",
        "Laptop",
        "Samsung Refrigerator",
        "Phone Cover",
        "Tempered Glass",
        "USB Cable",
    ]

    print("\nCATEGORY TESTS")
    print("-" * 60)

    for product in tests:
        result = classify_product(product)

        print(
            f"{product:30} -> "
            f"{result['matched']} | "
            f"{result['category']} | "
            f"{result['reason']}"
        )

    price_tests = [
        "Deal Price: ₹24,999",
        "🔥 Deal at Rs 18,999",
        "Offer Price ₹34,999",
        "Now at ₹12,499",
        "Buy at INR 25999",
        "₹49,999 only",
        "24999/-",
        "Deal Price - 24999",
        "Deal @ ₹12999",
        "Current Price: Rs. 14,999",
        "Sale Price: INR 19,999",
    ]

    print("\nPRICE TESTS")
    print("-" * 60)

    for test_text in price_tests:
        price = extract_price(test_text)

        print(
            f"{test_text:40} -> ₹{price}"
        )

    print("=" * 60)
    print("VALIDATOR TEST COMPLETE")
    print("=" * 60)
