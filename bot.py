import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import httpx

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CHECK_INTERVAL = 60  # seconds
SEEN_FILE = "seen.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ================== STORAGE ==================
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, "r") as f:
        SEEN = set(json.load(f))
else:
    SEEN = set()


def save_seen():
    with open(SEEN_FILE, "w") as f:
        json.dump(list(SEEN), f)


def make_hash(exchange: str, symbol: str, action: str) -> str:
    raw = f"{exchange}:{symbol}:{action}".lower()
    return hashlib.md5(raw.encode()).hexdigest()


# ================== TELEGRAM ==================
async def send(msg: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(url, json={
            "chat_id": CHAT_ID,
            "text": msg,
            "disable_web_page_preview": False
        })


# ================== CHECKERS ==================

# ---------- BINANCE ----------
async def check_binance():
    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    payload = {"type": 1, "catalogId": 48, "pageNo": 1, "pageSize": 20}

    async with httpx.AsyncClient(headers=HEADERS) as c:
        r = await c.post(url, json=payload)
        data = r.json()

    for a in data.get("data", {}).get("articles", []):
        title = a["title"]
        if "USDT" not in title:
            continue

        symbol = title.split(" ")[-1]
        h = make_hash("BINANCE", symbol, "LISTING")

        if h in SEEN:
            continue

        SEEN.add(h)
        await send(f"🆕 BINANCE FUTURES\n{title}")
        save_seen()


# ---------- BYBIT (API → HTML) ----------
async def check_bybit():
    # API
    try:
        url = "https://api.bybit.com/v5/announcement/list"
        async with httpx.AsyncClient(headers=HEADERS) as c:
            r = await c.get(url)

        if "application/json" in r.headers.get("content-type", ""):
            data = r.json()
            for a in data.get("result", {}).get("list", []):
                title = a["title"]
                if "USDT" not in title:
                    continue
                symbol = title.split(" ")[-1]
                h = make_hash("BYBIT", symbol, "LISTING")
                if h in SEEN:
                    continue
                SEEN.add(h)
                await send(f"🆕 BYBIT FUTURES\n{title}")
                save_seen()
            return
    except Exception:
        pass

    # HTML fallback
    logger.warning("Bybit API blocked → fallback HTML")
    html_url = "https://announcements.bybit.com/en-US/"
    async with httpx.AsyncClient(headers=HEADERS) as c:
        r = await c.get(html_url)

    for line in r.text.splitlines():
        if "USDT" in line and "List" in line:
            symbol = line.split("USDT")[0][-10:] + "USDT"
            h = make_hash("BYBIT", symbol, "LISTING")
            if h in SEEN:
                continue
            SEEN.add(h)
            await send(f"🆕 BYBIT FUTURES\n{symbol}")
            save_seen()


# ---------- MEXC ----------
async def check_mexc():
    url = "https://www.mexc.com/api/platform/notice/api"
    params = {"type": "notice", "page_num": 1, "page_size": 20}

    async with httpx.AsyncClient(headers=HEADERS) as c:
        r = await c.get(url, params=params)
        data = r.json()

    for a in data.get("data", {}).get("list", []):
        title = a["title"]
        if "USDT" not in title:
            continue
        symbol = title.split(" ")[-1]
        h = make_hash("MEXC", symbol, "LISTING")
        if h in SEEN:
            continue
        SEEN.add(h)
        await send(f"🆕 MEXC FUTURES\n{title}")
        save_seen()


# ---------- GATE ----------
async def check_gate():
    url = "https://www.gate.io/json_svr/query?u=123"
    async with httpx.AsyncClient(headers=HEADERS) as c:
        r = await c.get(url)

    if "USDT" not in r.text:
        return

    for line in r.text.splitlines():
        if "USDT" in line:
            symbol = line.strip()
            h = make_hash("GATE", symbol, "LISTING")
            if h in SEEN:
                continue
            SEEN.add(h)
            await send(f"🆕 GATE FUTURES\n{symbol}")
            save_seen()


# ---------- BITGET ----------
async def check_bitget():
    url = "https://www.bitget.com/v1/announcement/list"
    async with httpx.AsyncClient(headers=HEADERS) as c:
        r = await c.get(url)
        data = r.json()

    for a in data.get("data", []):
        title = a["title"]
        if "USDT" not in title:
            continue
        symbol = title.split(" ")[-1]
        h = make_hash("BITGET", symbol, "LISTING")
        if h in SEEN:
            continue
        SEEN.add(h)
        await send(f"🆕 BITGET FUTURES\n{title}")
        save_seen()


# ---------- BINGX ----------
async def check_bingx():
    url = "https://www.bingx.com/api/notice"
    async with httpx.AsyncClient(headers=HEADERS) as c:
        r = await c.get(url)

    if "USDT" not in r.text:
        return

    for line in r.text.splitlines():
        if "USDT" in line:
            symbol = line.strip()
            h = make_hash("BINGX", symbol, "LISTING")
            if h in SEEN:
                continue
            SEEN.add(h)
            await send(f"🆕 BINGX FUTURES\n{symbol}")
            save_seen()


# ---------- KUCOIN ----------
async def check_kucoin():
    url = "https://api-futures.kucoin.com/api/v1/contracts/active"
    async with httpx.AsyncClient(headers=HEADERS) as c:
        r = await c.get(url)
        data = r.json()

    for a in data.get("data", []):
        symbol = a.get("symbol")
        if not symbol or "USDT" not in symbol:
            continue
        h = make_hash("KUCOIN", symbol, "LISTING")
        if h in SEEN:
            continue
        SEEN.add(h)
        await send(f"🆕 KUCOIN FUTURES\n{symbol}")
        save_seen()


# ================== MAIN ==================
async def main():
    await send("🤖 Bot started")
    while True:
        try:
            await check_binance()
            await check_bybit()
            await check_mexc()
            await check_gate()
            await check_bitget()
            await check_bingx()
            await check_kucoin()
            logger.info("✅ Check done")
        except Exception as e:
            logger.exception(e)
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())