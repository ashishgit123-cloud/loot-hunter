from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import traceback
import logging
import sqlite3
from collections import OrderedDict, deque
from typing import Optional
from dataclasses import asdict
from datetime import datetime, timezone

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from flask import Flask, jsonify, render_template, request
import threading

from deal_validator import validate_deal
from deal_models import Verdict
from deal_sources import get_offer_price, resolve_url, canonical_url

# Suppress Flask/Werkzeug HTTP access logs (GET /stats 200 clutter)
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)

VERSION = "5.7"
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

if not API_ID or not API_HASH or not TG_SESSION:
    raise RuntimeError("TG_API_ID, TG_API_HASH and TG_SESSION are required")

client = TelegramClient(StringSession(TG_SESSION), API_ID, API_HASH)
sem = asyncio.Semaphore(MAX_CONCURRENCY)

seen = OrderedDict()

# --- SQLITE DATABASE INITIALIZATION ---
DB_FILE = "loot_history.db"
DEAL_TTL_SECONDS = 2 * 24 * 60 * 60  # 48 Hours

def init_db():
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

init_db()

START_TIME = time.time()
CHANNELS_COUNT = 0
DEALS_SCANNED = 0
RECENT_DEALS = deque(maxlen=15)
POSTED_DEALS = deque(maxlen=15)
RECENT_LOGS = deque(maxlen=50)

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
        return jsonify([])
    
    try:
        purge_old_deals()
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, price, min_price, avg_price, source, url, timestamp 
            FROM historical_deals 
            WHERE title LIKE ? 
            ORDER BY timestamp DESC 
            LIMIT 10
        """, (f"%{query}%",))
        rows = cursor.fetchall()
        conn.close()
        
        matched_deals = []
        for row in rows:
            title, price, min_price, avg_price, source, url, timestamp = row
            matched_deals.append({
                "title": title[:100],
                "price": price,
                "min_price": min_price,
                "avg_price": avg_price,
                "source": source,
                "url": url,
                "time": datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
            })
        return jsonify(matched_deals)
    except Exception as e:
        print(f"Search API error: {e}")
        return jsonify([])

def run_web():
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def purge_old_deals():
    """Automatically purges deals older than 2 days from SQLite."""
    try:
        cutoff = time.time() - DEAL_TTL_SECONDS
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM historical_deals WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception:
        pass


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
    """Restores recent deals from SQLite into memory queues on boot."""
    try:
        purge_old_deals()
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT deal_id, title, price, min_price, avg_price, source, url, verdict, timestamp 
            FROM historical_deals 
            ORDER BY timestamp DESC 
            LIMIT 15
        """)
        rows = cursor.fetchall()
        conn.close()
        
        if rows:
            for row in rows:
                deal_id, title, price, min_price, avg_price, source, url, verdict_val, timestamp = row
                item = {
                    "title": title[:100],
                    "price": price,
                    "min_price": min_price,
                    "avg_price": avg_price,
                    "source": source,
                    "url": url,
                    "time": datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
                }
                RECENT_DEALS.append(item)
                if verdict_val in {Verdict.DEAL.value, Verdict.POSSIBLE_DEAL.value, "DEAL", "POSSIBLE_DEAL"}:
                    POSTED_DEALS.append(item)
            print(f"Restored {len(rows)} deals from SQLite cache.")
    except Exception as e:
        print(f"Error loading SQLite cache: {e}")


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
        if line.startswith(("http://", "https://")):
            continue
        if re.fullmatch(r"[\d₹$€£,.\s]+", line):
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
    RECENT_LOGS.appendleft({
        "time": timestamp,
        "prefix": prefix,
        "msg": msg,
        "is_error": error
    })

    if LOG_CHANNEL:
        try:
            await client.send_message(LOG_CHANNEL, line)
        except Exception:
            pass


def channel_allowed(chat) -> bool:
    if not WATCH_CHANNELS:
        return bool(getattr(chat, "broadcast", False))
    username = (getattr(chat, "username", "") or "").lower().lstrip("@")
    return username in WATCH_CHANNELS


async def send_result(result, source, title, price, final_url):
    if result.verdict not in {Verdict.DEAL, Verdict.POSSIBLE_DEAL}:
        return

    evidence_prices = [item.price for item in result.evidence if item.price and item.price > 100]
    evidence_lows = [item.historical_low for item in result.evidence if item.historical_low and item.historical_low > 100]
    all_prices = evidence_prices + evidence_lows

    min_price_str = f"₹{min(all_prices):,.0f}" if all_prices else "-"
    avg_price_str = f"₹{sum(all_prices)/len(all_prices):,.0f}" if all_prices else "-"

    global POSTED_DEALS
    price_display = f"₹{price:,.0f}" if isinstance(price, (int, float)) else (price if price else "N/A")
    
    posted_item = {
        "title": title[:100],
        "price": price_display,
        "min_price": min_price_str,
        "avg_price": avg_price_str,
        "source": source,
        "url": final_url,
        "time": datetime.now().strftime("%H:%M:%S")
    }
    
    if not POSTED_DEALS or POSTED_DEALS[0]["url"] != final_url:
        POSTED_DEALS.appendleft(posted_item)

    for deal in RECENT_DEALS:
        if deal["url"] == final_url:
            deal["min_price"] = min_price_str
            deal["avg_price"] = avg_price_str

    deal_id = hashlib.sha256(f"{final_url}:{title}".encode()).hexdigest()[:16]
    save_deal_to_sqlite(deal_id, title, price_display, source, final_url, result.verdict.value, min_price_str, avg_price_str)

    emoji = "🔥" if result.verdict == Verdict.DEAL else "🟡"
    e = result.evidence

    lines = [
        f"{emoji} {'VERIFIED DEAL' if result.verdict == Verdict.DEAL else 'POSSIBLE DEAL'}",
        "",
        f"📦 {result.offer.title}",
        f"💰 Telegram price: ₹{result.offer.price:,.0f}",
        f"🎯 Confidence: {result.confidence:.0%}",
        f"🧠 {result.reason}",
    ]

    for item in e:
        bits = [item.provider, item.kind]
        if item.price and item.price > 100:
            bits.append(f"₹{item.price:,.0f}")
        if item.historical_low and item.historical_low > 100:
            bits.append(f"low ₹{item.historical_low:,.0f}")
        lines.append("• " + " | ".join(bits))

    for warning in result.warnings:
        lines.append(f"⚠️ {warning}")

    lines += ["", f"📢 {result.offer.source}", f"🔗 {result.offer.url}"]
    await client.send_message(DESTINATION, "\n".join(lines))


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

    clean_text_snippet = text.replace('\n', ' ')[:80]
    await log(f"📥 [{source}] SCAN: '{clean_text_snippet}' | URL: {first_url}")

    price = await asyncio.to_thread(get_offer_price, text, first_url)
    price_status = f"₹{price}" if price else "Not Found ❌"
    await log(f"💰 [{source}] Price Extracted: {price_status} | Title: {title[:40]}")

    if price and price < MIN_PRICE:
        await log(f"⏭️ [{source}] Skipped: Price ₹{price} is below MIN_PRICE (₹{MIN_PRICE})", error=True)
        return

    deal_url = first_url
    if first_url:
        try:
            resolved_url = await asyncio.to_thread(resolve_url, first_url)
            if resolved_url:
                deal_url = await asyncio.to_thread(canonical_url, resolved_url)
        except Exception as e:
            await log(f"⚠️ [{source}] URL resolution failed for {first_url}: {e}. Falling back to raw URL.", error=True)
            deal_url = first_url

    global DEALS_SCANNED, RECENT_DEALS
    DEALS_SCANNED += 1
    price_display = f"₹{price:,.0f}" if isinstance(price, (int, float)) else (price if price else "N/A")
    
    new_deal_item = {
        "title": title[:100],
        "price": price_display,
        "min_price": "-",
        "avg_price": "-",
        "source": source,
        "url": deal_url,
        "time": datetime.now().strftime("%H:%M:%S")
    }
    
    if not RECENT_DEALS or RECENT_DEALS[0]["url"] != deal_url:
        RECENT_DEALS.appendleft(new_deal_item)

    deal_id = hashlib.sha256(f"{deal_url}:{title}".encode()).hexdigest()[:16]
    save_deal_to_sqlite(deal_id, title, price_display, source, deal_url, "SCANNED", "-", "-")

    for url in found[:3]:
        async with sem:
            try:
                try:
                    res_url = await asyncio.to_thread(resolve_url, url)
                    final_url = (await asyncio.to_thread(canonical_url, res_url)) if res_url else url
                except Exception:
                    final_url = url

                await log(f"🔍 [{source}] Validating URL... Target: {final_url}")

                result = await asyncio.wait_for(
                    validate_deal(title, price, final_url, source, text),
                    timeout=45,
                )

                evidence_prices = [item.price for item in result.evidence if item.price and item.price > 100]
                evidence_lows = [item.historical_low for item in result.evidence if item.historical_low and item.historical_low > 100]
                all_prices = evidence_prices + evidence_lows
                min_found = f"₹{min(all_prices):,.0f}" if all_prices else "Not Found ❌"

                is_err = result.verdict not in {Verdict.DEAL, Verdict.POSSIBLE_DEAL}
                await log(
                    f"🎯 [{source}] Verdict: {result.verdict.value} | TG Price: {price_status} | "
                    f"Evidence MinRef: {min_found} | Reason: {result.reason}",
                    error=is_err
                )
                
                await send_result(result, source, title, price, final_url)
            except asyncio.TimeoutError:
                await log(f"❌ Validation timeout on URL: {url}", error=True)
            except Exception as exc:
                await log(
                    f"❌ Processing error {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                    error=True,
                )


@client.on(events.NewMessage)
async def on_new_message(event):
    try:
        await process_message(event)
    except Exception as exc:
        await log(f"NewMessage error: {type(exc).__name__}: {exc}", error=True)


@client.on(events.MessageEdited)
async def on_edited_message(event):
    try:
        await process_message(event)
    except Exception as exc:
        await log(f"MessageEdited error: {type(exc).__name__}: {exc}", error=True)


async def heartbeat():
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await log(f"HEARTBEAT v{VERSION} | scanned={DEALS_SCANNED} | posted={len(POSTED_DEALS)} | channels={CHANNELS_COUNT} | uptime={get_uptime_string()}")


async def discover():
    global CHANNELS_COUNT
    load_deals_from_sqlite_on_startup()
    dialogs = await client.get_dialogs()
    count = 0
    for dialog in dialogs:
        entity = dialog.entity
        if getattr(entity, "broadcast", False):
            count += 1
    CHANNELS_COUNT = count
    await log(f"Listening to {count} broadcast channels")


async def main():
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    await log(f"Web dashboard thread started")

    await client.start()
    me = await client.get_me()
    await log(f"Started v{VERSION} as @{getattr(me, 'username', None) or me.first_name}")
    await discover()
    hb = asyncio.create_task(heartbeat())
    try:
        await client.run_until_disconnected()
    finally:
        hb.cancel()
        await asyncio.gather(hb, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())