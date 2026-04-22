#!/usr/bin/env python3
"""Blocket.se Volvo V90 monitor – posílá Telegram notifikace pro nové inzeráty."""

import requests
import sys
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN = "8796100241:AAHZpaeWLqHAEZX6Sa855sNhapO3g1LIZUA"
CHAT_ID = 5711350539
HOURS_WINDOW = 13
SEK_TO_CZK = 2.27

MIN_YEAR = 2020
MAX_PRICE_SEK = 270000
MAX_MILEAGE_KM = 140000
ACCEPTED_FUELS = ["bensin", "laddhybrid", "hybrid", "el/bensin", "bensin/el", "plug-in"]
ACCEPTED_TRANSMISSIONS = ["automat", "automatisk", "geartronic"]


def fetch_listings():
    url = "https://api.blocket.se/search_bff/v1/content"
    params = {
        "q": "volvo v90", "cg": "1020", "w": "3", "st": "s",
        "c": "1020", "ca": "11", "is": "1", "lim": "60",
        "mj": str(MIN_YEAR), "xp": str(MAX_PRICE_SEK),
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    }
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def get_param(listing, *keys):
    for p in listing.get("parameters", []):
        label = p.get("label", "").lower()
        if any(k.lower() in label for k in keys):
            return p.get("value", "")
    return ""


def parse_mileage_km(value):
    if not value:
        return None
    digits = "".join(c for c in str(value) if c.isdigit())
    if not digits:
        return None
    m = int(digits)
    return m * 10 if m < 25000 else m  # Swedish mil → km if small number


def is_new(listing):
    t = listing.get("list_time", "")
    if not t:
        return True
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt > datetime.now(timezone.utc) - timedelta(hours=HOURS_WINDOW)
    except Exception:
        return True


def matches(listing):
    if "v90" not in listing.get("subject", "").lower():
        return False, "není V90"
    year_s = get_param(listing, "modellår", "årsmodell", "år")
    if year_s:
        try:
            if int("".join(c for c in year_s if c.isdigit())[:4]) < MIN_YEAR:
                return False, "starý rok"
        except Exception:
            pass
    price = (listing.get("price") or {}).get("value", 0)
    if price and price > MAX_PRICE_SEK:
        return False, "vysoká cena"
    fuel = get_param(listing, "drivmedel", "bränsle").lower()
    if fuel and not any(f in fuel for f in ACCEPTED_FUELS):
        return False, f"palivo: {fuel}"
    trans = get_param(listing, "växellåda", "transmission").lower()
    if trans and not any(t in trans for t in ACCEPTED_TRANSMISSIONS):
        return False, f"převodovka: {trans}"
    mileage_raw = get_param(listing, "miltal", "körsträcka")
    km = parse_mileage_km(mileage_raw)
    if km and km > MAX_MILEAGE_KM:
        return False, f"nájezd {km} km"
    return True, "OK"


def analyze(listing, km, price, year_s):
    notes = []
    s = listing.get("subject", "").lower()
    if price:
        if price < 210000:
            notes.append("Cena výrazně pod průměrem trhu — stojí za pozornost.")
        elif price < 245000:
            notes.append("Velmi dobrá cena pro tento model a rok.")
        elif price < 265000:
            notes.append("Cena odpovídá tržní hodnotě.")
        else:
            notes.append("Cena na horní hranici — zkontroluj výbavu.")
    if km:
        if km < 50000:
            notes.append(f"Výjimečně nízký nájezd ({km:,} km).".replace(",", " "))
        elif km < 80000:
            notes.append(f"Nízký nájezd ({km:,} km).".replace(",", " "))
        elif km > 115000:
            notes.append(f"Vyšší nájezd ({km:,} km) — doporučuji prověřit servisní historii.".replace(",", " "))
    if "t8" in s or "recharge" in s:
        notes.append("T8 Recharge je nejsilnější varianta V90 (390 hp) s PHEV pohonem.")
    elif "t6" in s:
        notes.append("T6 nabízí solidní výkon při benzínovém provozu.")
    if "cross country" in s:
        notes.append("Cross Country má vyšší světlou výšku — vhodný i do mírného terénu.")
    if "awd" in s or "4wd" in s:
        notes.append("Pohon AWD — výhoda pro zimní provoz.")
    return " ".join(notes[:3]) or "Nabídka splňuje všechna zadaná kritéria."


def format_msg(listing):
    subject = listing.get("subject", "Volvo V90")
    price = (listing.get("price") or {}).get("value", 0)
    price_sek = f"{price:,}".replace(",", " ") if price else "neuvedeno"
    price_czk = f"{round(price * SEK_TO_CZK / 1000) * 1000:,}".replace(",", " ") if price else "—"
    year_s = get_param(listing, "modellår", "årsmodell", "år") or "neuvedeno"
    mileage_raw = get_param(listing, "miltal", "körsträcka")
    km = parse_mileage_km(mileage_raw)
    mileage_str = f"{km:,} km".replace(",", " ") if km else "neuvedeno"
    fuel = get_param(listing, "drivmedel", "bränsle") or "neuvedeno"
    effect = get_param(listing, "hästkrafter", "effekt")
    motor_str = f"{fuel}, {effect} hp" if effect else fuel
    drivetrain = get_param(listing, "drivning", "drift") or "neuvedeno"
    loc = listing.get("location", [])
    if isinstance(loc, list) and loc:
        parts = [l.get("name", "") for l in loc[:2] if isinstance(l, dict)]
        location_str = ", ".join(p for p in parts if p) or "neuvedeno"
    else:
        location_str = "neuvedeno"
    url = listing.get("ad_link") or listing.get("share_url") or "https://www.blocket.se"
    try:
        year = int("".join(c for c in year_s if c.isdigit())[:4])
    except Exception:
        year = 0
    note = analyze(listing, km, price, year_s)
    return (
        f"🚗 <b>{subject}</b>\n\n"
        f"💰 <b>Cena:</b> {price_sek} SEK (~{price_czk} CZK)\n"
        f"📅 <b>Rok výroby:</b> {year_s}\n"
        f"🛣️ <b>Nájezd:</b> {mileage_str}\n"
        f"⚙️ <b>Motor:</b> {motor_str}\n"
        f"🚙 <b>Pohon:</b> {drivetrain}\n"
        f"📍 <b>Lokalita:</b> {location_str}\n\n"
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
    try:
        listings = fetch_listings()
    except Exception as e:
        print(f"Chyba načítání: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Nalezeno celkem: {len(listings)}")

    matching = [l for l in listings if matches(l)[0]]
    print(f"Po filtrech: {len(matching)}")

    new = [l for l in matching if is_new(l)]
    print(f"Nových (posledních {HOURS_WINDOW} h): {len(new)}")

    sent = 0
    for l in new:
        try:
            send_telegram(format_msg(l))
            sent += 1
            print(f"  Odesláno: {l.get('subject')}")
        except Exception as e:
            print(f"  Telegram chyba: {e}", file=sys.stderr)

    print(f"Odesláno notifikací: {sent}")


if __name__ == "__main__":
    main()
