import os
import re
import asyncio

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "@lootdeals2005")
TG_SESSION = os.environ.get("TG_SESSION")

if not TG_SESSION:
    raise RuntimeError("TG_SESSION is missing in Railway Variables")

client = TelegramClient(
    StringSession(TG_SESSION),
    API_ID,
    API_HASH
)


def extract_prices(text):
    prices = re.findall(
        r'(?:₹|Rs\.?|INR)\s*([\d,]+)',
        text,
        flags=re.IGNORECASE
    )
    return [int(p.replace(",", "")) for p in prices]


def looks_like_deal(text):
    t = text.lower()
    prices = ext
        "price error",
        "price error",
        "loot",
        "glitch",
        "₹1",
        "rs 1",
        "rs. 1",
        "99 only",
        "free",
        "90% off",
        "80% off",
        "90% discount",
        "80% discount"
    ]

    if any(k in t for k in keywords):
        return True

    if any(p <= 299 for p in prices):
        return True

    percentages = re.findall(r'(\d{2,3})\s*%\s*(?:off|discount)', t)
    if any(int(p) >= 70 for p in percentages):
        return True

    return False


@client.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def handler(event):
    text = event.raw_text or ""

    if looks_like_deal(text):
        print("\n🔥 POSSIBLE LOOT 🔥")
        print(text)
        print("-" * 60)


async def main():
    await client.connect()

    if not await client.is_user_authorized():
        raise RuntimeError(
            "TG_SESSION is invalid or not authorized. "
            "Create a new Telegram session."
        )

    me = await client.get_me()
    print(f"✅ Telegram connected as: {me.first_name}")
    print(f"👀 Listening to {SOURCE_CHANNEL} ...")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
