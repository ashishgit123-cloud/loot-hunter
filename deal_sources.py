import re
import requests
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)


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
        r"(?:deal price|offer price|sale price|current price|buy at|now)\s*[:\-]?\s*₹?\s*([\d,]+(?:\.\d+)?)",
        r"₹\s*([\d,]+(?:\.\d+)?)",
        r"\bRs\.?\s*([\d,]+(?:\.\d+)?)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.I)

        for value in matches:
            try:
                price = float(value.replace(",", ""))
                if price > 0:
                    return price
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


def get_all_web_deals():
    """
    Web discovery is intentionally conservative.
    Telegram remains the primary real-time source.
    """

    deals = []

    # Web discovery is optional.
    # If a site changes its HTML, Telegram listener
    # continues working normally.

    return deals