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
TG_SESSION = os.environ["TG_SESSION"]

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
    API_HASH,
    connection_retries=None,
    retry_delay=5
)

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

    if any(keyword in t for keyword in strong_keywords):
        return True

    if any(price <= 199 for price in prices):
        return True

    percentages = re.findall(
        r"(\d{2,3})\s*%\s*(?:off|discount)",
        t
    )

    for percentage in percentages:
        if int(percentage) >= 70:
            return True

    return False


# =========================
# MESSAGE HANDLER
# =========================

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):

    try:
        text = event.raw_text or ""

        if not text.strip():
            return

        chat = await event.get_chat()

        chat_id = getattr(chat, "id", None)
        username = getattr(chat, "username", None)
        title = getattr(chat, "title", None)

        if username:
            source = f"@{username}"
        elif title:
            source = title
        else:
            source = "Telegram Channel"

        message_key = (
            chat_id,
            event.id
        )

        if message_key in seen_messages:
            return

        seen_messages.add(message_key)

        if len(seen_messages) > 10000:
            seen_messages.clear()

        if not looks_like_deal(text):
            return

        alert = (
            "🔥🔥 POSSIBLE LOOT DEAL 🔥🔥\n\n"
            f"{text}\n\n"
            f"📌 Source: {source}\n"
            f"🆔 Post ID: {event.id}"
        )

        await client.send_message(
            "me",
            alert
        )

        print()
        print("🚨 ALERT SENT")
        print(f"📌 Source: {source}")
        print(f"🆔 Post ID: {event.id}")
        print(text)
        print("-" * 60)

    except Exception as e:
        print(
            f"❌ Handler error: "
            f"{type(e).__name__}: {e}"
        )


# =========================
# MAIN
# =========================

async def main():

    while True:

        try:
            print("🔄 Connecting to Telegram...")

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

            print("👀 Listening to:")

            for channel in SOURCE_CHANNELS:
                print(f"   • {channel}")

            print("🟢 Listener is running...")

            await client.run_until_disconnected()

            print(
                "⚠️ Telegram disconnected. "
                "Reconnecting in 5 seconds..."
            )

        except Exception as e:

            print(
                f"❌ Runtime error: "
                f"{type(e).__name__}: {e}"
            )

            print(
                "🔄 Retrying in 10 seconds..."
            )

        await asyncio.sleep(10)


# =========================
# START
# =========================

if __name__ == "__main__":
    asyncio.run(main())