"""PostgreSQL storage helpers for Loot Bot.

This module owns database connection setup and persistence helpers.
Set DATABASE_URL in the environment before starting the application.
"""
import os
import time
from datetime import datetime, timezone, timedelta

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
IST = timezone(timedelta(hours=5, minutes=30))
DEAL_TTL_SECONDS = int(os.getenv("DEAL_TTL_SECONDS", str(7 * 24 * 60 * 60)))


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL connection")
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS keyword_feeds (
                keyword TEXT PRIMARY KEY
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database initialization error: {e}")

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

def load_keyword_feeds_from_db():
    keywords = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT keyword FROM keyword_feeds")
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            keywords.append(row[0])
    except Exception as e:
        print(f"Error loading keyword feeds: {e}")
    return keywords

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


init_db()
