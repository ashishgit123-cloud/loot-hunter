import os
import asyncio
import re

from dotenv import load_dotenv
from telethon import TelegramClient, events

from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
TG_SESSION = os.environ["TG_SESSION"]

SOURCE_CHANNELS = [
    x.strip()
    for x in os.environ.get(
        "SOURCE_CHANNEL",
        "@lootdeals2005,@pricehistory,@lootersindia"
    ).split(",")
    if x.strip()
]

PRIVATE_CHANNEL_NAMES = [
    "Offerzone 2.0"
]

PRIORITY_KEYWORDS = [
    x.strip().lower()
    for x in os.environ.get(
        "PRIORITY_KEYWORDS",
        "iphone,furniture"
    ).split(",")
    if x.strip()
]

client = TelegramClient(
    StringSession(TG_SESSION),
    API_ID,
    API_HASH,
    connection_retries=None,
    retry_delay=5
)

seen_messages = set()
resolved_private_channels = []


def get_priority_category(text):
    t = text.lower()

    iphone_ignore = [
        "cover", "case", "cable", "charger",
        "screen protector", "tempered glass",
        "back glass", "skin", "sleeve", "adapter",
        "holder", "stand", "lens protector",
        "camera protector", "strap", "replacement",
        "battery", "display", "screen",
        "earphone", "airpods", "watch"
    ]

    furniture_ignore = [
        "cover", "cushion cover", "table cover",
        "mattress", "bedsheet", "curtain", "pillow",
        "cleaner", "cleaning", "polish", "hardware",
        "hinge", "handle", "knob", "screw",
        "bracket", "stand", "mat", "carpet", "rug",
        "lamp", "light", "decor", "decoration",
        "wall art", "clock"
    ]

    for keyword in PRIORITY_KEYWORDS:

        if keyword == "iphone":
            if re.search(r"\biphone\s*(?:11|12|13|14|15|16|17)\b", t):
                if any(word in t for word in iphone_ignore):
                    return None
                return "iphone"

        elif keyword == "furniture":
            furniture_items = [
                "sofa", "couch", "recliner", "bed",
                "wardrobe", "almirah", "dining table",
                "dining chair", "table", "chair",
                "bookshelf", "book shelf", "shoe rack",
                "tv unit", "tv cabinet", "coffee table",
                "side table", "study table", "office chair",
                "computer table", "dresser", "cabinet",
                "drawer", "furniture"
            ]

            if any(item in t for item in furniture_items):
                if any(word in t for word in furniture_ignore):
                    return None
                return "furniture"

    return None


def is_normal_loot(text):
    t = text.lower()

    prices = re.findall(
        r"(?:₹|rs\.?|inr)\s*([\d,]+)",
        t,
        flags=re.IGNORECASE
    )

    prices = [
        int(x.replace(",", ""))
        for x in prices
        if x.replace(",", "").isdigit()
    ]

    strong_words = [
        "price error",
        "price glitch",
        "pricing error",
        "glitch deal",
        "loot deal",
        "loot",
        "free",
        "₹1",
        "rs 1",
        "rs. 1",
        "₹99",
        "rs 99",
        "99 only"
    ]

    if any(word in t for word in strong_words):
        return True

    if any(price <= 199 for price in prices):
        return True

    discounts = re.findall(
        r"(\d{2,3})\s*%\s*(?:off|discount)",
        t
    )

    return any(int(x) >= 70 for x in discounts)


async def resolve_private_channels():
    global resolved_private_channels

    resolved_private_channels = []

    print("🔎 Searching private channels...")

    dialogs = await client.get_dialogs()

    for wanted_name in PRIVATE_CHANNEL_NAMES:
        found = False

        for dialog in dialogs:
            entity = dialog.entity
            title = getattr(entity, "title", "")

            if title and title.strip().lower() == wanted_name.lower():
                resolved_private_channels.append(entity)

                print(
                    f"✅ Private channel found: {title}"
                )

                found = True
                break

        if not found:
            print(
                f"⚠️ Private channel not found: {wanted_name}"
            )

    return resolved_private_channels


async def process_message(event):
    try:
        text = event.raw_text or ""

        if not text.strip():
            return

        chat = await event.get_chat()

        username = getattr(chat, "username", None)
        title = getattr(chat, "title", None)

        if username:
            source = f"@{username}"
        elif title:
            source = title
        else:
            source = "Telegram Channel"

        message_key = (
            getattr(chat, "id", None),
            event.id
        )

        if message_key in seen_messages:
            return

        seen_messages.add(message_key)

        category = get_priority_category(text)

        if category == "iphone":
            header = "📱🔥 IPHONE DEAL 🔥📱"

        elif category == "furniture":
            header = "🛋️🔥 FURNITURE DEAL 🔥🛋️"

        elif is_normal_loot(text):
            header = "🔥🔥 POSSIBLE LOOT DEAL 🔥🔥"

        else:
            return

        alert = (
            f"{header}\n\n"
            f"{text}\n\n"
            f"📌 Source: {source}\n"
            f"🆔 Post ID: {event.id}"
        )

        await client.send_message("me", alert)

        print()
        print("🚨 ALERT SENT")
        print(f"🏷️ Category: {category or 'loot'}")
        print(f"📌 Source: {source}")
        print(text)
        print("-" * 60)

    except Exception as e:
        print(
            f"❌ Handler error: "
            f"{type(e).__name__}: {e}"
        )


async def heartbeat():
    while True:
        print(
            "💚 Listener is alive and monitoring..."
        )
        await asyncio.sleep(60)


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

            # Resolve private channels
            private_channels = (
                await resolve_private_channels()
            )

            # Combine public + private sources
            all_sources = list(SOURCE_CHANNELS)

            all_sources.extend(private_channels)

            print()
            print("👀 Listening to:")

            for source in SOURCE_CHANNELS:
                print(f"   • {source}")

            for source in private_channels:
                print(
                    f"   • {getattr(source, 'title', source)}"
                )

            print()
            print(
                f"🎯 Priority: "
                f"{', '.join(PRIORITY_KEYWORDS)}"
            )

            print("🟢 Listener is running...")

            # Register handler dynamically
            client.add_event_handler(
                process_message,
                events.NewMessage(chats=all_sources)
            )

            await asyncio.gather(
                client.run_until_disconnected(),
                heartbeat()
            )

        except Exception as e:

            print(
                f"❌ Runtime error: "
                f"{type(e).__name__}: {e}"
            )

        print(
            "🔄 Reconnecting in 10 seconds..."
        )

        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())