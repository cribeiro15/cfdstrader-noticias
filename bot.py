"""
CFDsTrader · Bot de noticias de mercado
Lee feeds RSS y el calendario de ForexFactory y los publica en un canal de
Discord mediante un webhook. Pensado para ejecutarse cada 15 min en GitHub Actions.

Variables de entorno:
  DISCORD_WEBHOOK_URL  (obligatoria) URL del webhook del canal #información
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
STATE_FILE = Path(__file__).with_name("seen.json")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
UA = "Mozilla/5.0 (compatible; CFDsTraderNewsBot/1.0)"

# nombre, url, color del embed, máximo de publicaciones por ejecución
FEEDS = [
    ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss", 0x000000, 4),
    ("Wall Street Journal",
     "https://news.google.com/rss/search?q=site:wsj.com+markets+when:1d&hl=en-US&gl=US&ceid=US:en",
     0x0080C3, 4),
    ("Financial Times", "https://www.ft.com/markets?format=rss", 0xFCD0B1, 4),
    ("Yahoo Finance",
     "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC,%5EIXIC,%5EDJI&region=US&lang=en-US",
     0x6001D2, 4),
    ("Investing.com", "https://www.investing.com/rss/news.rss", 0xF7A21B, 4),
    ("TradingView · Ideas", "https://www.tradingview.com/feed/", 0x2962FF, 2),
]

FOREXFACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FOREXFACTORY_HOUR = 7          # hora de Madrid a partir de la que se publica el calendario del día
MAX_SEEN_PER_FEED = 400        # tamaño del historial para no repetir noticias
MAX_AGE_HOURS = 24             # ignorar noticias más antiguas que esto


# ---------------------------------------------------------------- utilidades

def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def clean(text: str, limit: int) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_date(raw: str):
    if not raw:
        return None
    raw = raw.strip()
    try:
        d = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        d = None
    if d is None:
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
            try:
                d = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if d is not None and d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(el, name: str) -> str:
    for c in el:
        if local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_feed(xml_bytes: bytes):
    """Devuelve [{id, title, link, summary, date}] para RSS 2.0 y Atom."""
    root = ET.fromstring(xml_bytes)
    items = []
    for el in root.iter():
        tag = local(el.tag)
        if tag not in ("item", "entry"):
            continue
        title = child_text(el, "title")
        link = child_text(el, "link")
        if not link:  # Atom
            for c in el:
                if local(c.tag) == "link" and c.get("href"):
                    link = c.get("href")
                    break
        guid = child_text(el, "guid") or child_text(el, "id") or link or title
        summary = child_text(el, "description") or child_text(el, "summary")
        date = parse_date(child_text(el, "pubDate") or child_text(el, "published")
                          or child_text(el, "updated"))
        if title and link:
            items.append({"id": guid, "title": title, "link": link,
                          "summary": summary, "date": date})
    return items


def post(payload: dict) -> bool:
    data = json.dumps(payload).encode()
    for attempt in range(3):
        req = urllib.request.Request(WEBHOOK, data=data, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": UA})
        try:
            urllib.request.urlopen(req, timeout=20)
            time.sleep(1.2)  # respetar el límite de Discord
            return True
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = float(json.loads(e.read() or b"{}").get("retry_after", 2))
                time.sleep(wait + 0.5)
                continue
            print(f"  ! Discord respondió {e.code}: {e.read()[:200]!r}")
            return False
        except urllib.error.URLError as e:
            print(f"  ! Error de red con Discord: {e}")
            time.sleep(2)
    return False


# ---------------------------------------------------------------- noticias

def run_feeds(state: dict, first_run: bool) -> None:
    now = datetime.now(timezone.utc)
    for name, url, color, max_posts in FEEDS:
        try:
            items = parse_feed(fetch(url))
        except Exception as e:  # una fuente caída no debe parar al resto
            print(f"✗ {name}: no se pudo leer ({e})")
            continue

        seen = state.setdefault(name, [])
        seen_set = set(seen)
        fresh = [it for it in items if it["id"] not in seen_set
                 and (it["date"] is None or now - it["date"] < timedelta(hours=MAX_AGE_HOURS))]
        fresh.sort(key=lambda it: it["date"] or now)  # las más antiguas primero

        # Primera ejecución: solo la última noticia de cada fuente, para no inundar el canal.
        to_post = fresh[-1:] if first_run else fresh[-max_posts:]
        posted = 0
        for it in to_post:
            embed = {
                "title": clean(it["title"], 250),
                "url": it["link"],
                "color": color,
                "author": {"name": name},
            }
            desc = clean(it["summary"], 300)
            if desc and desc.lower() != embed["title"].lower():
                embed["description"] = desc
            if it["date"]:
                embed["timestamp"] = it["date"].astimezone(timezone.utc).isoformat()
            if post({"username": "CFDsTrader · Noticias", "embeds": [embed]}):
                posted += 1

        # Todo lo leído pasa a "visto" (también lo que se saltó por el límite).
        for it in items:
            if it["id"] not in seen_set:
                seen.append(it["id"])
                seen_set.add(it["id"])
        state[name] = seen[-MAX_SEEN_PER_FEED:]
        print(f"✓ {name}: {len(items)} leídas, {len(fresh)} nuevas, {posted} publicadas")


# ---------------------------------------------------------------- ForexFactory

FLAGS = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵", "CHF": "🇨🇭",
         "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿", "CNY": "🇨🇳"}


def run_forexfactory(state: dict) -> None:
    today = datetime.now(MADRID).date()
    if datetime.now(MADRID).hour < FOREXFACTORY_HOUR or state.get("_ff_last") == today.isoformat():
        return
    try:
        root = ET.fromstring(fetch(FOREXFACTORY_URL))
    except Exception as e:
        print(f"✗ ForexFactory: no se pudo leer ({e})")
        return

    lines = []
    for ev in root.iter("event"):
        if child_text(ev, "impact") != "High":
            continue
        d, t = child_text(ev, "date"), child_text(ev, "time")
        try:
            day = datetime.strptime(d, "%m-%d-%Y").date()
        except ValueError:
            continue
        when, sort_key = t or "—", "99"
        if re.match(r"^\d{1,2}:\d{2}(am|pm)$", t or ""):
            dt_utc = datetime.strptime(f"{d} {t}", "%m-%d-%Y %I:%M%p").replace(tzinfo=timezone.utc)
            dt_mad = dt_utc.astimezone(MADRID)
            day, when, sort_key = dt_mad.date(), dt_mad.strftime("%H:%M"), dt_mad.strftime("%H:%M")
        if day != today:
            continue
        cur = child_text(ev, "country")
        extra = []
        if child_text(ev, "forecast"):
            extra.append(f"prev. {child_text(ev, 'forecast')}")
        if child_text(ev, "previous"):
            extra.append(f"ant. {child_text(ev, 'previous')}")
        tail = f" · {' · '.join(extra)}" if extra else ""
        lines.append((sort_key, f"`{when}` {FLAGS.get(cur, '🌐')} **{cur}** {child_text(ev, 'title')}{tail}"))

    lines.sort()
    body = "\n".join(l for _, l in lines) if lines else "Hoy no hay eventos de alto impacto. 😴"
    embed = {
        "title": f"📅 Calendario económico · {today.strftime('%d/%m/%Y')}",
        "description": body[:4000] + "\n\n_Solo impacto alto · horas de Madrid · fuente: ForexFactory_",
        "url": "https://www.forexfactory.com/calendar",
        "color": 0xD32F2F,
    }
    if post({"username": "CFDsTrader · Calendario", "embeds": [embed]}):
        state["_ff_last"] = today.isoformat()
        print(f"✓ ForexFactory: {len(lines)} eventos de alto impacto publicados")


# ---------------------------------------------------------------- main

def main() -> int:
    if not WEBHOOK.startswith("https://"):
        print("Falta el secreto DISCORD_WEBHOOK_URL.")
        return 1
    first_run = not STATE_FILE.exists()
    state = json.loads(STATE_FILE.read_text()) if not first_run else {}
    run_feeds(state, first_run)
    run_forexfactory(state)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
