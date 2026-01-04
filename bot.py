import asyncio
import aiohttp
import json
import os
import logging
import hashlib
from datetime import datetime, timezone

from telegram import Bot
from telegram.error import TelegramError
from bs4 import BeautifulSoup
import re

# ================== CONFIG ==================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = 600  # 10 хв

STATE_FILE = "bot_state.json"

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані")

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ================== STATE ==================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "sent_hashes": [],
        "first_run": True,
        "known_pairs": {
            "bingx": [],
            "bitget": []
        },
        "bot_start_ts": int(datetime.now(timezone.utc).timestamp())
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def make_hash(exchange, title, date):
    raw = f"{exchange}|{title}|{date}"
    return hashlib.md5(raw.encode()).hexdigest()

# ================== HELPERS ==================
def is_listing(title):
    t = title.lower()
    return any(x in t for x in ["list", "listing", "launch", "perpetual"])

def is_delisting(title):
    t = title.lower()
    return any(x in t for x in ["delist", "delisting", "remove"])

def is_futures(title):
    t = title.lower()
    return any(x in t for x in ["usdt", "perpetual", "futures", "swap"])

# ================== EXCHANGES ==================

# ---------- BINANCE ----------
async def check_binance(session):
    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20"
    async with session.get(url, timeout=15) as r:
        data = await r.json()

    out = []
    for a in data["data"]["catalogs"][0]["articles"]:
        title = a["title"]
        if is_futures(title) and (is_listing(title) or is_delisting(title)):
            ts = a["releaseDate"] // 1000
            date = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M")
            out.append({
                "exchange": "BINANCE",
                "title": title,
                "date": date,
                "url": f"https://www.binance.com/en/support/announcement/{a['code']}",
                "type": "DELISTING" if is_delisting(title) else "LISTING",
                "ts": ts
            })
    logger.info(f"Binance: {len(out)}")
    return out

# ---------- BYBIT (API + HTML FALLBACK) ----------
async def check_bybit(session):
    out = []

    # === API TRY ===
    api_url = "https://api.bybit.com/v5/announcements/index?locale=en-US"
    try:
        async with session.get(api_url, timeout=10) as r:
            if r.headers.get("Content-Type", "").startswith("application/json"):
                data = await r.json()
                for i in data["result"]["list"]:
                    title = i["title"]
                    if is_futures(title) and (is_listing(title) or is_delisting(title)):
                        ts = i["dateTimestamp"] // 1000
                        out.append({
                            "exchange": "BYBIT",
                            "title": title,
                            "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                            "url": i["url"],
                            "type": "DELISTING" if is_delisting(title) else "LISTING",
                            "ts": ts
                        })
                logger.info(f"Bybit(API): {len(out)}")
                return out
    except Exception:
        logger.warning("Bybit API blocked → fallback HTML")

    # === HTML FALLBACK ===
    html_url = "https://announcements.bybit.com/en-US/?category=derivatives"
    async with session.get(html_url, timeout=15) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")

    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        if is_futures(title) and (is_listing(title) or is_delisting(title)):
            out.append({
                "exchange": "BYBIT",
                "title": title,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "url": "https://announcements.bybit.com",
                "type": "DELISTING" if is_delisting(title) else "LISTING",
                "ts": int(datetime.now(timezone.utc).timestamp())
            })

    logger.info(f"Bybit(HTML): {len(out)}")
    return out

# ---------- MEXC ----------
async def check_mexc(session):
    url = "https://www.mexc.com/announcements/new-listings"
    async with session.get(url, timeout=15) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")

    out = []
    for a in soup.find_all("a", href=re.compile("/announcements/")):
        title = a.get_text(strip=True)
        if is_futures(title) and (is_listing(title) or is_delisting(title)):
            out.append({
                "exchange": "MEXC",
                "title": title,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "url": "https://www.mexc.com" + a["href"],
                "type": "DELISTING" if is_delisting(title) else "LISTING",
                "ts": int(datetime.now(timezone.utc).timestamp())
            })
    logger.info(f"MEXC: {len(out)}")
    return out

# ---------- GATE ----------
async def check_gate(session):
    url = "https://www.gate.io/announcements"
    async with session.get(url, timeout=15) as r:
        soup = BeautifulSoup(await r.text(), "html.parser")

    out = []
    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        if is_futures(title) and (is_listing(title) or is_delisting(title)):
            out.append({
                "exchange": "GATE",
                "title": title,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "url": "https://www.gate.io",
                "type": "DELISTING" if is_delisting(title) else "LISTING",
                "ts": int(datetime.now(timezone.utc).timestamp())
            })
    logger.info(f"Gate: {len(out)}")
    return out

# ---------- BINGX ----------
async def check_bingx(session, state):
    url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
    async with session.get(url, timeout=10) as r:
        data = await r.json()

    current = [c["symbol"] for c in data["data"] if c["status"] == 1]
    old = set(state["known_pairs"]["bingx"])
    state["known_pairs"]["bingx"] = current

    out = []
    for s in set(current) - old:
        out.append({
            "exchange": "BINGX",
            "title": f"New Listing: {s} Perpetual",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "url": "https://bingx.com",
            "type": "LISTING",
            "ts": int(datetime.now(timezone.utc).timestamp())
        })
    logger.info(f"BingX: {len(out)}")
    return out

# ---------- BITGET ----------
async def check_bitget(session, state):
    url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
    async with session.get(url, timeout=10) as r:
        data = await r.json()

    current = [t["symbol"] for t in data["data"]]
    old = set(state["known_pairs"]["bitget"])
    state["known_pairs"]["bitget"] = current

    out = []
    for s in set(current) - old:
        out.append({
            "exchange": "BITGET",
            "title": f"New Listing: {s} Perpetual",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "url": "https://www.bitget.com",
            "type": "LISTING",
            "ts": int(datetime.now(timezone.utc).timestamp())
        })
    logger.info(f"Bitget: {len(out)}")
    return out

# ---------- KUCOIN ----------
async def check_kucoin(session):
    url = "https://futures.kucoin.com/_api/v1/announcement?type=futures"
    async with session.get(url, timeout=10) as r:
        data = await r.json()

    out = []
    for a in data["items"]:
        title = a["title"]
        if is_futures(title) and (is_listing(title) or is_delisting(title)):
            ts = a["createdAt"] // 1000
            out.append({
                "exchange": "KUCOIN",
                "title": title,
                "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "url": "https://futures.kucoin.com",
                "type": "DELISTING" if is_delisting(title) else "LISTING",
                "ts": ts
            })
    logger.info(f"KuCoin: {len(out)}")
    return out

# ================== TELEGRAM ==================
async def send(bot, a):
    emoji = "🆕" if a["type"] == "LISTING" else "⚠️"
    msg = (
        f"{emoji} <b>{a['exchange']} FUTURES {a['type']}</b>\n\n"
        f"<b>{a['title']}</b>\n"
        f"{a['date']}\n"
        f"<a href='{a['url']}'>Читати</a>"
    )
    await bot.send_message(
        TELEGRAM_CHAT_ID,
        msg,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

# ================== MAIN ==================
async def main():
    bot = Bot(TELEGRAM_BOT_TOKEN)
    state = load_state()

    logger.info("🤖 Бот запущено!")

    async with aiohttp.ClientSession() as session:
        checks = [
            check_binance(session),
            check_bybit(session),
            check_mexc(session),
            check_gate(session),
            check_bingx(session, state),
            check_bitget(session, state),
            check_kucoin(session)
        ]

        results = []
        for r in await asyncio.gather(*checks):
            results.extend(r)

        for a in results:
            if a["ts"] < state["bot_start_ts"]:
                continue

            h = make_hash(a["exchange"], a["title"], a["date"])
            if h in state["sent_hashes"]:
                continue

            await send(bot, a)
            state["sent_hashes"].append(h)
            await asyncio.sleep(1)

        state["sent_hashes"] = state["sent_hashes"][-500:]
        state["first_run"] = False
        save_state(state)

    logger.info("✅ Check done")
    await asyncio.sleep(CHECK_INTERVAL)
    await main()

if __name__ == "__main__":
    asyncio.run(main())