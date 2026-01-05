import asyncio
import aiohttp
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from telegram import Bot

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = 600
STATE_FILE = "state.json"

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError("TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані")

# ================== LOG ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("bot")

# ================== STATE ==================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"seen": []}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def make_hash(exchange, title, url):
    return hashlib.md5(f"{exchange}|{title}|{url}".encode()).hexdigest()

# ================== HELPERS ==================
def is_futures(title: str):
    t = title.lower()
    return any(k in t for k in [
        "futures", "perpetual", "perp", "usdt-m", "usdⓢ-m", "contract"
    ])

def is_listing(title: str):
    return "list" in title.lower() and "delist" not in title.lower()

def is_delisting(title: str):
    return "delist" in title.lower() or "remove" in title.lower()

# ================== BINANCE (HTML) ==================
async def binance(session):
    out = []
    url = "https://www.binance.com/en/support/announcement/c-48"
    async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
        html = await r.text()
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a[href*='/announcement/']"):
        title = a.get_text(strip=True)
        if not is_futures(title):
            continue
        link = "https://www.binance.com" + a["href"]
        out.append(("BINANCE", title, link))
    log.info(f"Binance: {len(out)}")
    return out

# ================== BYBIT (API → HTML) ==================
async def bybit(session):
    out = []
    api = "https://api.bybit.com/v5/announcements/index?type=new_crypto"
    async with session.get(api) as r:
        if r.headers.get("Content-Type", "").startswith("application/json"):
            data = await r.json()
            for x in data.get("result", {}).get("list", []):
                title = x["title"]
                if is_futures(title):
                    out.append(("BYBIT", title, x["url"]))
            log.info(f"Bybit API: {len(out)}")
            return out

    log.warning("Bybit API blocked → HTML")
    html_url = "https://announcements.bybit.com/en-US/"
    async with session.get(html_url, headers={"User-Agent": "Mozilla/5.0"}) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")
    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        if is_futures(title):
            out.append(("BYBIT", title, html_url))
    log.info(f"Bybit HTML: {len(out)}")
    return out

# ================== MEXC ==================
async def mexc(session):
    out = []
    url = "https://www.mexc.com/announcements/futures"
    async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")
    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        if is_futures(title):
            out.append(("MEXC", title, "https://www.mexc.com"))
    log.info(f"MEXC: {len(out)}")
    return out

# ================== GATE ==================
async def gate(session):
    out = []
    url = "https://www.gate.io/announcements"
    async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")
    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        if is_futures(title):
            out.append(("GATE", title, url))
    log.info(f"Gate: {len(out)}")
    return out

# ================== BINGX ==================
async def bingx(session):
    out = []
    url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
    async with session.get(url) as r:
        data = await r.json()
    for c in data.get("data", []):
        out.append(("BINGX", f"{c['symbol']} Perpetual", "https://bingx.com"))
    log.info(f"BingX: {len(out)}")
    return out

# ================== BITGET ==================
async def bitget(session):
    out = []
    url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
    async with session.get(url) as r:
        data = await r.json()
    for x in data.get("data", []):
        out.append(("BITGET", f"{x['symbol']} Perpetual", "https://bitget.com"))
    log.info(f"Bitget: {len(out)}")
    return out

# ================== KUCOIN ==================
async def kucoin(session):
    out = []
    url = "https://futures.kucoin.com/announcement"
    async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")
    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        if is_futures(title):
            out.append(("KUCOIN", title, url))
    log.info(f"KuCoin: {len(out)}")
    return out

# ================== TELEGRAM ==================
async def send(bot, ex, title, url, typ):
    emoji = "🆕" if typ == "LISTING" else "⚠️"
    text = (
        f"{emoji} <b>{ex} FUTURES {typ}</b>\n\n"
        f"📰 {title}\n"
        f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"🔗 <a href='{url}'>Читати</a>"
    )
    await bot.send_message(CHAT_ID, text, parse_mode="HTML", disable_web_page_preview=True)

# ================== MAIN ==================
async def main():
    bot = Bot(BOT_TOKEN)
    state = load_state()
    seen = set(state["seen"])

    await bot.send_message(CHAT_ID, "🤖 Бот запущено\nМоніторю 7 бірж")

    async with aiohttp.ClientSession() as session:
        sources = await asyncio.gather(
            binance(session),
            bybit(session),
            mexc(session),
            gate(session),
            bingx(session),
            bitget(session),
            kucoin(session),
        )

        for src in sources:
            for ex, title, url in src:
                h = make_hash(ex, title, url)
                if h in seen:
                    continue

                typ = "DELISTING" if is_delisting(title) else "LISTING"
                await send(bot, ex, title, url, typ)
                seen.add(h)
                await asyncio.sleep(1)

    state["seen"] = list(seen)[-2000:]
    save_state(state)
    log.info("✅ Check done")

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        await main()

if __name__ == "__main__":
    asyncio.run(main())