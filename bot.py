import asyncio
import aiohttp
import json
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
import logging
import hashlib
from bs4 import BeautifulSoup
import re
import os

# ================= НАСТРОЙКИ =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = 600  # 10 хв

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані")

# ================= ЛОГИ =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

STATE_FILE = "bot_state.json"

# ================= STATE =================
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "seen_hashes": [],
            "first_run": True,
            "known_pairs": {
                "bingx": [],
                "bitget": []
            }
        }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def gen_hash(title, date):
    return hashlib.md5(f"{title}_{date}".encode()).hexdigest()

# ================= HELPERS =================
def is_futures(title: str) -> bool:
    t = title.lower()
    keys = [
        "perpetual", "perp", "futures", "swap", "contract",
        "usdt-m", "usdⓢ-m", "coin-m"
    ]
    return any(k in t for k in keys)

def is_listing(title: str) -> bool:
    return any(k in title.lower() for k in ["list", "listing", "launch"])

def is_delisting(title: str) -> bool:
    return any(k in title.lower() for k in ["delist", "remov"])

# ================= BINANCE =================
async def check_binance(session):
    out = []
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20"
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
            data = await r.json()
            arts = data["data"]["catalogs"][0]["articles"]
            for a in arts:
                title = a["title"]
                if is_futures(title) and (is_listing(title) or is_delisting(title)):
                    date = datetime.fromtimestamp(a["releaseDate"]/1000).strftime("%Y-%m-%d %H:%M")
                    out.append({
                        "hash": gen_hash(title, date),
                        "title": title,
                        "url": f"https://www.binance.com/en/support/announcement/{a['code']}",
                        "date": date,
                        "type": "DELISTING" if is_delisting(title) else "LISTING"
                    })
        logger.info(f"Binance: {len(out)}")
    except Exception as e:
        logger.error(f"Binance error: {e}")
    return out

# ================= BYBIT (HYBRID) =================
async def check_bybit(session):
    out = []

    # ---- METHOD 1: API ----
    try:
        api_url = "https://api.bybit.com/v5/announcements/index?locale=en-US&type=new_crypto"
        async with session.get(api_url, timeout=15) as r:
            ct = r.headers.get("Content-Type", "")
            if r.status == 200 and "application/json" in ct:
                data = await r.json()
                for i in data.get("result", {}).get("list", []):
                    title = i.get("title", "")
                    if is_futures(title) and (is_listing(title) or is_delisting(title)):
                        date = datetime.fromtimestamp(i["dateTimestamp"]/1000).strftime("%Y-%m-%d %H:%M")
                        out.append({
                            "hash": gen_hash(title, date),
                            "title": title,
                            "url": i.get("url", ""),
                            "date": date,
                            "type": "DELISTING" if is_delisting(title) else "LISTING"
                        })
                if out:
                    logger.info(f"Bybit(API): {len(out)}")
                    return out
            else:
                logger.warning("Bybit API blocked → fallback HTML")
    except Exception as e:
        logger.warning(f"Bybit API error → fallback HTML ({e})")

    # ---- METHOD 2: HTML FALLBACK ----
    try:
        html_url = "https://www.bybit.com/en-US/support/announcement"
        async with session.get(html_url, headers={"User-Agent": "Mozilla/5.0"}) as r:
            html = await r.text()
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a"):
                title = a.get_text(strip=True)
                if len(title) > 20 and is_futures(title) and (is_listing(title) or is_delisting(title)):
                    date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                    href = a.get("href", "")
                    out.append({
                        "hash": gen_hash(title, date),
                        "title": title,
                        "url": f"https://www.bybit.com{href}" if href.startswith("/") else html_url,
                        "date": date,
                        "type": "DELISTING" if is_delisting(title) else "LISTING"
                    })
        logger.info(f"Bybit(HTML): {len(out)}")
    except Exception as e:
        logger.error(f"Bybit HTML error: {e}")

    return out

# ================= MEXC =================
async def check_mexc(session):
    out = []
    try:
        url = "https://www.mexc.com/announcements/new-listings"
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
            soup = BeautifulSoup(await r.text(), "html.parser")
            for a in soup.find_all("a"):
                title = a.get_text(strip=True)
                if len(title) > 15 and is_futures(title) and (is_listing(title) or is_delisting(title)):
                    date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                    out.append({
                        "hash": gen_hash(title, date),
                        "title": title,
                        "url": "https://www.mexc.com" + a.get("href", ""),
                        "date": date,
                        "type": "DELISTING" if is_delisting(title) else "LISTING"
                    })
        logger.info(f"MEXC: {len(out)}")
    except Exception as e:
        logger.error(f"MEXC error: {e}")
    return out

# ================= GATE =================
async def check_gate(session):
    out = []
    try:
        url = "https://www.gate.io/announcements"
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
            soup = BeautifulSoup(await r.text(), "html.parser")
            for a in soup.find_all("a"):
                title = a.get_text(strip=True)
                if len(title) > 20 and is_futures(title) and (is_listing(title) or is_delisting(title)):
                    date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                    out.append({
                        "hash": gen_hash(title, date),
                        "title": title,
                        "url": "https://www.gate.io" + a.get("href", ""),
                        "date": date,
                        "type": "DELISTING" if is_delisting(title) else "LISTING"
                    })
        logger.info(f"Gate: {len(out)}")
    except Exception as e:
        logger.error(f"Gate error: {e}")
    return out

# ================= BINGX =================
async def check_bingx(session, state, silent=False):
    out = []
    try:
        url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
        async with session.get(url) as r:
            data = await r.json()
            symbols = [c["symbol"] for c in data["data"] if c["status"] == 1]
            if silent:
                state["known_pairs"]["bingx"] = symbols
                return []
            old = set(state["known_pairs"]["bingx"])
            for s in set(symbols) - old:
                title = f"New Listing {s} Perpetual"
                out.append({
                    "hash": gen_hash(title, s),
                    "title": title,
                    "url": "https://bingx.com",
                    "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                    "type": "LISTING"
                })
            state["known_pairs"]["bingx"] = symbols
        logger.info(f"BingX: {len(out)}")
    except Exception as e:
        logger.error(f"BingX error: {e}")
    return out

# ================= BITGET =================
async def check_bitget(session, state, silent=False):
    out = []
    try:
        url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        async with session.get(url) as r:
            data = await r.json()
            symbols = [d["symbol"] for d in data["data"]]
            if silent:
                state["known_pairs"]["bitget"] = symbols
                return []
            old = set(state["known_pairs"]["bitget"])
            for s in set(symbols) - old:
                title = f"New Listing {s} Perpetual"
                out.append({
                    "hash": gen_hash(title, s),
                    "title": title,
                    "url": "https://www.bitget.com",
                    "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                    "type": "LISTING"
                })
            state["known_pairs"]["bitget"] = symbols
        logger.info(f"Bitget: {len(out)}")
    except Exception as e:
        logger.error(f"Bitget error: {e}")
    return out

# ================= KUCOIN =================
async def check_kucoin(session):
    out = []
    try:
        url = "https://futures.kucoin.com/_api/v1/announcement?type=futures"
        async with session.get(url) as r:
            data = await r.json()
            for i in data.get("items", []):
                title = i["title"]
                if is_futures(title) and (is_listing(title) or is_delisting(title)):
                    date = i["createdAt"]
                    out.append({
                        "hash": gen_hash(title, date),
                        "title": title,
                        "url": f"https://futures.kucoin.com/announcement/{i['id']}",
                        "date": date,
                        "type": "DELISTING" if is_delisting(title) else "LISTING"
                    })
        logger.info(f"KuCoin: {len(out)}")
    except Exception as e:
        logger.error(f"KuCoin error: {e}")
    return out

# ================= TELEGRAM =================
async def send(bot, ex, ann):
    emoji = "🆕" if ann["type"] == "LISTING" else "⚠️"
    msg = (
        f"{emoji} <b>{ex} FUTURES {ann['type']}</b>\n\n"
        f"<b>{ann['title']}</b>\n"
        f"{ann['date']}\n"
        f"<a href='{ann['url']}'>Читати</a>"
    )
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode="HTML", disable_web_page_preview=True)

# ================= MAIN =================
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    state = load_state()

    if state["first_run"]:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🤖 Bot started")
        async with aiohttp.ClientSession() as s:
            await check_bingx(s, state, True)
            await check_bitget(s, state, True)
        state["first_run"] = False
        save_state(state)

    while True:
        try:
            async with aiohttp.ClientSession() as s:
                all_anns = (
                    await check_binance(s)
                    + await check_bybit(s)
                    + await check_mexc(s)
                    + await check_gate(s)
                    + await check_bingx(s, state)
                    + await check_bitget(s, state)
                    + await check_kucoin(s)
                )
                for a in all_anns:
                    if a["hash"] not in state["seen_hashes"]:
                        await send(bot, "EXCHANGE", a)
                        state["seen_hashes"].append(a["hash"])
                save_state(state)
                logger.info("✅ Check done")
        except Exception as e:
            logger.error(e)

        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())