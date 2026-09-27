# loot_listener.py
# VERSION: 3.0

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


# ============================================================
# VERSION
# ============================================================

VERSION = "3.0"


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "")

DESTINATION = os.getenv(
    "DESTINATION",
    "lootersAmer",
)

LOG_CHANNEL = os.getenv(
    "LOG_CHANNEL",
    "",
)


# ============================================================
# CONFIG
# ============================================================

MIN_PRICE = 1000

CHANNEL_REFRESH_SECONDS = 60
HEARTBEAT_SECONDS = 60
WEB_SCAN_SECONDS = 300

STATE_FILE = "deal_state.json"


# ============================================================
# BASIC CHECK
# ============================================================

if not API_ID:
    raise RuntimeError("TG_API_ID is missing")

if not API_HASH:
    raise RuntimeError("TG_API_HASH is missing")

if not TG_SESSION:
    raise RuntimeError("TG_SESSION is missing")


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    StringSession(TG_SESSION),
    API_ID,
    API_HASH,
)


# ============================================================
# STATE
# ============================================================

processed_urls = set()


def load_state():
    global processed_urls

    if not os.path.exists(STATE_FILE):
        processed_urls = set()
        return

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            processed_urls = set(data)

        elif isinstance(data, dict):
            processed_urls = set(
                data.get(
                    "processed_urls",
                    [],
                )
            )

        else:
            processed_urls = set()

    except Exception as e:
        print(
            "STATE LOAD ERROR:",
            type(e).__name__,
            str(e),
        )
        processed_urls = set()


def save_state():
    try:
        with open(
            STATE_FILE,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                list(processed_urls),
                f,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as e:
        print(
            "STATE SAVE ERROR:",
            type(e).__name__,
            str(e),
        )


# ============================================================
# CHANNEL CACHE
# ============================================================

known_channels = {}


# ============================================================
# URL EXTRACTION
# ============================================================

URL_PATTERN = re.compile(
    r"https?://[^\s<>]+",
    re.IGNORECASE,
)


def extract_urls(text):
    if not text:
        return []

    urls = URL_PATTERN.findall(text)

    cleaned = []

    for url in urls:
        url = url.rstrip(
            ".,!?;:)]}"
        )

        if url:
            cleaned.append(url)

    return list(dict.fromkeys(cleaned))


# ============================================================
# PRICE EXTRACTION
# ============================================================

def extract_deal_price(text):
    """
    Extract price from Telegram deal text.

    Examples:

    ₹52,999
    Rs 52,999
    Rs. 52,999
    INR 52999
    Deal Price: ₹52,999
    Deal at ₹52,999
    Offer Price: ₹52,999
    Now at ₹52,999
    Buy at ₹52,999
    52999/-
    52999 only
    """

    if not text:
        return None

    text = str(text)

    patterns = [
        # Deal Price / Deal At
        (
            r"(?:deal\s*price|deal\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Offer Price / Offer
        (
            r"(?:offer\s*price|offer)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Sale Price
        (
            r"(?:sale\s*price)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Current Price
        (
            r"(?:current\s*price)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Buy At / Now At
        (
            r"(?:buy\s*at|now\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Currency
        (
            r"(?:₹|rs\.?|inr)"
            r"\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # 52999/-
        (
            r"\b([\d,]{4,})\s*/-"
        ),

        # 52999 only
        (
            r"\b([\d,]{4,})\s+only\b"
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if not match:
            continue

        try:
            value = match.group(1)
            value = value.replace(",", "")

            price = float(value)

            if price > 0:
                return price

        except Exception:
            continue

    return None


# ============================================================
# TITLE EXTRACTION
# ============================================================

def extract_product_title(text):
    if not text:
        return "Unknown Product"

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    ignored = {
        "deal",
        "offer",
        "buy now",
        "click here",
        "shop now",
        "limited time",
        "amazon",
        "flipkart",
    }

    for line in lines:

        if len(line) < 4:
            continue

        lower = line.lower()

        if lower in ignored:
            continue

        if line.startswith(
            (
                "http://",
                "https://",
            )
        ):
            continue

        if re.fullmatch(
            r"[\d₹$€£,.\s]+",
            line,
        ):
            continue

        return line[:300]

    if lines:
        return lines[0][:300]

    return "Unknown Product"


# ============================================================
# VALIDATOR RESULT NORMALIZATION
# ============================================================

def normalize_validation_result(result):

    if isinstance(result, dict):
        return {
            "status": result.get(
                "status",
                "UNKNOWN",
            ),
            "historical_low": result.get(
                "historical_low"
            ),
            "current_price": result.get(
                "current_price"
            ),
            "category": result.get(
                "category"
            ),
            "reason": (
                result.get("reason")
                or result.get("reject_reason")
                or result.get("message")
                or "Validator returned no reason"
            ),
            "url": result.get("url"),
            "pricehistory_url": result.get(
                "pricehistory_url"
            ),
        }

    if isinstance(result, tuple):

        return {
            "status": (
                result[0]
                if len(result) > 0
                else "UNKNOWN"
            ),
            "historical_low": (
                result[1]
                if len(result) > 1
                else None
            ),
            "current_price": (
                result[2]
                if len(result) > 2
                else None
            ),
            "reason": (
                result[3]
                if len(result) > 3
                else "Validator returned no reason"
            ),
        }

    if isinstance(result, str):

        return {
            "status": result,
            "historical_low": None,
            "current_price": None,
            "reason": "Validator returned no reason",
        }

    return {
        "status": "UNKNOWN",
        "historical_low": None,
        "current_price": None,
        "reason": "Invalid validator response",
    }


# ============================================================
# LOGGING
# ============================================================

async def send_log(message):

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    final_message = (
        f"[{timestamp}] {message}"
    )

    print(final_message)

    if not LOG_CHANNEL:
        return

    try:
        await client.send_message(
            LOG_CHANNEL,
            final_message,
        )

    except Exception as e:
        print(
            "LOG CHANNEL ERROR:",
            type(e).__name__,
            str(e),
        )


async def log_info(message):
    await send_log(
        f"ℹ️ {message}"
    )


async def log_error(message):
    await send_log(
        f"❌ ERROR: {message}"
    )


async def log_heartbeat():

    await send_log(
        "💓 HEARTBEAT | "
        f"version={VERSION} | "
        f"channels={len(known_channels)} | "
        f"processed={len(processed_urls)} | "
        f"destination={DESTINATION}"
    )


# ============================================================
# REJECT LOG
# ============================================================

async def reject(
    reason,
    status,
    source,
    product,
    price,
    url,
):

    message = (
        "❌ REJECT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📝 Reason: {reason}\n"
        f"📊 Status: {status}\n"
        f"📢 Source: {source}\n"
        f"📦 Product: {product}\n"
        f"💰 Price: ₹"
        f"{price if price is not None else 'N/A'}\n"
        f"🔗 URL: {url}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    await send_log(message)


# ============================================================
# ACCEPTED DEAL
# ============================================================

async def send_deal(
    product,
    price,
    url,
    source,
    validation,
):

    status = validation.get(
        "status",
        "UNKNOWN",
    )

    historical_low = validation.get(
        "historical_low"
    )

    if status == "NEW_LOW":
        headline = "🔥 NEW ALL-TIME LOW"
    else:
        headline = "🟢 NEAR HISTORICAL LOW"

    message = (
        f"{headline}\n\n"
        f"📦 {product}\n\n"
        f"💰 Deal Price: ₹{price:.0f}\n"
    )

    if historical_low is not None:
        message += (
            f"📉 Historical Low: "
            f"₹{historical_low:.0f}\n"
        )

    message += (
        f"📢 Source: {source}\n\n"
        f"🔗 {url}"
    )

    try:

        await client.send_message(
            DESTINATION,
            message,
        )

        await log_info(
            f"✅ ACCEPTED | "
            f"{status} | "
            f"{product} | "
            f"₹{price:.0f} | "
            f"{source}"
        )

        return True

    except Exception as e:

        await log_error(
            "Destination send failed: "
            f"{type(e).__name__}: {e}"
        )

        return False


# ============================================================
# PROCESS DEAL
# ============================================================

async def process_deal(
    text,
    source,
):

    if not text:
        return

    urls = extract_urls(text)

    if not urls:
        return

    product = extract_product_title(text)

    # --------------------------------------------------------
    # LOCAL PRICE
    # --------------------------------------------------------

    price = extract_deal_price(text)

    # --------------------------------------------------------
    # PROCESS EACH URL
    # --------------------------------------------------------

    for url in urls:

        if url in processed_urls:
            continue

        try:

            validation_raw = await asyncio.to_thread(
                validate_deal,
                product,
                price,
                url,
                source,
                text,
            )

            validation = normalize_validation_result(
                validation_raw
            )

        except Exception as e:

            await log_error(
                "Validator exception | "
                f"{type(e).__name__}: {e}\n"
                f"{traceback.format_exc()}"
            )

            continue

        status = validation.get(
            "status",
            "UNKNOWN",
        )

        # ----------------------------------------------------
        # GET FINAL PRICE
        # ----------------------------------------------------

        final_price = price

        if final_price is None:
            final_price = validation.get(
                "current_price"
            )

        # ----------------------------------------------------
        # SILENT LOW PRICE REJECT
        # ----------------------------------------------------

        if (
            final_price is not None
            and final_price <= MIN_PRICE
        ):
            continue

        # ----------------------------------------------------
        # ACCEPTED
        # ----------------------------------------------------

        if status in (
            "NEW_LOW",
            "NEAR_LOW",
        ):

            if final_price is None:

                await reject(
                    "Validator approved status but "
                    "current price was not returned",
                    "PRICE_UNKNOWN",
                    source,
                    product,
                    None,
                    url,
                )

                continue

            sent = await send_deal(
                product,
                final_price,
                url,
                source,
                validation,
            )

            if sent:
                processed_urls.add(url)
                save_state()

            continue

        # ----------------------------------------------------
        # REJECT
        # ----------------------------------------------------

        await reject(
            validation.get(
                "reason",
                "Validator rejected deal",
            ),
            status,
            source,
            product,
            final_price,
            url,
        )


# ============================================================
# CHANNEL DISCOVERY
# ============================================================

async def discover_channels():

    try:

        dialogs = await client.get_dialogs()

        new_channels = 0

        for dialog in dialogs:

            entity = dialog.entity

            if not getattr(
                entity,
                "broadcast",
                False,
            ):
                continue

            channel_id = entity.id

            if channel_id in known_channels:
                continue

            known_channels[channel_id] = entity

            new_channels += 1

            username = getattr(
                entity,
                "username",
                None,
            )

            name = (
                f"@{username}"
                if username
                else getattr(
                    entity,
                    "title",
                    None,
                )
                or str(channel_id)
            )

            await log_info(
                "📢 NEW CHANNEL DISCOVERED: "
                f"{name}"
            )

        if new_channels:

            await log_info(
                "📡 Channel discovery complete | "
                f"total={len(known_channels)}"
            )

    except Exception as e:

        await log_error(
            "Channel discovery failed: "
            f"{type(e).__name__}: {e}"
        )


# ============================================================
# CHANNEL REFRESH
# ============================================================

async def channel_refresh_loop():

    while True:

        try:

            await asyncio.sleep(
                CHANNEL_REFRESH_SECONDS
            )

            await discover_channels()

        except asyncio.CancelledError:
            raise

        except Exception as e:

            await log_error(
                "Channel refresh error: "
                f"{type(e).__name__}: {e}"
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

            await log_heartbeat()

        except asyncio.CancelledError:
            raise

        except Exception as e:

            print(
                "HEARTBEAT ERROR:",
                type(e).__name__,
                e,
            )


# ============================================================
# WEB SCANNER
# ============================================================

async def web_scan_loop():

    while True:

        try:

            await asyncio.sleep(
                WEB_SCAN_SECONDS
            )

            await log_info(
                "🌐 WEB SCAN STARTED"
            )

            candidates = await asyncio.to_thread(
                get_all_web_deals
            )

            if not candidates:

                await log_info(
                    "🌐 WEB SCAN COMPLETE | "
                    "candidates=0"
                )

                continue

            await log_info(
                "🌐 WEB SCAN COMPLETE | "
                f"candidates={len(candidates)}"
            )

            for candidate in candidates:

                if not isinstance(
                    candidate,
                    dict,
                ):
                    continue

                text = candidate.get(
                    "text",
                    "",
                )

                source = candidate.get(
                    "source",
                    "WEB",
                )

                url = candidate.get(
                    "url"
                )

                if url and url not in text:

                    text = (
                        f"{text}\n"
                        f"{url}"
                    )

                await process_deal(
                    text,
                    source,
                )

        except asyncio.CancelledError:
            raise

        except Exception as e:

            await log_error(
                "Web scan error: "
                f"{type(e).__name__}: {e}"
            )


# ============================================================
# TELEGRAM NEW MESSAGE
# ============================================================

@client.on(events.NewMessage)
async def new_message_handler(event):

    try:

        chat = await event.get_chat()

        if not getattr(
            chat,
            "broadcast",
            False,
        ):
            return

        username = getattr(
            chat,
            "username",
            None,
        )

        if username:
            source = f"@{username}"

        else:
            source = getattr(
                chat,
                "title",
                str(chat.id),
            )

        text = event.raw_text or ""

        await process_deal(
            text,
            source,
        )

    except Exception as e:

        await log_error(
            "NewMessage handler error: "
            f"{type(e).__name__}: {e}"
        )


# ============================================================
# TELEGRAM EDITED MESSAGE
# ============================================================

@client.on(events.MessageEdited)
async def edited_message_handler(event):

    try:

        chat = await event.get_chat()

        if not getattr(
            chat,
            "broadcast",
            False,
        ):
            return

        username = getattr(
            chat,
            "username",
            None,
        )

        if username:
            source = f"@{username}"

        else:
            source = getattr(
                chat,
                "title",
                str(chat.id),
            )

        text = event.raw_text or ""

        await process_deal(
            text,
            source,
        )

    except Exception as e:

        await log_error(
            "MessageEdited handler error: "
            f"{type(e).__name__}: {e}"
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    load_state()

    print(
        f"🚀 Loot Hunter v{VERSION} starting..."
    )

    await client.start()

    me = await client.get_me()

    username = getattr(
        me,
        "username",
        None,
    )

    if username:

        display_name = f"@{username}"

    else:

        display_name = getattr(
            me,
            "first_name",
            "Telegram User",
        )

    await log_info(
        f"🚀 Loot Hunter v{VERSION} started | "
        f"Telegram connected as: {display_name}"
    )

    await discover_channels()

    await log_info(
        "👀 Listening to "
        f"{len(known_channels)} broadcast channels"
    )

    tasks = [
        asyncio.create_task(
            channel_refresh_loop()
        ),
        asyncio.create_task(
            heartbeat_loop()
        ),
        asyncio.create_task(
            web_scan_loop()
        ),
    ]

    try:

        await client.run_until_disconnected()

    finally:

        for task in tasks:
            task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "🛑 Loot Hunter stopped"
        )

    except Exception as e:

        print(
            "FATAL ERROR:",
            type(e).__name__,
            str(e),
        )

        traceback.print_exc()

        raise
