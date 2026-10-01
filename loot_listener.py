from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import logging
import sqlite3
from collections import OrderedDict, deque
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from flask import Flask, jsonify, render_template_string, request, Response
import threading
from groq import Groq

from deal_validator import validate_deal
from deal_models import Verdict
from deal_sources import get_offer_price, resolve_url, canonical_url, fetch_product_price

# Suppress Flask/Werkzeug HTTP access logs
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)

VERSION = "6.6"
load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "")
DESTINATION = os.getenv("DESTINATION", "lootersAmer")
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "")

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

client = TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)
sem = asyncio.Semaphore(MAX_CONCURRENCY)

seen = OrderedDict()

DB_FILE = "loot_history.db"
DEAL_TTL_SECONDS = 7 * 24 * 60 * 60

# Live Tracker Status storage for Dashboard UI
WATCHED_ITEMS_STATUS = {}

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_deals (
                deal_id TEXT PRIMARY KEY,
                title TEXT,
                price TEXT,
                min_price TEXT,
                avg_price TEXT,
                source TEXT,
                url TEXT,
                verdict TEXT,
                timestamp REAL
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database initialization error: {e}")

init_db()

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
    return jsonify({
        "deals_scanned": DEALS_SCANNED,
        "recent_deals": list(RECENT_DEALS),
        "posted_deals": list(POSTED_DEALS),
        "recent_logs": list(RECENT_LOGS),
        "tracker_logs": list(TRACKER_LOGS),
        "watched_items": list(WATCHED_ITEMS_STATUS.values()),
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
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, price, min_price, avg_price, source, url, timestamp 
            FROM historical_deals 
            WHERE title LIKE ? OR source LIKE ?
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
                "time": datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
            }
            matched_deals.append(deal_obj)
            deals_context.append(f"- Title: {title} | Price: {price} | Source: {source} | URL: {url}")

        ai_answer = ""
        if groq_client and deals_context:
            try:
                context_str = "\n".join(deals_context)
                prompt = f"AI Shopping Assistant. Query: '{query}'. Deals:\n{context_str}\nSummarize best matches."
                completion = groq_client.chat.completions.create(
                    model="llama3-70b-8192", messages=[{"role": "user", "content": prompt}], max_tokens=250, temperature=0.7
                )
                ai_answer = completion.choices[0].message.content.strip()
            except Exception:
                ai_answer = f"Found {len(matched_deals)} relevant deals."
        else:
            ai_answer = f"Here are the top deals found for '{query}':" if matched_deals else "No matching deals found."

        return jsonify({"answer": ai_answer, "deals": matched_deals})
    except Exception:
        return jsonify({"answer": "An error occurred.", "deals": []})


@app.route("/add_watchlist", methods=["POST"])
def add_watchlist():
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"status": "error", "message": "URL is required"}), 400
    try:
        with open("watchlist.txt", "a") as f:
            f.write(url + "\n")
        return jsonify({"status": "success", "message": "URL added to live watchlist!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/export")
def export_deals_csv():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT deal_id, title, price, min_price, avg_price, source, url, verdict, timestamp FROM historical_deals ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()

        def generate():
            yield "Deal ID,Title,Price,Min Price,Avg Price,Source,URL,Verdict,Time\n"
            for row in rows:
                deal_id, title, price, min_price, avg_price, source, url, verdict, ts = row
                time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
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
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM historical_deals WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def parse_price_to_float(val) -> Optional[float]:
    if not val or val in {"-", "N/A", "Not Found ❌"}:
        return None
    try:
        cleaned = re.sub(r'[^\d.]', '', str(val))
        return float(cleaned) if cleaned else None
    except Exception:
        return None


def save_deal_to_sqlite(deal_id: str, title: str, price: any, source: str, url: str, verdict: str, min_price: str, avg_price: str):
    try:
        purge_old_deals()
        now = time.time()
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO historical_deals 
            (deal_id, title, price, min_price, avg_price, source, url, verdict, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (deal_id, title, str(price), str(min_price), str(avg_price), source, url, verdict, now))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"SQLite save error: {e}")


def load_deals_from_sqlite_on_startup():
    try:
        purge_old_deals()
        conn = sqlite3.connect(DB_FILE)
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
                    "time": datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
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


async def log(msg: str, error: bool = False):
    prefix = "❌" if error else "ℹ️"
    timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
    line = f"[{timestamp}] {prefix} {msg}"
    print(line)
    global RECENT_LOGS
    RECENT_LOGS.appendleft({"time": timestamp, "prefix": prefix, "msg": msg, "is_error": error})
    if LOG_CHANNEL:
        try:
            await client.send_message(LOG_CHANNEL, line)
        except Exception:
            pass


async def tracker_log(msg: str, error: bool = False):
    prefix = "❌" if error else "⚡"
    timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
    line = f"[{timestamp}] {prefix} [Tracker] {msg}"
    print(line)
    global TRACKER_LOGS
    TRACKER_LOGS.appendleft({"time": timestamp, "prefix": prefix, "msg": msg, "is_error": error})


def channel_allowed(chat) -> bool:
    if not WATCH_CHANNELS:
        return bool(getattr(chat, "broadcast", False))
    username = (getattr(chat, "username", "") or "").lower().lstrip("@")
    return username in WATCH_CHANNELS


async def send_result(result, source, title, price, final_url):
    if result.verdict not in {Verdict.DEAL, Verdict.POSSIBLE_DEAL}:
        return

    evidence_prices = [item.price for item in result.evidence if item.price and item.price > 50]
    all_prices = evidence_prices

    min_price_str = f"₹{min(all_prices):,.0f}" if all_prices else "-"
    avg_price_str = f"₹{sum(all_prices)/len(all_prices):,.0f}" if all_prices else "-"

    global POSTED_DEALS
    price_display = f"₹{price:,.0f}" if isinstance(price, (int, float)) else (price if price else "N/A")
    
    posted_item = {
        "title": title[:100], "price": price_display, "min_price": min_price_str,
        "avg_price": avg_price_str, "source": source, "url": final_url, "time": datetime.now().strftime("%H:%M:%S")
    }
    
    if not POSTED_DEALS or POSTED_DEALS[0]["url"] != final_url:
        POSTED_DEALS.appendleft(posted_item)

    deal_id = hashlib.sha256(f"{final_url}:{title}".encode()).hexdigest()[:16]
    save_deal_to_sqlite(deal_id, title, price_display, source, final_url, result.verdict.value, min_price_str, avg_price_str)

    emoji = "🔥" if result.verdict == Verdict.DEAL else "🟡"
    lines = [
        f"{emoji} {'VERIFIED DEAL' if result.verdict == Verdict.DEAL else 'POSSIBLE DEAL'}",
        "", f"📦 {result.offer.title}", f"💰 Price: ₹{result.offer.price:,.0f}",
        f"🎯 Confidence: {result.confidence:.0%}", f"🧠 {result.reason}",
        "", f"📢 {result.offer.source}", f"🔗 {result.offer.url}"
    ]
    await client.send_message(DESTINATION, "\n".join(lines))


# --- PARALLEL BACKGROUND PRICE TRACKER WORKER (With Live Status Feed) ---
async def price_tracker_worker():
    await asyncio.sleep(15)
    alerted_cache = {}
    
    while True:
        try:
            watchlist_path = "watchlist.txt"
            if os.path.exists(watchlist_path):
                with open(watchlist_path, "r") as f:
                    urls_to_check = [line.strip() for line in f if line.strip() and not line.startswith("#")]
                
                if urls_to_check:
                    await tracker_log(f"Scanning {len(urls_to_check)} watchlisted items...")
                    for raw_url in urls_to_check:
                        try:
                            resolved = await asyncio.to_thread(resolve_url, raw_url)
                            canonical = canonical_url(resolved) if resolved else raw_url
                            if not canonical:
                                canonical = raw_url

                            live_price = await asyncio.to_thread(fetch_product_price, canonical)
                            if not live_price or live_price <= 50:
                                continue

                            conn = sqlite3.connect(DB_FILE)
                            cursor = conn.cursor()
                            cursor.execute("SELECT price, min_price, title FROM historical_deals WHERE url = ? ORDER BY timestamp DESC LIMIT 1", (canonical,))
                            row = cursor.fetchone()
                            conn.close()

                            item_title = "Monitored Item"
                            if row:
                                db_price_str, db_min_str, title = row
                                item_title = title if title else "Monitored Item"
                                db_price = parse_price_to_float(db_price_str)
                                db_min = parse_price_to_float(db_min_str)
                                
                                ref_price = db_min if (db_min and db_min > 50) else db_price
                                
                                if ref_price and ref_price > 50:
                                    threshold_price = ref_price * 0.90  
                                    
                                    if live_price <= threshold_price:
                                        drop_pct = ((ref_price - live_price) / ref_price) * 100
                                        alert_key = f"{canonical}:{live_price}"
                                        
                                        if alert_key not in alerted_cache:
                                            alerted_cache[alert_key] = time.time()
                                            await tracker_log(f"🔥 GENUINE PRICE DROP! Live: ₹{live_price:,.0f} vs Old: ₹{ref_price:,.0f} ({drop_pct:.1f}% cheaper)")

                                            new_min = min(live_price, ref_price)
                                            new_min_str = f"₹{new_min:,.0f}"
                                            
                                            msg = (
                                                f"🔥 **PRICE DROP ALERT ({drop_pct:.1f}% OFF)**\n\n"
                                                f"📦 {item_title}\n"
                                                f"💰 New Live Price: **₹{live_price:,.0f}**\n"
                                                f"📉 Previous Price: ₹{ref_price:,.0f}\n"
                                                f"🎯 Total Drop: {drop_pct:.1f}%\n\n"
                                                f"🔗 {canonical}"
                                            )
                                            await client.send_message(DESTINATION, msg)
                                            
                                            deal_id = hashlib.sha256(f"{canonical}:{item_title}".encode()).hexdigest()[:16]
                                            save_deal_to_sqlite(
                                                deal_id, item_title, f"₹{live_price:,.0f}", 
                                                "Live Tracker", canonical, "DEAL", 
                                                new_min_str, f"₹{ref_price:,.0f}"
                                            )
                            else:
                                deal_id = hashlib.sha256(f"{canonical}:Watchlist Baseline".encode()).hexdigest()[:16]
                                save_deal_to_sqlite(
                                    deal_id, "Watchlist Monitored Item", f"₹{live_price:,.0f}", 
                                    "Live Tracker", canonical, "SCANNED", 
                                    f"₹{live_price:,.0f}", f"₹{live_price:,.0f}"
                                )

                            # Update Live Status Feed for Web Dashboard
                            global WATCHED_ITEMS_STATUS
                            WATCHED_ITEMS_STATUS[canonical] = {
                                "title": item_title[:100],
                                "price": f"₹{live_price:,.0f}",
                                "url": canonical,
                                "time": datetime.now().strftime("%H:%M:%S")
                            }
                        
                        except Exception as item_err:
                            pass
        except Exception as e:
            await tracker_log(f"Worker error: {e}", error=True)
            
        await asyncio.sleep(20)


async def process_message(event):
    chat = await event.get_chat()
    if not channel_allowed(chat):
        return

    text = event.raw_text or ""
    found = urls(text)
    if not found:
        return

    source = f"@{chat.username}" if getattr(chat, "username", None) else str(chat.id)
    message_key = f"{chat.id}:{event.id}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    if not remember_once(message_key):
        return

    title = title_from(text)
    first_url = found[0] if found else None

    price = await asyncio.to_thread(get_offer_price, text, first_url)
    if price and price < MIN_PRICE:
        return

    deal_url = first_url
    if first_url:
        try:
            resolved_url = await asyncio.to_thread(resolve_url, first_url)
            if resolved_url:
                deal_url = await asyncio.to_thread(canonical_url, resolved_url)
        except Exception:
            deal_url = first_url

    if deal_url and await asyncio.to_thread(is_deal_already_processed, deal_url):
        return

    global DEALS_SCANNED
    DEALS_SCANNED += 1
    price_display = f"₹{price:,.0f}" if isinstance(price, (int, float)) else (price if price else "N/A")
    
    deal_id = hashlib.sha256(f"{deal_url}:{title}".encode()).hexdigest()[:16]
    save_deal_to_sqlite(deal_id, title, price_display, source, deal_url, "SCANNED", "-", "-")

    for url in found[:3]:
        async with sem:
            try:
                res_url = await asyncio.to_thread(resolve_url, url)
                final_url = (await asyncio.to_thread(canonical_url, res_url)) if res_url else url
                result = await asyncio.wait_for(validate_deal(title, price, final_url, source, text), timeout=45)
                await send_result(result, source, title, price, final_url)
            except Exception:
                pass


@client.on(events.NewMessage)
async def on_new_message(event):
    try:
        await process_message(event)
    except Exception:
        pass


async def heartbeat():
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await log(f"HEARTBEAT v{VERSION} | scanned={DEALS_SCANNED} | uptime={get_uptime_string()}")


async def discover():
    global CHANNELS_COUNT
    load_deals_from_sqlite_on_startup()
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