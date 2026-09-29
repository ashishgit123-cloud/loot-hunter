from __future__ import annotations

import sys
import re
from urllib.parse import urlparse, parse_qs, quote_plus
import requests  # For fast, lightweight manual redirect resolution
from curl_cffi import requests as curl_requests  # Stealth client to bypass Cloudflare

def resolve_url(short_url: str, max_hops: int = 5) -> str:
    """
    Manually follows redirect chains (301/302) by checking Location headers only.
    Avoids downloading heavy page bodies, preventing read timeouts.
    """
    if not short_url or not short_url.startswith("http"):
        return short_url

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    current_url = short_url
    session = requests.Session()

    for _ in range(max_hops):
        try:
            response = session.head(current_url, headers=headers, allow_redirects=False, timeout=6)
            if response.status_code >= 400:
                response = session.get(current_url, headers=headers, allow_redirects=False, timeout=6, stream=True)
                response.close()

            if 300 <= response.status_code < 400 and "Location" in response.headers:
                next_url = response.headers["Location"]
                if next_url.startswith("/"):
                    parsed = urlparse(current_url)
                    next_url = f"{parsed.scheme}://{parsed.netloc}{next_url}"
                current_url = next_url
            else:
                break
        except Exception as e:
            print(f"⚠️ Resolution hop warning for {current_url}: {e}")
            break

    return current_url


def extract_flipkart_identifiers(resolved_url: str) -> dict:
    """
    Extracts unique pid, itm code, and clean title slug from a resolved Flipkart URL.
    """
    if not resolved_url:
        return {"pid": None, "itm": None, "title_slug": None}
    
    parsed = urlparse(resolved_url)
    
    # 1. Extract 'pid' from query parameters
    query_params = parse_qs(parsed.query)
    pid = query_params.get("pid", [None])[0]
    
    # 2. Extract 'itm' code from path
    itm_match = re.search(r'/p/(itm[a-zA-Z0-9]+)', parsed.path)
    itm = itm_match.group(1) if itm_match else None
    
    # 3. Extract title slug
    path_parts = parsed.path.strip("/").split("/")
    title_slug = ""
    for part in path_parts:
        if part not in ["dl", "p"] and not part.startswith("itm"):
            title_slug = part
            break
            
    return {"pid": pid, "itm": itm, "title_slug": title_slug}


def get_price_history_page_url(resolved_url: str) -> str:
    """
    Uses curl_cffi with browser impersonation to bypass Cloudflare 
    and search pricehistory.app for the correct hashed product URL.
    """
    identifiers = extract_flipkart_identifiers(resolved_url)
    pid = identifiers["pid"]
    itm = identifiers["itm"]
    title_slug = identifiers["title_slug"]
    
    # Query priority: PID -> ITM Code -> Title Slug
    query = pid or itm or title_slug
    if not query:
        return ""
        
    search_url = f"https://pricehistory.app/search?q={quote_plus(query)}"
    
    try:
        # curl_cffi impersonates a real Chrome browser TLS fingerprint
        response = curl_requests.get(search_url, impersonate="chrome110", timeout=10)
        
        if response.status_code == 200:
            # If pricehistory.app directly redirects to the product page
            if "/p/" in response.url and response.url != search_url:
                return response.url
                
            # Parse the search result page for the first matching product link
            html = response.text
            matches = re.findall(r'href=["\'](https://pricehistory\.app/p/[^"\']+|/p/[^"\']+)["\']', html)
            for m in matches:
                if m.startswith("/"):
                    return f"https://pricehistory.app{m}"
                return m
    except Exception as e:
        print(f"⚠️ PriceHistory curl_cffi lookup error: {e}")
        
    return ""


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        test_url = input("🔗 Enter short URL to resolve: ").strip()

    if test_url:
        print(f"\n🔄 Resolving short URL: {test_url} ...")
        resolved = resolve_url(test_url)
        print(f"✨ Final Clean Flipkart URL: {resolved}")
        
        ids = extract_flipkart_identifiers(resolved)
        print(f"🔍 Extracted IDs -> PID: {ids['pid']} | ITM: {ids['itm']}")
        
        print(f"📈 Querying PriceHistory.app using curl_cffi stealth mode...")
        ph_url = get_price_history_page_url(resolved)
        if ph_url:
            print(f"✅ Found PriceHistory Page: {ph_url}")
        else:
            print("❌ Could not bypass or find matching PriceHistory URL.")
    else:
        print("❌ No URL provided.")