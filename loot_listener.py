import os
import re
import json
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from deal_validator import validate_deal
from deal_sources import get_all_web_deals


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

API_ID = int(os.getenv("TG_API_ID"))
API_HASH = os.getenv("TG_API_HASH")
SESSION = os.getenv("TG_SESSION")

DESTINATION = "lootersAmer"

MIN_PRICE = 1000

CHANNEL_REFRESH_SECONDS = 60
HEARTBEAT_SECONDS = 60
WEB_SCAN_SECONDS = 300

STATE_FILE = Path("deal_state.json")


# =========================================================
# TELEGRAM CLIENT
# =========================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH
)


# =========================================================
# STATE
# =========================================================

MONITORED_CHAT_IDS = set()
MONITORED_CHAT_NAMES = {}

STATE = {
    "sent_urls": []
}


def load_state():
    global STATE

    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                STATE = data

            if "sent_urls" not in STATE:
                STATE["sent_urls"] = []

    except Exception as e:
        print(f"⚠️ State load error: {e}")

        STATE = {
            "sent_urls": []
        }


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

URL_REGEX = re.compile(
    r"https?://[^\s<>\]\)]+",
    re.IGNORECASE
)


def extract_urls(text):
    if not text:
        return []

    urls = URL_REGEX.findall(text)

    cleaned = []

    for url in urls:

        url = url.rstrip(".,;:!?)]}\"'")

        if url not in cleaned:
            cleaned.append(url)

    return cleaned


# =========================================================
# PRICE EXTRACTION
# =========================================================

def extract_deal_price(text):
    """
    Try to identify the actual deal/sale price.

    Priority:
    1. Deal Price
    2. Offer Price
    3. Sale Price
    4. Now Price
    5. Current Price
    6. Explicit ₹ price
    """

    if not text:
        return None

    # -----------------------------------------------------
    # Explicit deal price patterns
    # -----------------------------------------------------

    patterns = [

        r"(?:deal\s*price|deal\s*at)\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:offer\s*price|offer\s*at)\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:sale\s*price|sale\s*at)\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:now|now\s*at)\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:current\s*price)\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:buy\s*at|buy\s*for)\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:price)\s*[:\-]?\s*₹\s*([\d,]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            try:
                return int(
                    match.group(1).replace(",", "")
                )
            except Exception:
                pass

    # -----------------------------------------------------
    # Generic ₹ prices
    # -----------------------------------------------------

    prices = re.findall(
        r"₹\s*([\d,]+)",
        text,
        re.IGNORECASE
    )

    if prices:

        values = []

        for value in prices:

            try:
                values.append(
                    int(value.replace(",", ""))
                )
            except Exception:
                continue

        if values:

            # Prefer a price above minimum
            valid = [
                x for x in values
                if x > MIN_PRICE
            ]

            if valid:
                return min(valid)

            return min(values)

    # -----------------------------------------------------
    # INR / Rs patterns
    # -----------------------------------------------------

    prices = re.findall(
        r"(?:INR|Rs\.?|Rs)\s*([\d,]+)",
        text,
        re.IGNORECASE
    )

    if prices:

        values = []

        for value in prices:

            try:
                values.append(
                    int(value.replace(",", ""))
                )
            except Exception:
                continue

        if values:

            valid = [
                x for x in values
                if x > MIN_PRICE
            ]

            if valid:
                return min(valid)

            return min(values)

    return None


# =========================================================
# PRODUCT TITLE
# =========================================================

def extract_product_title(text):
    if not text:
        return "Unknown Product"

    lines = [
        x.strip()
        for x in text.splitlines()
        if x.strip()
    ]

    # Remove obvious Telegram deal metadata
    ignore_patterns = [
        r"^https?://",
        r"^₹",
        r"^rs\.?",
        r"^inr",
        r"^deal\s*price",
        r"^offer\s*price",
        r"^sale\s*price",
        r"^current\s*price",
        r"^mrp",
        r"^discount",
        r"^coupon",
        r"^use\s*code",
        r"^limited\s*time",
        r"^buy\s*now",
        r"^shop\s*now",
        r"^click\s*here",
    ]

    candidates = []

    for line in lines:

        if len(line) < 5:
            continue

        skip = False

        for pattern in ignore_patterns:

            if re.search(
                pattern,
                line,
                re.IGNORECASE
            ):
                skip = True
                break

        if skip:
            continue

        candidates.append(line)

    if candidates:

        # Usually first meaningful line is product title
        title = candidates[0]

        # Remove excessive emojis
        title = re.sub(
            r"[🔥⚡🚨💥🎯😍🥳👇👉✅❌🛍️📢💰📉]",
            "",
            title
        )

        title = re.sub(
            r"\s+",
            " ",
            title
        ).strip()

        if len(title) > 250:
            title = title[:250].rsplit(" ", 1)[0]

        return title

    return "Unknown Product"


# =========================================================
# URL NORMALIZATION
# =========================================================

def normalize_url(url):
    if not url:
        return None

    url = url.strip()

    url = url.rstrip(
        ".,;:!?)]}\"'"
    )

    return url


# =========================================================
# DUPLICATE CHECK
# =========================================================

def already_sent(url):

    if not url:
        return False

    return url in STATE.get(
        "sent_urls",
        []
    )


def mark_sent(url):

    if not url:
        return

    if "sent_urls" not in STATE:
        STATE["sent_urls"] = []

    if url not in STATE["sent_urls"]:

        STATE["sent_urls"].append(url)

    # Keep state file small
    if len(STATE["sent_urls"]) > 5000:

        STATE["sent_urls"] = \
            STATE["sent_urls"][-5000:]

    save_state()


# =========================================================
# AUTO DISCOVER TELEGRAM CHANNELS
# =========================================================

async def discover_channels():

    global MONITORED_CHAT_IDS
    global MONITORED_CHAT_NAMES

    try:

        dialogs = await client.get_dialogs()

        new_ids = set()
        new_names = {}

        for dialog in dialogs:

            entity = dialog.entity

            # We only want broadcast channels
            if not getattr(
                entity,
                "broadcast",
                False
            ):
                continue

            chat_id = entity.id

            new_ids.add(chat_id)

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

            if username:

                new_names[chat_id] = (
                    f"@{username}"
                )

            else:

                new_names[chat_id] = (
                    title or str(chat_id)
                )

        MONITORED_CHAT_IDS = new_ids
        MONITORED_CHAT_NAMES = new_names

        print(
            f"📡 Broadcast channels discovered: "
            f"{len(MONITORED_CHAT_IDS)}"
        )

        for chat_id in sorted(
            MONITORED_CHAT_IDS
        ):

            print(
                f"   • "
                f"{MONITORED_CHAT_NAMES.get(chat_id, chat_id)}"
            )

    except Exception as e:

        print(
            f"❌ Channel discovery error: {e}"
        )


# =========================================================
# SEND DEAL
# =========================================================

async def send_deal(
    product_title,
    deal_price,
    historical_low,
    status,
    source,
    url
):

    if status == "NEW_LOW":

        label = (
            "🚨 NEW ALL-TIME LOW"
        )

    elif status == "NEAR_LOW":

        label = (
            "🔥 NEAR HISTORICAL LOW"
        )

    else:

        label = "🔥 LOOT DEAL FOUND"

    message = (
        f"{label}\n\n"
        f"📦 Product: {product_title}\n"
        f"💰 Deal Price: ₹{deal_price:,}\n"
        f"📉 Historical Low: "
        f"₹{historical_low:,}\n"
        f"📊 Status: {status}\n"
        f"📢 Source: {source}\n\n"
        f"🔗 {url}"
    )

    try:

        await client.send_message(
            DESTINATION,
            message,
            link_preview=False
        )

        print(
            f"🚀 SENT | "
            f"{status} | "
            f"₹{deal_price:,} | "
            f"{product_title}"
        )

        mark_sent(url)

    except Exception as e:

        print(
            f"❌ Send error: {e}"
        )


# =========================================================
# PROCESS DEAL
# =========================================================

async def process_deal(
    text,
    source
):

    if not text:
        return

    # -----------------------------------------------------
    # URL
    # -----------------------------------------------------

    urls = extract_urls(text)

    if not urls:
        return

    # -----------------------------------------------------
    # Price
    # -----------------------------------------------------

    deal_price = extract_deal_price(text)

    if not deal_price:

        print(
            f"⏭️ SKIP | No price | {source}"
        )

        return

    # Strict minimum
    if deal_price <= MIN_PRICE:

        print(
            f"⏭️ SKIP | "
            f"Price <= ₹{MIN_PRICE} | "
            f"₹{deal_price} | "
            f"{source}"
        )

        return

    # -----------------------------------------------------
    # Product title
    # -----------------------------------------------------

    product_title = extract_product_title(text)

    # -----------------------------------------------------
    # Try every URL
    # -----------------------------------------------------

    for raw_url in urls:

        url = normalize_url(raw_url)

        if not url:
            continue

        if already_sent(url):

            print(
                f"⏭️ DUPLICATE | {url}"
            )

            continue

        print(
            f"🔎 VALIDATING | "
            f"{product_title} | "
            f"₹{deal_price} | "
            f"{url}"
        )

        try:

            result = await asyncio.to_thread(
                validate_deal,
                product_title,
                url,
                deal_price
            )

        except Exception as e:

            print(
                f"❌ Validator error | "
                f"{e}"
            )

            continue

        # -------------------------------------------------
        # Support both possible validator return formats
        # -------------------------------------------------

        status = None
        historical_low = None

        if isinstance(result, dict):

            status = result.get(
                "status"
            )

            historical_low = result.get(
                "historical_low"
            )

            if historical_low is None:

                historical_low = result.get(
                    "lowest"
                )

        elif isinstance(result, tuple):

            if len(result) >= 1:
                status = result[0]

            if len(result) >= 2:
                historical_low = result[1]

        elif isinstance(result, str):

            status = result

        # -------------------------------------------------
        # Only real low-price deals pass
        # -------------------------------------------------

        if status not in (
            "NEW_LOW",
            "NEAR_LOW"
        ):

            print(
                f"❌ REJECT | "
                f"{status} | "
                f"{product_title}"
            )

            continue

        if not historical_low:

            print(
                f"❌ REJECT | "
                f"No historical low | "
                f"{product_title}"
            )

            continue

        # -------------------------------------------------
        # Send
        # -------------------------------------------------

        await send_deal(
            product_title=product_title,
            deal_price=deal_price,
            historical_low=historical_low,
            status=status,
            source=source,
            url=url
        )


# =========================================================
# TELEGRAM NEW MESSAGE
# =========================================================

@client.on(events.NewMessage)
async def new_message_handler(event):

    try:

        chat = await event.get_chat()

        chat_id = chat.id

        if chat_id not in MONITORED_CHAT_IDS:
            return

        source = MONITORED_CHAT_NAMES.get(
            chat_id,
            str(chat_id)
        )

        text = event.raw_text or ""

        print(
            f"📥 NEW | "
            f"{source}"
        )

        await process_deal(
            text,
            source
        )

    except Exception as e:

        print(
            f"❌ New message handler error: "
            f"{e}"
        )


# =========================================================
# TELEGRAM EDITED MESSAGE
# =========================================================

@client.on(events.MessageEdited)
async def edited_message_handler(event):

    try:

        chat = await event.get_chat()

        chat_id = chat.id

        if chat_id not in MONITORED_CHAT_IDS:
            return

        source = MONITORED_CHAT_NAMES.get(
            chat_id,
            str(chat_id)
        )

        text = event.raw_text or ""

        print(
            f"✏️ EDITED | "
            f"{source}"
        )

        await process_deal(
            text,
            source
        )

    except Exception as e:

        print(
            f"❌ Edited message handler error: "
            f"{e}"
        )


# =========================================================
# CHANNEL REFRESH LOOP
# =========================================================

async def channel_refresh_loop():

    while True:

        try:

            await asyncio.sleep(
                CHANNEL_REFRESH_SECONDS
            )

            await discover_channels()

        except asyncio.CancelledError:

            break

        except Exception as e:

            print(
                f"❌ Refresh loop error: {e}"
            )


# =========================================================
# HEARTBEAT
# =========================================================

async def heartbeat_loop():

    while True:

        try:

            await asyncio.sleep(
                HEARTBEAT_SECONDS
            )

            print(
                f"💓 ALIVE | "
                f"Channels: "
                f"{len(MONITORED_CHAT_IDS)} | "
                f"Sent: "
                f"{len(STATE.get('sent_urls', []))}"
            )

        except asyncio.CancelledError:

            break

        except Exception as e:

            print(
                f"❌ Heartbeat error: {e}"
            )


# =========================================================
# WEB DEAL SCANNER
# =========================================================

async def web_scanner_loop():

    while True:

        try:

            await asyncio.sleep(
                WEB_SCAN_SECONDS
            )

            print(
                "🌐 Checking web deal sources..."
            )

            deals = await asyncio.to_thread(
                get_all_web_deals
            )

            if not deals:

                print(
                    "🌐 No web deals returned."
                )

                continue

            for deal in deals:

                try:

                    title = deal.get(
                        "title",
                        "Unknown Product"
                    )

                    url = deal.get(
                        "url"
                    )

                    price = deal.get(
                        "price"
                    )

                    source = deal.get(
                        "source",
                        "Web"
                    )

                    if not url or not price:
                        continue

                    if price <= MIN_PRICE:
                        continue

                    if already_sent(url):
                        continue

                    await process_deal(
                        f"{title}\n₹{price}\n{url}",
                        source
                    )

                except Exception as e:

                    print(
                        f"❌ Web deal error: "
                        f"{e}"
                    )

        except asyncio.CancelledError:

            break

        except Exception as e:

            print(
                f"❌ Web scanner error: "
                f"{e}"
            )


# =========================================================
# MAIN
# =========================================================

async def main():

    load_state()

    print(
        "🚀 Starting Loot Hunter..."
    )

    await client.start()

    me = await client.get_me()

    print(
        f"✅ Telegram connected as: "
        f"{getattr(me, 'username', None) or me.first_name}"
    )

    # -----------------------------------------------------
    # Destination check
    # -----------------------------------------------------

    try:

        destination = await client.get_entity(
            DESTINATION
        )

        print(
            f"🎯 Destination: "
            f"{getattr(destination, 'title', DESTINATION)}"
        )

    except Exception as e:

        print(
            f"❌ Destination '{DESTINATION}' "
            f"not accessible: {e}"
        )

        print(
            "⚠️ Make sure the Telegram account "
            "can access the destination channel."
        )

        return

    # -----------------------------------------------------
    # Initial channel discovery
    # -----------------------------------------------------

    await discover_channels()

    # -----------------------------------------------------
    # Background loops
    # -----------------------------------------------------

    asyncio.create_task(
        channel_refresh_loop()
    )

    asyncio.create_task(
        heartbeat_loop()
    )

    asyncio.create_task(
        web_scanner_loop()
    )

    print(
        "👀 Listening to ALL joined "
        "broadcast channels..."
    )

    print(
        f"📤 Alerts → {DESTINATION}"
    )

    print(
        f"💰 Minimum deal price → "
        f"₹{MIN_PRICE:,}"
    )

    print(
        "📉 Accepted → NEW_LOW / NEAR_LOW"
    )

    # -----------------------------------------------------
    # Stay alive
    # -----------------------------------------------------

    await client.run_until_disconnected()


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "🛑 Stopped manually."
        )

    except Exception as e:

        print(
            f"💥 Fatal error: {e}"
        )