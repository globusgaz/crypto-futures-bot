import asyncio
import aiohttp
import json
import os
import logging
import hashlib
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError

# ================== CONFIG ==================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = 600  # 10 хв

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані")

STATE_FILE = "bot_state.json"

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ================== STATE ==================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "seen": [],
            "first_run": True,
            "pairs": {"bingx": [], "bitget": []}
        }
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def h(x):
    return hashlib.md5(x.encode()).hexdigest()

# ================== FILTERS ==================
def is_futures(t):
    t = t.lower()
    return any(x in t for x in [
        "perpetual", "perp", "futures", "usdt-m", "swap", "contract"
    ])

def is_listing(t):
    return any(x in t.lower() for x in ["list", "listing", "launch"])

def is_delisting(t):
    return any(x in t.lower() for x in ["delist", "remove", "termination"])

# ================== BINANCE ==================
async def check_binance(session):
    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20"
    out = []
    try:
        async with session.get(url, timeout=15) as r:
            j = await r.json()
        for a in j["data"]["catalogs"][0]["articles"]:
            title = a["title"]
            if is_futures(title) and (is_listing(title) or is_delisting(title)):
                ts = a["releaseDate"] // 1000
                out.append({
                    "id": h(title + str(ts)),
                    "exchange": "BINANCE",
                    "title": title,
                    "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "url": "https://www.binance.com/en/support/announcement/" + a["code"]
                })
        logger.info(f"Binance: {len(out)}")
    except Exception as e:
        logger.error(f"Binance error: {e}")
    return out

# ================== BYBIT (API + HTML) ==================
async def check_bybit(session):
    out = []

    # API
    try:
        url = "https://api.bybit.com/v5/announcements/index?locale=en-US&type=new_crypto"
        async with session.get(url, timeout=10) as r:
            if "application/json" in r.headers.get("Content-Type", ""):
                j = await r.json()
                for a in j["result"]["list"]:
                    title = a["title"]
                    if is_futures(title) and (is_listing(title) or is_delisting(title)):
                        ts = a["dateTimestamp"] // 1000
                        out.append({
                            "id": h(title + str(ts)),
                            "exchange": "BYBIT",
                            "title": title,
                            "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                            "url": a.get("url", "")
                        })
                logger.info(f"Bybit(API): {len(out)}")
                return out
    except:
        logger.warning("Bybit API blocked → fallback HTML")

    # HTML fallback
    try:
        html_url = "https://announcements.bybit.com/en-US/?category=new_crypto"
        async with session.get(html_url, timeout=15) as r:
            html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a"):
            title = a.text.strip()
            if len(title) < 20:
                continue
            if is_futures(title) and (is_listing(title) or is_delisting(title)):
                out.append({
                    "id": h(title),
                    "exchange": "BYBIT",
                    "title": title,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "url": "https://announcements.bybit.com"
                })
        logger.info(f"Bybit(HTML): {len(out)}")
    except Exception as e:
        logger.error(f"Bybit HTML error: {e}")

    return out

# ================== MEXC ==================
async def check_mexc(session):
    out = []
    try:
        url = "https://www.mexc.com/announcements/new-listings"
        async with session.get(url, timeout=15) as r:
            soup = BeautifulSoup(await r.text(), "html.parser")
        for a in soup.select("a"):
            title = a.text.strip()
            if is_futures(title) and (is_listing(title) or is_delisting(title)):
                out.append({
                    "id": h(title),
                    "exchange": "MEXC",
                    "title": title,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "url": "https://www.mexc.com"
                })
        logger.info(f"MEXC: {len(out)}")
    except Exception as e:
        logger.error(f"MEXC error: {e}")
    return out

# ================== GATE ==================
async def check_gate(session):
    out = []
    try:
        async with session.get("https://www.gate.io/announcements", timeout=15) as r:
            soup = BeautifulSoup(await r.text(), "html.parser")
        for a in soup.select("a"):
            title = a.text.strip()
            if is_futures(title) and (is_listing(title) or is_delisting(title)):
                out.append({
                    "id": h(title),
                    "exchange": "GATE",
                    "title": title,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "url": "https://www.gate.io"
                })
        logger.info(f"Gate: {len(out)}")
    except Exception as e:
        logger.error(f"Gate error: {e}")
    return out

# ================== BINGX ==================
async def check_bingx(session, state):
    out = []
    url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
    async with session.get(url, timeout=10) as r:
        j = await r.json()
    symbols = [x["symbol"] for x in j["data"]]
    old = set(state["pairs"]["bingx"])
    for s in set(symbols) - old:
        out.append({
            "id": h(s),
            "exchange": "BINGX",
            "title": f"New Futures Listing {s}",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "url": "https://bingx.com"
        })
    state["pairs"]["bingx"] = symbols
    logger.info(f"BingX: {len(out)}")
    return out

# ================== BITGET ==================
async def check_bitget(session, state):
    out = []
    url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
    async with session.get(url, timeout=10) as r:
        j = await r.json()
    symbols = [x["symbol"] for x in j["data"]]
    old = set(state["pairs"]["bitget"])
    for s in set(symbols) - old:
        out.append({
            "id": h(s),
            "exchange": "BITGET",
            "title": f"New Futures Listing {s}",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "url": "https://bitget.com"
        })
    state["pairs"]["bitget"] = symbols
    logger.info(f"Bitget: {len(out)}")
    return out

# ================== KUCOIN ==================
async def check_kucoin(session):
    out = []
    try:
        async with session.get("https://futures.kucoin.com/_api/v1/announcement?type=futures", timeout=15) as r:
            j = await r.json()
        items = j.get("items") or j.get("data", {}).get("items", [])
        for a in items:
            title = a.get("title", "")
            if is_futures(title) and (is_listing(title) or is_delisting(title)):
                ts = int(a.get("createdAt", 0)) // 1000
                out.append({
                    "id": h(title + str(ts)),
                    "exchange": "KUCOIN",
                    "title": title,
                    "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "url": "https://futures.kucoin.com"
                })
        logger.info(f"KuCoin: {len(out)}")
    except Exception as e:
        logger.error(f"KuCoin error: {e}")
    return out

# ================== TELEGRAM ==================
async def send(bot, a):
    msg = f"🆕 <b>{a['exchange']} FUTURES</b>\n\n<b>{a['title']}</b>\n📅 {a['date']}\n🔗 {a['url']}"
    await bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode="HTML")

# ================== MAIN ==================
async def main():
    bot = Bot(TELEGRAM_BOT_TOKEN)
    state = load_state()

    async with aiohttp.ClientSession() as s:
        if state["first_run"]:
            await check_bingx(s, state)
            await check_bitget(s, state)
            state["first_run"] = False
            save_state(state)

        while True:
            all_news = []
            all_news += await check_binance(s)
            all_news += await check_bybit(s)
            all_news += await check_mexc(s)
            all_news += await check_gate(s)
            all_news += await check_bingx(s, state)
            all_news += await check_bitget(s, state)
            all_news += await check_kucoin(s)

            for a in all_news:
                if a["id"] not in state["seen"]:
                    await send(bot, a)
                    state["seen"].append(a["id"])
                    await asyncio.sleep(1)

            state["seen"] = state["seen"][-500:]
            save_state(state)
            logger.info("✅ Check done")
            await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())