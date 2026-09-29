# bot_pipeline.py
from __future__ import annotations

from datetime import datetime, timedelta
import chromadb

# Import from our previous modules
from resolve_url import resolve_url, extract_flipkart_identifiers
from target_products import is_target_product

# Initialize Local ChromaDB with persistent storage
chroma_client = chromadb.PersistentClient(path="./loot_db")
collection = chroma_client.get_or_create_collection(name="verified_loot_history")

def process_incoming_deal(short_url: str, product_title: str, current_price: float) -> dict:
    """
    Complete Pipeline:
    1. Resolves short URL and extracts PID.
    2. Validates against target product whitelist (No junk).
    3. Compares with ChromaDB (30-day retention) to check price history.
    4. Saves/Updates record in ChromaDB if valid.
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
        pid = identifiers["itm"] or product_title[:30] # Fallback key if PID missing
        
    # Step 3: Check ChromaDB for 30-Day Price History
    historical_min = current_price
    stored_expiry = None
    
    try:
        existing_record = collection.get(ids=[pid], include=["metadatas"])
        if existing_record and existing_record["metadatas"]:
            meta = existing_record["metadatas"][0]
            old_min = float(meta.get("price", current_price))
            expiry_str = meta.get("expiry")
            
            # Check if record is within 30-day window
            if expiry_str and datetime.utcnow() < datetime.fromisoformat(expiry_str):
                historical_min = min(old_min, current_price)
                print(f"📊 30-Day History Found -> Previous Lowest: Rs.{old_min}")
            else:
                print("⏳ Previous history expired (>30 days). Resetting tracking window.")
    except Exception as e:
        print(f"⚠️ DB lookup notice: {e}")
        
    # Step 4: Save/Update in ChromaDB with 30-Day Expiry TTL
    expiry_date = datetime.utcnow() + timedelta(days=30)
    collection.upsert(
        ids=[pid],
        documents=[product_title],
        metadatas=[{
            "price": float(historical_min),
            "current_price": float(current_price),
            "timestamp": datetime.utcnow().isoformat(),
            "expiry": expiry_date.isoformat(),
            "resolved_url": resolved_url
        }]
    )
    
    print(f"✅ APPROVED & SAVED: Lowest tracked price in last 30 days is Rs.{historical_min}")
    return {
        "status": "approved",
        "pid": pid,
        "resolved_url": resolved_url,
        "historical_min": historical_min,
        "current_price": current_price
    }


if __name__ == "__main__":
    # Test simulation
    test_short_link = "https://fkrt.cc/ha3xGjc"
    test_title = "Whirlpool 192 L Direct Cool Single Door 4 Star Refrigerator" # Should be rejected based on rules
    test_price = 14500.0
    
    process_incoming_deal(test_short_link, test_title, test_price)
    
    # Test with a valid target product (e.g. iPhone)
    iphone_title = "Apple iPhone 15 (128 GB) - Black"
    iphone_price = 58999.0
    process_incoming_deal("https://fkrt.cc/sampleiphone", iphone_title, iphone_price)