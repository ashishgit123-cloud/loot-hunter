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


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

API_ID = int(os.getenv("TG_API_ID"))
API_HASH = os.getenv("TG_API_HASH")
TG_SESSION = os.getenv("TG_SESSION")

DESTINATION = "lootersAmer"

MIN_PRICE = 1000

CHANNEL_REFRESH_SECONDS = 60
HEARTBEAT_SECONDS = 60
WEB_SCAN_SECONDS = 300

STATE_FILE = Path("deal_state.json")


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    StringSession(TG_SESSION),
    API_ID,
    API_HASH
)


# ============================================================
# GLOBAL STATE
# ============================================================

MONITORED_CHAT_IDS = set()
MONITORED_CHAT_NAMES = {}

STATE = {
    "sent_urls": []
}


# ============================================================
# STATE
# ============================================================

def load_state():
    global STATE

    try:
        if STATE_FILE.exists():
            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:
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
        print(f"⚠️ State save error: {e}")


# ============================================================
# URL EXTRACTION
# ============================================================

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
        url = url.rstrip(
            ".,;:!?)]}\"'"
        )

        if url not in result:
            result.append(url)

    return result


# ============================================================
# PRICE EXTRACTION
# ============================================================

def extract_deal_price(text):
    if not text:
        return None

    # Most reliable patterns first
    patterns = [
        r"(?:deal\s*price|deal\s*at)"
        r"\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:offer\s*price|offer\s*at)"
        r"\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:sale\s*price|sale\s*at)"
        r"\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:current\s*price)"
        r"\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:buy\s*at|buy\s*for)"
        r"\s*[:\-]?\s*₹\s*([\d,]+)",

        r"(?:now|now\s*at)"
        r"\s*[:\-]?\s*₹\s*([\d,]+)",
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

    # Generic ₹ prices
    prices = re.findall(
        r"₹\s*([\d,]+)",
        text
    )

    values = []

    for price in prices:
        try:
            values.append(
                int(
                    price.replace(",", "")
                )
            )
        except Exception:
            pass

    if values:
        valid = [
            p for p in values
            if p > MIN_PRICE
        ]

        if valid:
            return min(valid)

        return min(values)

    # Rs / INR fallback
    prices = re.findall(
        r"(?:INR|Rs\.?|Rs)\s*([\d,]+)",
        text,
        re.IGNORECASE
    )

    values = []

    for price in prices:
        try:
            values.append(
                int(
                    price.replace(",", "")
                )
            )
        except Exception:
            pass

    if values:
        valid = [
            p for p in values
            if p > MIN_PRICE
        ]

        if valid:
            return min(valid)

        return min(values)

    return None


# ============================================================
# PRODUCT TITLE
# ============================================================

def extract_product_title(text):
    if not text:
        return "Unknown Product"

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    ignored = [
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
        r"^buy\s*now",
        r"^shop\s*now",
        r"^click\s*here",
    ]

    candidates = []

    for line in lines:
        if len(line) < 5:
            continue

        skip = False

        for pattern in ignored:
            if re.search(
                pattern,
                line,
                re.IGNORECASE
            ):
                skip = True
                break

        if not skip:
            candidates.append(line)

    if not candidates:
        return "Unknown Product"

    title = candidates[0]

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
        title = title[:250].rsplit(
            " ",
            1
        )[0]

    return title


# ============================================================
# DUPLICATE CONTROL
# ============================================================

def already_sent(url):
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

    # Keep state file manageable
    if len(STATE["sent_urls"]) > 5000:
        STATE["sent_urls"] = (
            STATE["sent_urls"][-5000:]
        )

    save_state()


# ============================================================
# AUTO DISCOVER TELEGRAM BROADCAST CHANNELS
# ============================================================

async def discover_channels():
    global MONITORED_CHAT_IDS
    global MONITORED_CHAT_NAMES

    try:
        dialogs = await client.get_dialogs()

        ids = set()
        names = {}

        for dialog in dialogs:
            entity = dialog.entity

            # Only broadcast channels
            if not getattr(
                entity,
                "broadcast",
                False
            ):
                continue

            chat_id = entity.id

            ids.add(chat_id)

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
                names[chat_id] = f"@{username}"
            else:
                names[chat_id] = (
                    title or str(chat_id)
                )

        old_ids = MONITORED_CHAT_IDS

        MONITORED_CHAT_IDS = ids
        MONITORED_CHAT_NAMES = names

        print(
            f"📡 Telegram sources: {len(ids)}"
        )

        new_channels = ids - old_ids

        for chat_id in new_channels:
            print(
                f"➕ NEW SOURCE | "
                f"{names.get(chat_id, chat_id)}"
            )

    except Exception as e:
        print(
            f"❌ Channel discovery error: {e}"
        )


# ============================================================
# VALIDATION RESULT
# ============================================================

def normalize_validation_result(result):
    status = None
    historical_low = None

    if isinstance(result, dict):
        status = result.get("status")

        historical_low = (
            result.get("historical_low")
            or result.get("lowest")
            or result.get("lowest_price")
        )

    elif isinstance(result, tuple):
        if len(result) >= 1:
            status = result[0]

        if len(result) >= 2:
            historical_low = result[1]

    elif isinstance(result, str):
        status = result

    return status, historical_low


# ============================================================
# SEND DEAL
# ============================================================

async def send_deal(
    product_title,
    deal_price,
    historical_low,
    status,
    source,
    url
):
    if status == "NEW_LOW":
        heading = "🚨 NEW ALL-TIME LOW"
    else:
        heading = "🔥 NEAR HISTORICAL LOW"

    message = (
        f"{heading}\n\n"
        f"📦 {product_title}\n"
        f"💰 Deal Price: ₹{deal_price:,}\n"
        f"📉 Historical Low: ₹{historical_low:,}\n"
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
            f"{source} | "
            f"{product_title}"
        )

        mark_sent(url)

    except Exception as e:
        print(
            f"❌ Telegram send error: {e}"
        )


# ============================================================
# PROCESS + VALIDATE DEAL
# ============================================================

async def process_deal(
    text,
    source
):
    if not text:
        return

    urls = extract_urls(text)

    if not urls:
        return

    deal_price = extract_deal_price(text)

    if not deal_price:
        print(
            f"⏭️ SKIP | No price | {source}"
        )
        return

    if deal_price <= MIN_PRICE:
        print(
            f"⏭️ SKIP | "
            f"₹{deal_price:,} <= "
            f"₹{MIN_PRICE:,} | "
            f"{source}"
        )
        return

    product_title = extract_product_title(
        text
    )

    for url in urls:

        if already_sent(url):
            print(
                f"⏭️ DUPLICATE | {url}"
            )
            continue

        print(
            f"🔎 VALIDATING | "
            f"{product_title} | "
            f"₹{deal_price:,} | "
            f"{source}"
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
                f"❌ Validator error | {e}"
            )
            continue

        status, historical_low = (
            normalize_validation_result(
                result
            )
        )

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
                f"Historical low missing | "
                f"{product_title}"
            )
            continue

        await send_deal(
            product_title,
            deal_price,
            historical_low,
            status,
            source,
            url
        )


# ============================================================
# TELEGRAM NEW MESSAGE
# ============================================================

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
            f"📥 TELEGRAM | {source}"
        )

        await process_deal(
            text,
            source
        )

    except Exception as e:
        print(
            f"❌ New message error: {e}"
        )


# ============================================================
# TELEGRAM EDITED MESSAGE
# ============================================================

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
            f"✏️ EDITED | {source}"
        )

        await process_deal(
            text,
            source
        )

    except Exception as e:
        print(
            f"❌ Edited message error: {e}"
        )


# ============================================================
# CHANNEL REFRESH LOOP
# ============================================================

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
                f"❌ Source refresh error: {e}"
            )


# ============================================================
# HEARTBEAT
# ============================================================

async def heartbeat_loop():
    while True:
        try:
            await asyncio.sleep(
                HEARTBEAT_SECONDS
            )

            print("\n" + "=" * 45)
            print("💓 LOOT HUNTER ALIVE")
            print(
                f"📡 Telegram Sources: "
                f"{len(MONITORED_CHAT_IDS)}"
            )
            print(
                "🌐 Web Sources: "
                "PriceHistory + PriceTrail + Buyhatke"
            )
            print(
                f"📤 Sent Deals: "
                f"{len(STATE.get('sent_urls', []))}"
            )
            print(
                f"🎯 Destination: {DESTINATION}"
            )
            print("=" * 45)

        except asyncio.CancelledError:
            break

        except Exception as e:
            print(
                f"❌ Heartbeat error: {e}"
            )


# ============================================================
# WEB DEAL SCANNER
# ============================================================

async def web_scanner_loop():
    while True:
        try:
            await asyncio.sleep(
                WEB_SCAN_SECONDS
            )

            print(
                "\n🌐 WEB SCAN STARTED"
            )

            deals = await asyncio.to_thread(
                get_all_web_deals
            )

            if not deals:
                print(
                    "🌐 No web deals found."
                )
                continue

            print(
                f"🌐 Web candidates: "
                f"{len(deals)}"
            )

            for deal in deals:
                try:
                    title = deal.get(
                        "title",
                        "Unknown Product"
                    )

                    url = deal.get("url")

                    price = deal.get("price")

                    source = deal.get(
                        "source",
                        "Web"
                    )

                    if not url or not price:
                        continue

                    try:
                        price = int(
                            str(price)
                            .replace(",", "")
                            .replace("₹", "")
                            .strip()
                        )
                    except Exception:
                        continue

                    if price <= MIN_PRICE:
                        continue

                    if already_sent(url):
                        continue

                    validation_text = (
                        f"{title}\n"
                        f"₹{price}\n"
                        f"{url}"
                    )

                    await process_deal(
                        validation_text,
                        source
                    )

                except Exception as e:
                    print(
                        f"❌ Web deal error: {e}"
                    )

        except asyncio.CancelledError:
            break

        except Exception as e:
            print(
                f"❌ Web scanner error: {e}"
            )


# ============================================================
# MAIN
# ============================================================

async def main():

    load_state()

    print(
        "🚀 Starting Loot Hunter..."
    )

    await client.start()

    me = await client.get_me()

    username = getattr(
        me,
        "username",
        None
    )

    display_name = (
        username
        if username
        else getattr(
            me,
            "first_name",
            "Unknown"
        )
    )

    print(
        f"✅ Telegram connected as: "
        f"{display_name}"
    )

    # --------------------------------------------------------
    # Destination check
    # --------------------------------------------------------

    try:

        destination = await client.get_entity(
            DESTINATION
        )

        destination_name = getattr(
            destination,
            "title",
            DESTINATION
        )

        print(
            f"🎯 Destination OK: "
            f"{destination_name}"
        )

    except Exception as e:

        print(
            f"❌ Destination error: {e}"
        )

        return

    # --------------------------------------------------------
    # Initial source discovery
    # --------------------------------------------------------

    await discover_channels()

    # --------------------------------------------------------
    # Background loops
    # --------------------------------------------------------

    asyncio.create_task(
        channel_refresh_loop()
    )

    asyncio.create_task(
        heartbeat_loop()
    )

    asyncio.create_task(
        web_scanner_loop()
    )

    # --------------------------------------------------------
    # Startup
    # --------------------------------------------------------

    print("")
    print("=" * 50)
    print("🚀 LOOT HUNTER RUNNING")
    print("=" * 50)
    print("📡 Telegram: AUTO DISCOVERY")
    print(
        "🌐 Web: PriceHistory / PriceTrail / Buyhatke"
    )
    print(
        f"💰 Minimum Price: ₹{MIN_PRICE:,}"
    )
    print("📉 Validation: Historical Low")
    print("🚨 NEW_LOW: ON")
    print("🔥 NEAR_LOW: ON")
    print(
        f"📤 Output: {DESTINATION}"
    )
    print("=" * 50)

    await client.run_until_disconnected()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "🛑 Stopped manually."
        )

    except Exception as e:

        print(
            f"💥 Fatal error: {e}"
        )