import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 30122529
API_HASH = "7309758c276e3beb9280a39cfec2db32"

async def main():
    client = TelegramClient(
        StringSession(),
        API_ID,
        API_HASH
    )

    await client.start()

    print("\nLOGIN SUCCESS")
    print("SESSION STRING:")
    print(client.session.save())

    await client.disconnect()

asyncio.run(main())