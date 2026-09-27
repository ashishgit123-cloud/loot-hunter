# deal_validator.py
# VERSION: 2.8

import re
import json
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin


VERSION = "2.8"


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
    # Electronics
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

    # Audio
    "Headphones",
    "Earphones",
    "TWS Earbuds",
    "Bluetooth Speakers",
    "Home Audio Systems",
    "Soundbars",
    "Amplifiers",
    "Microphones",
    "Audio Equipment",

    # Appliances
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

    # Smart Home
    "Smart Home Devices",
    "Smart Lighting",
    "Smart Switches",
    "Smart Plugs",
    "Security Cameras",
    "Smart Doorbells",
    "Home Automation Devices",

    # Furniture
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

    # Sports
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

    # Automotive
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

    # Tools
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

    # Travel
    "Trolley Bags",
    "Suitcases",
    "Backpacks",
    "Duffle Bags",
    "Travel Bags",
    "Travel Gear",
    "Travel Accessories",

    # Outdoor
    "Tents",
    "Camping Gear",
    "Trekking Equipment",
    "Hiking Equipment",
    "Outdoor Furniture",
    "Outdoor Equipment",

    # Home
    "Home Utility",
    "Home Organization",
    "Storage Solutions",
    "Cleaning Equipment",
    "Kitchen Storage",
    "Bathroom Utility",
    "Dining & Serving",
    "Home Improvement Equipment",

    # Kids
    "Premium Toys",
    "Building Sets",
    "Construction Sets",
    "Educational Toys",
    "Kids Ride-ons",
    "Kids Equipment",
    "Learning Devices",

    # Pets
    "Pet Beds",
    "Pet Feeders",
    "Pet Grooming Equipment",
    "Pet Travel Equipment",
    "Pet Accessories",

    # Garden
    "Gardening Tools",
    "Garden Equipment",
    "Planters",
    "Outdoor Storage",

    # Books / Education
    "Books",
    "Educational Equipment",
    "Study Equipment",
    "Educational Devices",

    # Personal Care Devices
    "Trimmers",
    "Shavers",
    "Hair Dryers",
    "Hair Straighteners",
    "Hair Styling Appliances",
    "Electric Grooming Devices",
    "Electric Personal Care Devices",

    # Professional
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
# TEXT NORMALIZATION
# ============================================================

def normalize(text):
    if not text:
        return ""

    text = str(text).lower()
    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = text.replace("-", " ")

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

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
        return bool(
            product_words.intersection(category_words)
        )

    return category_words.issubset(product_words)


# ============================================================
# CLASSIFY PRODUCT
# ============================================================

def classify_product(title, extra_text=""):
    combined = normalize(
        f"{title} {extra_text}"
    )

    # Exclusions first
    for keyword in EXCLUDED_KEYWORDS:
        if normalize(keyword) in combined:
            return {
                "matched": False,
                "category": None,
                "reason": (
                    f"Excluded product type: {keyword}"
                ),
            }

    # Allowed categories
    for category in ALLOWED_CATEGORIES:
        if category_match(
            combined,
            category,
        ):
            return {
                "matched": True,
                "category": category,
                "reason": (
                    f"Matched category: {category}"
                ),
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

    # Remove HTML entities / spaces
    value = value.replace(
        "&nbsp;",
        " ",
    )

    # Remove currency labels
    value = re.sub(
        r"(?i)\bINR\b",
        "",
        value,
    )

    value = re.sub(
        r"(?i)\bRs\.?\b",
        "",
        value,
    )

    value = value.replace(
        "₹",
        "",
    )

    value = value.replace(
        ",",
        "",
    )

    match = re.search(
        r"\d+(?:\.\d+)?",
        value,
    )

    if not match:
        return None

    try:
        number = float(match.group())

        # Ignore impossible tiny values
        if number <= 0:
            return None

        return number

    except Exception:
        return None


# ============================================================
# PRICE EXTRACTION FROM TEXT
# ============================================================

def extract_price(text):
    if not text:
        return None

    text = str(text)

    patterns = [

        # Deal Price: ₹24,999
        r"(?i)\bdeal\s*price\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Deal at ₹24,999
        r"(?i)\bdeal\s*at\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Offer Price: ₹24,999
        r"(?i)\boffer\s*price\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Offer ₹24,999
        r"(?i)\boffer\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Sale Price
        r"(?i)\bsale\s*price\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Current Price
        r"(?i)\bcurrent\s*price\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Buy at
        r"(?i)\bbuy\s*at\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # Now at
        r"(?i)\bnow\s*at\s*[:\-@]?\s*"
        r"(?:₹|rs\.?|inr)?\s*"
        r"([\d,]+(?:\.\d+)?)",

        # ₹24,999
        r"₹\s*([\d,]+(?:\.\d+)?)",

        # Rs 24,999
        r"(?i)\brs\.?\s*([\d,]+(?:\.\d+)?)",

        # INR 24,999
        r"(?i)\binr\s*([\d,]+(?:\.\d+)?)",

        # 24999/-
        r"\b([\d,]+)\s*/-",

        # 24999 only
        r"\b([\d,]{4,})\s+only\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
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
# FETCH PRODUCT PAGE
# ============================================================

def fetch_page(url):
    if not url:
        return None

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return None

        return response.text

    except Exception:
        return None


# ============================================================
# EXTRACT PRICE FROM HTML
# ============================================================

def extract_price_from_html(html):
    if not html:
        return None

    # --------------------------------------------------------
    # JSON-LD structured data
    # --------------------------------------------------------

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # Product JSON-LD
    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            raw = script.string or script.get_text(
                strip=True
            )

            if not raw:
                continue

            data = json.loads(raw)

            objects = []

            if isinstance(data, list):
                objects.extend(data)

            elif isinstance(data, dict):
                objects.append(data)

                graph = data.get("@graph")

                if isinstance(graph, list):
                    objects.extend(graph)

            for obj in objects:
                if not isinstance(obj, dict):
                    continue

                offers = obj.get("offers")

                if isinstance(offers, dict):
                    for key in (
                        "price",
                        "lowPrice",
                    ):
                        price = clean_price(
                            offers.get(key)
                        )

                        if price is not None:
                            return price

                elif isinstance(offers, list):
                    for offer in offers:
                        if not isinstance(
                            offer,
                            dict,
                        ):
                            continue

                        for key in (
                            "price",
                            "lowPrice",
                        ):
                            price = clean_price(
                                offer.get(key)
                            )

                            if price is not None:
                                return price

        except Exception:
            continue

    # --------------------------------------------------------
    # Meta price tags
    # --------------------------------------------------------

    meta_selectors = [
        {
            "property": "product:price:amount"
        },
        {
            "property": "og:price:amount"
        },
        {
            "name": "price"
        },
        {
            "itemprop": "price"
        },
    ]

    for selector in meta_selectors:
        tag = soup.find(
            "meta",
            selector,
        )

        if tag:
            price = clean_price(
                tag.get("content")
            )

            if price is not None:
                return price

    # --------------------------------------------------------
    # HTML elements with price attributes
    # --------------------------------------------------------

    price_elements = soup.find_all(
        attrs={
            "itemprop": "price"
        }
    )

    for element in price_elements:
        value = (
            element.get("content")
            or element.get_text(
                " ",
                strip=True,
            )
        )

        price = clean_price(value)

        if price is not None:
            return price

    # --------------------------------------------------------
    # Common HTML / JS price patterns
    # --------------------------------------------------------

    raw_patterns = [

        # "price": 24999
        r'"price"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
        r"([\d,]+(?:\.\d+)?)",

        # "salePrice": 24999
        r'"salePrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
        r"([\d,]+(?:\.\d+)?)",

        # "sellingPrice": 24999
        r'"sellingPrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
        r"([\d,]+(?:\.\d+)?)",

        # "currentPrice": 24999
        r'"currentPrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
        r"([\d,]+(?:\.\d+)?)",

        # "finalPrice": 24999
        r'"finalPrice"\s*:\s*"?(?:₹|Rs\.?|INR)?\s*'
        r"([\d,]+(?:\.\d+)?)",

        # price: 24999
        r"\bprice\s*[:=]\s*['\"]?"
        r"(?:₹|Rs\.?|INR)?\s*"
        r"([\d,]+(?:\.\d+)?)",
    ]

    for pattern in raw_patterns:
        match = re.search(
            pattern,
            html,
            re.I,
        )

        if match:
            price = clean_price(
                match.group(1)
            )

            if price is not None:
                return price

    # --------------------------------------------------------
    # Visible page text fallback
    # --------------------------------------------------------

    visible_text = soup.get_text(
        " ",
        strip=True,
    )

    price = extract_price(
        visible_text
    )

    if price is not None:
        return price

    return None


# ============================================================
# PRICE EXTRACTION FROM URL
# ============================================================

def extract_price_from_url(url):
    if not url:
        return None

    html = fetch_page(url)

    if not html:
        return None

    return extract_price_from_html(
        html
    )


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

        return (
            response.url
            or url
        )

    except Exception:
        return url


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

    # --------------------------------------------------------
    # Visible text
    # --------------------------------------------------------

    patterns = [
        (
            r"(?:all[\s-]*time\s*low|"
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

    # --------------------------------------------------------
    # Raw HTML / JSON
    # --------------------------------------------------------

    raw_patterns = [
        r'"lowestPrice"\s*:\s*"?([\d,.]+)',
        r'"lowest_price"\s*:\s*"?([\d,.]+)',
        r'"historicalLow"\s*:\s*"?([\d,.]+)',
        r'"historical_low"\s*:\s*"?([\d,.]+)',
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
        current_price
        - historical_low
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
        title = (
            title or ""
        ).strip()

        text = (
            text or ""
        ).strip()

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
        # PRICE
        # ----------------------------------------------------

        current_price = clean_price(
            price
        )

        price_source = "argument"

        # 1. Try Telegram/deal text
        if current_price is None:
            current_price = extract_price(
                text
            )
            price_source = "deal_text"

        # 2. Try product URL
        if current_price is None and url:
            current_price = extract_price_from_url(
                url
            )
            price_source = "product_page"

        # Still no price
        if current_price is None:
            return {
                "status": "PRICE_UNKNOWN",
                "historical_low": None,
                "category": None,
                "reason": (
                    "Deal price could not be extracted "
                    "from deal text or product page"
                ),
                "price_source": None,
                "source": source,
                "url": url,
            }

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
                    f"is not above minimum "
                    f"price ₹{MIN_PRICE}"
                ),
                "price_source": price_source,
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
                "reason": (
                    category_result["reason"]
                ),
                "price_source": price_source,
                "source": source,
                "url": url,
            }

        category = (
            category_result["category"]
        )

        # ----------------------------------------------------
        # URL
        # ----------------------------------------------------

        final_url = resolve_url(
            url
        )

        # ----------------------------------------------------
        # PRICEHISTORY SEARCH
        # ----------------------------------------------------

        result = pricehistory_search(
            title
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
                "price_source": price_source,
                "source": source,
                "url": final_url,
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
                "price_source": price_source,
                "source": source,
                "url": final_url,
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
            "price_source": price_source,
            "current_price": current_price,
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

    # --------------------------------------------------------
    # Category tests
    # --------------------------------------------------------

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
        result = classify_product(
            product
        )

        print(
            f"{product:30} -> "
            f"{result['matched']} | "
            f"{result['category']} | "
            f"{result['reason']}"
        )

    # --------------------------------------------------------
    # Price tests
    # --------------------------------------------------------

    price_tests = [
        "Deal Price: ₹24,999",
        "🔥 Deal at Rs 18,999",
        "Offer Price ₹34,999",
        "Now at ₹12,499",
        "Buy at INR 25999",
        "₹49,999 only",
        "24999/-",
        "Current Price: Rs. 21,499",
    ]

    print("\nPRICE TESTS")
    print("-" * 60)

    for test_text in price_tests:
        price = extract_price(
            test_text
        )

        print(
            f"{test_text:40} -> ₹{price}"
        )

    print("\n" + "=" * 60)
    print("VALIDATOR TEST COMPLETE")
    print("=" * 60)

