import os
import json
import asyncio
import re
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from deal_validator import validate_deal
from deal_sources import (
    get_all_web_deals,
    extract_urls,
    extract_price,
    clean_title,
)


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
SESSION = os.getenv("TG_SESSION", "")

DESTINATION = "lootersAmer"

MIN_PRICE = 1000

CHANNEL_REFRESH_SECONDS = 60
WEB_SCAN_SECONDS = 300
HEARTBEAT_SECONDS = 60

STATE_FILE = "deal_state.json"


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH
)


# ============================================================
# STATE
# ============================================================

sent_deals = {}


def load_state():
    global sent_deals

    try:
        if os.path.exists(STATE_FILE):
            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:
                sent_deals = json.load(f)

            print(
                f"💾 Loaded {len(sent_deals)} previous deals"
            )

    except Exception as e:
        print(
            f"⚠️ State load failed: {e}"
        )

        sent_deals = {}


def save_state():
    try:
        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                sent_deals,
                f,
                indent=2,
                ensure_ascii=False
            )

    except Exception as e:
        print(
            f"⚠️ State save failed: {e}"
        )


# ============================================================
# CHANNEL DISCOVERY
# ============================================================

MONITORED_CHAT_IDS = set()
CHANNEL_NAMES = {}


async def discover_channels():

    global MONITORED_CHAT_IDS
    global CHANNEL_NAMES

    try:

        dialogs = await client.get_dialogs()

        new_ids = set()
        new_names = {}

        for dialog in dialogs:

            entity = dialog.entity

            # Only Telegram broadcast channels
            if not getattr(
                entity,
                "broadcast",
                False
            ):
                continue

            chat_id = entity.id

            new_ids.add(chat_id)

            title = getattr(
                entity,
                "title",
                str(chat_id)
            )

            new_names[chat_id] = title

        MONITORED_CHAT_IDS = new_ids
        CHANNEL_NAMES = new_names

        print(
            f"📡 Channels monitored: "
            f"{len(MONITORED_CHAT_IDS)}"
        )

    except Exception as e:

        print(
            f"⚠️ Channel discovery failed: {e}"
        )


# ============================================================
# BASIC JUNK FILTER
# ============================================================

HARD_JUNK_TERMS = [
    "mobile cover",
    "phone cover",
    "back cover",
    "screen protector",
    "tempered glass",
    "camera lens protector",
    "lens protector",
    "replacement screen",
    "replacement display",
    "charging cable",
    "usb cable",
    "data cable",
    "watch strap",
    "case only",
]


def looks_like_junk(title):

    if not title:
        return False

    text = title.lower()

    for term in HARD_JUNK_TERMS:

        if term in text:
            return True

    return False


# ============================================================
# PRODUCT TITLE EXTRACTION
# ============================================================

def extract_product_title(text):

    if not text:
        return ""

    title = clean_title(text)

    # Remove common promotional lines
    lines = []

    for line in title.splitlines():

        line = line.strip()

        if not line:
            continue

        lower = line.lower()

        if lower.startswith(
            (
                "http",
                "deal price",
                "offer price",
                "buy now",
                "shop now",
                "coupon",
                "discount",
            )
        ):
            continue

        lines.append(line)

    title = " ".join(lines)

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    return title[:500].strip()


# ============================================================
# DEAL KEY
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = url.strip()

    url = url.rstrip(
        ".,;:!?)]}>"
    )

    return url


def deal_key(url, title=""):

    url = normalize_url(url)

    if url:
        return url.lower()

    return re.sub(
        r"\W+",
        "",
        title.lower()
    )[:150]


# ============================================================
# DUPLICATE CHECK
# ============================================================

def already_sent(key, price):

    old = sent_deals.get(key)

    if old is None:
        return False

    try:
        old_price = float(
            old.get("price", 0)
        )

        # Same or higher price = don't resend
        if price >= old_price:
            return True

        # Lower price = send again
        return False

    except Exception:
        return False


def mark_sent(
    key,
    price,
    source,
    title
):

    sent_deals[key] = {
        "price": price,
        "source": source,
        "title": title[:300],
        "time": datetime.utcnow().isoformat(),
    }

    save_state()


# ============================================================
# SEND DEAL
# ============================================================

async def send_deal(
    source,
    title,
    url,
    price,
    validation
):

    lowest = validation.get(
        "lowest_price"
    )

    message = (
        "🔥 LOOT DEAL FOUND\n\n"
        f"📢 Source: {source}\n"
        f"📝 {title[:500]}\n\n"
        f"💰 Deal Price: ₹{price:,.0f}\n"
    )

    if lowest:
        message += (
            f"📉 Historical Low: "
            f"₹{lowest:,.0f}\n"
        )

    message += (
        "\n✅ Validation: "
        f"{validation.get('status')}\n"
        f"🔗 {url}"
    )

    try:

        await client.send_message(
            DESTINATION,
            message,
            link_preview=False
        )

        print(
            f"🚨 POSTED → {DESTINATION} "
            f"| ₹{price:,.0f} "
            f"| {source}"
        )

        return True

    except Exception as e:

        print(
            f"❌ Send failed: {e}"
        )

        return False


# ============================================================
# PROCESS ONE DEAL
# ============================================================

async def process_deal(
    source,
    title,
    url,
    price=None
):

    try:

        url = normalize_url(url)

        if not url:
            return

        # ----------------------------------------------------
        # PRICE
        # ----------------------------------------------------

        if price is None:

            price = extract_price(
                title
            )

        if price is None:

            print(
                f"❌ REJECT | NO_PRICE | {source}"
            )

            return

        try:
            price = float(price)
        except Exception:
            return

        # ----------------------------------------------------
        # MINIMUM PRICE
        # ----------------------------------------------------

        if price <= MIN_PRICE:

            print(
                f"❌ REJECT | PRICE_LOW "
                f"| ₹{price:,.0f} "
                f"| {source}"
            )

            return

        # ----------------------------------------------------
        # PRODUCT TITLE
        # ----------------------------------------------------

        product_title = extract_product_title(
            title
        )

        if not product_title:

            product_title = "Unknown Product"

        # ----------------------------------------------------
        # JUNK FILTER
        # ----------------------------------------------------

        if looks_like_junk(
            product_title
        ):

            print(
                f"❌ REJECT | ACCESSORY "
                f"| {product_title[:100]}"
            )

            return

        # ----------------------------------------------------
        # DUPLICATE
        # ----------------------------------------------------

        key = deal_key(
            url,
            product_title
        )

        if already_sent(
            key,
            price
        ):

            print(
                f"↩️ DUPLICATE | "
                f"₹{price:,.0f} "
                f"| {source}"
            )

            return

        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

        print(
            f"🔎 VALIDATING | "
            f"₹{price:,.0f} "
            f"| {source}"
        )

        validation = await asyncio.to_thread(
            validate_deal,
            product_title,
            url,
            price
        )

        status = validation.get(
            "status",
            "UNKNOWN"
        )

        lowest = validation.get(
            "lowest_price"
        )

        print(
            f"🧪 VALIDATION | "
            f"{status} "
            f"| deal=₹{price:,.0f} "
            f"| low={lowest}"
        )

        # ----------------------------------------------------
        # ONLY VALIDATED LOWEST DEALS
        # ----------------------------------------------------

        if status != "VALID":

            print(
                f"❌ REJECT | "
                f"{status} "
                f"| {source}"
            )

            return

        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        sent = await send_deal(
            source,
            product_title,
            url,
            price,
            validation
        )

        if sent:

            mark_sent(
                key,
                price,
                source,
                product_title
            )

    except Exception as e:

        print(
            f"❌ PROCESS ERROR: {e}"
        )


# ============================================================
# TELEGRAM MESSAGE HANDLER
# ============================================================

async def handle_telegram_message(
    message
):

    try:

        text = (
            message.raw_text
            or ""
        )

        if not text:
            return

        urls = extract_urls(
            text
        )

        if not urls:
            return

        chat = await message.get_chat()

        source = getattr(
            chat,
            "title",
            "Telegram"
        )

        print(
            f"📨 NEW MESSAGE | {source}"
        )

        # One message can contain
        # multiple products/URLs
        for url in urls:

            await process_deal(
                source=source,
                title=text,
                url=url,
                price=extract_price(text)
            )

    except Exception as e:

        print(
            f"❌ Telegram handler error: {e}"
        )


# ============================================================
# NEW MESSAGE
# ============================================================

@client.on(events.NewMessage)
async def new_message_handler(
    event
):

    chat_id = event.chat_id

    if chat_id not in MONITORED_CHAT_IDS:
        return

    await handle_telegram_message(
        event.message
    )


# ============================================================
# EDITED MESSAGE
# ============================================================

@client.on(events.MessageEdited)
async def edited_message_handler(
    event
):

    chat_id = event.chat_id

    if chat_id not in MONITORED_CHAT_IDS:
        return

    print(
        f"✏️ EDITED MESSAGE | "
        f"{CHANNEL_NAMES.get(chat_id, chat_id)}"
    )

    await handle_telegram_message(
        event.message
    )


# ============================================================
# WEB DEAL SCANNER
# ============================================================

async def web_deal_scanner():

    while True:

        try:

            print(
                "🌐 Scanning web deal sources..."
            )

            deals = await asyncio.to_thread(
                get_all_web_deals
            )

            print(
                f"🌐 Web candidates found: "
                f"{len(deals)}"
            )

            for deal in deals:

                await process_deal(
                    source=deal.get(
                        "source",
                        "Web"
                    ),

                    title=deal.get(
                        "title",
                        ""
                    ),

                    url=deal.get(
                        "url",
                        ""
                    ),

                    price=deal.get(
                        "price"
                    )
                )

                # Don't hammer websites
                await asyncio.sleep(
                    0.5
                )

        except Exception as e:

            print(
                f"⚠️ Web scanner error: {e}"
            )

        await asyncio.sleep(
            WEB_SCAN_SECONDS
        )


# ============================================================
# HEARTBEAT
# ============================================================

async def heartbeat():

    while True:

        try:

            await discover_channels()

            print(
                "❤️ Listening OK | "
                f"{len(MONITORED_CHAT_IDS)} "
                "channels active"
            )

        except Exception as e:

            print(
                f"⚠️ Heartbeat error: {e}"
            )

        await asyncio.sleep(
            HEARTBEAT_SECONDS
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    if not API_ID:
        raise RuntimeError(
            "TG_API_ID missing"
        )

    if not API_HASH:
        raise RuntimeError(
            "TG_API_HASH missing"
        )

    if not SESSION:
        raise RuntimeError(
            "TG_SESSION missing"
        )

    load_state()

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

        destination = await client.get_entity(
            DESTINATION
        )

        print(
            f"🎯 Destination OK: "
            f"{getattr(destination, 'title', DESTINATION)}"
        )

    except Exception as e:

        print(
            f"❌ Destination error: {e}"
        )

        raise

    # Initial channel discovery
    await discover_channels()

    # Background tasks
    asyncio.create_task(
        heartbeat()
    )

    asyncio.create_task(
        web_deal_scanner()
    )

    print(
        "👀 Listening to all joined "
        "broadcast channels..."
    )

    print(
        "🌐 Web deal scanner enabled"
    )

    print(
        "🧪 Validation engine enabled"
    )

    await client.run_until_disconnected()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "🛑 Stopped"
        )

    except Exception as e:

        print(
            f"💥 FATAL ERROR: {e}"
        )