#!/usr/bin/env python3
"""Blocket.se Volvo V90 monitor – DOM extrakce po GDPR souhlasu."""

import sys
import json
import re
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

SEARCH_URL = (
    "https://www.blocket.se/annonser/hela_sverige/fordon/bilar"
    "?q=volvo+v90&mj=2020&xp=270000&cg=1020&ca=11"
)


def fetch_listings():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8"},
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = context.new_page()

        # Zachyť JSON inzeráty z API
        captured = []
        def on_response(response):
            if "blocket.se" not in response.url:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                data = response.json()
                def find_ads(obj, depth=0):
                    if depth > 5: return []
                    if isinstance(obj, list) and obj:
                        if isinstance(obj[0], dict) and any(k in obj[0] for k in ["ad_id","subject","list_time"]):
                            return obj
                    if isinstance(obj, dict):
                        for v in obj.values():
                            r = find_ads(v, depth+1)
                            if r: return r
                    return []
                found = find_ads(data)
                if found:
                    captured.extend(found)
                    print(f"  ✓ API: {len(found)} inzerátů z {response.url[:60]}")
            except Exception:
                pass

        page.on("response", on_response)

        print(f"  Načítám: {SEARCH_URL[:60]}...")
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=40000)

        # Akceptuj GDPR dialog
        for selector in [
            "button:has-text('Godkänn alla')",
            "button:has-text('Accept all')",
            "[id*='accept'] button",
            ".sp-message-container button:first-child",
        ]:
            try:
                btn = page.wait_for_selector(selector, timeout=5000)
                if btn:
                    btn.click()
                    print(f"  ✓ GDPR akceptován ({selector})")
                    break
            except Exception:
                pass

        # Čekej na výsledky
        page.wait_for_timeout(8000)

        # Screenshot
        page.screenshot(path="screenshot.png")
        print(f"  API výsledky: {len(captured)}")

        # Ulož HTML pro analýzu
        html = page.content()
        with open("page.html", "w") as f:
            f.write(html)
        print(f"  HTML uložen ({len(html)} znaků)")

        browser.close()
    return captured


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
    return m * 10 if m < 25000 else m


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
    subject = listing.get("subject", "").lower()
    if "v90" not in subject:
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
    km = parse_mileage_km(get_param(listing, "miltal", "körsträcka"))
    if km and km > MAX_MILEAGE_KM:
        return False, f"nájezd {km} km"
    return True, "OK"


def format_msg(listing):
    subject = listing.get("subject", "Volvo V90")
    price = (listing.get("price") or {}).get("value", 0)
    price_sek = f"{price:,}".replace(",", " ") if price else "neuvedeno"
    price_czk = f"{round(price * SEK_TO_CZK / 1000) * 1000:,}".replace(",", " ") if price else "—"
    year_s = get_param(listing, "modellår", "årsmodell", "år") or "neuvedeno"
    km = parse_mileage_km(get_param(listing, "miltal", "körsträcka"))
    mileage_str = f"{km:,} km".replace(",", " ") if km else "neuvedeno"
    fuel = get_param(listing, "drivmedel", "bränsle") or "neuvedeno"
    effect = get_param(listing, "hästkrafter", "effekt")
    motor_str = f"{fuel}, {effect} hp" if effect else fuel
    drivetrain = get_param(listing, "drivning", "drift") or "neuvedeno"
    loc = listing.get("location", [])
    location_str = ", ".join(
        l.get("name", "") for l in (loc[:2] if isinstance(loc, list) else [])
        if isinstance(l, dict) and l.get("name")
    ) or "neuvedeno"
    url = listing.get("ad_link") or listing.get("share_url") or "https://www.blocket.se"
    s = listing.get("subject", "").lower()
    notes = []
    if price < 210000:
        notes.append("Cena výrazně pod průměrem trhu.")
    elif price < 245000:
        notes.append("Velmi dobrá cena.")
    if km and km < 60000:
        notes.append(f"Nízký nájezd ({km:,} km).".replace(",", " "))
    if "t8" in s or "recharge" in s:
        notes.append("T8 Recharge — nejsilnější V90 s PHEV pohonem.")
    if "cross country" in s:
        notes.append("Cross Country má vyšší světlou výšku.")
    note = " ".join(notes) or "Nabídka splňuje kritéria."
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
    import requests
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )
    r.raise_for_status()


def main():
    import requests  # noqa
    print(f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        listings = fetch_listings()
    except Exception as e:
        print(f"Chyba: {e}", file=sys.stderr)
        sys.exit(1)

    matching = [l for l in listings if matches(l)[0]]
    new = [l for l in matching if is_new(l)]
    print(f"Celkem: {len(listings)} | Filtr: {len(matching)} | Nové: {len(new)}")

    sent = 0
    for l in new:
        try:
            send_telegram(format_msg(l))
            sent += 1
            print(f"  ✓ {l.get('subject')}")
        except Exception as e:
            print(f"  Telegram chyba: {e}", file=sys.stderr)
    print(f"Odesláno: {sent}")


if __name__ == "__main__":
    main()
