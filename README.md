# Loot Hunter v4

This version treats Telegram deals as **untrusted claims**.

## Design

Telegram -> extraction -> retailer URL -> independent evidence -> deterministic evaluation -> output.

PriceHistory is one evidence provider, not the truth source.

## Important behavior

- No permanent database of rejected deals.
- Only a short-lived in-memory dedup cache is kept.
- Historical low alone does not create a high-confidence deal.
- A current retailer price and historical evidence are kept separate.
- Unknown evidence produces `UNKNOWN`, not a fake deal.
- Telegram claimed MRP/discount is not trusted as proof.
- Validation is concurrency-limited.
- Each message is deduplicated by channel/message/content fingerprint.
- Explicit channel allow-list is supported.
- Provider failures fail closed.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env
python loot_listener.py
```

## Extending providers

Add licensed APIs as provider functions in `deal_sources.py`.

A provider should return evidence such as:

- current price
- historical low
- typical/median price
- timestamp
- source URL
- provider confidence

Do not make a provider return `DEAL` directly.

## Why this is different from the old version

The old implementation accepted `NEW_LOW`/`NEAR_LOW` based primarily on one scraped historical low. v4 requires independent evidence and exposes uncertainty instead of converting missing/ambiguous data into a positive result.
