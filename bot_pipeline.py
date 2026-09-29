# bot_pipeline.py
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

# Import from our previous modules
from resolve_url import resolve_url, extract_flipkart_identifiers
from target_products import is_target_product

# Initialize Local SQLite Database (Super fast, zero RAM overhead)
DB_FILE = "loot_history.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            pid TEXT PRIMARY KEY,
            title TEXT,
            price REAL,
            expiry TEXT,
            resolved_url TEXT
        )
    """)
    conn.commit()
    conn.close()

# Initialize table on startup
init_db()


def process_incoming_deal(short_url: str, product_title: str, current_price: float) -> dict:
    """
    Lightning-fast pipeline using SQLite for 30-day history tracking.
    """
    print(f"\n🔍 Processing deal: {product_title} | Price: Rs.{current_price}")
    
    # Step 1: Whitelist Filter Check
    if not is_target_product(product_title):
        print("❌ REJECTED: Product does not match target whitelist criteria.")
        return {"status": "rejected", "reason": "not_in_whitelist"}
        
    # Step 2: Resolve URL & Get Identifiers
    resolved_url = resolve_url(short_url)
    identifiers = extract_flipkart_identifiers(resolved_url)
    pid = identifiers["pid"]
    
    if not pid:
        print("⚠️ Warning: Could not find PID in resolved URL. Using fallback identifier...")
        pid = identifiers["itm"] or product_title[:30]
        
    historical_min = current_price
    now = datetime.utcnow()
    
    # Step 3: Check SQLite for 30-Day Price History
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT price, expiry FROM price_history WHERE pid = ?", (pid,))
    row = cursor.fetchone()
    
    if row:
        old_min, expiry_str = row
        if expiry_str and now < datetime.fromisoformat(expiry_str):
            historical_min = min(float(old_min), current_price)
            print(f"📊 30-Day History Found -> Previous Lowest: Rs.{old_min}")
        else:
            print("⏳ Previous history expired (>30 days). Resetting tracking window.")
            
    # Step 4: Save/Update in SQLite with 30-Day Expiry TTL
    expiry_date = (now + timedelta(days=30)).isoformat()
    cursor.execute("""
        INSERT INTO price_history (pid, title, price, expiry, resolved_url)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(pid) DO UPDATE SET
            price = excluded.price,
            expiry = excluded.expiry,
            resolved_url = excluded.resolved_url
    """, (pid, product_title, historical_min, expiry_date, resolved_url))
    
    conn.commit()
    conn.close()
    
    print(f"✅ APPROVED & SAVED: Lowest tracked price in last 30 days is Rs.{historical_min}")
    return {
        "status": "approved",
        "pid": pid,
        "resolved_url": resolved_url,
        "historical_min": historical_min,
        "current_price": current_price
    }