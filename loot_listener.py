import os
import re
import json
import asyncio
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from dotenv import load_dotenv

from telethon import TelegramClient, events
from telethon.sessions import StringSession


# =========================================================
# ENV
# =========================================================

load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "").strip()
SESSION = os.getenv("TG_SESSION", "").strip()

if not API_ID or not API_HASH or not SESSION:
    raise RuntimeError("TG_API_ID / TG_API_HASH / TG_SESSION missing")


# =========================================================
# TELEGRAM CLIENT
# =========================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH
)


# =========================================================
# SETTINGS
# =========================================================

HEARTBEAT_SECONDS = 60
DIALOG_REFRESH_SECONDS = 60

STATE_FILE = "deal_state.json"

MONITORED_CHAT_IDS = set()
CHAT_NAMES = {}

last_dialog_refresh = 0


# =========================================================
# TARGET PRODUCT TERMS
# =========================================================

IPHONE_TERMS = [
    "iphone 11",
    "iphone 12",
    "iphone 13",
    "iphone 14",
    "iphone 15",
    "iphone 16",
    "iphone 17",
]

SAMSUNG_ULTRA_PATTERN = re.compile(
    r"\bs\d{2}\s*ultra\b",
    re.IGNORECASE
)

FURNITURE_TERMS = [
    "sofa",
    "couch",
    "recliner",
    "sectional",
    "sofa set",

    "bed",
    "double bed",
    "king bed",
    "queen bed",

    "wardrobe",
    "almirah",

    "dining table",
    "dining chair",
    "dining set",

    "coffee table",
    "side table",
    "study table",
    "office table",

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
    "chest",

    "storage cabinet",
    "storage furniture",
]


# =========================================================
# ACCESSORY / JUNK REJECTION
# =========================================================

REJECT_TERMS = [
    # phone accessories
    "case",
    "cover",
    "mobile cover",
    "phone cover",
    "back cover",
    "silicone case",

    "screen protector",
    "tempered glass",
    "glass protector",
    "back glass",

    "screen guard",
    "skin",
    "skins",
    "sleeve",

    "charger",
    "charging cable",
    "usb cable",
    "adapter",
    "power adapter",

    "holder",
    "stand",
    "mobile stand",
    "phone stand",

    "lens protector",
    "camera protector",

    "replacement",
    "battery replacement",
    "display replacement",
    "screen replacement",

    "earphone",
    "earphones",
    "airpods",
    "airpod",

    "watch",
    "smartwatch",
    "watch strap",
    "strap",

    # furniture unrelated / junk
    "mattress",
    "bedsheet",
    "bed sheet",
    "pillow",
    "curtain",

    "carpet",
    "rug",
    "mat",

    "lamp",
    "light",
    "wall art",
    "clock",

    "cleaner",
    "cleaning",
    "polish",

    "hinge",
    "handle",
    "knob",
    "screw",
    "bracket",

    "laptop stand",
    "monitor stand",
    "tablet stand",

    # orthopedic/support products
    "ankle supporter",
    "ankle support",
    "knee supporter",
    "knee support",
    "wrist supporter",
    "wrist support",
    "back support",
    "neck support",
    "lumbar support",
    "elbow support",
    "brace",
    "orthopedic",
    "compression",
    "cushion",
]


# =========================================================
# LOOT / DEAL TERMS
# =========================================================

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
    "loot deal",

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
    "new low",

    "price drop",
    "massive discount",
    "huge discount",
]


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
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        print(f"⚠️ State save error: {e}")


# =========================================================
# URL EXTRACTION
# =========================================================

def extract_urls(text):
    if not text:
        return []

    urls = re.findall(
        r"https?://[^\s<>\]\)]+",
        text
    )

    cleaned = []

    for url in urls:
        url = url.rstrip(".,;:!?)]}>")

        if url not in cleaned:
            cleaned.append(url)

    return cleaned


# =========================================================
# PRICE EXTRACTION
# =========================================================

def extract_price(text):
    if not text:
        return None

    patterns = [
        r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:₹|rs\.?|inr)",
    ]

    values = []

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        for value in matches:
            try:
                number = float(value.replace(",", ""))

                if 100 <= number <= 10000000:
                    values.append(number)

            except Exception:
                pass

    if not values:
        return None

    return min(values)


# =========================================================
# PRODUCT DETECTION
# =========================================================

def is_iphone(text):
    text_lower = text.lower()

    for model in IPHONE_TERMS:
        if model in text_lower:
            return True

    return False


def is_samsung_ultra(text):
    return bool(
        SAMSUNG_ULTRA_PATTERN.search(text)
    )


def is_furniture(text):
    text_lower = text.lower()

    for term in FURNITURE_TERMS:
        if term in text_lower:
            return True

    return False


def is_rejected_product(text):
    text_lower = text.lower()

    for term in REJECT_TERMS:
        if term in text_lower:
            return True

    return False


def is_target_product(text):
    return (
        is_iphone(text)
        or is_samsung_ultra(text)
        or is_furniture(text)
    )


# =========================================================
# LOOT DETECTION
# =========================================================

def has_loot_keyword(text):
    text_lower = text.lower()

    for term in LOOT_TERMS:
        if term in text_lower:
            return True

    return False


# =========================================================
# MESSAGE VALIDATION
# =========================================================

def validate_message(text, urls):
    if not text:
        return False

    if not urls:
        return False

    # obvious junk/accessories
    if is_rejected_product(text):
        return False

    target = is_target_product(text)
    loot = has_loot_keyword(text)

    # Target products can pass even without explicit "loot"
    if target:
        return True

    # Other products need explicit loot/deal language
    if loot:
        return True

    return False


# =========================================================
# PRICEHISTORY
# =========================================================

def get_pricehistory_data(product_url):
    try:
        search_url = (
            "https://pricehistory.app/?search="
            + quote_plus(product_url)
        )

        response = requests.get(
            search_url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "Chrome/140 Safari/537.36"
                )
            }
        )

        if response.status_code != 200:
            return None, None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(
            " ",
            strip=True
        )

        lowest = None
        current = None

        low_match = re.search(
            r"Lowest\s*(?:Price)?\s*₹?\s*([0-9,]+)",
            text,
            re.IGNORECASE
        )

        current_match = re.search(
            r"Current\s*Price\s*₹?\s*([0-9,]+)",
            text,
            re.IGNORECASE
        )

        if low_match:
            lowest = float(
                low_match.group(1).replace(",", "")
            )

        if current_match:
            current = float(
                current_match.group(1).replace(",", "")
            )

        return lowest, current

    except Exception:
        return None, None


# =========================================================
# PRICE VALIDATION
# =========================================================

def validate_price(price, historical_low):
    if price is None:
        return "UNKNOWN"

    if historical_low is None:
        return "UNKNOWN"

    # At or below historical low
    if price <= historical_low:
        return "VALID"

    # Within 2% of historical low
    if price <= historical_low * 1.02:
        return "VALID"

    return "REJECT"


# =========================================================
# DUPLICATE CHECK
# =========================================================

def already_sent(url, price):
    record = STATE.get(url)

    if not record:
        return False

    old_price = record.get("price")

    if old_price is None:
        return True

    if price is None:
        return True

    # Don't send same/higher price again
    if price >= old_price:
        return True

    return False


def mark_sent(url, price):
    STATE[url] = {
        "price": price
    }

    save_state()


# =========================================================
# DEAL ALERT
# =========================================================

async def send_deal(
    source_name,
    text,
    url,
    price,
    historical_low,
    validation
):

    alert = (
        "🔥 LOOT DEAL FOUND\n\n"
        f"📢 Source: {source_name}\n"
        f"💰 Price: ₹{price:,.0f}\n"
    )

    if historical_low is not None:
        alert += (
            f"📉 Historical Low: "
            f"₹{historical_low:,.0f}\n"
        )

    alert += (
        f"✅ Validation: {validation}\n\n"
        f"🔗 {url}\n\n"
        f"📝 {text[:1000]}"
    )

    try:
        await client.send_message(
            "me",
            alert,
            link_preview=False
        )

        print(
            f"🚨 DEAL SENT | {source_name} | "
            f"₹{price if price else 'UNKNOWN'}"
        )

    except Exception as e:
        print(f"❌ Alert error: {e}")


# =========================================================
# PROCESS MESSAGE
# =========================================================

async def process_message(message):

    chat_id = message.chat_id

    if chat_id not in MONITORED_CHAT_IDS:
        return

    text = message.message or ""

    if not text.strip():
        return

    urls = extract_urls(text)

    if not urls:
        return

    if not validate_message(text, urls):
        return

    source_name = CHAT_NAMES.get(
        chat_id,
        str(chat_id)
    )

    price = extract_price(text)

    # Check every URL in the message
    for url in urls:

        if already_sent(url, price):
            continue

        historical_low = None
        current_price = None

        # PriceHistory best-effort validation
        if price is not None:
            (
                historical_low,
                current_price
            ) = await asyncio.to_thread(
                get_pricehistory_data,
                url
            )

        validation = validate_price(
            price,
            historical_low
        )

        # If history is unavailable, don't
        # automatically kill a genuine target deal.
        if validation == "REJECT":
            print(
                f"⛔ Rejected price | "
                f"{source_name} | {url}"
            )
            continue

        await send_deal(
            source_name,
            text,
            url,
            price,
            historical_low,
            validation
        )

        mark_sent(
            url,
            price
        )


# =========================================================
# DISCOVER ALL CHANNELS
# =========================================================

async def discover_channels():

    global MONITORED_CHAT_IDS
    global CHAT_NAMES

    try:
        dialogs = await client.get_dialogs()

        new_ids = set()
        new_names = {}

        for dialog in dialogs:

            entity = dialog.entity

            # Only BROADCAST CHANNELS.
            # Groups and personal chats are ignored.
            if not getattr(entity, "broadcast", False):
                continue

            chat_id = dialog.id
            title = (
                getattr(entity, "title", None)
                or dialog.name
                or str(chat_id)
            )

            new_ids.add(chat_id)
            new_names[chat_id] = title

        added = new_ids - MONITORED_CHAT_IDS
        removed = MONITORED_CHAT_IDS - new_ids

        MONITORED_CHAT_IDS = new_ids
        CHAT_NAMES = new_names

        if added:
            for chat_id in added:
                print(
                    f"➕ NEW CHANNEL: "
                    f"{CHAT_NAMES.get(chat_id, chat_id)}"
                )

        if removed:
            for chat_id in removed:
                print(
                    f"➖ CHANNEL REMOVED: "
                    f"{chat_id}"
                )

        print(
            f"📡 Channels monitored: "
            f"{len(MONITORED_CHAT_IDS)}"
        )

        return True

    except Exception as e:
        print(
            f"❌ Channel discovery error: {e}"
        )
        return False


# =========================================================
# NEW MESSAGE
# =========================================================

@client.on(events.NewMessage)
async def new_message_handler(event):

    try:
        await process_message(
            event.message
        )

    except Exception as e:
        print(
            f"❌ Message processing error: {e}"
        )


# =========================================================
# EDITED MESSAGE
# =========================================================

@client.on(events.MessageEdited)
async def edited_message_handler(event):

    try:
        await process_message(
            event.message
        )

    except Exception as e:
        print(
            f"❌ Edited message error: {e}"
        )


# =========================================================
# HEARTBEAT
# =========================================================

async def heartbeat():

    global last_dialog_refresh

    while True:

        try:
            now = asyncio.get_running_loop().time()

            # Refresh channel list every minute
            if (
                now - last_dialog_refresh
                >= DIALOG_REFRESH_SECONDS
            ):
                await discover_channels()
                last_dialog_refresh = now

            print(
                f"❤️ Listening OK | "
                f"{len(MONITORED_CHAT_IDS)} channels active"
            )

        except Exception as e:
            print(
                f"⚠️ Heartbeat error: {e}"
            )

        await asyncio.sleep(
            HEARTBEAT_SECONDS
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    print("🚀 Starting Loot Hunter...")

    await client.start()

    me = await client.get_me()

    print(
        f"✅ Telegram connected as: "
        f"{getattr(me, 'first_name', 'User')}"
    )

    # Initial discovery
    await discover_channels()

    print(
        "👀 Listening to all joined channels..."
    )

    # Heartbeat background task
    asyncio.create_task(
        heartbeat()
    )

    await client.run_until_disconnected()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())