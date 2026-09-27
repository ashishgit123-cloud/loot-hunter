import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession


API_ID = 30122529
API_HASH = "7309758c276e3beb9280a39cfec2db32"


async def main():

    client = TelegramClient(
        StringSession(),
        API_ID,
        API_HASH,
    )

    print("Starting Telegram login...")

    await client.start()

    me = await client.get_me()

    print("\n" + "=" * 60)
    print("LOGIN SUCCESS")
    print("=" * 60)

    print(f"User ID: {me.id}")
    print(f"Username: @{me.username}" if me.username else "Username: None")

    print("\nTG_SESSION:")
    print(client.session.save())

    print("\n" + "=" * 60)
    print("COPY THE COMPLETE TG_SESSION STRING")
    print("=" * 60)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())