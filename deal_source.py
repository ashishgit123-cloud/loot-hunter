import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140.0 Safari/537.36"
    )
}


def extract_urls(text):
    if not text:
        return []

    return re.findall(
        r"https?://[^\s<>\]\)]+",
        text
    )


def extract_price(text):
    if not text:
        return None

    patterns = [
        r"(?:deal price|offer price|sale price|current price)"
        r"\s*[:\-]?\s*₹?\s*([\d,]+)",

        r"(?:buy at|now|today)"
        r"\s*[:\-]?\s*₹?\s*([\d,]+)",

        r"₹\s*([\d,]+)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.I
        )

        if match:
            try:
                return float(
                    match.group(1).replace(",", "")
                )
            except Exception:
                pass

    return None


def clean_title(text):
    if not text:
        return ""

    text = re.sub(
        r"https?://\S+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# PRICEHISTORY DEALS
# ============================================================

def get_pricehistory_deals():
    deals = []

    try:
        url = "https://pricehistory.app/deals"

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for a in soup.find_all("a"):
            href = a.get("href")

            if not href:
                continue

            full_url = urljoin(
                url,
                href
            )

            text = a.get_text(
                " ",
                strip=True
            )

            if not text:
                continue

            price = extract_price(text)

            if price:
                deals.append({
                    "source": "PriceHistory",
                    "title": clean_title(text),
                    "url": full_url,
                    "price": price,
                })

    except Exception as e:
        print(f"⚠️ PriceHistory source error: {e}")

    return deals


# ============================================================
# PRICETRAIL
# ============================================================

def get_pricetrail_deals():
    deals = []

    try:
        url = "https://www.pricehistorytracker.in/"

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for a in soup.find_all("a"):
            href = a.get("href")

            if not href:
                continue

            text = a.get_text(
                " ",
                strip=True
            )

            if not text:
                continue

            price = extract_price(text)

            if price:
                deals.append({
                    "source": "PriceTrail",
                    "title": clean_title(text),
                    "url": urljoin(url, href),
                    "price": price,
                })

    except Exception as e:
        print(f"⚠️ PriceTrail source error: {e}")

    return deals


# ============================================================
# BUYHATKE
# ============================================================

def get_buyhatke_deals():
    deals = []

    try:
        url = "https://www.buyhatke.com/deals"

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for a in soup.find_all("a"):
            href = a.get("href")

            if not href:
                continue

            text = a.get_text(
                " ",
                strip=True
            )

            if not text:
                continue

            price = extract_price(text)

            if price:
                deals.append({
                    "source": "Buyhatke",
                    "title": clean_title(text),
                    "url": urljoin(url, href),
                    "price": price,
                })

    except Exception as e:
        print(f"⚠️ Buyhatke source error: {e}")

    return deals


# ============================================================
# ALL WEB SOURCES
# ============================================================

def get_all_web_deals():

    deals = []

    deals.extend(
        get_pricehistory_deals()
    )

    deals.extend(
        get_pricetrail_deals()
    )

    deals.extend(
        get_buyhatke_deals()
    )

    return deals