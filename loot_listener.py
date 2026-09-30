# loot_listener.py
from __future__ import annotations

import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from bot_pipeline import process_incoming_deal

# --- ENVIRONMENT CONFIGURATION ---
raw_api_id = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION")

if not raw_api_id or not API_HASH:
    raise ValueError(
        "❌ CRITICAL ERROR: TG_API_ID or TG_API_HASH environment variables are missing! "
        "Please check your Railway variables."
    )

API_ID = int(raw_api_id)

channels_env = os.getenv("SOURCE_CHANNEL", "")
SOURCE_CHANNELS = [ch.strip() for ch in channels_env.split(",") if ch.strip()]
OUTPUT_CHANNEL = os.getenv("DESTINATION_CHANNEL", "")

# Initialize Telethon Client
if SESSION_STRING:
    print("🔐 Using Telegram Session String from Railway...")
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    print("📁 Using local session file...")
    client = TelegramClient("loot_bot_session", API_ID, API_HASH)


def extract_price_from_text(text: str) -> float:
    if not text:
        return 0.0
    patterns = [
        r'(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)',
        r'price\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    numbers = re.findall(r'\b[1-9]\d{2,5}\b', text)
    return float(numbers[0]) if numbers else 0.0


def extract_url_from_text(text: str) -> str:
    if not text:
        return ""
    url_match = re.search(r'(https?://\S+)', text)
    return url_match.group(1).strip(".,") if url_match else ""


@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handle_new_loot_message(event):
    message_text = event.message.message
    if not message_text:
        return
        
    print(f"\n📥 New message received from source channel...")
    short_url = extract_url_from_text(message_text)
    current_price = extract_price_from_text(message_text)
    
    lines = [line.strip() for line in message_text.split('\n') if line.strip()]
    product_title = lines[0] if lines else "Unknown Product"
    
    if not short_url:
        print("⚠️ No valid URL found in message. Skipping.")
        return
        
    result = process_incoming_deal(short_url, product_title, current_price)
    
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


# --- DUMMY HTTP SERVER FOR RAILWAY HEALTH CHECKS ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Loot Bot is active and running!")

    def log_message(self, format, *args):
        # Suppress routine HTTP log spam in console
        return

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"🌐 Health check server running on port {port}...")
    server.serve_forever()


def main():
    print("🤖 Starting Telegram Loot Bot Listener...")
    
    # Start the dummy HTTP server in a background thread so Railway is satisfied
    server_thread = threading.Thread(target=run_health_server, daemon=True)
    server_thread.start()
    
    # Start Telethon client
    client.start()
    print("✨ Bot is active and listening to target channels...")
    client.run_until_disconnected()


if __name__ == "__main__":
    main()