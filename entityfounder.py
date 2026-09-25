import os
import asyncio

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
TG_SESSION = os.environ["TG_SESSION"]

client = TelegramClient(
    StringSession(TG_SESSION),
    API_ID,
    API_HASH
)


async def main():
    await client.connect()

    if not await client.is_user_authorized():
        print("❌ Telegram session is not authorized.")
        return

    me = await client.get_me()
    print(f"✅ Telegram connected as: {me.first_name}")

    dialogs = await client.get_dialogs()

    print("\n🔎 Searching for LootersAmer...\n")

    found = False

    for dialog in dialogs:
        entity = dialog.entity
        title = getattr(entity, "title", "")

        if title and title.strip().lower() == "lootersamer":
            print("✅ Channel found!")
            print(f"📌 Name: {title}")
            print(f"🆔 CHANNEL ID: {entity.id}")
            found = True
            break

    if not found:
        print("❌ LootersAmer channel not found.")
        print("Make sure this Telegram account is a member/admin of the channel.")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())