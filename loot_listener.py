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
        print("STATE | no state file found")
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

        print(
            "STATE LOADED | "
            f"processed={len(processed_urls)}"
        )

    except Exception as e:
        print(
            "STATE LOAD ERROR:",
            type(e).__name__,
            str(e),
        )

        processed_urls = set()


def save_state():
    try:
        temp_file = f"{STATE_FILE}.tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                list(processed_urls),
                f,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            temp_file,
            STATE_FILE,
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
# PRICE NORMALIZATION
# ============================================================

def normalize_price(value):
    if value is None:
        return None

    try:
        value = str(value).strip()

        value = value.replace(
            ",",
            "",
        )

        value = value.replace(
            "₹",
            "",
        )

        value = re.sub(
            r"\bINR\b",
            "",
            value,
            flags=re.IGNORECASE,
        )

        value = re.sub(
            r"\bRs\.?\b",
            "",
            value,
            flags=re.IGNORECASE,
        )

        value = value.strip()

        match = re.search(
            r"\d+(?:\.\d+)?",
            value,
        )

        if not match:
            return None

        price = float(
            match.group(0)
        )

        if price <= 0:
            return None

        return price

    except Exception:
        return None


# ============================================================
# PRICE EXTRACTION
# ============================================================

def extract_deal_price(text):
    """
    Robust Telegram deal-price extraction.

    Supported examples:

        ₹52,999
        ₹ 52,999
        Rs 52,999
        Rs. 52,999
        INR 52,999

        Deal Price: ₹52,999
        Deal at ₹52,999
        Deal @ ₹52,999
        Deal @ 52,999

        Offer Price: ₹52,999
        Current Price: ₹52,999
        Sale Price: ₹52,999

        Buy at ₹52,999
        Now at ₹52,999

        @52,999
        @ 52,999
        @ ₹52,999
        @ Rs 52,999
        @ INR 52,999

        52,999/-
        52,999 only
    """

    if not text:
        return None

    text = str(text)

    # --------------------------------------------------------
    # Remove URLs from price scanning.
    #
    # This prevents numbers such as:
    # /dp/B0F8Q96N8G
    # tag=123456
    # etc. from interfering.
    # --------------------------------------------------------

    scan_text = URL_PATTERN.sub(
        " ",
        text,
    )

    # --------------------------------------------------------
    # Normalize common spacing
    # --------------------------------------------------------

    scan_text = re.sub(
        r"[ \t]+",
        " ",
        scan_text,
    )

    # --------------------------------------------------------
    # Ordered patterns
    #
    # Most specific patterns first.
    # --------------------------------------------------------

    patterns = [

        # Deal Price / Deal At
        (
            "deal_price",
            r"(?:deal\s*price|deal\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Deal @ 52999
        (
            "deal_at_symbol",
            r"deal\s*@\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Offer Price / Offer
        (
            "offer_price",
            r"(?:offer\s*price|offer)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Sale Price
        (
            "sale_price",
            r"sale\s*price"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Current Price
        (
            "current_price",
            r"current\s*price"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Buy At / Now At
        (
            "buy_now_price",
            r"(?:buy\s*at|now\s*at)"
            r"\s*[:\-@]?\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # @52,999
        (
            "at_price",
            r"@\s*"
            r"(?:₹|rs\.?|inr)?\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # Explicit currency
        (
            "currency_price",
            r"(?:₹|rs\.?|inr)"
            r"\s*"
            r"([\d,]+(?:\.\d+)?)"
        ),

        # 52,999/-
        (
            "slash_price",
            r"\b([\d,]{4,})\s*/-"
        ),

        # 52,999 only
        (
            "only_price",
            r"\b([\d,]{4,})\s+only\b"
        ),
    ]

    for pattern_name, pattern in patterns:

        matches = re.finditer(
            pattern,
            scan_text,
            re.IGNORECASE,
        )

        for match in matches:
            price = normalize_price(
                match.group(1)
            )

            if price is None:
                continue

            # ------------------------------------------------
            # Ignore obvious unrealistic tiny values.
            # The listener itself doesn't decide final
            # eligibility; validator does that.
            # ------------------------------------------------

            if price < 1:
                continue

            print(
                "PRICE EXTRACTED | "
                f"method={pattern_name} | "
                f"price=₹{price:.0f}"
            )

            return price

    # --------------------------------------------------------
    # Last-resort fallback:
    #
    # Find a standalone 4+ digit number in non-URL text.
    #
    # This is deliberately conservative and avoids blindly
    # taking random small numbers.
    # --------------------------------------------------------

    fallback_candidates = re.findall(
        r"(?<![\w])"
        r"(\d{1,3}(?:,\d{3})+|\d{4,})"
        r"(?![\w])",
        scan_text,
    )

    for candidate in fallback_candidates:

        price = normalize_price(
            candidate
        )

        if price is None:
            continue

        # Avoid years and tiny incidental numbers.
        if price < 1000:
            continue

        print(
            "PRICE EXTRACTED | "
            "method=fallback_number | "
            f"price=₹{price:.0f}"
        )

        return price

    print(
        "PRICE EXTRACTION FAILED | "
        "No usable price found in message"
    )

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
    """
    Preserve all important validator fields.
    """

    if isinstance(result, dict):

        return {
            "status": result.get(
                "status",
                "UNKNOWN",
            ),

            "current_price": result.get(
                "current_price"
            ),

            "historical_low": result.get(
                "historical_low"
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

            "source": result.get(
                "source"
            ),

            "url": result.get(
                "url"
            ),

            "pricehistory_url": result.get(
                "pricehistory_url"
            ),

            "pricehistory_title": result.get(
                "pricehistory_title"
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

            "reason": (
                result[2]
                if len(result) > 2
                else "Validator returned no reason"
            ),

            "current_price": (
                result[3]
                if len(result) > 3
                else None
            ),

            "category": None,
        }

    if isinstance(result, str):

        return {
            "status": result,
            "current_price": None,
            "historical_low": None,
            "category": None,
            "reason": "Validator returned no reason",
        }

    return {
        "status": "UNKNOWN",
        "current_price": None,
        "historical_low": None,
        "category": None,
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
    if price is None:
        display_price = "N/A"
    else:
        try:
            display_price = f"{float(price):.0f}"
        except Exception:
            display_price = str(price)

    message = (
        "❌ REJECT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📝 Reason: {reason}\n"
        f"📊 Status: {status}\n"
        f"📢 Source: {source}\n"
        f"📦 Product: {product}\n"
        f"💰 Price: ₹{display_price}\n"
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
        f"💰 Deal Price: ₹{float(price):.0f}\n"
    )

    if historical_low is not None:
        message += (
            f"📉 Historical Low: "
            f"₹{float(historical_low):.0f}\n"
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
            "✅ ACCEPTED | "
            f"{status} | "
            f"{product} | "
            f"₹{float(price):.0f} | "
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

    product = extract_product_title(
        text
    )

    await log_info(
        "📨 DEAL RECEIVED | "
        f"source={source} | "
        f"product={product} | "
        f"urls={len(urls)}"
    )

    # --------------------------------------------------------
    # Extract local message price
    # --------------------------------------------------------

    price = extract_deal_price(
        text
    )

    if price is not None:

        await log_info(
            "💰 MESSAGE PRICE FOUND | "
            f"price=₹{price:.0f} | "
            f"product={product}"
        )

    else:

        await log_info(
            "💰 MESSAGE PRICE NOT FOUND | "
            "validator/web recovery required | "
            f"product={product}"
        )

    # --------------------------------------------------------
    # Process URLs
    # --------------------------------------------------------

    for url in urls:

        if url in processed_urls:

            await log_info(
                "⏭️ SKIPPED PROCESSED URL | "
                f"{url}"
            )

            continue

        await log_info(
            "🔎 PROCESSING URL | "
            f"url={url} | "
            f"message_price={price}"
        )

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

        recovered_price = validation.get(
            "current_price"
        )

        historical_low = validation.get(
            "historical_low"
        )

        reason = validation.get(
            "reason",
            "No reason returned",
        )

        # ----------------------------------------------------
        # Detailed validator debug
        # ----------------------------------------------------

        await log_info(
            "🧪 VALIDATOR RESULT | "
            f"status={status} | "
            f"message_price={price} | "
            f"recovered_price={recovered_price} | "
            f"historical_low={historical_low} | "
            f"reason={reason}"
        )

        # ----------------------------------------------------
        # ACCEPT
        # ----------------------------------------------------

        if status in (
            "NEW_LOW",
            "NEAR_LOW",
        ):

            final_price = price

            if final_price is None:
                final_price = recovered_price

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

        reject_price = price

        if reject_price is None:
            reject_price = recovered_price

        await reject(
            reason,
            status,
            source,
            product,
            reject_price,
            url,
        )

        # Rejected URLs are NOT saved.


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

            if username:
                name = f"@{username}"
            else:
                name = (
                    getattr(
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
            raise

        except Exception as e:

            await log_error(
                "Channel refresh error: "
                f"{type(e).__name__}: {e}"
            )


# ============================================================
# HEARTBEAT LOOP
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
                str(e),
            )


# ============================================================
# WEB SCANNER LOOP
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
