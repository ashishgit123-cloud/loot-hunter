import os
import re
import json
import asyncio
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from telethon import TelegramClient, events
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

API_ID = int(os.getenv("TG_API_ID"))
API_HASH = os.getenv("TG_API_HASH")
SESSION = os.getenv("TG_SESSION")

SOURCE_CHANNELS = [
    x.strip()
    for x in os.getenv(
        "SOURCE_CHANNEL",
        "@lootdeals2005,@pricehistory,@lootersindia"
    ).split(",")
    if x.strip()
]

PRIVATE_CHANNEL_NAMES = [
    "Offerzone 2.0"
]

STATE_FILE = "deal_state.json"


# =========================================================
# TELEGRAM
# =========================================================

client = TelegramClient(
    SESSION,
    API_ID,
    API_HASH
)

MONITORED_CHAT_IDS = set()
MONITORED_SOURCE_NAMES = {}


# =========================================================
# STATE
# =========================================================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


STATE = load_state()


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                STATE,
                f,
                indent=2,
                ensure_ascii=False
            )
    except Exception as e:
        print("State save error:", e)


# =========================================================
# PRODUCT FILTERS
# =========================================================

ACCESSORY_TERMS = [
    "cover",
    "case",
    "cable",
    "charger",
    "adapter",
    "screen protector",
    "tempered glass",
    "back glass",
    "screen guard",
    "screen film",
    "skin",
    "sleeve",
    "holder",
    "mount",
    "lens protector",
    "camera protector",
    "replacement",
    "battery replacement",
    "display replacement",
    "screen replacement",
    "lcd",
    "strap",
    "earphone",
    "earphones",
    "airpods",
    "galaxy buds",
    "watch",
    "smartwatch"
]

FURNITURE_TERMS = [
    "sofa",
    "couch",
    "recliner",
    "sectional",
    "sofa set",
    "bed",
    "king bed",
    "queen bed",
    "double bed",
    "single bed",
    "bunk bed",
    "wardrobe",
    "almirah",
    "dining table",
    "dining chair",
    "dining set",
    "coffee table",
    "side table",
    "study table",
    "office table",
    "desk",
    "office chair",
    "study chair",
    "reclining chair",
    "bookshelf",
    "book shelf",
    "shoe rack",
    "shoe cabinet",
    "tv unit",
    "tv cabinet",
    "tv stand",
    "dresser",
    "cabinet",
    "drawer",
    "chest of drawers",
    "storage cabinet",
    "furniture"
]

FURNITURE_REJECT_TERMS = [
    "ankle supporter",
    "ankle support",
    "knee supporter",
    "knee support",
    "wrist support",
    "back support",
    "elbow support",
    "neck support",
    "lumbar support",
    "brace",
    "orthopedic",
    "compression",
    "mattress",
    "bedsheet",
    "bed sheet",
    "pillow",
    "cushion",
    "curtain",
    "cleaner",
    "cleaning",
    "polish",
    "hinge",
    "handle",
    "knob",
    "screw",
    "bracket",
    "lamp",
    "light",
    "decor",
    "wall art",
    "clock",
    "carpet",
    "rug",
    "mat",
    "laptop stand",
    "mobile stand",
    "phone stand",
    "tablet stand",
    "monitor stand"
]

LOOT_TERMS = [
    "price error",
    "pricing error",
    "price glitch",
    "pricing glitch",
    "glitch deal",
    "glitch price",
    "error price",
    "error pricing",
    "loot deal",
    "loot",
    "crazy price",
    "crazy deal",
    "mistakenly priced",
    "wrong price",
    "lowest ever",
    "all time low",
    "all-time low",
    "atl",
    "historical low",
    "historic low",
    "new low"
]


# =========================================================
# URL
# =========================================================

URL_REGEX = re.compile(
    r"https?://[^\s<>\]\)]+",
    re.IGNORECASE
)


def extract_urls(text):
    if not text:
        return []

    urls = URL_REGEX.findall(text)

    result = []

    for url in urls:
        url = url.rstrip(".,;:!?)]}")

        if url not in result:
            result.append(url)

    return result


# =========================================================
# PRICE
# =========================================================

def extract_prices(text):
    if not text:
        return []

    prices = []

    patterns = [
        r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:₹|Rs\.?|INR)"
    ]

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        for value in matches:
            try:
                prices.append(
                    float(value.replace(",", ""))
                )
            except Exception:
                pass

    return list(dict.fromkeys(prices))


def get_price(text):
    prices = extract_prices(text)

    if not prices:
        return None

    return min(prices)


# =========================================================
# PRODUCT DETECTION
# =========================================================

def contains_accessory(text):
    return any(
        term in text
        for term in ACCESSORY_TERMS
    )


def is_iphone(text):
    text = text.lower()

    if contains_accessory(text):
        return False

    patterns = [
        r"\biphone\s*(11|12|13|14|15|16|17)\b",
        r"\biphone\s*(11|12|13|14|15|16|17)\s*(pro|max|plus|pro max)?\b"
    ]

    return any(
        re.search(pattern, text)
        for pattern in patterns
    )


def is_samsung_ultra(text):
    text = text.lower()

    if contains_accessory(text):
        return False

    patterns = [
        r"\bs\d{2}\s*ultra\b",
        r"\bsamsung\s+s\d{2}\s*ultra\b",
        r"\bgalaxy\s+s\d{2}\s*ultra\b"
    ]

    return any(
        re.search(pattern, text)
        for pattern in patterns
    )


def is_furniture(text):
    text = text.lower()

    for term in FURNITURE_REJECT_TERMS:
        if term in text:
            return False

    return any(
        term in text
        for term in FURNITURE_TERMS
    )


def get_product_type(text):
    if is_iphone(text):
        return "iPhone"

    if is_samsung_ultra(text):
        return "Samsung Ultra"

    if is_furniture(text):
        return "Furniture"

    return None


def is_loot_message(text):
    text = text.lower()

    return any(
        term in text
        for term in LOOT_TERMS
    )


# =========================================================
# PRICEHISTORY
# =========================================================

def parse_money(value):
    if value is None:
        return None

    match = re.search(
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
        str(value)
    )

    if not match:
        return None

    try:
        return float(
            match.group(1).replace(",", "")
        )
    except Exception:
        return None


def check_pricehistory(product_url):
    try:
        search_url = (
            "https://pricehistory.app/?search="
            + quote_plus(product_url)
        )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            )
        }

        response = requests.get(
            search_url,
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:
            return {
                "status": "unknown"
            }

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        page_text = soup.get_text(
            " ",
            strip=True
        )

        lowest = None
        current = None

        lowest_match = re.search(
            r"Lowest(?:\s*Price)?\s*[:₹RsINR]*\s*([0-9][0-9,]*)",
            page_text,
            re.IGNORECASE
        )

        current_match = re.search(
            r"Current Price\s*[:₹RsINR]*\s*([0-9][0-9,]*)",
            page_text,
            re.IGNORECASE
        )

        if lowest_match:
            lowest = parse_money(
                lowest_match.group(1)
            )

        if current_match:
            current = parse_money(
                current_match.group(1)
            )

        if lowest is None:
            return {
                "status": "unknown"
            }

        return {
            "status": "ok",
            "lowest": lowest,
            "current": current
        }

    except Exception as e:
        print(
            "PriceHistory error:",
            e
        )

        return {
            "status": "unknown"
        }


# =========================================================
# PRICE VALIDATION
# =========================================================

def validate_price(telegram_price, history):
    if telegram_price is None:
        return "unknown"

    if history.get("status") != "ok":
        return "unknown"

    lowest = history.get("lowest")

    if lowest is None:
        return "unknown"

    if telegram_price <= lowest:
        return "accept"

    if telegram_price <= lowest * 1.02:
        return "accept"

    return "reject"


# =========================================================
# DUPLICATE CONTROL
# =========================================================

def normalize_url(url):
    url = url.lower().strip()

    url = url.replace(
        "https://",
        ""
    )

    url = url.replace(
        "http://",
        ""
    )

    url = url.split("?")[0]

    return url.rstrip("/")


def already_seen(url, price):
    key = normalize_url(url)

    old = STATE.get(key)

    if not old:
        return False

    old_price = old.get("price")

    if old_price is None:
        return False

    if price is None:
        return True

    return float(price) >= float(old_price)


def remember_deal(
    url,
    price,
    product_type
):
    key = normalize_url(url)

    old = STATE.get(key)

    if old:
        old_price = old.get("price")

        if (
            price is not None
            and (
                old_price is None
                or price < old_price
            )
        ):
            old["price"] = price

        save_state()
        return

    STATE[key] = {
        "price": price,
        "product_type": product_type
    }

    save_state()


# =========================================================
# SOURCE RESOLUTION
# =========================================================

async def resolve_sources():
    MONITORED_CHAT_IDS.clear()
    MONITORED_SOURCE_NAMES.clear()

    print()
    print("Resolving Telegram sources...")
    print()

    try:
        dialogs = await client.get_dialogs()

        print(
            f"Telegram dialogs loaded: {len(dialogs)}"
        )

    except Exception as e:
        print(
            "Could not load Telegram dialogs:",
            e
        )
        dialogs = []

    # -----------------------------------------------------
    # PUBLIC CHANNELS
    # -----------------------------------------------------

    for source in SOURCE_CHANNELS:

        try:
            entity = await client.get_entity(
                source
            )

            chat_id = int(entity.id)

            MONITORED_CHAT_IDS.add(
                chat_id
            )

            username = getattr(
                entity,
                "username",
                None
            )

            title = getattr(
                entity,
                "title",
                None
            )

            display_name = (
                f"@{username}"
                if username
                else title or source
            )

            MONITORED_SOURCE_NAMES[
                chat_id
            ] = display_name

            print(
                f"FOUND: {display_name} | ID={chat_id}"
            )

        except Exception as e:

            print(
                f"NOT FOUND: {source} | {e}"
            )

    # -----------------------------------------------------
    # PRIVATE CHANNEL
    # -----------------------------------------------------

    for wanted_name in PRIVATE_CHANNEL_NAMES:

        found = False

        for dialog in dialogs:

            title = (
                getattr(
                    dialog,
                    "title",
                    ""
                ) or ""
            ).strip()

            if title.lower() == wanted_name.lower():

                entity = dialog.entity

                chat_id = int(entity.id)

                MONITORED_CHAT_IDS.add(
                    chat_id
                )

                MONITORED_SOURCE_NAMES[
                    chat_id
                ] = title

                print(
                    f"FOUND PRIVATE: "
                    f"{title} | ID={chat_id}"
                )

                found = True
                break

        if not found:

            print(
                f"PRIVATE SOURCE NOT FOUND: "
                f"{wanted_name}"
            )

    print()
    print("==============================")
    print("MONITORED SOURCES")
    print("==============================")

    for chat_id in MONITORED_CHAT_IDS:

        print(
            f"OK: "
            f"{MONITORED_SOURCE_NAMES.get(chat_id)} "
            f"| ID={chat_id}"
        )

    print(
        f"Total sources: "
        f"{len(MONITORED_CHAT_IDS)}"
    )

    print("==============================")
    print()


# =========================================================
# MESSAGE PROCESSOR
# =========================================================

async def process_message(event):

    chat_id = event.chat_id

    if chat_id not in MONITORED_CHAT_IDS:
        return

    text = event.raw_text or ""

    if not text.strip():
        return

    source_name = (
        MONITORED_SOURCE_NAMES.get(
            chat_id,
            str(chat_id)
        )
    )

    print()
    print("MESSAGE RECEIVED")
    print(
        f"Source: {source_name}"
    )
    print(
        f"Message ID: {event.id}"
    )

    preview = text.replace(
        "\n",
        " "
    )

    print(
        f"Text: {preview[:300]}"
    )

    product_type = get_product_type(
        text
    )

    loot_message = is_loot_message(
        text
    )

    urls = extract_urls(text)

    if not product_type and not loot_message:
        print(
            "Ignored: no product/loot signal"
        )
        return

    if not urls:
        print(
            "Candidate found but no URL"
        )
        return

    telegram_price = get_price(text)

    for url in urls:

        print(
            f"Checking: {url}"
        )

        history = check_pricehistory(
            url
        )

        validation = validate_price(
            telegram_price,
            history
        )

        # -------------------------------------------------
        # ONLY reject when PriceHistory proves it is
        # substantially above historical low.
        # -------------------------------------------------

        if validation == "reject":

            print(
                "Rejected: above historical low"
            )

            continue

        if already_seen(
            url,
            telegram_price
        ):

            print(
                "Ignored: duplicate/same price"
            )

            continue

        remember_deal(
            url,
            telegram_price,
            product_type
        )

        if product_type:
            title = product_type
        else:
            title = "Loot Deal"

        if telegram_price is not None:

            price_text = (
                f"₹{telegram_price:,.0f}"
            )

        else:

            price_text = "Not detected"

        if history.get("status") == "ok":

            lowest = history.get(
                "lowest"
            )

            if lowest is not None:

                history_text = (
                    f"₹{lowest:,.0f}"
                )

            else:

                history_text = "Unknown"

        else:

            history_text = "Unavailable"

        alert = (
            "🚨 LOOT ALERT\n\n"
            f"📦 Type: {title}\n"
            f"💰 Price: {price_text}\n"
            f"📉 Historical Low: {history_text}\n"
            f"📡 Source: {source_name}\n\n"
            f"🔗 {url}\n\n"
            f"🆔 Message: {event.id}"
        )

        print()
        print(alert)
        print()

        try:

            await client.send_message(
                "me",
                alert,
                link_preview=False
            )

            print(
                "Alert sent to Saved Messages"
            )

        except Exception as e:

            print(
                "Alert send error:",
                e
            )


# =========================================================
# NEW MESSAGE
# =========================================================

@client.on(events.NewMessage)
async def new_message_handler(event):

    try:

        if event.chat_id not in MONITORED_CHAT_IDS:
            return

        await process_message(event)

    except Exception as e:

        print(
            "NewMessage error:",
            e
        )


# =========================================================
# EDITED MESSAGE
# =========================================================

@client.on(events.MessageEdited)
async def edited_message_handler(event):

    try:

        if event.chat_id not in MONITORED_CHAT_IDS:
            return

        print(
            "MESSAGE EDITED"
        )

        await process_message(event)

    except Exception as e:

        print(
            "MessageEdited error:",
            e
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    print(
        "Starting Loot Hunter..."
    )

    await client.start()

    me = await client.get_me()

    print(
        "Telegram connected"
    )

    print(
        f"Logged in as: "
        f"{getattr(me, 'first_name', '')}"
    )

    await resolve_sources()

    if not MONITORED_CHAT_IDS:

        print(
            "ERROR: No monitored sources found."
        )

        return

    print(
        "Listening for new messages..."
    )

    print(
        "Monitoring edited messages..."
    )

    await client.run_until_disconnected()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "Loot Hunter stopped."
        )

    except Exception as e:

        print(
            "Fatal error:",
            e
        )