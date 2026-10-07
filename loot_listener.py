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
import sys
import queue
from playwright.sync_api import sync_playwright
from collections import OrderedDict, deque
from typing import Optional
from datetime import datetime, timezone, timedelta
from enum import Enum

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from flask import Flask, jsonify, render_template, request, Response, redirect
import threading
from groq import Groq
import requests
from bs4 import BeautifulSoup
import psycopg2
from curl_cffi import requests as curl_requests

# Suppress Flask/Werkzeug HTTP access logs
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)

VERSION = "6.9.7"
load_dotenv()


API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "")
DESTINATION = os.getenv("DESTINATION", "lootersAmer")
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
BRIDGE_URL = os.getenv("BRIDGE_URL", "")

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

# Thread-safe queue for background Telegram alerts
telegram_alert_queue = queue.Queue()
telegram_photo_queue = queue.Queue()

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
                target_price DOUBLE PRECISION,
                timestamp DOUBLE PRECISION
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS added_to_cart (
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
        cursor.execute("SELECT title, url, price, target_price, timestamp FROM watchlist ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            title, url, price, target_price, ts = row
            time_str = datetime.fromtimestamp(ts, IST).strftime("%H:%M:%S") if ts else datetime.now(IST).strftime("%H:%M:%S")
            items.append({
                "title": title,
                "url": url,
                "price": price,
                "target_price": target_price if target_price is not None else 0.0,
                "time": time_str
            })
    except Exception as e:
        print(f"Error loading watchlist from DB: {e}")
    return items

def load_cart_items_from_db():
    items = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT title, url, price, timestamp FROM added_to_cart ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            title, url, price, ts = row
            time_str = datetime.fromtimestamp(ts, IST).strftime("%H:%M:%S") if ts else datetime.now(IST).strftime("%H:%M:%S")
            items.append({
                "title": title,
                "url": url,
                "price": price,
                "time": time_str
            })
    except Exception as e:
        print(f"Error loading cart items from DB: {e}")
    return items

def save_watchlist_item_to_db(title: str, url: str, price: str, target_price: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO watchlist (url, title, price, target_price, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (url) DO UPDATE SET 
        title = EXCLUDED.title, price = EXCLUDED.price, target_price = EXCLUDED.target_price, timestamp = EXCLUDED.timestamp
    """, (url, title, price, target_price, time.time()))
    conn.commit()
    conn.close()

WATCHED_ITEMS = load_watchlist_from_db()
CART_ITEMS = load_cart_items_from_db()

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
def get_stats():
    return jsonify({
        "deals_scanned": DEALS_SCANNED,
        "posted_deals": list(POSTED_DEALS),
        "watched_items": WATCHED_ITEMS,
        "cart_items": CART_ITEMS,
        "channels_count": CHANNELS_COUNT,
        "uptime": get_uptime_string(),
        "dedup_size": len(seen),
        "recent_deals": list(RECENT_DEALS),
        "recent_logs": list(RECENT_LOGS),
        "tracker_logs": list(TRACKER_LOGS)
    })

@app.route("/search")
def search_db():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"answer": "Please enter a search query.", "deals": []})
    
    try:
        purge_old_deals()
        
        keyword = query
        order_by = "timestamp DESC"
        limit = 15
        
        if groq_client:
            try:
                prompt = (
                    "Analyze the user's search query for a loot deals database and extract parameters into a strict JSON object. "
                    "Fields required: "
                    "- 'keyword': the core product, item, or brand name to search for (string, e.g., 'shoes', 'iphone', or general term). "
                    "- 'sort': use 'cheapest' if the user wants lowest price / min price, use 'newest' if they want latest, otherwise 'default' (string). "
                    "Return ONLY valid JSON. No markdown code blocks, no extra text.\n\n"
                    f"Query: '{query}'"
                )
                completion = groq_client.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=80,
                    temperature=0.0
                )
                res_text = completion.choices[0].message.content.strip()
                
                if res_text.startswith("```"):
                    res_text = res_text.split("```")[1]
                    if res_text.startswith("json"):
                        res_text = res_text[4:].strip()
                
                parsed_data = json.loads(res_text)
                keyword = parsed_data.get("keyword", query) or query
                sort_intent = parsed_data.get("sort", "default")
                
                if sort_intent == "cheapest":
                    order_by = "price ASC"
                elif sort_intent == "newest":
                    order_by = "timestamp DESC"
            except Exception as e:
                print("Intent extraction error:", e)

        stopwords = ['minimum', 'min', 'max', 'maximum', 'sasta', 'cheapest', 'best', 'latest', 'konsa', 'ka', 'ki', 'ke', 'hai', 'kya', 'deal', 'deals', 'me', 'mein', 'price', 'wala', 'wali']
        if keyword.lower() in stopwords or len(keyword.strip()) < 2:
            words = [w for w in query.lower().split() if w not in stopwords]
            keyword = " ".join(words) if words else query

        conn = get_db_connection()
        cursor = conn.cursor()
        
        sql_query = f"""
            SELECT title, price, min_price, avg_price, source, url, timestamp 
            FROM historical_deals 
            WHERE title ILIKE %s OR source ILIKE %s 
            ORDER BY {order_by}
            LIMIT %s
        """
        cursor.execute(sql_query, (f"%{keyword}%", f"%{keyword}%", limit))
        rows = cursor.fetchall()
        conn.close()
        
        matched_deals = []
        for row in rows:
            title, price, min_price, avg_price, source, url, timestamp = row
            deal_obj = {
                "title": title[:100] if title else "", 
                "price": price, 
                "min_price": min_price,
                "avg_price": avg_price, 
                "source": source, 
                "url": url,
                "time": datetime.fromtimestamp(timestamp, IST).strftime("%H:%M:%S") if timestamp else datetime.now(IST).strftime("%H:%M:%S")
            }
            matched_deals.append(deal_obj)

        if not matched_deals:
            return jsonify({
                "answer": f"Maaf kijiye, database mein '{keyword}' se related koi deal available nahi hai.",
                "deals": []
            })

        deals_context = [f"- Title: {d['title']} | Price: {d['price']} | Source: {d['source']} | URL: {d['url']}" for d in matched_deals]
        ai_answer = f"Yahan '{keyword}' se related deals hain:"
        if groq_client:
            try:
                context_str = "\n".join(deals_context)
                prompt = (
                    "You are a helpful Loot Deals Assistant. Answer the user's conversational query naturally and highlight the best or cheapest matches based on the data below.\n\n"
                    f"User Query: '{query}'\n\nDatabase Results:\n{context_str}"
                )
                completion = groq_client.chat.completions.create(
                    model="llama3-70b-8192", 
                    messages=[{"role": "user", "content": prompt}], 
                    max_tokens=250, 
                    temperature=0.3
                )
                ai_answer = completion.choices[0].message.content.strip()
            except Exception as e:
                pass

        return jsonify({"answer": ai_answer, "deals": matched_deals})
    except Exception as e:
        print("Search error:", e)
        return jsonify({"answer": "An error occurred while processing your request.", "deals": []})

@app.route("/add_watchlist", methods=["POST"])
def add_watchlist():
    global WATCHED_ITEMS
    
    if request.is_json:
        data = request.json or {}
        url = data.get("url", "").strip()
        try:
            target_price = float(data.get("target_price", 0) or 0)
        except ValueError:
            target_price = 0.0
    else:
        url = request.form.get("url", "").strip()
        try:
            target_price = float(request.form.get("target_price", 0) or 0)
        except ValueError:
            target_price = 0.0

    if not url:
        return jsonify({"status": "error", "message": "URL is required"}), 400
    
    product_title = ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        }
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            if soup.find('meta', property='og:title'):
                product_title = soup.find('meta', property='og:title')['content'].strip()
            elif soup.find('title'):
                product_title = soup.find('title').get_text().strip()
    except Exception as e:
        print(f"Title scrape error: {e}")

    if not product_title or product_title == "Watched Product" or len(product_title) < 3:
        parts = [p for p in url.split('/') if p and p not in ('https:', 'http:', 'www.amazon.in', 'www.flipkart.com', 'dl.flipkart.com', 'dp', 'gp', 'p', 's')]
        if parts:
            longest_part = max(parts, key=len)
            product_title = longest_part.replace('-', ' ').replace('_', ' ').title()
        else:
            product_title = "Custom Watched Item"

    if len(product_title) > 60:
        product_title = product_title[:57] + "..."

    try:
        save_watchlist_item_to_db(product_title, url, "Checking...", target_price)
    except Exception as e:
        if request.is_json:
            return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500
        return f"Database error: {str(e)}", 500

    WATCHED_ITEMS = load_watchlist_from_db()
    
    if not request.is_json:
        return redirect("/")
        
    return jsonify({"status": "success", "message": f"Added: {product_title} (Target: ₹{target_price:,.0f})"})

@app.route("/delete_watchlist", methods=["POST"])
def delete_watchlist():
    global WATCHED_ITEMS
    if request.is_json:
        data = request.json or {}
        url = data.get("url", "").strip()
    else:
        url = request.form.get("url", "").strip()

    if not url:
        return jsonify({"status": "error", "message": "URL is required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM watchlist WHERE url = %s", (url,))
        conn.commit()
        conn.close()
    except Exception as e:
        if request.is_json:
            return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500
        return f"Database error: {str(e)}", 500

    WATCHED_ITEMS = load_watchlist_from_db()
    if not request.is_json:
        return redirect("/")
    return jsonify({"status": "success", "message": "Item deleted from watchlist"})

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
    prefix = "❌" if error else "ℹ"
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

def add_tracker_log(msg: str, is_error: bool = False):
    prefix = "❌" if is_error else "⚡"
    timestamp = datetime.now(IST).strftime("%H:%M:%S")
    line = f"[{timestamp}] {prefix} [Tracker] {msg}"
    print(line)
    TRACKER_LOGS.appendleft({"time": timestamp, "prefix": prefix, "msg": msg, "is_error": is_error})

async def tracker_log(msg: str, error: bool = False):
    add_tracker_log(msg, is_error=error)

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

# Setup proper Python logger for Railway console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("AddToCartDebugger")

def trigger_add_to_cart(url: str, source_site: str, title: str, price_val: float):
    logger.info(f"🛒 [CART-STEP 1] Automation initiated for Product: {title}")
    logger.info(f"🔗 [CART-STEP 2] Target URL: {url}")
    
    success = False
    context = None
    
    try:
        with sync_playwright() as p:
            user_data_dir = "./chrome_profile"
            logger.info(f"🛒 [CART-STEP 3] Launching Persistent Context with profile: {user_data_dir}")
            
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu"
                ],
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            
            page = context.new_page()
            logger.info("🛒 [CART-STEP 4] Navigating to product page...")
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            
            time.sleep(4)
            
            if "amazon" in url.lower():
                logger.info("🛒 [CART-STEP 5A] [Amazon] Searching for 'Add to Cart' selectors...")
                selectors = [
                    "#add-to-cart-button", 
                    "input#add-to-cart-button", 
                    "input[name='submit.add-to-cart']",
                    "#submit\\.add-to-cart"
                ]
                clicked = False
                for sel in selectors:
                    try:
                        if page.is_visible(sel, timeout=4000):
                            page.click(sel, timeout=4000)
                            logger.info(f"✅ [Amazon] Successfully clicked using selector: {sel}")
                            clicked = True
                            break
                    except Exception as err:
                        logger.debug(f"Selector {sel} not interactive: {err}")
                        continue
                success = clicked

            elif "flipkart" in url.lower():
                logger.info("🛒 [CART-STEP 5B] [Flipkart] Searching for 'Add to Cart' selectors...")
                
                # Close any login/promo popups if they appear
                try:
                    close_btn = page.locator("button._2KpZ6l._2doB4z, button._2EdNRl, span._30XB9F").first
                    if close_btn.is_visible(timeout=2000):
                        close_btn.click()
                        logger.info("✖ Closed Flipkart login/promo popup.")
                except:
                    pass

                # Check and handle pincode if blocking
                try:
                    pincode_input = page.locator("input._3704LK, input[name='pincode']").first
                    if pincode_input.is_visible(timeout=2000):
                        pincode_input.fill("302028")
                        page.keyboard.press("Enter")
                        time.sleep(2)
                        logger.info("📍 Entered default pincode for delivery check.")
                except:
                    pass

                try:
                    page.evaluate("window.scrollBy(0, 400)")
                    time.sleep(1)
                except:
                    pass

                selectors = [
                    "text=Add to Cart",
                    "text=ADD TO CART",
                    "button:has-text('Add to Cart')",
                    "button:has-text('ADD TO CART')",
                    "div:has-text('Add to Cart')",
                    "._2KpZ6l._3AWRsL._3vhnxf",
                    ".QqFHMw.vslbG+"
                ]
                
                clicked = False
                for sel in selectors:
                    try:
                        element = page.locator(sel).first
                        if element.is_visible(timeout=3000):
                            element.scroll_into_view_if_needed()
                            element.click(timeout=3000)
                            logger.info(f"✅ [Flipkart] Successfully clicked using selector/text: {sel}")
                            clicked = True
                            break
                    except Exception as err:
                        logger.debug(f"Selector {sel} not interactive: {err}")
                        continue
                success = clicked

            else:
                logger.info("🛒 [CART-STEP 5C] [Generic/Quick Commerce] Searching for cart buttons...")
                try:
                    cart_btn = page.wait_for_selector("button:has-text('Add to Cart'), button:has-text('Add to Bag'), button:has-text('ADD')", timeout=8000)
                    if cart_btn:
                        cart_btn.click()
                        logger.info("✅ [Generic] Clicked cart button successfully!")
                        success = True
                except Exception as e:
                    logger.error(f"❌ [Generic] Cart button search failed: {e}")
            
            # Take debug screenshot and send directly to Telegram queue
            time.sleep(3)
            screenshot_path = "cart_debug_screenshot.png"
            try:
                page.screenshot(path=screenshot_path)
                logger.info("📸 [DEBUG] Screenshot saved.")
                
                # Queue mein daal dein taaki Telegram par photo mil jaye
                caption_text = f"📸 **Cart Debug Screenshot**\n📦 {title}\n🔗 Success: {success}"
                telegram_photo_queue.put((screenshot_path, caption_text))
            except Exception as sc_err:
                logger.error(f"Failed to take screenshot: {sc_err}")

            time.sleep(3)
            if context:
                context.close()
            logger.info("🛒 [CART-STEP 6] Browser session closed gracefully.")
            
    except Exception as e:
        logger.error(f"❌ [CART-FATAL ERROR] Playwright crashed: {str(e)}", exc_info=True)
        if context:
            try:
                context.close()
            except:
                pass

    if success:
        logger.info("🛒 [DB-STEP 7] Cart click was successful, updating database...")
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO added_to_cart (url, title, price, timestamp)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET title = EXCLUDED.title, price = EXCLUDED.price, timestamp = EXCLUDED.timestamp
            """, (url, title, f"₹{price_val:,.0f}", time.time()))
            cursor.execute("DELETE FROM watchlist WHERE url = %s", (url,))
            conn.commit()
            conn.close()
            logger.info(f"📦 [DB SUCCESS] Item successfully moved to 'Added to Cart' table: {title}")
        except Exception as db_err:
            logger.error(f"❌ [DB ERROR] Failed to update database after cart click: {db_err}")
    else:
        logger.warning(f"⚠️ [FAILED] Automation finished with success=False for: {title}. Item remains in watchlist.")

def fetch_live_price(url: str) -> Optional[float]:
    try:
        # Affiliate tracker link ko resolve karke direct product URL banayein
        from deal_sources import resolve_url, canonical_url
        try:
            res_url = resolve_url(url)
            direct_url = canonical_url(res_url) if res_url else url
        except Exception:
            direct_url = url

        target_fetch_url = direct_url
        if BRIDGE_URL:
            target_fetch_url = f"{BRIDGE_URL}/get-data?url={direct_url}"
            logger.info(f"🌉 [BRIDGE ROUTE] Routing through Laptop Bridge for direct URL: {direct_url}")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": "https://www.google.com/"
        }
        
        resp = requests.get(target_fetch_url, headers=headers, timeout=20)
        
        logger.info(f"🔍 [PRICE FETCH] URL: {direct_url} | Status Code: {resp.status_code}")
        
        if resp.status_code != 200:
            logger.warning(f"⚠️ Failed to fetch price, non-200 status code: {resp.status_code}")
            return None
            
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. Flipkart Specific CSS Selectors
        if "flipkart" in direct_url.lower():
            for selector in [".Nx9bqj", "._30jeq3", "._16Jk6d", "._25b18c ._30jeq3"]:
                elem = soup.select_one(selector)
                if elem:
                    cleaned = re.sub(r'[^\d.]', '', elem.get_text())
                    if cleaned:
                        try:
                            val = float(cleaned)
                            if val > 0:
                                return val
                        except:
                            pass

        # 2. Amazon Specific Selector
        if "amazon" in direct_url.lower():
            offscreen_elem = soup.select_one(".a-price .a-offscreen")
            if offscreen_elem:
                cleaned = re.sub(r'[^\d.]', '', offscreen_elem.get_text())
                if cleaned:
                    val = float(cleaned)
                    if val > 0:
                        return val

        # 3. JSON-LD Structured Data Parsing
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if isinstance(data, dict):
                    offers = data.get('offers')
                    if isinstance(offers, dict):
                        p = offers.get('price') or offers.get('lowPrice')
                        if p:
                            val = float(str(p).replace(',', ''))
                            if val > 0:
                                return val
            except:
                pass

        # 4. Meta Tags Fallback
        price_meta = soup.find('meta', property='product:price:amount') or soup.find('meta', property='og:price:amount')
        if price_meta and price_meta.get('content'):
            try:
                val = float(price_meta['content'])
                if val > 0:
                    return val
            except:
                pass
        
        # 5. General Regex Fallback
        text_content = soup.get_text()
        prices = re.findall(r'(?:₹|Rs\.?)\s*([\d,]+(?:\.\d{1,2})?)', text_content, re.IGNORECASE)
        if prices:
            cleaned_prices = []
            for p in prices:
                try:
                    val = float(p.replace(',', ''))
                    if val > 0:
                        cleaned_prices.append(val)
                except:
                    continue
            if cleaned_prices:
                return float(min(cleaned_prices))
                
    except Exception as e:
        print(f"Error fetching live price for {url}: {e}")
        
    return None
    
def price_tracker_worker():
    global WATCHED_ITEMS, CART_ITEMS
    while True:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT title, url, price, target_price FROM watchlist ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            conn.close()
            
            updated_watched_list = []
            
            for row in rows:
                title, url, old_price, target_price = row
                target_price = target_price if target_price is not None else 0.0
                
                price_val = fetch_live_price(url)
                current_price_str = f"₹{price_val:,.0f}" if price_val is not None else old_price
                
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE watchlist SET price = %s, timestamp = %s WHERE url = %s
                """, (str(current_price_str), time.time(), url))
                conn.commit()
                conn.close()
                
                add_tracker_log(f"🟢 DEBUG -> Price: {price_val} | Target: {target_price} | DESTINATION: '{DESTINATION}'")

                if price_val is not None and target_price > 0 and price_val <= target_price:
                    add_tracker_log(f"🟢 DEBUG: IF condition matched! Price ({price_val}) <= Target ({target_price})")
                    alert_msg = (
                        f"🚨🎯 **TARGET PRICE REACHED! ADDING TO CART!** 🎯🚨\n\n"
                        f"📦 **{title}**\n"
                        f"💰 Current Price: ₹{price_val:,.0f}\n"
                        f"🎯 Target Price: ₹{target_price:,.0f}\n"
                        f"🔗 {url}"
                    )
                    
                    if DESTINATION:
                        telegram_alert_queue.put(alert_msg)
                        add_tracker_log("Target price reached! Alert queued for Telegram.")

                    try:
                        add_tracker_log("🚀 [DEBUG] Spawning cart thread...")
                        cart_thread = threading.Thread(
                            target=trigger_add_to_cart, 
                            args=(url, "e-commerce", title, price_val)
                        )
                        cart_thread.start()
                        add_tracker_log("✅ [DEBUG] Cart thread started successfully.")
                    except Exception as ex:
                        add_tracker_log(f"Failed to run add-to-cart automation: {ex}", is_error=True)

                updated_watched_list.append({
                    "title": title[:60] if title else "Watched Item",
                    "price": str(current_price_str),
                    "target_price": target_price,
                    "url": url,
                    "time": datetime.now(IST).strftime("%H:%M:%S")
                })
                
                add_tracker_log(f"Checked '{title[:25]}': {current_price_str} (Target: ₹{target_price:,.0f})")
            
            WATCHED_ITEMS = load_watchlist_from_db()
            CART_ITEMS = load_cart_items_from_db()
            
        except Exception as e:
            add_tracker_log(f"Error in price tracker worker: {str(e)}", is_error=True)
            
        time.sleep(60)

async def process_telegram_alerts():
    while True:
        try:
            if not telegram_alert_queue.empty():
                msg = telegram_alert_queue.get_nowait()
                if DESTINATION:
                    await client.send_message(DESTINATION, msg)
            
            if not telegram_photo_queue.empty():
                photo_path, caption = telegram_photo_queue.get_nowait()
                target_chat = LOG_CHANNEL if LOG_CHANNEL else DESTINATION
                if target_chat:
                    try:
                        await client.send_file(target_chat, photo_path, caption=caption)
                        print(f"✅ Telegram photo sent successfully to {target_chat}")
                    except Exception as send_err:
                        print(f"❌ Telegram photo send FAILED: {send_err}")
        except Exception as e:
            print(f"Telegram queue consumer error: {e}")
        await asyncio.sleep(1)
        
async def process_message(event):
    chat = await event.get_chat()
    chat_identifier = getattr(chat, "username", None) or str(chat.id)
    print(f"📥 Message received from chat: {chat_identifier}")

    if not channel_allowed(chat):
        print(f"⚠ Channel {chat_identifier} is not in WATCH_CHANNELS filter list!")
        return

    text = event.raw_text or ""
    found = urls(text)
    if not found:
        print(f"ℹ️ Message ignored (No URL found): {text[:50]}...")
        return

    text_lower = text.lower()
    promo_keywords = [
        "great indian festival", "big billion days", "sale is live", 
        "sale starts", "upcoming sale", "loot sale live", "festival store", "blockbuster deals live"
    ]
    
    first_url = found[0]
    is_product_url = bool(re.search(r'(/dp/|/gp/|/p/|\?pid=)', first_url, re.I))
    
    if any(pk in text_lower for pk in promo_keywords) and not is_product_url:
        print(f"ℹ Skipped promotional event banner: {text[:50]}...")
        return

    source = f"@{chat.username}" if getattr(chat, "username", None) else str(chat.id)
    message_key = f"{chat.id}:{event.id}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    if not remember_once(message_key):
        return

    from deal_sources import get_offer_price, resolve_url, canonical_url
    
    deal_url = first_url
    try:
        resolved_url = await asyncio.to_thread(resolve_url, first_url)
        if resolved_url:
            deal_url = await asyncio.to_thread(canonical_url, resolved_url)
    except Exception:
        deal_url = first_url

    title = get_smart_title(text, deal_url)
    
    if (not title 
        or title == "Unknown Product" 
        or "amazon.in" in title.lower() 
        or "online shopping site" in title.lower()
        or "flipkart" == title.lower().strip()):
        print(f"ℹ️ Skipped generic/invalid title or homepage: {title}")
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
    dialogs = await client.load_dialogs() if hasattr(client, 'load_dialogs') else await client.get_dialogs()
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

    threading.Thread(target=price_tracker_worker, daemon=True).start()
    await tracker_log("Live Price Tracker worker spawned in parallel background loop.")

    await client.start()
    
    asyncio.create_task(process_telegram_alerts())

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