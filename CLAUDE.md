# Blocket.se – Volvo V90 Monitor

Okamžitě spusť monitorovací úkol níže. Neanalyzuj repozitář, nepiš kód, neklás otázky.

## Úkol

Najdi nové inzeráty Volvo V90 na blocket.se přidané za posledních 13 hodin a pošli Telegram notifikace pro každý vyhovující inzerát.

## Kritéria

- Model: Volvo V90 nebo Volvo V90 Cross Country (obě varianty)
- Rok výroby: 2020 nebo novější
- Maximální cena: 270 000 SEK
- Palivo: benzín (bensin) nebo plug-in hybrid (PHEV / Recharge / laddhybrid)
- Pohon: AWD nebo FWD
- Převodovka: automatická (automat / Geartronic)
- Maximální nájezd: 140 000 km

## Krok 1: Získej inzeráty z blocket.se

Spusť tento příkaz:

```bash
curl -s "https://api.blocket.se/search_bff/v1/content?q=volvo+v90&cg=1020&w=3&st=s&c=1020&ca=11&is=1&lim=60&mj=2020&xp=270000&xl=140000" \
  -H "Accept: application/json" \
  -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
```

Pokud vrátí chybu nebo prázdná data, zkus:

```bash
curl -s "https://www.blocket.se/annonser/hela_sverige/fordon/bilar?q=volvo+v90&mj=2020&xp=270000&xl=140000" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -H "Accept-Language: sv-SE,sv;q=0.9" -L
```

Analyzuj odpověď a extrahuj seznam inzerátů s atributy: ID, název, rok, cena, nájezd, palivo, pohon, převodovka, lokalita, datum přidání, URL.

## Krok 2: Filtruj podle kritérií

Zachovej pouze inzeráty splňující VŠECHNA kritéria. Pokud atribut chybí, inzerát nevyřazuj — uveď "neuvedeno".

## Krok 3: Filtr nových inzerátů

Zachovej pouze inzeráty přidané za posledních 13 hodin od aktuálního UTC času.

## Krok 4: Odešli Telegram notifikace

Pro každý vyhovující inzerát odešli zprávu:

```bash
curl -s -X POST "https://api.telegram.org/bot8796100241:AAHZpaeWLqHAEZX6Sa855sNhapO3g1LIZUA/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{"chat_id": 5711350539, "text": "ZPRAVA", "parse_mode": "HTML"}'
```

Formát zprávy v češtině:

```
🚗 <b>Volvo V90 [Cross Country] [rok]</b>

💰 <b>Cena:</b> [X] SEK (~[X×2.27 zaokr. na 1000] CZK)
📅 <b>Rok výroby:</b> [rok]
🛣️ <b>Nájezd:</b> [X] km
⚙️ <b>Motor:</b> [palivo, výkon]
🚙 <b>Pohon:</b> AWD / FWD
📍 <b>Lokalita:</b> [město, kraj]

💡 <b>Hodnocení:</b> [2–4 věty proč je nabídka zajímavá nebo na co si dát pozor]

🔗 <a href="[URL]">Zobrazit inzerát</a>
```

Pokud nejsou žádné nové vyhovující inzeráty, nic neposílej.

## Krok 5: Log

Na konci vypiš:
- Aktuální UTC čas
- Celkem nalezeno inzerátů Volvo V90
- Po aplikaci filtrů kritérií
- Přidáno za posledních 13 hodin
- Odesláno Telegram notifikací
