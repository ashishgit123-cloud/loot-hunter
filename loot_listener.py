import os
import asyncio
import re

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

load_dotenv()

# =========================
# CONFIG
# =========================

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SOURCE_CHANNEL = os.environ.get(
    "SOURCE_CHANNEL",
    "@lootdeals2005"
)
TG_SESSION = os.environ["TG_SESSION"]

# =========================
# TELEGRAM CLIENT
# =========================

client = TelegramClient(
    StringSession(TG_SESSION),
    API_ID,
    API_HASH
)

# Prevent duplicate alerts
seen_messages = set()


# =========================
# PRICE EXTRACTION
# =========================

def extract_prices(text):
    matches = re.findall(
        r"(?:₹|Rs\.?|INR)\s*([\d,]+)",
        text,
        flags=re.IGNORECASE
    )

    prices = []

    for value in matches:
        try:
            prices.append(int(value.replace(",", "")))
        except ValueError:
            pass

    return prices


# =========================
# DEAL FILTER
# =========================

def looks_like_deal(text):

    t = text.lower()
    prices = extract_prices(text)

    # Strong loot keywords
    strong_keywords = [
        "price error",
        "price glitch",
        "pricing error",
        "glitch deal",
        "loot deal",
        "loot",
        "₹1",
        "rs 1",
        "rs. 1",
        "99 only",
        "₹99",
        "rs 99",
        "free",
        "90% off",
        "80% off",
        "90% discount",
        "80% discount"
    ]

    if any(keyword in t for keyword in strong_keywords):
        return True

    # Very low price
    if any(price <= 199 for price in prices):
        return True

    # High discount
    percentages = re.findall(
        r"(\d{2,3})\s*%\s*(?:off|discount)",
        t
    )

    for percentage in percentages:
        if int(percentage) >= 70:
            return True

    return False


# =========================
# NEW MESSAGE HANDLER
# =========================

@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):

    text = event.raw_text or ""

    # Ignore empty posts
    if not text.strip():
        return

    # Prevent duplicate alerts
    message_id = event.id

    if message_id in seen_messages:
        return

    seen_messages.add(message_id)

    # Keep memory under control
    if len(seen_messages) > 5000:
        seen_messages.clear()

    # Apply deal filter
    if not looks_like_deal(text):
        return

    # Build alert
    alert = (
        "🔥🔥 POSSIBLE LOOT DEAL 🔥🔥\n\n"
        f"{text}\n\n"
        "📌 Source: @lootdeals2005\n"
        f"🆔 Post ID: {message_id}"
    )

    # Send to Telegram Saved Messages
    await client.send_message("me", alert)

    print("\n🚨 ALERT SENT TO SAVED MESSAGES")
    print(text)
    print("-" * 60)


# =========================
# MAIN
# =========================

async def main():

    await client.connect()

    if not await client.is_user_authorized():
        raise RuntimeError(
            "Telegram session is not authorized."
        )

    me = await client.get_me()

    print(
        f"✅ Telegram connected as: "
        f"{me.first_name}"
    )

    print(
        f"👀 Listening to "
        f"{SOURCE_CHANNEL} ..."
    )

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())