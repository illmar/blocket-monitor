#!/usr/bin/env python3
"""Blocket.se Volvo V90 monitor – requests + JSON-LD + seen_ids deduplication."""

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
ACCEPTED_FUELS = ["bensin", "laddhybrid", "hybrid", "plug-in", "t5", "t6", "t8"]
REJECTED_FUELS = ["diesel", "el ", "etanol", "gas", "d2", "d3", "d4", "d5"]

SEARCH_URL = (
    "https://www.blocket.se/annonser/hela_sverige/fordon/bilar"
    "?q=volvo+v90&mj=2020&xp=270000&cg=1020&ca=11"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
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
        subprocess.run(["git", "commit", "-m", f"Update seen_ids ({len(ids)} IDs)"], check=False)
        subprocess.run(["git", "push"], check=False)
    except Exception as e:
        print(f"  Git commit selhal: {e}")


def fetch_search_listings():
    r = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        r.text, re.DOTALL
    )
    for s in scripts:
        try:
            data = json.loads(s)
            items = data.get("mainEntity", {}).get("itemListElement", [])
            if items:
                return items
        except Exception:
            pass
    return []


def get_listing_detail(url):
    """Stáhni stránku inzerátu a extrahuj rok a nájezd z <title>."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        title_m = re.search(r'<title>([^<]+)</title>', r.text)
        if not title_m:
            return {}
        title = title_m.group(1)
        # Formát: "... Volvo V90 ... - YYYY - Barva - NNN Hk - ..."
        year_m = re.search(r'\b(20[12]\d)\b', title)
        power_m = re.search(r'(\d+)\s*Hk', title, re.IGNORECASE)
        # Hledej nájezd v meta description
        desc_m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', r.text)
        mileage_km = None
        if desc_m:
            # Hledej číslo + mil nebo km
            mil_m = re.search(r'(\d[\d\s]+)\s*mil\b', desc_m.group(1), re.IGNORECASE)
            km_m = re.search(r'(\d[\d\s]+)\s*km\b', desc_m.group(1), re.IGNORECASE)
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
    """Extrahuj data z JSON-LD položky."""
    it = item.get("item", {})
    name = it.get("name", "Volvo V90")
    model = it.get("model", "")
    desc = it.get("description", "")
    price = int(it.get("offers", {}).get("price", 0) or 0)
    url = it.get("url", "")
    listing_id = re.search(r'/item/(\d+)', url)
    listing_id = listing_id.group(1) if listing_id else None
    return {
        "id": listing_id,
        "name": name,
        "model": model,
        "description": desc,
        "price": price,
        "url": url,
    }


def is_accepted_fuel(name, desc):
    """Benzín nebo plug-in hybrid podle názvu/popisu."""
    text = (name + " " + desc).lower()
    # Vyloučit diesel
    if any(f in text for f in ["d2 ", "d3 ", "d4 ", "d5 ", " diesel", "tdi", "cdti"]):
        return False
    # Akceptovat bensin/hybrid
    if any(f in text for f in ["t5", "t6", "t8", "recharge", "plug-in", "laddhybrid", "bensin"]):
        return True
    return None  # Neznámé – nevylučuj


def is_automatic(desc):
    """Automatická převodovka."""
    text = desc.lower()
    if any(t in text for t in ["geartronic", "automat", "automatic"]):
        return True
    if "manuell" in text or "manual" in text:
        return False
    return None  # Neznámé


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

    if "t8" in name or "recharge" in name or "t8" in desc or "recharge" in desc:
        notes.append("T8 Recharge — nejsilnější V90 s PHEV pohonem.")
    elif "t6" in name or "t6" in desc:
        notes.append("T6 — silná benzínová verze.")
    if "cross country" in name:
        notes.append("Cross Country má vyšší světlou výšku.")
    if "awd" in desc or "4wd" in desc or "awd" in name:
        notes.append("Pohon AWD — výhoda pro zimní provoz.")

    return " ".join(notes[:3]) or "Nabídka splňuje zadaná kritéria."


def format_msg(listing, detail):
    name = listing["name"]
    price = listing["price"]
    desc = listing["description"]
    url = listing["url"]

    price_sek = f"{price:,}".replace(",", " ") if price else "neuvedeno"
    price_czk = f"{round(price * SEK_TO_CZK / 1000) * 1000:,}".replace(",", " ") if price else "—"

    year = detail.get("year", "neuvedeno")
    power = detail.get("power_hk")
    km = detail.get("mileage_km")
    mileage_str = f"{km:,} km".replace(",", " ") if km else "neuvedeno"
    motor_str = f"{desc}"
    if power:
        motor_str = f"{desc} ({power} Hk)"
    note = analyze(listing, detail)

    return (
        f"🚗 <b>{name}</b>\n\n"
        f"💰 <b>Cena:</b> {price_sek} SEK (~{price_czk} CZK)\n"
        f"📅 <b>Rok výroby:</b> {year}\n"
        f"🛣️ <b>Nájezd:</b> {mileage_str}\n"
        f"⚙️ <b>Specifikace:</b> {motor_str}\n\n"
        f"💡 <b>Hodnocení:</b> {note}\n\n"
        f'🔗 <a href="{url}">Zobrazit inzerát</a>'
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

    # Načti inzeráty
    try:
        items = fetch_search_listings()
    except Exception as e:
        print(f"Chyba načítání: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Nalezeno: {len(items)} inzerátů")

    # Načti viděné ID
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

        # Nový inzerát — zkontroluj filtry
        price = listing["price"]
        if price > MAX_PRICE_SEK:
            print(f"  Vyřazen (cena {price}): {listing['name']}")
            continue

        fuel_ok = is_accepted_fuel(listing["name"], listing["description"])
        if fuel_ok is False:
            print(f"  Vyřazen (palivo): {listing['name']} – {listing['description'][:50]}")
            continue

        # Stáhni detail pro rok
        print(f"  Nový: {listing['name']} – {price:,} SEK".replace(",", " "))
        detail = get_listing_detail(listing["url"])

        year = detail.get("year")
        if year and year < MIN_YEAR:
            print(f"    Vyřazen (rok {year} < {MIN_YEAR})")
            continue

        # Pošli notifikaci
        try:
            send_telegram(format_msg(listing, detail))
            sent += 1
            print(f"    ✓ Telegram odesláno")
        except Exception as e:
            print(f"    Telegram chyba: {e}", file=sys.stderr)

    # Aktualizuj seen_ids
    updated_ids = seen_ids | new_ids
    if updated_ids != seen_ids:
        save_seen_ids(updated_ids)
        print(f"Uloženo {len(updated_ids)} ID")

    print(f"Odesláno notifikací: {sent}")


if __name__ == "__main__":
    main()
