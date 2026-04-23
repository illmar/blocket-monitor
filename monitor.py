#!/usr/bin/env python3
"""Blocket.se Volvo V90 monitor – Firecrawl + JSON-LD + Actions cache."""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
FIRECRAWL_API_KEY = os.environ["FIRECRAWL_API_KEY"]

SEK_TO_CZK = 2.27
MIN_YEAR = 2020
MAX_PRICE_SEK = 270000
SEARCH_URL = (
    "https://www.blocket.se/annonser/hela_sverige/fordon/bilar"
    "?q=volvo+v90&mj=2020&xp=270000&cg=1020&ca=11"
)
SEEN_FILE = Path("seen_ids.json")
DIESEL_RE = re.compile(r'\b(d[2-5]|diesel|tdi|cdti)\b', re.IGNORECASE)


def firecrawl_scrape(url: str) -> str:
    r = requests.post(
        "https://api.firecrawl.dev/v1/scrape",
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
        json={"url": url, "formats": ["rawHtml"], "onlyMainContent": False},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["data"]["rawHtml"]


def parse_listings(html: str) -> list[dict]:
    for s in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    ):
        try:
            items = json.loads(s).get("mainEntity", {}).get("itemListElement", [])
        except json.JSONDecodeError:
            continue
        if not items:
            continue
        return [
            {
                "id": m.group(1),
                "name": it.get("name", "Volvo V90"),
                "description": it.get("description", ""),
                "price": int(it.get("offers", {}).get("price", 0) or 0),
                "url": it.get("url", ""),
            }
            for item in items
            if (it := item.get("item", {}))
            and (m := re.search(r"/item/(\d+)", it.get("url", "")))
        ]
    return []


def fetch_detail(url: str) -> dict:
    try:
        html = firecrawl_scrape(url)
    except Exception:
        return {}
    title = (re.search(r"<title>([^<]+)</title>", html) or [None, ""])[1]
    desc = (re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', html) or [None, ""])[1]
    year = (re.search(r"\b(20[12]\d)\b", title) or [None, None])[1]
    power = (re.search(r"(\d+)\s*Hk", title, re.IGNORECASE) or [None, None])[1]
    mil_m = re.search(r'"key":"mileage","value":\["(\d+)"\]', html)
    mileage = int(mil_m.group(1)) * 10 if mil_m else None
    return {
        "year": int(year) if year else None,
        "power_hk": int(power) if power else None,
        "mileage_km": mileage,
    }


def analyze(listing: dict, detail: dict) -> str:
    price = listing["price"]
    text = (listing["name"] + " " + listing["description"]).lower()
    km = detail.get("mileage_km")
    notes = []

    if price < 210000:
        notes.append("Cena výrazně pod průměrem trhu.")
    elif price < 245000:
        notes.append("Velmi dobrá cena.")
    elif price >= 265000:
        notes.append("Cena na horní hranici — zkontroluj výbavu.")

    if km:
        km_str = f"{km:,} km".replace(",", " ")
        if km < 60000:
            notes.append(f"Výjimečně nízký nájezd ({km_str}).")
        elif km < 90000:
            notes.append(f"Nízký nájezd ({km_str}).")
        elif km > 120000:
            notes.append("Vyšší nájezd — prověř servisní historii.")

    if "t8" in text or "recharge" in text:
        notes.append("T8 Recharge — nejsilnější V90 s PHEV pohonem.")
    elif "t6" in text:
        notes.append("T6 — silná benzínová verze.")
    if "cross country" in text:
        notes.append("Cross Country má vyšší světlou výšku.")
    if "awd" in text:
        notes.append("Pohon AWD.")

    return " ".join(notes[:3]) or "Nabídka splňuje zadaná kritéria."


def format_msg(listing: dict, detail: dict) -> str:
    price = listing["price"]
    price_sek = f"{price:,}".replace(",", " ") if price else "neuvedeno"
    price_czk = f"{round(price * SEK_TO_CZK / 1000) * 1000:,}".replace(",", " ") if price else "—"
    km = detail.get("mileage_km")
    km_str = f"{km:,} km".replace(",", " ") if km else "neuvedeno"
    spec = listing["description"]
    if power := detail.get("power_hk"):
        spec += f" ({power} Hk)"
    return (
        f"🚗 <b>{listing['name']}</b>\n\n"
        f"💰 <b>Cena:</b> {price_sek} SEK (~{price_czk} CZK)\n"
        f"📅 <b>Rok výroby:</b> {detail.get('year', 'neuvedeno')}\n"
        f"🛣️ <b>Nájezd:</b> {km_str}\n"
        f"⚙️ <b>Specifikace:</b> {spec}\n\n"
        f"💡 <b>Hodnocení:</b> {analyze(listing, detail)}\n\n"
        f'🔗 <a href="{listing["url"]}">Zobrazit inzerát</a>'
    )


def send_telegram(text: str) -> None:
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )
    r.raise_for_status()


def main() -> None:
    print(f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")

    html = firecrawl_scrape(SEARCH_URL)
    listings = parse_listings(html)
    if not listings:
        sys.exit("Žádné inzeráty v JSON-LD.")

    seen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()
    print(f"Uložených ID: {len(seen)} | Nalezeno: {len(listings)}")

    sent = 0
    new_ids = set()
    for listing in listings:
        new_ids.add(listing["id"])
        if listing["id"] in seen:
            continue
        if DIESEL_RE.search(listing["name"] + " " + listing["description"]):
            continue
        if listing["price"] > MAX_PRICE_SEK:
            continue

        detail = fetch_detail(listing["url"])
        if (y := detail.get("year")) and y < MIN_YEAR:
            continue

        try:
            send_telegram(format_msg(listing, detail))
            sent += 1
            print(f"  ✓ {listing['name']} – {listing['price']:,} SEK".replace(",", " "))
        except Exception as e:
            print(f"  Telegram: {e}", file=sys.stderr)

    SEEN_FILE.write_text(json.dumps(sorted(seen | new_ids)))
    print(f"Odesláno: {sent}")


if __name__ == "__main__":
    main()
