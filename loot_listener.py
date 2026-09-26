import os
import re
import json
import asyncio
import traceback
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from deal_validator import validate_deal
from deal_sources import get_all_web_deals


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "")

# Real deals will be sent here
DESTINATION = "lootersAmer"

# Logs / diagnostics will be sent here
# Example: @loot_hunter_logs
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "@YOUR_LOG_CHANNEL")

MIN_PRICE = 1000

CHANNEL_REFRESH_SECONDS = 60
HEARTBEAT_SECONDS = 60
WEB_SCAN_SECONDS = 300

STATE_FILE = "deal_state.json"


# =========================================================
# TELEGRAM CLIENT
# =========================================================

client = TelegramClient(
    StringSession(TG_SESSION),
    API_ID,
    API_HASH
)


# =========================================================
# STATE
# =========================================================

processed_urls = set()


def load_state():
    global processed_urls

    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            processed_urls = set(data.get("processed_urls", []))

            print(
                f"📦 Loaded state | "
                f"{len(processed_urls)} processed URLs"
            )

    except Exception as e:
        print(f"⚠️ State load error: {e}")


def save_state():
    try:
        data = {
            "processed_urls": list(processed_urls)[-5000:]
        }

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        print(f"⚠️ State save error: {e}")


# =========================================================
# LOGGING
# =========================================================

async def send_log(message):
    """
    Send diagnostic log to Telegram logs channel.
    Also print it in Railway logs.
    """

    print(message)

    try:
        if LOG_CHANNEL and "YOUR_LOG_CHANNEL" not in LOG_CHANNEL:
            await client.send_message(
                LOG_CHANNEL,
                message,
                link_preview=False
            )

    except Exception as e:
        print(f"⚠️ Telegram log send failed: {e}")


async def log_info(message):
    await send_log(f"ℹ️ {message}")


async def log_error(message):
    await send_log(f"🚨 ERROR\n{message}")


async def log_heartbeat(message):
    await send_log(f"💓 HEARTBEAT\n{message}")


# =========================================================
# URL EXTRACTION
# =========================================================

URL_RE = re.compile(
    r"https?://[^\s<>\"]+",
    re.IGNORECASE
)


def extract_urls(text):
    if not text:
        return []

    urls = URL_RE.findall(text)

    cleaned = []

    for url in urls:
        url = url.rstrip(".,);]}>'\"")

        if url not in cleaned:
            cleaned.append(url)

    return cleaned


# =========================================================
# PRICE EXTRACTION
# =========================================================

def extract_deal_price(text):
    if not text:
        return None

    patterns = [

        # Deal Price: ₹1,499
        r"(?:deal\s*price|deal\s*at)\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+)",

        # Offer Price
        r"(?:offer\s*price|offer)\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+)",

        # Sale Price
        r"(?:sale\s*price)\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+)",

        # Current Price
        r"(?:current\s*price)\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+)",

        # Buy At
        r"(?:buy\s*at|now\s*at)\s*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+)",

        # ₹1499 / Rs 1499 / INR 1499
        r"(?:₹|rs\.?|inr)\s*([\d,]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            try:
                price = int(match.group(1).replace(",", ""))

                if price > 0:
                    return price

            except Exception:
                pass

    return None


# =========================================================
# TITLE EXTRACTION
# =========================================================

def extract_product_title(text):
    if not text:
        return None

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not lines:
        return None

    bad_prefixes = (
        "http://",
        "https://",
        "deal price",
        "offer price",
        "sale price",
        "current price",
        "buy at",
        "mrp",
        "discount",
        "coupon"
    )

    candidates = []

    for line in lines:

        low = line.lower()

        if low.startswith(bad_prefixes):
            continue

        if "₹" in line and len(line) < 80:
            continue

        if re.search(r"https?://", line):
            continue

        candidates.append(line)

    if not candidates:
        return lines[0][:250]

    title = candidates[0]

    return title[:250]


# =========================================================
# VALIDATOR RESULT NORMALIZER
# =========================================================

def normalize_validation_result(result):

    status = "UNKNOWN"
    historical_low = None
    reason = "Validator returned no reason"

    if isinstance(result, dict):

        status = result.get("status", "UNKNOWN")

        historical_low = result.get(
            "historical_low",
            result.get("lowest")
        )

        reason = (
            result.get("reason")
            or result.get("reject_reason")
            or result.get("message")
            or reason
        )

    elif isinstance(result, tuple):

        if len(result) >= 1:
            status = result[0]

        if len(result) >= 2:
            historical_low = result[1]

        if len(result) >= 3:
            reason = result[2]

    elif isinstance(result, str):

        status = result
        reason = result

    return status, historical_low, reason


# =========================================================
# REJECT LOGGER
# =========================================================

async def reject(
    reason,
    source="UNKNOWN",
    product=None,
    price=None,
    url=None,
    status="REJECT"
):

    message = (
        "❌ REJECT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📝 Reason: {reason}\n"
        f"📊 Status: {status}\n"
        f"📢 Source: {source}\n"
        f"📦 Product: {product or 'N/A'}\n"
        f"💰 Price: ₹{price if price else 'N/A'}\n"
        f"🔗 URL: {url or 'N/A'}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    await send_log(message)


# =========================================================
# SEND ACCEPTED DEAL
# =========================================================

async def send_deal(
    source,
    product,
    price,
    historical_low,
    url,
    status
):

    if status == "NEW_LOW":

        validation_text = (
            "🔥 NEW ALL-TIME LOW\n"
            f"📉 Historical Low: ₹{historical_low:,}"
        )

    else:

        validation_text = (
            "🟢 NEAR HISTORICAL LOW\n"
            f"📉 Historical Low: ₹{historical_low:,}"
        )

    alert = (
        "🔥 LOOT DEAL FOUND\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📢 Source: {source}\n"
        f"📦 Product: {product}\n"
        f"💰 Price: ₹{price:,}\n"
        f"{validation_text}\n"
        f"🔗 {url}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    await client.send_message(
        DESTINATION,
        alert,
        link_preview=False
    )

    await send_log(
        "✅ ACCEPTED\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📢 Source: {source}\n"
        f"📦 Product: {product}\n"
        f"💰 Price: ₹{price:,}\n"
        f"📉 Historical Low: ₹{historical_low:,}\n"
        f"📊 Status: {status}\n"
        f"🔗 {url}\n"
        "━━━━━━━━━━━━━━━━━━"
    )


# =========================================================
# PROCESS DEAL
# =========================================================

async def process_deal(
    text,
    source="UNKNOWN"
):

    if not text:
        await reject(
            "EMPTY_MESSAGE",
            source=source
        )
        return

    urls = extract_urls(text)

    if not urls:

        await reject(
            "NO_PRODUCT_URL_FOUND",
            source=source
        )

        return

    product = extract_product_title(text)

    if not product:

        await reject(
            "PRODUCT_TITLE_NOT_FOUND",
            source=source,
            url=urls[0]
        )

        return

    price = extract_deal_price(text)

    if price is None:

        await reject(
            "DEAL_PRICE_NOT_FOUND",
            source=source,
            product=product,
            url=urls[0]
        )

        return

    if price <= MIN_PRICE:

        await reject(
            f"PRICE_TOO_LOW_OR_SMALL_DEAL | Minimum allowed: ₹{MIN_PRICE + 1}",
            source=source,
            product=product,
            price=price,
            url=urls[0]
        )

        return

    url = urls[0]

    # Duplicate check
    if url in processed_urls:

        await reject(
            "DUPLICATE_URL",
            source=source,
            product=product,
            price=price,
            url=url
        )

        return

    print(
        f"🔎 VALIDATING | "
        f"{product[:80]} | ₹{price} | {url}"
    )

    try:

        result = await asyncio.to_thread(
            validate_deal,
            product,
            url,
            price
        )

        status, historical_low, reason = (
            normalize_validation_result(result)
        )

    except Exception as e:

        await reject(
            f"VALIDATOR_ERROR: {type(e).__name__}: {e}",
            source=source,
            product=product,
            price=price,
            url=url,
            status="ERROR"
        )

        return

    # -----------------------------------------------------
    # ACCEPT ONLY GENUINE LOWS
    # -----------------------------------------------------

    if status not in ("NEW_LOW", "NEAR_LOW"):

        await reject(
            reason or f"VALIDATION_FAILED: {status}",
            source=source,
            product=product,
            price=price,
            url=url,
            status=status
        )

        return

    if historical_low is None:

        await reject(
            "HISTORICAL_LOW_MISSING",
            source=source,
            product=product,
            price=price,
            url=url,
            status=status
        )

        return

    # Mark processed only after successful validation
    processed_urls.add(url)
    save_state()

    await send_deal(
        source=source,
        product=product,
        price=price,
        historical_low=historical_low,
        url=url,
        status=status
    )


# =========================================================
# DISCOVER ALL JOINED BROADCAST CHANNELS
# =========================================================

async def discover_channels():

    channels = []

    try:

        dialogs = await client.get_dialogs()

        for dialog in dialogs:

            entity = dialog.entity

            # Broadcast channel
            if getattr(entity, "broadcast", False):

                channels.append(entity)

        return channels

    except Exception as e:

        await log_error(
            f"CHANNEL DISCOVERY FAILED\n"
            f"{type(e).__name__}: {e}"
        )

        return []


# =========================================================
# CHANNEL REFRESH LOOP
# =========================================================

async def channel_refresh_loop():

    previous_ids = set()

    while True:

        try:

            channels = await discover_channels()

            current_ids = {
                channel.id
                for channel in channels
            }

            new_channels = current_ids - previous_ids

            if new_channels:

                names = []

                for channel in channels:

                    if channel.id in new_channels:

                        username = getattr(
                            channel,
                            "username",
                            None
                        )

                        title = getattr(
                            channel,
                            "title",
                            "Unknown"
                        )

                        names.append(
                            f"{title}"
                            f"{' @' + username if username else ''}"
                        )

                await log_info(
                    "🆕 NEW CHANNELS DISCOVERED\n"
                    + "\n".join(
                        f"• {name}"
                        for name in names
                    )
                )

            previous_ids = current_ids

            print(
                f"📡 Channels discovered: "
                f"{len(channels)}"
            )

        except Exception as e:

            await log_error(
                f"CHANNEL REFRESH ERROR\n"
                f"{type(e).__name__}: {e}"
            )

        await asyncio.sleep(
            CHANNEL_REFRESH_SECONDS
        )


# =========================================================
# HEARTBEAT
# =========================================================

async def heartbeat_loop():

    while True:

        try:

            channels = await discover_channels()

            me = await client.get_me()

            username = (
                getattr(me, "username", None)
                or getattr(me, "first_name", None)
                or "Unknown"
            )

            await log_heartbeat(
                f"Bot: @{username}\n"
                f"📡 Broadcast Channels: {len(channels)}\n"
                f"📦 Processed URLs: {len(processed_urls)}\n"
                f"🎯 Destination: {DESTINATION}\n"
                f"📝 Log Channel: {LOG_CHANNEL}\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

        except Exception as e:

            await log_error(
                f"HEARTBEAT ERROR\n"
                f"{type(e).__name__}: {e}"
            )

        await asyncio.sleep(
            HEARTBEAT_SECONDS
        )


# =========================================================
# WEB DEAL SCANNER
# =========================================================

async def web_scan_loop():

    while True:

        try:

            await log_info(
                "🌐 WEB SCAN STARTED\n"
                "Sources: PriceHistory / PriceTrail / Buyhatke"
            )

            deals = await asyncio.to_thread(
                get_all_web_deals
            )

            if not deals:

                await log_info(
                    "🌐 WEB SCAN COMPLETE\n"
                    "No deals returned by web sources."
                )

            else:

                await log_info(
                    f"🌐 WEB SCAN COMPLETE\n"
                    f"Found: {len(deals)} candidate deals"
                )

                for deal in deals:

                    try:

                        text = deal.get("text", "")

                        source = deal.get(
                            "source",
                            "WEB"
                        )

                        await process_deal(
                            text,
                            source=source
                        )

                    except Exception as e:

                        await log_error(
                            f"WEB DEAL PROCESS ERROR\n"
                            f"{type(e).__name__}: {e}"
                        )

        except Exception as e:

            await log_error(
                f"WEB SCANNER ERROR\n"
                f"{type(e).__name__}: {e}\n"
                f"{traceback.format_exc()}"
            )

        await asyncio.sleep(
            WEB_SCAN_SECONDS
        )


# =========================================================
# TELEGRAM NEW MESSAGE
# =========================================================

@client.on(events.NewMessage)
async def new_message_handler(event):

    try:

        chat = await event.get_chat()

        # Only broadcast channels
        if not getattr(chat, "broadcast", False):
            return

        source = (
            f"@{chat.username}"
            if getattr(chat, "username", None)
            else getattr(
                chat,
                "title",
                "Telegram Channel"
            )
        )

        text = event.raw_text or ""

        print(
            f"📨 NEW MESSAGE | {source}"
        )

        await process_deal(
            text,
            source=source
        )

    except Exception as e:

        await log_error(
            f"NEW MESSAGE HANDLER ERROR\n"
            f"{type(e).__name__}: {e}"
        )


# =========================================================
# TELEGRAM EDITED MESSAGE
# =========================================================

@client.on(events.MessageEdited)
async def edited_message_handler(event):

    try:

        chat = await event.get_chat()

        if not getattr(chat, "broadcast", False):
            return

        source = (
            f"@{chat.username}"
            if getattr(chat, "username", None)
            else getattr(
                chat,
                "title",
                "Telegram Channel"
            )
        )

        text = event.raw_text or ""

        print(
            f"✏️ EDITED MESSAGE | {source}"
        )

        await process_deal(
            text,
            source=source
        )

    except Exception as e:

        await log_error(
            f"EDITED MESSAGE HANDLER ERROR\n"
            f"{type(e).__name__}: {e}"
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    if not API_ID:
        raise RuntimeError(
            "TG_API_ID missing"
        )

    if not API_HASH:
        raise RuntimeError(
            "TG_API_HASH missing"
        )

    if not TG_SESSION:
        raise RuntimeError(
            "TG_SESSION missing"
        )

    load_state()

    print("🚀 Starting Loot Hunter...")

    await client.start()

    me = await client.get_me()

    username = (
        getattr(me, "username", None)
        or getattr(me, "first_name", None)
        or "Unknown"
    )

    print(
        f"✅ Telegram connected as: {username}"
    )

    await log_info(
        "🚀 LOOT HUNTER STARTED\n"
        f"👤 Telegram: {username}\n"
        f"🎯 Deals: {DESTINATION}\n"
        f"📝 Logs: {LOG_CHANNEL}\n"
        f"💰 Minimum Price: ₹{MIN_PRICE + 1}\n"
        "📡 Telegram Sources: AUTO-DISCOVERY\n"
        "🌐 Web Sources: PriceHistory / PriceTrail / Buyhatke"
    )

    channels = await discover_channels()

    await log_info(
        f"📡 INITIAL CHANNEL DISCOVERY\n"
        f"Found {len(channels)} broadcast channels."
    )

    await asyncio.gather(
        channel_refresh_loop(),
        heartbeat_loop(),
        web_scan_loop(),
        client.run_until_disconnected()
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print("🛑 Stopped by user.")

    except Exception as e:

        print(
            f"🚨 FATAL ERROR: "
            f"{type(e).__name__}: {e}"
        )

        traceback.print_exc()