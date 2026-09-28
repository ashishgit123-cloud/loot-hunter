from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import traceback
from collections import OrderedDict
from typing import Optional
from dataclasses import asdict
from datetime import datetime, timezone

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from deal_validator import validate_deal
from deal_models import Verdict
# Yahan deal_sources hi use kiya gaya hai (no changes to filename)
from deal_sources import get_offer_price


VERSION = "4.1"
load_dotenv()

API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "")
DESTINATION = os.getenv("DESTINATION", "lootersAmer")
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "")

# Only channels explicitly listed here are processed.
# Empty means all broadcast channels visible to the account.
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

# Short-lived dedup only. This is NOT deal history.
seen = OrderedDict()


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
    line = f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {prefix} {msg}"
    print(line)
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


async def send_result(result):
    if result.verdict not in {Verdict.DEAL, Verdict.POSSIBLE_DEAL}:
        return

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
        if item.price:
            bits.append(f"₹{item.price:,.0f}")
        if item.historical_low:
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

    # Message-level dedup: edited messages can arrive more than once.
    message_key = f"{chat.id}:{event.id}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    if not remember_once(message_key):
        return

    title = title_from(text)

    # Usually first product URL is the deal URL. Validate multiple URLs only
    # when they resolve to distinct product pages.
    for url in found[:3]:
        async with sem:
            try:
                # Smart Fallback: Text se price lo, agar N/A ho toh url se fetch karo
                first_url = found[0] if found else None
                price = await asyncio.to_thread(get_offer_price, text, first_url)

                # MIN_PRICE validation check
                if price and price < MIN_PRICE:
                    continue

                result = await asyncio.wait_for(
                    validate_deal(title, price, url, source, text),
                    timeout=45,
                )
                await log(
                    f"{source} | {result.verdict.value} | "
                    f"{title[:80]} | ₹{price if price else 'N/A'} | "
                    f"{result.reason}"
                )
                await send_result(result)
            except asyncio.TimeoutError:
                await log(f"Validation timeout: {url}", error=True)
            except Exception as exc:
                await log(
                    f"Processing error {type(exc).__name__}: {exc}\n"
                    f"{traceback.format_exc()}",
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
        await log(f"HEARTBEAT v{VERSION} | dedup={len(seen)} | concurrency={MAX_CONCURRENCY}")


async def discover():
    dialogs = await client.get_dialogs()
    count = 0
    for dialog in dialogs:
        entity = dialog.entity
        if getattr(entity, "broadcast", False):
            count += 1
    await log(f"Listening to {count} broadcast channels")


async def main():
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