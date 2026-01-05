import asyncio
import aiohttp
import json
import os
import hashlib
import logging
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import TelegramError
from bs4 import BeautifulSoup
import re

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = 600  # 10 min
STATE_FILE = "state.json"

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані")

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("bot")

# ================= STATE =================
def default_state():
    return {
        "sent": [],
        "pairs": {
            "bingx": [],
            "bitget": []
        }
    }

def load_state():
    try:
        if not os.path.exists(STATE_FILE):
            return default_state()
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        log.warning("State broken → reset")
        return default_state()

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def make_hash(exchange, title, extra=""):
    base = f"{exchange}|{title}|{extra}".lower()
    return hashlib.sha256(base.encode()).hexdigest()

# ================= HELPERS =================
def is_futures(title: str):
    t = title.lower()
    return any(k in t for k in [
        "futures", "perpetual", "perp", "swap", "usdt-m", "usdⓢ-m"
    ])

def is_listing(title: str):
    return any(k in title.lower() for k in ["list", "launch"])

def is_delisting(title: str):
    return any(k in title.lower() for k in ["delist", "remove"])

# ================= TELEGRAM =================
async def send(bot, ex, typ, title, url):
    emoji = "🆕" if typ == "LISTING" else "⚠️"
    msg = (
        f"{emoji} <b>{ex} FUTURES {typ}</b>\n\n"
        f"📰 <b>{title}</b>\n\n"
        f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"🔗 <a href=\"{url}\">Читати</a>"
    )
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        log.info(f"✅ {ex} {typ}")
    except TelegramError as e:
        log.error(f"Telegram error: {e}")

# ================= EXCHANGES =================

# BINANCE
async def binance(session):
    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    payload = {
        "type": 1,
        "catalogId": 48,
        "pageNo": 1,
        "pageSize": 20
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    out = []

    try:
        async with session.post(url, json=payload, headers=headers, timeout=15) as r:
            if r.status != 200:
                log.warning("Binance blocked")
                return []
            data = await r.json()
            articles = data["data"]["catalogs"][0]["articles"]
            for a in articles:
                title = a["title"]
                if not is_futures(title):
                    continue
                typ = "DELISTING" if is_delisting(title) else "LISTING"
                out.append({
                    "exchange": "BINANCE",
                    "type": typ,
                    "title": title,
                    "url": f"https://www.binance.com/en/support/announcement/{a['code']}"
                })
    except Exception as e:
        log.warning(f"Binance error: {e}")
    return out

# BYBIT (API + HTML fallback)
async def bybit(session):
    out = []
    api = "https://api.bybit.com/v5/announcements/index?locale=en-US"
    try:
        async with session.get(api, timeout=15) as r:
            if r.headers.get("Content-Type","").startswith("application/json"):
                data = await r.json()
                for a in data["result"]["list"]:
                    title = a["title"]
                    if is_futures(title):
                        typ = "DELISTING" if is_delisting(title) else "LISTING"
                        out.append({
                            "exchange": "BYBIT",
                            "type": typ,
                            "title": title,
                            "url": a["url"]
                        })
                return out
    except Exception:
        log.warning("Bybit API blocked → HTML")

    # HTML fallback
    try:
        html_url = "https://announcements.bybit.com/en-US/"
        async with session.get(html_url, timeout=15) as r:
            soup = BeautifulSoup(await r.text(), "html.parser")
            for a in soup.select("a"):
                title = a.get_text(strip=True)
                if is_futures(title):
                    typ = "DELISTING" if is_delisting(title) else "LISTING"
                    out.append({
                        "exchange": "BYBIT",
                        "type": typ,
                        "title": title,
                        "url": "https://announcements.bybit.com"
                    })
    except Exception:
        pass
    return out

# MEXC
async def mexc(session):
    out = []
    url = "https://www.mexc.com/announcements/new-listings"
    async with session.get(url, headers={"User-Agent":"Mozilla"}, timeout=20) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")
        for a in soup.find_all("a"):
            title = a.get_text(strip=True)
            if is_futures(title):
                typ = "DELISTING" if is_delisting(title) else "LISTING"
                out.append({
                    "exchange": "MEXC",
                    "type": typ,
                    "title": title,
                    "url": "https://www.mexc.com"
                })
    return out

# GATE
async def gate(session):
    out = []
    url = "https://www.gate.io/announcements"
    async with session.get(url, headers={"User-Agent":"Mozilla"}, timeout=20) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")
        for a in soup.find_all("a"):
            title = a.get_text(strip=True)
            if is_futures(title):
                typ = "DELISTING" if is_delisting(title) else "LISTING"
                out.append({
                    "exchange": "GATE",
                    "type": typ,
                    "title": title,
                    "url": "https://www.gate.io/announcements"
                })
    return out

# BINGX (PAIR DIFF)
async def bingx(session, state):
    url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
    r = await session.get(url)
    data = await r.json()
    now = [c["symbol"] for c in data["data"] if c["status"] == 1]
    old = set(state["pairs"]["bingx"])
    out = []

    for s in set(now) - old:
        out.append({"exchange":"BINGX","type":"LISTING","title":f"{s} Perpetual","url":"https://bingx.com"})
    for s in old - set(now):
        out.append({"exchange":"BINGX","type":"DELISTING","title":f"{s} Removed","url":"https://bingx.com"})

    state["pairs"]["bingx"] = now
    return out

# BITGET (PAIR DIFF)
async def bitget(session, state):
    url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
    r = await session.get(url)
    data = await r.json()
    now = [t["symbol"] for t in data["data"]]
    old = set(state["pairs"]["bitget"])
    out = []

    for s in set(now) - old:
        out.append({"exchange":"BITGET","type":"LISTING","title":f"{s} Perpetual","url":"https://bitget.com"})
    for s in old - set(now):
        out.append({"exchange":"BITGET","type":"DELISTING","title":f"{s} Removed","url":"https://bitget.com"})

    state["pairs"]["bitget"] = now
    return out

# KUCOIN
async def kucoin(session):
    out = []
    url = "https://futures.kucoin.com/_api/v1/announcement?type=futures"
    async with session.get(url, timeout=15) as r:
        data = await r.json()
        for a in data.get("items", []):
            title = a["title"]
            if is_futures(title):
                typ = "DELISTING" if is_delisting(title) else "LISTING"
                out.append({
                    "exchange": "KUCOIN",
                    "type": typ,
                    "title": title,
                    "url": "https://futures.kucoin.com"
                })
    return out

# ================= MAIN =================
async def main():
    bot = Bot(BOT_TOKEN)
    state = load_state()

    async with aiohttp.ClientSession() as session:
        results = []
        results += await binance(session)
        results += await bybit(session)
        results += await mexc(session)
        results += await gate(session)
        results += await kucoin(session)
        results += await bingx(session, state)
        results += await bitget(session, state)

        for a in results:
            h = make_hash(a["exchange"], a["title"])
            if h in state["sent"]:
                continue
            await send(bot, a["exchange"], a["type"], a["title"], a["url"])
            state["sent"].append(h)
            await asyncio.sleep(1)

        state["sent"] = state["sent"][-500:]
        save_state(state)

    log.info("🆕 Check done")

if __name__ == "__main__":
    while True:
        asyncio.run(main())
        asyncio.sleep(CHECK_INTERVAL)