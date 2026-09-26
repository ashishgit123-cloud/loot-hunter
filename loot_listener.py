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
    raise RuntimeError(
        "TG_API_ID / TG_API_HASH / TG_SESSION missing"
    )


# =========================================================
# TELEGRAM
# =========================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH
)


# =========================================================
# SETTINGS
# =========================================================

DESTINATION = "lootersAmer"

MIN_PRICE = 1000

HEARTBEAT_SECONDS = 60
CHANNEL_REFRESH_SECONDS = 60

STATE_FILE = "deal_state.json"

MONITORED_CHAT_IDS = set()
CHAT_NAMES = {}

last_channel_refresh = 0


# =========================================================
# TARGET PRODUCTS
# =========================================================

IPHONE_PATTERN = re.compile(
    r"\biphone\s*(11|12|13|14|15|16|17)\b",
    re.IGNORECASE
)

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
# HARD REJECT
# =========================================================

REJECT_TERMS = [
    # phone accessories
    "case",
    "cover",
    "back cover",
    "phone cover",
    "mobile cover",
    "silicone case",

    "screen protector",
    "tempered glass",
    "glass protector",
    "back glass",
    "screen guard",

    "skin",
    "sleeve",

    "charger",
    "charging cable",
    "usb cable",
    "adapter",

    "holder",
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

    "smartwatch",
    "watch strap",
    "strap",

    # furniture accessories / unrelated
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

    # support products
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
# DEAL KEYWORDS
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
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception:
        return {}


STATE = load_state()


def save_state():
    try:
        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                STATE,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:
        print(
            f"⚠️ State save error: {e}"
        )


# =========================================================
# URL
# =========================================================

def extract_urls(text):

    if not text:
        return []

    urls = re.findall(
        r"https?://[^\s<>\]\)]+",
        text
    )

    result = []

    for url in urls:

        url = url.rstrip(
            ".,;:!?)]}>"
        )

        if url not in result:
            result.append(url)

    return result


# =========================================================
# PRICE
# =========================================================

def extract_prices(text):

    if not text:
        return []

    patterns = [
        r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:₹|rs\.?|inr)",
    ]

    prices = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        for value in matches:

            try:
                number = float(
                    value.replace(",", "")
                )

                if 1 <= number <= 10000000:
                    prices.append(number)

            except Exception:
                pass

    return prices


def extract_deal_price(text):

    prices = extract_prices(text)

    if not prices:
        return None

    # Prefer explicit deal/current price wording
    patterns = [
        r"(?:deal price|offer price|current price)"
        r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",

        r"(?:now|today|buy at)"
        r"\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            try:
                value = float(
                    match.group(1).replace(",", "")
                )

                if value > 0:
                    return value

            except Exception:
                pass

    # If no explicit deal price:
    # use lowest extracted price.
    return min(prices)


# =========================================================
# PRODUCT DETECTION
# =========================================================

def is_iphone(text):
    return bool(
        IPHONE_PATTERN.search(text)
    )


def is_samsung_ultra(text):
    return bool(
        SAMSUNG_ULTRA_PATTERN.search(text)
    )


def is_furniture(text):

    lower = text.lower()

    return any(
        term in lower
        for term in FURNITURE_TERMS
    )


def is_target_product(text):

    return (
        is_iphone(text)
        or is_samsung_ultra(text)
        or is_furniture(text)
    )


# =========================================================
# REJECT
# =========================================================

def is_rejected_product(text):

    lower = text.lower()

    return any(
        term in lower
        for term in REJECT_TERMS
    )


# =========================================================
# LOOT WORD
# =========================================================

def has_loot_keyword(text):

    lower = text.lower()

    return any(
        term in lower
        for term in LOOT_TERMS
    )


# =========================================================
# BASIC MESSAGE FILTER
# =========================================================

def basic_message_filter(text, urls):

    if not text:
        return False

    if not urls:
        return False

    if is_rejected_product(text):
        return False

    price = extract_deal_price(text)

    # HARD ₹1000 FILTER
    if price is not None and price <= MIN_PRICE:
        return False

    # If it's one of our important categories,
    # don't require "loot" wording.
    if is_target_product(text):
        return True

    # Other products require deal wording.
    if has_loot_keyword(text):
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
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                )
            }
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

        if not text:
            return None

        return text

    except Exception as e:

        print(
            f"⚠️ PriceHistory request error: {e}"
        )

        return None


# =========================================================
# PRICEHISTORY NUMBER PARSER
# =========================================================

def parse_pricehistory_numbers(text):

    if not text:
        return {}

    result = {}

    # IMPORTANT:
    # Do NOT blindly take the first "Lowest".
    # Extract labelled fields independently.

    patterns = {

        "historic_low": [
            r"Historic\s*Lowest(?:\s*Ever)?"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",

            r"Historical\s*Lowest(?:\s*Ever)?"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",

            r"Lowest\s*Ever"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",
        ],

        "current_low": [
            r"Current\s*Lowest\s*Price"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",

            r"Current\s*Lowest"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",
        ],

        "current_offer": [
            r"Current\s*Lowest\s*Offer\s*Price"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",

            r"Lowest\s*Offer\s*Price"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",

            r"Offer\s*Price"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",
        ],

        "current_price": [
            r"Current\s*Price"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",

            r"(?:^|\s)Price"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)",
        ],

        "lowest": [
            r"(?:^|\s)Lowest"
            r"\s*[:\-]?\s*₹?\s*([0-9][0-9,]*)"
        ]
    }

    for key, pattern_list in patterns.items():

        for pattern in pattern_list:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:

                try:

                    value = float(
                        match.group(1).replace(",", "")
                    )

                    if value > 0:
                        result[key] = value
                        break

                except Exception:
                    pass

    return result


# =========================================================
# PRICEHISTORY VALIDATION
# =========================================================

def validate_against_pricehistory(
    telegram_price,
    history
):

    if telegram_price is None:
        return "NO_PRICE", None, None

    if telegram_price <= MIN_PRICE:
        return "LOW_PRICE", None, None

    if not history:
        return "UNKNOWN", None, None

    data = parse_pricehistory_numbers(
        history
    )

    if not data:
        return "UNKNOWN", None, None

    historic_low = data.get(
        "historic_low"
    )

    current_low = data.get(
        "current_low"
    )

    current_offer = data.get(
        "current_offer"
    )

    current_price = data.get(
        "current_price"
    )

    # -----------------------------------------------------
    # Detect obviously corrupt / unrelated scrape
    # -----------------------------------------------------

    candidates = [
        current_offer,
        current_low,
        current_price
    ]

    candidates = [
        x for x in candidates
        if x is not None
    ]

    # Telegram price must approximately match
    # a CURRENT PriceHistory value.
    if candidates:

        matching_current = min(
            candidates,
            key=lambda x: abs(
                x - telegram_price
            )
        )

        difference = abs(
            matching_current - telegram_price
        )

        tolerance = max(
            20,
            telegram_price * 0.05
        )

        if difference > tolerance:

            print(
                "⚠️ PriceHistory mismatch | "
                f"Telegram ₹{telegram_price} | "
                f"PH values {candidates}"
            )

            return (
                "PH_MISMATCH",
                historic_low,
                matching_current
            )

    else:

        return (
            "UNKNOWN",
            historic_low,
            None
        )

    # -----------------------------------------------------
    # If historical low is missing
    # -----------------------------------------------------

    if historic_low is None:

        # Current price verified but no historical low.
        return (
            "UNKNOWN",
            None,
            matching_current
        )

    # -----------------------------------------------------
    # SANITY CHECK
    #
    # If historical low is wildly above the
    # verified current price, something is wrong.
    # Example:
    #
    # Telegram ₹176
    # PH Lowest ₹2599
    #
    # This must NOT become VALID.
    # -----------------------------------------------------

    if historic_low > matching_current * 2:

        print(
            "⚠️ Invalid PriceHistory low | "
            f"Current ₹{matching_current} | "
            f"Historical ₹{historic_low}"
        )

        return (
            "PH_INVALID",
            historic_low,
            matching_current
        )

    # -----------------------------------------------------
    # DEAL TEST
    #
    # Current price should be at/near historical low.
    # -----------------------------------------------------

    allowed_difference = max(
        50,
        historic_low * 0.02
    )

    if matching_current <= (
        historic_low + allowed_difference
    ):

        return (
            "VALID",
            historic_low,
            matching_current
        )

    return (
        "NOT_LOW",
        historic_low,
        matching_current
    )


# =========================================================
# DUPLICATE
# =========================================================

def already_sent(url, price):

    record = STATE.get(url)

    if not record:
        return False

    old_price = record.get(
        "price"
    )

    if old_price is None:
        return True

    if price is None:
        return True

    # New lower price can be sent again.
    if price < old_price:
        return False

    return True


def mark_sent(url, price):

    STATE[url] = {
        "price": price
    }

    save_state()


# =========================================================
# SEND
# =========================================================

async def send_deal(
    source_name,
    text,
    url,
    price,
    historic_low,
    current_ph
):

    alert = (
        "🔥 LOOT DEAL FOUND\n\n"
        f"📢 Source: {source_name}\n"
        f"💰 Price: ₹{price:,.0f}\n"
    )

    if historic_low is not None:

        alert += (
            f"📉 Historical Low: "
            f"₹{historic_low:,.0f}\n"
        )

    if current_ph is not None:

        alert += (
            f"📊 PriceHistory Current: "
            f"₹{current_ph:,.0f}\n"
        )

    alert += (
        "✅ Validation: VALID\n\n"
        f"🔗 {url}\n\n"
        f"📝 {text[:1200]}"
    )

    try:

        await client.send_message(
            DESTINATION,
            alert,
            link_preview=False
        )

        print(
            f"🚨 POSTED → {DESTINATION} | "
            f"{source_name} | "
            f"₹{price:,.0f}"
        )

    except Exception as e:

        print(
            f"❌ POST ERROR → "
            f"{DESTINATION}: {e}"
        )


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

    if not basic_message_filter(
        text,
        urls
    ):
        return

    price = extract_deal_price(text)

    # HARD MINIMUM
    if price is None:
        return

    if price <= MIN_PRICE:
        return

    source_name = CHAT_NAMES.get(
        chat_id,
        str(chat_id)
    )

    for url in urls:

        if already_sent(
            url,
            price
        ):
            continue

        # ---------------------------------------------
        # PriceHistory
        # ---------------------------------------------

        history = await asyncio.to_thread(
            get_pricehistory_data,
            url
        )

        (
            validation,
            historic_low,
            current_ph
        ) = validate_against_pricehistory(
            price,
            history
        )

        print(
            f"🔎 {source_name} | "
            f"₹{price:,.0f} | "
            f"PH={validation}"
        )

        # ---------------------------------------------
        # ONLY VALID DEALS POST
        # ---------------------------------------------

        if validation != "VALID":
            continue

        await send_deal(
            source_name,
            text,
            url,
            price,
            historic_low,
            current_ph
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

            # Only broadcast channels
            if not getattr(
                entity,
                "broadcast",
                False
            ):
                continue

            chat_id = dialog.id

            title = (
                getattr(
                    entity,
                    "title",
                    None
                )
                or dialog.name
                or str(chat_id)
            )

            new_ids.add(chat_id)
            new_names[chat_id] = title

        added = (
            new_ids
            - MONITORED_CHAT_IDS
        )

        removed = (
            MONITORED_CHAT_IDS
            - new_ids
        )

        MONITORED_CHAT_IDS = new_ids
        CHAT_NAMES = new_names

        for chat_id in added:

            print(
                f"➕ NEW CHANNEL: "
                f"{CHAT_NAMES.get(chat_id, chat_id)}"
            )

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
            f"❌ New message error: {e}"
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

    global last_channel_refresh

    while True:

        try:

            now = asyncio.get_running_loop().time()

            if (
                now - last_channel_refresh
                >= CHANNEL_REFRESH_SECONDS
            ):

                await discover_channels()

                last_channel_refresh = now

            print(
                f"❤️ Listening OK | "
                f"{len(MONITORED_CHAT_IDS)} "
                f"channels active"
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

    print(
        "🚀 Starting Loot Hunter..."
    )

    await client.start()

    me = await client.get_me()

    print(
        f"✅ Telegram connected as: "
        f"{getattr(me, 'first_name', 'User')}"
    )

    # Destination check
    try:

        destination_entity = (
            await client.get_entity(
                DESTINATION
            )
        )

        print(
            f"📤 Destination OK: "
            f"{getattr(destination_entity, 'title', DESTINATION)}"
        )

    except Exception as e:

        print(
            f"❌ Destination error "
            f"({DESTINATION}): {e}"
        )

    # Initial discovery
    await discover_channels()

    print(
        "👀 Listening to all joined "
        "broadcast channels..."
    )

    asyncio.create_task(
        heartbeat()
    )

    await client.run_until_disconnected()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())