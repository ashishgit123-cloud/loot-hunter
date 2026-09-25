import os
import asyncio
import re

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

load_dotenv()

# =========================
# TELEGRAM CONFIG
# =========================

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
TG_SESSION = os.environ["TG_SESSION"]

# Railway variable:
# @lootdeals2005,@pricehistory,@lootersindia

SOURCE_CHANNELS = [
    x.strip()
    for x in os.environ.get(
        "SOURCE_CHANNEL",
        "@lootdeals2005"
    ).split(",")
    if x.strip()
]

# =========================
# TELEGRAM CLIENT
# =========================

client = TelegramClient(
    StringSession(TG_SESSION),
    API_ID,
    API_HASH
)

# Keep track of processed messages
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
            prices.append(
                int(value.replace(",", ""))
            )
        except ValueError:
            pass

    return prices


# =========================
# DEAL FILTER
# =========================

def looks_like_deal(text):
    t = text.lower()

    prices = extract_prices(text)

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

    # Strong loot keywords
    if any(keyword in t for keyword in strong_keywords):
        return True

    # Extremely low price
    if any(price <= 199 for price in prices):
        return True

    # Very high discount
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

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):

    text = event.raw_text or ""

    if not text.strip():
        return

    # Get chat information
    chat = await event.get_chat()

    chat_id = getattr(chat, "id", None)

    username = getattr(
        chat,
        "username",
        None
    )

    title = getattr(
        chat,
        "title",
        None
    )

    # Actual source name
    if username:
        source = f"@{username}"
    elif title:
        source = title
    else:
        source = "Telegram Channel"

    # Unique message identifier
    message_key = (
        chat_id,
        event.id
    )

    # Duplicate protection
    if message_key in seen_messages:
        return

    seen_messages.add(message_key)

    # Prevent unlimited memory growth
    if len(seen_messages) > 10000:
        seen_messages.clear()

    # Check whether this looks like a loot deal
    if not looks_like_deal(text):
        return

    # =========================
    # ALERT
    # =========================

    alert = (
        "🔥🔥 POSSIBLE LOOT DEAL 🔥🔥\n\n"
        f"{text}\n\n"
        f"📌 Source: {source}\n"
        f"🆔 Post ID: {event.id}"
    )

    # Send to Telegram Saved Messages
    await client.send_message(
        "me",
        alert
    )

    print()
    print("🚨 ALERT SENT TO SAVED MESSAGES")
    print(f"📌 Source: {source}")
    print(f"🆔 Message ID: {event.id}")
    print(text)
    print("-" * 60)


# =========================
# MAIN
# =========================

async def main():

    await client.connect()

    # Check Telegram authorization
    if not await client.is_user_authorized():
        raise RuntimeError(
            "Telegram session is not authorized."
        )

    # Get logged-in account
    me = await client.get_me()

    print(
        f"✅ Telegram connected as: "
        f"{me.first_name}"
    )

    # Show all monitored channels
    print(
        "👀 Listening to:"
    )

    for channel in SOURCE_CHANNELS:
        print(f"   • {channel}")

    print()

    # Keep listener running
    await client.run_until_disconnected()


# =========================
# START
# =========================

if __name__ == "__main__":
    asyncio.run(main())