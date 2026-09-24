import os
import re
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events

load_dotenv()
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "@lootdeals2005")

PRICE_RE = re.compile(r"(?:₹|rs\.?\s*)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
PERCENT_RE = re.compile(r"([0-9]{2,3})\s*%", re.I)

def looks_like_deal(text: str) -> bool:
    t = text.lower()
    prices = []
    for m in PRICE_RE.finditer(text):
        try: prices.append(float(m.group(1).replace(",", "")))
        except ValueError: pass
    percents = [int(x) for x in PERCENT_RE.findall(text)]
    loot_words = ("price error", "error price", "loot", "glitch", "₹1", "rs 1", "99 only", "99/-", "free")
    if any(w in t for w in loot_words): return True
    if any(p >= 70 for p in percents): return True
    if prices and min(prices) <= 299: return True
    return False

async def main():
    client = TelegramClient("loot_hunter_session", API_ID, API_HASH)
    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        text = event.raw_text or ""
        if text.strip() and looks_like_deal(text):
            print("\n=== POSSIBLE LOOT ===\n" + text + "\n=====================\n")
    print(f"Listening to {SOURCE_CHANNEL} ...")
    await client.start()
    await client.run_until_disconnected()

if __name__ == "__main__": asyncio.run(main())
