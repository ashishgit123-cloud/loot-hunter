from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import logging
import json
import io
import csv
from collections import OrderedDict, deque
from typing import Optional
from datetime import datetime, timezone, timedelta
from enum import Enum

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from flask import Flask, jsonify, render_template, request, Response
import threading
from groq import Groq
import requests
from bs4 import BeautifulSoup
import psycopg2

# Suppress Flask/Werkzeug HTTP access logs
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)

VERSION = "6.9.3"
load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "")
DESTINATION = os.getenv("DESTINATION", "lootersAmer")
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

IST = timezone(timedelta(hours=5, minutes=30))

WATCH_CHANNELS = {
    x.strip().lower().lstrip("@")
    for x in os.getenv("WATCH_CHANNELS", "").split(",")
    if x.strip()
}

MIN_PRICE = float(os.getenv("MIN_PRICE", "1000"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "6"))
DEDUP_TTL_SECONDS = int(os.getenv("DEDUP_TTL_SECONDS", "21600"))
HEARTBEAT_SECONDS = int(os.getenv("HEARTBEAT_SECONDS", "120"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

if not API_ID or not API_HASH or not TG_SESSION:
    raise RuntimeError("TG_API_ID, TG_API_HASH and TG_SESSION are required")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required for PostgreSQL connection")

client = TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)
sem = asyncio.Semaphore(MAX_CONCURRENCY)

seen = OrderedDict()
DEAL_TTL_SECONDS = 7 * 24 * 60 * 60

class Verdict(Enum):
    DEAL = "DEAL"
    POSSIBLE_DEAL = "POSSIBLE_DEAL"
    NOT_A_DEAL = "NOT_A_DEAL"

class Offer:
    def __init__(self, title, price, url, source):
        self.title = title
        self.price = price
        self.url = url
        self.source = source

class DealResult:
    def __init__(self, verdict: Verdict, confidence: float, reason: str, offer: Offer):
        self.verdict = verdict
        self.confidence = confidence
        self.reason = reason
        self.offer = offer

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_deals (
                deal_id VARCHAR(64) PRIMARY KEY,
                title TEXT,
                price TEXT,
                min_price TEXT,
                avg_price TEXT,
                source TEXT,
                url TEXT,
                verdict TEXT,
                timestamp DOUBLE PRECISION
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                url TEXT PRIMARY KEY,
                title TEXT,
                price TEXT,
                timestamp DOUBLE PRECISION
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database initialization error: {e}")

init_db()

def load_watchlist_from_db():
    items = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT title, url, price, timestamp FROM watchlist ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            title, url, price, ts = row
            # Error fixed here: using datetime.fromtimestamp with IST
            time_str = datetime.fromtimestamp(ts, IST).strftime("%H:%M:%S") if ts else datetime.now(IST).strftime("%H:%M:%S")
            items.append({
                "title": title,
                "url": url,
                "price": price,
                "time": time_str
            })
    except Exception as e:
        print(f"Error loading watchlist from DB: {e}")
    return items

def save_watchlist_item_to_db(title: str, url: str, price: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO watchlist (url, title, price, timestamp)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (url) DO UPDATE SET 
        title = EXCLUDED.title, price = EXCLUDED.price, timestamp = EXCLUDED.timestamp
    """, (url, title, price, time.time()))
    conn.commit()
    conn.close()

WATCHED_ITEMS = load_watchlist_from_db()

START_TIME = time.time()
CHANNELS_COUNT = 0
DEALS_SCANNED = 0
RECENT_DEALS = deque(maxlen=20)
POSTED_DEALS = deque(maxlen=20)
RECENT_LOGS = deque(maxlen=50)
TRACKER_LOGS = deque(maxlen=50)

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

def get_uptime_string() -> str:
    seconds = int(time.time() - START_TIME)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h {minutes}m"

@app.route("/stats")
def stats():
    global WATCHED_ITEMS
    WATCHED_ITEMS = load_watchlist_from_db()
    return jsonify({
        "deals_scanned": DEALS_SCANNED,
        "recent_deals": list(RECENT_DEALS),
        "posted_deals": list(POSTED_DEALS),
        "recent_logs": list(RECENT_LOGS),
        "tracker_logs": list(TRACKER_LOGS),
        "watched_items": WATCHED_ITEMS,
        "channels_count": CHANNELS_COUNT,
        "uptime": get_uptime_string(),
        "dedup_size": len(seen),
        "concurrency": MAX_CONCURRENCY,
        "version": VERSION
    })

@app.route("/search")
def search_db():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"answer": "Please enter a search query.", "deals": []})
    
    try:
        purge_old_deals()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, price, min_price, avg_price, source, url, timestamp 
            FROM historical_deals 
            WHERE title ILIKE %s OR source ILIKE %s
            ORDER BY timestamp DESC 
            LIMIT 15
        """, (f"%{query}%", f"%{query}%"))
        rows = cursor.fetchall()
        conn.close()
        
        matched_deals = []
        deals_context = []
        for row in rows:
            title, price, min_price, avg_price, source, url, timestamp = row
            deal_obj = {
                "title": title[:100], "price": price, "min_price": min_price,
                "avg_price": avg_price, "source": source, "url": url,
                "time": datetime.fromtimestamp(timestamp, IST).strftime("%H:%M:%S") if timestamp else datetime.now(IST).strftime("%H:%M:%S")
            }
            matched_deals.append(deal_obj)
            deals_context.append(f"- Title: {title} | Price: {price} | Source: {source} | URL: {url}")

        ai_answer = ""
        if groq_client:
            try:
                context_str = "\n".join(deals_context) if deals_context else "No direct deals found in database for this query."
                prompt = (
                    "You are an expert, friendly AI Shopping & Loot Deals Assistant. "
                    "Answer the user's query conversationally and intelligently like a true AI chatbot. "
                    "If database deals are provided below, incorporate them naturally. "
                    "If no exact deals are found in the database, provide helpful shopping guidance, what prices to expect, or smart advice related to their query.\n\n"
                    f"User Query: '{query}'\n\nDatabase Deals Available:\n{context_str}"
                )
                completion = groq_client.chat.completions.create(
                    model="llama3-70b-8192", 
                    messages=[{"role": "user", "content": prompt}], 
                    max_tokens=300, 
                    temperature=0.7
                )
                ai_answer = completion.choices[0].message.content.strip()
            except Exception as e:
                ai_answer = f"Found {len(matched_deals)} matching deals."
        else:
            ai_answer = f"Here are the top deals found for '{query}':" if matched_deals else "No matching deals found."

        return jsonify({"answer": ai_answer, "deals": matched_deals})
    except Exception as e:
        return jsonify({"answer": "An error occurred while processing your request.", "deals": []})

@app.route("/add_watchlist", methods=["POST"])
def add_watchlist():
    global WATCHED_ITEMS
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"status": "error", "message": "URL is required"}), 400
    
    product_title = "Watched Product"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            if soup.find('meta', property='og:title'):
                product_title = soup.find('meta', property='og:title')['content'].strip()
            elif soup.find('title'):
                product_title = soup.find('title').get_text().strip()
            
            if len(product_title) > 60:
                product_title = product_title[:57] + "..."
    except Exception:
        product_title = url.split('/')[-1].replace('-', ' ').title() or "Custom Item"

    try:
        save_watchlist_item_to_db(product_title, url, "Checking...")
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500

    WATCHED_ITEMS = load_watchlist_from_db()
    return jsonify({"status": "success", "message": f"Added: {product_title}"})

@app.route("/export")
def export_deals_csv():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT deal_id, title, price, min_price, avg_price, source, url, verdict, timestamp FROM historical_deals ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()

        def generate():
            yield "Deal ID,Title,Price,Min Price,Avg Price,Source,URL,Verdict,Time\n"
            for row in rows:
                deal_id, title, price, min_price, avg_price, source, url, verdict, ts = row
                time_str = datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d %H:%M:%S") if ts else datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
                safe_title = str(title).replace('"', '""')
                yield f'"{deal_id}","{safe_title}","{price}","{min_price}","{avg_price}","{source}","{url}","{verdict}","{time_str}"\n'

        return Response(generate(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=loot_database_export.csv"})
    except Exception:
        return jsonify({"error": "Failed to export"}), 500

def run_web():
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def purge_old_deals():
    try:
        cutoff = time.time() - DEAL_TTL_SECONDS
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM historical_deals WHERE timestamp < %s", (cutoff,))
        conn.commit()
        conn.close()
    except Exception:
        pass

def save_deal_to_db(deal_id: str, title: str, price: any, source: str, url: str, verdict: str, min_price: str, avg_price: str):
    try:
        purge_old_deals()
        now = time.time()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO historical_deals 
            (deal_id, title, price, min_price, avg_price, source, url, verdict, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (deal_id) DO UPDATE SET 
            price = EXCLUDED.price, min_price = EXCLUDED.min_price, avg_price = EXCLUDED.avg_price, timestamp = EXCLUDED.timestamp
        """, (deal_id, title, str(price), str(min_price), str(avg_price), source, url, verdict, now))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"PostgreSQL save error: {e}")

def load_deals_from_db_on_startup():
    try:
        purge_old_deals()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT deal_id, title, price, min_price, avg_price, source, url, verdict, timestamp FROM historical_deals ORDER BY timestamp DESC LIMIT 20")
        rows = cursor.fetchall()
        conn.close()
        if rows:
            for row in rows:
                deal_id, title, price, min_price, avg_price, source, url, verdict_val, timestamp = row
                item = {
                    "title": title[:100], "price": price, "min_price": min_price,
                    "avg_price": avg_price, "source": source, "url": url,
                    "time": datetime.fromtimestamp(timestamp, IST).strftime("%H:%M:%S") if timestamp else datetime.now(IST).strftime("%H:%M:%S")
                }
                RECENT_DEALS.append(item)
                if verdict_val in {Verdict.DEAL.value, Verdict.POSSIBLE_DEAL.value, "DEAL", "POSSIBLE_DEAL"}:
                    POSTED_DEALS.append(item)
    except Exception as e:
        print(f"Cache load error: {e}")

def remember_once(key: str) -> bool:
    now = time.time()
    cutoff = now - DEDUP_TTL_SECONDS
    while seen:
        first_key = next(iter(seen))
        if seen[first_key] >= cutoff:
            break
        seen.popitem(last=False)
    if key in seen:
        return False
    seen[key] = now
    return True

URL_RE = re.compile(r"https?://[^\s<>]+", re.I)

def urls(text: str) -> list[str]:
    out = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,!?;:)]}")
        if u not in out:
            out.append(u)
    return out

def title_from(text: str) -> str:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    for line in lines:
        low = line.lower()
        if line.startswith(("http://", "https://")) or re.fullmatch(r"[\d₹$€£,.\s]+", line):
            continue
        if any(k in low for k in ("buy now", "click here", "shop now", "limited time")):
            continue
        return line[:300]
    return "Unknown Product"

def get_smart_title(text: str, url: Optional[str] = None) -> str:
    title = title_from(text)
    
    generic_keywords = [
        "off", "discount", "sale", "upto", "flat", 
        "price drop", "lowest price", "loot", "deal", "save", "time to shine"
    ]
    
    is_generic = (
        not title 
        or title == "Unknown Product" 
        or len(title) < 5 
        or "loot @" in title.lower() 
        or "deal @" in title.lower()
        or any(k in title.lower() for k in generic_keywords)
    )
    
    if is_generic and url:
        try:
            from deal_sources import resolve_url, canonical_url
            res_url = resolve_url(url)
            final_url = canonical_url(res_url) if res_url else url
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(final_url, headers=headers, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                scraped_title = ""
                if soup.find('meta', property='og:title'):
                    scraped_title = soup.find('meta', property='og:title')['content'].strip()
                elif soup.find('title'):
                    scraped_title = soup.find('title').get_text().strip()
                
                if scraped_title and len(scraped_title) > 3:
                    if len(scraped_title) > 100:
                        scraped_title = scraped_title[:97] + "..."
                    return scraped_title
        except Exception as e:
            print(f"URL Title Scraping Error: {e}")
            
    return title

async def log(msg: str, error: bool = False, send_to_telegram: bool = True):
    prefix = "❌" if error else "ℹ️"
    timestamp = datetime.now(IST).strftime("%H:%M:%S")
    line = f"[{timestamp}] {prefix} {msg}"
    print(line)
    global RECENT_LOGS
    RECENT_LOGS.appendleft({"time": timestamp, "prefix": prefix, "msg": msg, "is_error": error})
    if LOG_CHANNEL and send_to_telegram:
        try:
            await client.send_message(LOG_CHANNEL, line)
        except Exception:
            pass

async def tracker_log(msg: str, error: bool = False):
    prefix = "❌" if error else "⚡"
    timestamp = datetime.now(IST).strftime("%H:%M:%S")
    line = f"[{timestamp}] {prefix} [Tracker] {msg}"
    print(line)
    global TRACKER_LOGS
    TRACKER_LOGS.appendleft({"time": timestamp, "prefix": prefix, "msg": msg, "is_error": error})

def channel_allowed(chat) -> bool:
    if not WATCH_CHANNELS:
        return True
    username = (getattr(chat, "username", "") or "").lower().lstrip("@")
    chat_id_str = str(chat.id)
    return username in WATCH_CHANNELS or chat_id_str in WATCH_CHANNELS

async def validate_deal(title, price, final_url, source, text) -> DealResult:
    offer = Offer(title=title, price=price or 0, url=final_url, source=source)
    return DealResult(
        verdict=Verdict.DEAL,
        confidence=0.9,
        reason="Auto-verified valid deal format.",
        offer=offer
    )

async def send_result(result, source, title, price, final_url, min_price_str, avg_price_str):
    if not isinstance(price, (int, float)) or price <= 0:
        return

    if result.verdict not in {Verdict.DEAL, Verdict.POSSIBLE_DEAL}:
        return

    global POSTED_DEALS
    price_display = f"₹{price:,.0f}"
    
    posted_item = {
        "title": title[:100], "price": price_display, "min_price": min_price_str,
        "avg_price": avg_price_str, "source": source, "url": final_url, "time": datetime.now(IST).strftime("%H:%M:%S")
    }
    
    if not POSTED_DEALS or POSTED_DEALS[0]["url"] != final_url:
        POSTED_DEALS.appendleft(posted_item)

    deal_id = hashlib.sha256(f"{final_url}:{title}".encode()).hexdigest()[:16]
    save_deal_to_db(deal_id, title, price_display, source, final_url, result.verdict.value, min_price_str, avg_price_str)

    emoji = "🔥" if result.verdict == Verdict.DEAL else "🟡"
    lines = [
        f"{emoji} {'VERIFIED DEAL' if result.verdict == Verdict.DEAL else 'POSSIBLE DEAL'}",
        "", f"📦 {result.offer.title}", f"💰 Price: ₹{result.offer.price:,.0f}",
        f"📉 Min: {min_price_str} | 📊 Avg: {avg_price_str}",
        f"🎯 Confidence: {result.confidence:.0%}", f"🧠 {result.reason}",
        "", f"📢 {result.offer.source}", f"🔗 {result.offer.url}"
    ]
    if DESTINATION:
        try:
            await client.send_message(DESTINATION, "\n".join(lines))
        except Exception:
            pass

async def price_tracker_worker():
    while True:
        try:
            global WATCHED_ITEMS
            # Database se current watchlist load karo
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT title, url, price FROM watchlist")
            rows = cursor.fetchall()
            conn.close()

            if rows:
                for row in rows:
                    title, url, old_price_str = row
                    if url:
                        try:
                            from deal_sources import fetch_product_price, get_offer_price
                            price_val = await asyncio.to_thread(fetch_product_price, url)
                            if not price_val:
                                price_val = await asyncio.to_thread(get_offer_price, "", url)
                            
                            if isinstance(price_val, (int, float)) and price_val > 0:
                                price_display = f"₹{price_val:,.0f}"
                                
                                # Purane price ko numeric mein convert karke compare karo
                                old_numeric = float(re.sub(r'[^\d.]', '', str(old_price_str))) if old_price_str and old_price_str not in ["Checking...", "N/A", "-"] else None
                                
                                # Agar purana price mil gaya hai aur naya price usse kam hai, toh alert bhejo!
                                if old_numeric and price_val < old_numeric:
                                    drop_amount = old_numeric - price_val
                                    alert_msg = (
                                        f"📉 **WATCHLIST PRICE DROP ALERT!**\n\n"
                                        f"📦 {title}\n"
                                        f"💰 Old Price: ₹{old_numeric:,.0f}\n"
                                        f"🔥 New Price: {price_display} (Saved ₹{drop_amount:,.0f}!)\n"
                                        f"🔗 {url}"
                                    )
                                    if DESTINATION:
                                        try:
                                            await client.send_message(DESTINATION, alert_msg)
                                        except Exception:
                                            pass
                                    await tracker_log(f"Price dropped for watched item: {title} to {price_display}")

                                # Database mein naya price update kar do
                                save_watchlist_item_to_db(title, url, price_display)
                        except Exception as e:
                            print(f"Error checking watchlist item {url}: {e}")
                            
                    await asyncio.sleep(5) # Har item ke beech chhota gap
            await tracker_log("Checked and updated all database watchlist items successfully.")
        except Exception as e:
            await tracker_log(f"Tracker error: {str(e)}", error=True)
        
        await asyncio.sleep(60) # Har 1 minute mein poori watchlist check hogi

async def process_message(event):
    chat = await event.get_chat()
    chat_identifier = getattr(chat, "username", None) or str(chat.id)
    print(f"📥 Message received from chat: {chat_identifier}")

    if not channel_allowed(chat):
        print(f"⚠️ Channel {chat_identifier} is not in WATCH_CHANNELS filter list!")
        return

    text = event.raw_text or ""
    found = urls(text)
    if not found:
        print(f"ℹ️ Message ignored (No URL found): {text[:50]}...")
        return

    source = f"@{chat.username}" if getattr(chat, "username", None) else str(chat.id)
    message_key = f"{chat.id}:{event.id}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    if not remember_once(message_key):
        return

    from deal_sources import get_offer_price, resolve_url, canonical_url
    
    first_url = found[0]
    deal_url = first_url
    try:
        resolved_url = await asyncio.to_thread(resolve_url, first_url)
        if resolved_url:
            deal_url = await asyncio.to_thread(canonical_url, resolved_url)
    except Exception:
        deal_url = first_url

    title = get_smart_title(text, deal_url)
    if not title or title == "Unknown Product":
        return

    price = await asyncio.to_thread(get_offer_price, text, deal_url)
    if not isinstance(price, (int, float)) or price <= 0 or price < MIN_PRICE:
        return

    is_first_time = False
    db_min_str = "-"
    db_avg_str = "-"
    db_min_val = price

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM historical_deals WHERE url = %s", (deal_url,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            is_first_time = True
            db_min_str = f"₹{price:,.0f}"
            db_avg_str = f"₹{price:,.0f}"
        else:
            valid_prices = []
            for row in rows:
                val = row[0]
                if val and val not in {"-", "N/A"}:
                    cleaned = re.sub(r'[^\d.]', '', str(val))
                    if cleaned:
                        valid_prices.append(float(cleaned))
            if valid_prices:
                db_min_val = min(valid_prices)
                db_min_str = f"₹{db_min_val:,.0f}"
                db_avg_str = f"₹{sum(valid_prices) / len(valid_prices):,.0f}"
    except Exception as e:
        print(f"DB Check Error: {e}")

    global DEALS_SCANNED
    DEALS_SCANNED += 1
    price_display = f"₹{price:,.0f}"
    
    deal_id = hashlib.sha256(f"{deal_url}:{title}".encode()).hexdigest()[:16]
    save_deal_to_db(deal_id, title, price_display, source, deal_url, "SCANNED", db_min_str, db_avg_str)

    item = {
        "title": title[:100], "price": price_display, "min_price": db_min_str,
        "avg_price": db_avg_str, "source": source, "url": deal_url, "time": datetime.now(IST).strftime("%H:%M:%S")
    }
    RECENT_DEALS.appendleft(item)

    if is_first_time:
        print(f"ℹ️ First time seen. Saved to DB silently (No Post): {title} @ {price_display}")
        return

    if price >= db_min_val:
        print(f"ℹ️ Price (₹{price}) is not lower than historical min ({db_min_str}). Skipping channel post.")
        return

    async with sem:
        try:
            result = await asyncio.wait_for(validate_deal(title, price, deal_url, source, text), timeout=45)
            await send_result(result, source, title, price, deal_url, db_min_str, db_avg_str)
        except Exception as e:
            print(f"Validation error: {e}")

@client.on(events.NewMessage)
async def on_new_message(event):
    try:
        await process_message(event)
    except Exception as e:
        print(f"Event handler error: {e}")

async def heartbeat():
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await log(f"HEARTBEAT v{VERSION} | scanned={DEALS_SCANNED} | uptime={get_uptime_string()}", send_to_telegram=False)

async def discover():
    global CHANNELS_COUNT
    load_deals_from_db_on_startup()
    dialogs = await client.get_dialogs()
    count = 0
    for dialog in dialogs:
        if getattr(dialog.entity, "broadcast", False):
            count += 1
    CHANNELS_COUNT = count
    await log(f"Listening to {count} broadcast channels")

async def main():
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    await log("Web dashboard thread started")

    asyncio.create_task(price_tracker_worker())
    await tracker_log("Live Price Tracker worker spawned in parallel background loop.")

    await client.start()
    me = await client.get_me()
    await log(f"Started v{VERSION} as @{getattr(me, 'username', None) or me.first_name}")
    await discover()
    
    hb = asyncio.create_task(heartbeat())
    try:
        await client.run_until_disconnected()
    finally:
        hb.cancel()

if __name__ == "__main__":
    asyncio.run(main())