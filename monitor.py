#!/usr/bin/env python3
"""Blocket.se Volvo V90 monitor – Playwright pro Cloudflare, JSON-LD z HTML."""

import re
import sys
import json
import os
import subprocess
from datetime import datetime, timezone

import requests

TELEGRAM_TOKEN = "8796100241:AAHZpaeWLqHAEZX6Sa855sNhapO3g1LIZUA"
CHAT_ID = 5711350539
SEK_TO_CZK = 2.27
MIN_YEAR = 2020
MAX_PRICE_SEK = 270000

SEARCH_URL = (
    "https://www.blocket.se/annonser/hela_sverige/fordon/bilar"
    "?q=volvo+v90&mj=2020&xp=270000&cg=1020&ca=11"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "sv-SE,sv;q=0.9",
}
SEEN_FILE = "seen_ids.json"


def load_seen_ids():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(ids), f)
    try:
        subprocess.run(["git", "config", "user.email", "monitor@blocket"], check=False)
        subprocess.run(["git", "config", "user.name", "Blocket Monitor"], check=False)
        subprocess.run(["git", "add", SEEN_FILE], check=False)
        r = subprocess.run(["git", "commit", "-m", f"seen_ids: {len(ids)} ID"], capture_output=True, check=False)
        if r.returncode == 0:
            subprocess.run(["git", "push"], check=False)
            print(f"  seen_ids.json uložen ({len(ids)} ID)")
    except Exception as e:
        print(f"  Git: {e}")


def fetch_html_via_playwright():
    """Playwright prochází Cloudflare – vrátí HTML stránky."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language": "sv-SE,sv;q=0.9"},
        )
        context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = context.new_page()
        print(f"  Playwright: načítám stránku...")
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()
    print(f"  HTML: {len(html)} znaků")
    return html


def parse_json_ld(html):
    """Extrahuj inzeráty z JSON-LD (server-rendered, nezávisí na JS)."""
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    for s in scripts:
        try:
            data = json.loads(s)
            items = data.get("mainEntity", {}).get("itemListElement", [])
            if items:
                print(f"  JSON-LD: {len(items)} inzerátů")
                return items
        except Exception:
            pass
    return []


def get_detail(url):
    """Fetch individual listing – extrahuj rok z <title>."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        title_m = re.search(r'<title>([^<]+)</title>', r.text)
        if not title_m:
            return {}
        title = title_m.group(1)
        year_m = re.search(r'\b(20[12]\d)\b', title)
        power_m = re.search(r'(\d+)\s*Hk', title, re.IGNORECASE)
        # Nájezd v meta description
        desc_m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', r.text)
        mileage_km = None
        if desc_m:
            mil_m = re.search(r'(\d[\d\s]+)\s*mil\b', desc_m.group(1))
            km_m = re.search(r'(\d[\d\s]+)\s*km\b', desc_m.group(1))
            if mil_m:
                mileage_km = int(re.sub(r'\s', '', mil_m.group(1))) * 10
            elif km_m:
                mileage_km = int(re.sub(r'\s', '', km_m.group(1)))
        return {
            "year": int(year_m.group(1)) if year_m else None,
            "power_hk": int(power_m.group(1)) if power_m else None,
            "mileage_km": mileage_km,
        }
    except Exception as e:
        print(f"    Detail chyba: {e}")
        return {}


def parse_listing(item):
    it = item.get("item", {})
    url = it.get("url", "")
    lid = re.search(r'/item/(\d+)', url)
    return {
        "id": lid.group(1) if lid else None,
        "name": it.get("name", "Volvo V90"),
        "description": it.get("description", ""),
        "price": int(it.get("offers", {}).get("price", 0) or 0),
        "url": url,
    }


def is_diesel(name, desc):
    text = (name + " " + desc).lower()
    return any(f in text for f in ["d2 ", "d3 ", "d4 ", "d5 ", " diesel"])


def analyze(listing, detail):
    notes = []
    price = listing["price"]
    name = listing["name"].lower()
    desc = listing["description"].lower()
    km = detail.get("mileage_km")

    if price < 210000:
        notes.append("Cena výrazně pod průměrem trhu.")
    elif price < 245000:
        notes.append("Velmi dobrá cena.")
    elif price >= 265000:
        notes.append("Cena na horní hranici — zkontroluj výbavu.")

    if km:
        if km < 60000:
            notes.append(f"Výjimečně nízký nájezd ({km:,} km).".replace(",", " "))
        elif km < 90000:
            notes.append(f"Nízký nájezd ({km:,} km).".replace(",", " "))
        elif km > 120000:
            notes.append("Vyšší nájezd — prověř servisní historii.")

    if "t8" in name + desc or "recharge" in name + desc:
        notes.append("T8 Recharge — nejsilnější V90 s PHEV pohonem.")
    elif "t6" in name + desc:
        notes.append("T6 — silná benzínová verze.")
    if "cross country" in name:
        notes.append("Cross Country má vyšší světlou výšku.")
    if "awd" in name + desc:
        notes.append("Pohon AWD.")

    return " ".join(notes[:3]) or "Nabídka splňuje zadaná kritéria."


def format_msg(listing, detail):
    price = listing["price"]
    price_sek = f"{price:,}".replace(",", " ") if price else "neuvedeno"
    price_czk = f"{round(price * SEK_TO_CZK / 1000) * 1000:,}".replace(",", " ") if price else "—"
    year = detail.get("year", "neuvedeno")
    power = detail.get("power_hk")
    km = detail.get("mileage_km")
    mileage_str = f"{km:,} km".replace(",", " ") if km else "neuvedeno"
    spec = listing["description"]
    if power:
        spec += f" ({power} Hk)"
    note = analyze(listing, detail)
    return (
        f"🚗 <b>{listing['name']}</b>\n\n"
        f"💰 <b>Cena:</b> {price_sek} SEK (~{price_czk} CZK)\n"
        f"📅 <b>Rok výroby:</b> {year}\n"
        f"🛣️ <b>Nájezd:</b> {mileage_str}\n"
        f"⚙️ <b>Specifikace:</b> {spec}\n\n"
        f"💡 <b>Hodnocení:</b> {note}\n\n"
        f'🔗 <a href="{listing["url"]}">Zobrazit inzerát</a>'
    )


def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )
    r.raise_for_status()


def main():
    print(f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")

    html = fetch_html_via_playwright()
    items = parse_json_ld(html)
    if not items:
        print("Žádné inzeráty v JSON-LD.", file=sys.stderr)
        sys.exit(1)

    seen_ids = load_seen_ids()
    print(f"Uložených ID: {len(seen_ids)}")

    new_ids = set()
    sent = 0

    for item in items:
        listing = parse_listing(item)
        lid = listing["id"]
        if not lid:
            continue
        new_ids.add(lid)

        if lid in seen_ids:
            continue

        # Vyřaď diesel
        if is_diesel(listing["name"], listing["description"]):
            print(f"  Diesel vyřazen: {listing['name']}")
            continue

        # Cena
        if listing["price"] > MAX_PRICE_SEK:
            continue

        # Detail stránky (rok)
        print(f"  Nový: {listing['name']} – {listing['price']:,} SEK".replace(",", " "))
        detail = get_detail(listing["url"])

        year = detail.get("year")
        if year and year < MIN_YEAR:
            print(f"    Vyřazen rok {year}")
            continue

        try:
            send_telegram(format_msg(listing, detail))
            sent += 1
            print(f"    ✓ Odesláno")
        except Exception as e:
            print(f"    Telegram: {e}", file=sys.stderr)

    updated = seen_ids | new_ids
    if updated != seen_ids:
        save_seen_ids(updated)

    print(f"Celkem: {len(items)} | Nových: {len(new_ids - seen_ids)} | Odesláno: {sent}")


if __name__ == "__main__":
    main()
