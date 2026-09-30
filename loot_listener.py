# loot_listener.py
from __future__ import annotations

import os
import re
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from bot_pipeline import process_incoming_deal

# --- ENVIRONMENT CONFIGURATION (Mapping with your Railway Variables) ---
raw_api_id = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION")

if not raw_api_id or not API_HASH:
    raise ValueError(
        "❌ CRITICAL ERROR: TG_API_ID or TG_API_HASH environment variables are missing! "
        "Please check your Railway variables."
    )

API_ID = int(raw_api_id)

# Multiple channels comma-separated format mein read honge
channels_env = os.getenv("SOURCE_CHANNEL", "")
SOURCE_CHANNELS = [ch.strip() for ch in channels_env.split(",") if ch.strip()]

OUTPUT_CHANNEL = os.getenv("DESTINATION_CHANNEL", "")

# Initialize Telethon Client using your TG_SESSION
if SESSION_STRING:
    print("🔐 Using Telegram Session String from Railway...")
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    print("📁 Using local session file...")
    client = TelegramClient("loot_bot_session", API_ID, API_HASH)


def extract_price_from_text(text: str) -> float:
    """
    Extracts price from Telegram message text using regex.
    """
    if not text:
        return 0.0
        
    patterns = [
        r'(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)',
        r'price\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                return float(price_str)
            except ValueError:
                continue
                
    numbers = re.findall(r'\b[1-9]\d{2,5}\b', text)
    if numbers:
        return float(numbers[0])
        
    return 0.0


def extract_url_from_text(text: str) -> str:
    """
    Extracts the first valid URL from message text.
    """
    if not text:
        return ""
    url_match = re.search(r'(https?://\S+)', text)
    if url_match:
        return url_match.group(1).strip(".,")
    return ""


@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handle_new_loot_message(event):
    message_text = event.message.message
    if not message_text:
        return
        
    print(f"\n📥 New message received from source channel...")
    
    # 1. Extract URL and Price from raw message text
    short_url = extract_url_from_text(message_text)
    current_price = extract_price_from_text(message_text)
    
    # Use first non-empty line as product title candidate
    lines = [line.strip() for line in message_text.split('\n') if line.strip()]
    product_title = lines[0] if lines else "Unknown Product"
    
    if not short_url:
        print("⚠️ No valid URL found in message. Skipping.")
        return
        
    # 2. Run through Pipeline (Resolution -> Whitelist Filter -> SQLite 30-Day History)
    result = process_incoming_deal(short_url, product_title, current_price)
    
    # 3. If approved, broadcast to your target destination channel
    if result["status"] == "approved":
        historical_min = result["historical_min"]
        resolved_link = result["resolved_url"]
        
        alert_msg = (
            f"🚨 **VERIFIED LOOT DEAL!** 🚨\n\n"
            f"📦 **{product_title}**\n"
            f"💰 **Current Price:** Rs.{current_price}\n"
            f"📉 **30-Day Historical Low:** Rs.{historical_min}\n\n"
            f"🔗 [Grab Deal Here]({resolved_link})"
        )
        
        try:
            await client.send_message(OUTPUT_CHANNEL, alert_msg, link_preview=False)
            print("🚀 Successfully broadcasted verified loot alert!")
        except Exception as e:
            print(f"❌ Failed to send Telegram message: {e}")


def main():
    print("🤖 Starting Telegram Loot Bot Listener...")
    client.start()
    print("✨ Bot is active and listening to target channels...")
    client.run_until_disconnected()


if __name__ == "__main__":
    main()