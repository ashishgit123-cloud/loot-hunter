# target_products.py
from __future__ import annotations

import re

# Allowed Categories & Keywords Configuration
ALLOWED_CONFIG = {
    "phones": {
        "brands": ["iphone", "apple", "samsung"],
        "sub_filter": lambda title: "iphone" in title or ("samsung" in title and "ultra" in title)
    },
    "powerbanks": {
        "keywords": ["powerbank", "power bank"],
        "sub_filter": lambda title: any(k in title for k in ["magsafe", "magnetic", "iphone", "wireless", "type-c pd", "22.5w", "65w", "fast charging"])
    },
    "fans": {
        "keywords": ["bldc", "luxury fan", "ventilator", "ceiling fan"],
        "sub_filter": lambda title: any(k in title for k in ["bldc", "luxury", "ventilator", "ceiling fan"])
    },
    "worthy_electronics": {
        # Aap yahan aur bhi high-demand categories ya high-value electronics add kar sakte hain
        "keywords": ["oled tv", "ipad", "macbook", "smartwatch ultra"]
    }
}

def is_target_product(product_title: str) -> bool:
    """
    Strictly checks if the incoming product title matches the user's whitelist criteria.
    Rejects junk immediately.
    """
    if not product_title:
        return False
        
    title = product_title.lower()
    
    # 1. Check Phones (Only iPhone & Samsung Ultra)
    if "iphone" in title or "apple" in title:
        return True
    if "samsung" in title and "ultra" in title:
        return True
        
    # 2. Check Powerbanks (iPhone supported / MagSafe / Fast PD)
    if "powerbank" in title or "power bank" in title:
        if any(w in title for w in ["magsafe", "magnetic", "wireless", "pd", "fast", "iphone"]):
            return True
            
    # 3. Check Fans (BLDC Luxury & Ventilator Ceiling Fans)
    if any(f in title for f in ["bldc", "ventilator", "luxury fan"]):
        return True
        
    # 4. Check Worthy Electronics (Tablets, Premium TVs, MacBooks)
    if any(e in title for e in ["ipad", "macbook", "oled tv", "apple watch ultra"]):
        return True
        
    return False