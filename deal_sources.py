import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# =========================================================
# CONFIG
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

TIMEOUT = 20

SOURCE_URLS = {
    "PriceHistory Deals": "https://pricehistory.app/deals",
    "PriceHistory Drops": "https://pricehistory.app/price-drop",
    "PriceTrail": "https://www.pricehistorytracker.in/",
    "Buyhatke": "https://www.buyhatke.com/deals",
}

session = requests.Session()
session.headers.update(HEADERS)


# =========================================================
# COMMON HELPERS
# =========================================================

def clean_text(value):
    if not value:
        return ""

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def extract_price(text):
    if not text:
        return None

    patterns = [
        r"(?:Price|Offer Price|Current Price)\s*[:\-]?\s*₹\s*([\d,]+)",
        r"₹\s*([\d,]+)",
        r"(?:Rs\.?|INR)\s*([\d,]+)",
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        for value in matches:

            try:
                price = int(
                    value.replace(",", "")
                )

                if price > 0:
                    return price

            except Exception:
                pass

    return None


def extract_urls(text):
    if not text:
        return []

    urls = re.findall(
        r"https?://[^\s<>\"]+",
        text,
        flags=re.IGNORECASE
    )

    result = []

    for url in urls:

        url = url.rstrip(
            ".,);]}>'\""
        )

        if url not in result:
            result.append(url)

    return result


def is_product_url(url):
    if not url:
        return False

    low = url.lower()

    allowed_domains = (
        "amazon.in",
        "amazon.com",
        "flipkart.com",
        "myntra.com",
        "croma.com",
        "reliancedigital.in",
        "tatacliq.com",
        "nykaa.com",
    )

    return any(
        domain in low
        for domain in allowed_domains
    )


def make_deal_text(
    title,
    price,
    url,
    source,
    extra=""
):

    return (
        f"{title}\n"
        f"Deal Price: ₹{price}\n"
        f"{extra}\n"
        f"{url}"
    )


# =========================================================
# PRICEHISTORY
# =========================================================

def scrape_pricehistory_page(
    page_url,
    source_name
):

    deals = []

    try:

        response = session.get(
            page_url,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # -------------------------------------------------
        # Find anchors pointing to actual product/store
        # pages.
        # -------------------------------------------------

        seen = set()

        for anchor in soup.find_all("a"):

            href = anchor.get("href")

            if not href:
                continue

            full_url = urljoin(
                page_url,
                href
            )

            if not is_product_url(full_url):
                continue

            card = anchor

            # Walk upwards to capture the complete deal card
            for _ in range(5):

                if card.parent:
                    card = card.parent

                text = clean_text(
                    card.get_text(
                        " ",
                        strip=True
                    )
                )

                if len(text) >= 40:
                    break

            title = clean_text(
                anchor.get_text(
                    " ",
                    strip=True
                )
            )

            if not title or len(title) < 8:
                continue

            price = extract_price(text)

            if price is None:
                continue

            key = (
                title.lower(),
                full_url
            )

            if key in seen:
                continue

            seen.add(key)

            deals.append({
                "source": source_name,
                "text": make_deal_text(
                    title,
                    price,
                    full_url,
                    source_name,
                    text[:1000]
                )
            })

    except Exception as e:

        print(
            f"⚠️ {source_name} scrape error: "
            f"{type(e).__name__}: {e}"
        )

    return deals


# =========================================================
# PRICETRAIL
# =========================================================

def scrape_pricetrail():

    deals = []

    source_name = "PriceTrail"

    try:

        response = session.get(
            SOURCE_URLS["PriceTrail"],
            timeout=TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        seen = set()

        for anchor in soup.find_all("a"):

            href = anchor.get("href")

            if not href:
                continue

            full_url = urljoin(
                SOURCE_URLS["PriceTrail"],
                href
            )

            if not is_product_url(full_url):
                continue

            title = clean_text(
                anchor.get_text(
                    " ",
                    strip=True
                )
            )

            if not title or len(title) < 8:
                continue

            parent = anchor

            card_text = ""

            for _ in range(6):

                if parent.parent:
                    parent = parent.parent

                card_text = clean_text(
                    parent.get_text(
                        " ",
                        strip=True
                    )
                )

                if len(card_text) >= 40:
                    break

            price = extract_price(
                card_text
            )

            if price is None:
                continue

            key = (
                title.lower(),
                full_url
            )

            if key in seen:
                continue

            seen.add(key)

            deals.append({
                "source": source_name,
                "text": make_deal_text(
                    title,
                    price,
                    full_url,
                    source_name,
                    card_text[:1000]
                )
            })

    except Exception as e:

        print(
            f"⚠️ PriceTrail scrape error: "
            f"{type(e).__name__}: {e}"
        )

    return deals


# =========================================================
# BUYHATKE
# =========================================================

def scrape_buyhatke():

    deals = []

    source_name = "Buyhatke"

    try:

        response = session.get(
            SOURCE_URLS["Buyhatke"],
            timeout=TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        seen = set()

        for anchor in soup.find_all("a"):

            href = anchor.get("href")

            if not href:
                continue

            full_url = urljoin(
                SOURCE_URLS["Buyhatke"],
                href
            )

            if not is_product_url(full_url):
                continue

            title = clean_text(
                anchor.get_text(
                    " ",
                    strip=True
                )
            )

            if not title or len(title) < 8:
                continue

            parent = anchor

            card_text = ""

            for _ in range(7):

                if parent.parent:
                    parent = parent.parent

                card_text = clean_text(
                    parent.get_text(
                        " ",
                        strip=True
                    )
                )

                if len(card_text) >= 40:
                    break

            price = extract_price(
                card_text
            )

            if price is None:
                continue

            key = (
                title.lower(),
                full_url
            )

            if key in seen:
                continue

            seen.add(key)

            deals.append({
                "source": source_name,
                "text": make_deal_text(
                    title,
                    price,
                    full_url,
                    source_name,
                    card_text[:1000]
                )
            })

    except Exception as e:

        print(
            f"⚠️ Buyhatke scrape error: "
            f"{type(e).__name__}: {e}"
        )

    return deals


# =========================================================
# DEDUPLICATION
# =========================================================

def deduplicate_deals(deals):

    result = []
    seen = set()

    for deal in deals:

        text = deal.get(
            "text",
            ""
        )

        urls = extract_urls(text)

        if not urls:
            continue

        url = urls[0]

        if url in seen:
            continue

        seen.add(url)

        result.append(deal)

    return result


# =========================================================
# MAIN WEB SOURCE FUNCTION
# =========================================================

def get_all_web_deals():

    all_deals = []

    print(
        "🌐 Starting web deal collection..."
    )

    # -----------------------------------------------------
    # PriceHistory Deals
    # -----------------------------------------------------

    ph_deals = scrape_pricehistory_page(
        SOURCE_URLS["PriceHistory Deals"],
        "PriceHistory Deals"
    )

    print(
        f"🌐 PriceHistory Deals: "
        f"{len(ph_deals)} candidates"
    )

    all_deals.extend(
        ph_deals
    )

    # -----------------------------------------------------
    # PriceHistory Price Drops
    # -----------------------------------------------------

    ph_drops = scrape_pricehistory_page(
        SOURCE_URLS["PriceHistory Drops"],
        "PriceHistory Drops"
    )

    print(
        f"🌐 PriceHistory Drops: "
        f"{len(ph_drops)} candidates"
    )

    all_deals.extend(
        ph_drops
    )

    # -----------------------------------------------------
    # PriceTrail
    # -----------------------------------------------------

    pt_deals = scrape_pricetrail()

    print(
        f"🌐 PriceTrail: "
        f"{len(pt_deals)} candidates"
    )

    all_deals.extend(
        pt_deals
    )

    # -----------------------------------------------------
    # Buyhatke
    # -----------------------------------------------------

    bh_deals = scrape_buyhatke()

    print(
        f"🌐 Buyhatke: "
        f"{len(bh_deals)} candidates"
    )

    all_deals.extend(
        bh_deals
    )

    # -----------------------------------------------------
    # Final dedupe
    # -----------------------------------------------------

    all_deals = deduplicate_deals(
        all_deals
    )

    print(
        f"🌐 TOTAL WEB CANDIDATES: "
        f"{len(all_deals)}"
    )

    return all_deals