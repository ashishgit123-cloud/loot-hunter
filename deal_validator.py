# deal_validator.py
# VERSION: 2.6

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin


VERSION = "2.6"

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

    # Personal care devices
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
# TEXT
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


def classify_product(title, extra_text=""):
    combined = normalize(f"{title} {extra_text}")

    # Exclusions first
    for keyword in EXCLUDED_KEYWORDS:
        if normalize(keyword) in combined:
            return {
                "matched": False,
                "category": None,
                "reason": f"Excluded product type: {keyword}",
            }

    # Generic category matching
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
        "reason": "Product category is outside configured deal categories",
    }


# ============================================================
# PRICE
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
# URL
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

        return response.url or url

    except Exception:
        return url


# ============================================================
# PRICEHISTORY
# ============================================================

def pricehistory_search(query):
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

            for link in soup.find_all("a", href=True):

                href = link.get("href", "").strip()
                text = link.get_text(" ", strip=True)

                if not href or not text:
                    continue

                full_url = urljoin(
                    search_url,
                    href,
                )

                if "pricehistory" in full_url.lower():
                    return {
                        "title": text,
                        "url": full_url,
                    }

        except Exception:
            continue

    return None


def fetch_page(url):
    if not url:
        return None

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
# HISTORICAL LOW
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
        r"(?:all[\s\-]*time\s*low|historical\s*low|lowest\s*price)"
        r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",

        r'"(?:lowestPrice|lowest_price|historicalLow|historical_low)"'
        r'\s*:\s*"?(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)',
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

    # Search raw HTML too
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
# SUSPICIOUS LOW
# ============================================================

def suspicious_historical_low(
    current_price,
    historical_low,
):

    if current_price is None or historical_low is None:
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
            "reason": "Current price could not be determined",
        }

    if historical_low is None:
        return {
            "status": "HISTORICAL_LOW_UNKNOWN",
            "reason": "Historical low could not be found",
        }

    # Equal is also a NEW LOW
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
                f"₹{tolerance:.0f} of historical low "
                f"₹{historical_low:.0f}"
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

    try:

        title = (title or "").strip()
        text = (text or "").strip()

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

        if current_price is None:
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

        # Strictly greater than ₹1,000
        if current_price <= MIN_PRICE:
            return {
                "status": "PRICE_REJECT",
                "historical_low": None,
                "category": None,
                "reason": (
                    f"Product price ₹{current_price:.0f} is not above "
                    f"minimum price ₹{MIN_PRICE}"
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
        # URL
        # ----------------------------------------------------

        final_url = resolve_url(url)

        # ----------------------------------------------------
        # PRICEHISTORY
        # ----------------------------------------------------

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

            html = fetch_page(
                pricehistory_url
            )

            if html:
                historical_low = extract_historical_low(
                    html
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
                    "PriceHistory historical low could not be verified"
                ),
                "source": source,
                "url": final_url,
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
                    f"Historical low ₹{historical_low:.0f} appears "
                    f"suspicious against current price "
                    f"₹{current_price:.0f}"
                ),
                "source": source,
                "url": final_url,
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

    print("=" * 45)
    print("DEAL VALIDATOR")
    print("VERSION:", VERSION)
    print("=" * 45)

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

    for product in tests:

        result = classify_product(product)

        print(
            f"{product:30} -> "
            f"{result['matched']} | "
            f"{result['category']} | "
            f"{result['reason']}"
        )

    print("=" * 45)
    print("VALIDATOR TEST COMPLETE")
    print("=" * 45)