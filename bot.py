import asyncio
import httpx
import json
import os
import re
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict

# ================== CONFIG ==================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = 300  # 5 хв
STATE_FILE = "state.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FuturesBot/1.0)"
}

# ================== LOGGING ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)

# ================== STATE ==================

def load_state() -> Dict[str, bool]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: Dict[str, bool]):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def make_hash(exchange: str, title: str) -> str:
    raw = f"{exchange}:{title}".lower()
    return hashlib.sha256(raw.encode()).hexdigest()

# ================== TELEGRAM ==================

async def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False
        })

# ================== PARSER ==================

LISTING_RE = re.compile(r"list|launch|introduc", re.I)
DELISTING_RE = re.compile(r"delist|remove|terminate", re.I)
FUTURES_RE = re.compile(r"future|perpetual|swap", re.I)

def classify(title: str) -> str | None:
    if not FUTURES_RE.search(title):
        return None
    if LISTING_RE.search(title):
        return "LISTING"
    if DELISTING_RE.search(title):
        return "DELISTING"
    return None

# ================== CHECKERS ==================

async def check_binance() -> List[Dict]:
    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    payload = {"type": 1, "pageNo": 1, "pageSize": 20}
    items = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        r = await client.post(url, json=payload)
        if r.status_code != 200:
            log.warning("Binance blocked")
            return []
        data = r.json()
        for a in data.get("data", {}).get("articles", []):
            items.append({
                "exchange": "Binance",
                "title": a["title"],
                "url": "https://www.binance.com/en/support/announcement/" + a["code"]
            })
    return items

async def check_bybit() -> List[Dict]:
    url = "https://api.bybit.com/v5/announcements/index"
    items = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        r = await client.get(url)
        if r.status_code != 200:
            log.warning("Bybit API blocked → HTML")
            return []
        data = r.json()
        for a in data.get("result", {}).get("list", []):
            items.append({
                "exchange": "Bybit",
                "title": a["title"],
                "url": a["url"]
            })
    return items

async def check_mexc() -> List[Dict]:
    url = "https://www.mexc.com/api/platform/notice/api/notice/list"
    items = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        r = await client.get(url)
        data = r.json()
        for a in data.get("data", []):
            items.append({
                "exchange": "MEXC",
                "title": a["title"],
                "url": "https://www.mexc.com" + a["url"]
            })
    return items

async def check_gate() -> List[Dict]:
    url = "https://www.gate.io/apiweb/v1/announcement/list"
    items = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        r = await client.get(url)
        data = r.json()
        for a in data.get("data", {}).get("list", []):
            items.append({
                "exchange": "Gate",
                "title": a["title"],
                "url": "https://www.gate.io" + a["path"]
            })
    return items

async def check_bingx() -> List[Dict]:
    url = "https://www.bingx.com/api/notice/list"
    items = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        r = await client.get(url)
        data = r.json()
        for a in data.get("data", []):
            items.append({
                "exchange": "BingX",
                "title": a["title"],
                "url": a["url"]
            })
    return items

async def check_bitget() -> List[Dict]:
    url = "https://www.bitget.com/v1/spot/public/noticeList"
    items = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        r = await client.get(url)
        data = r.json()
        for a in data.get("data", []):
            items.append({
                "exchange": "Bitget",
                "title": a["title"],
                "url": a["url"]
            })
    return items

async def check_kucoin() -> List[Dict]:
    url = "https://www.kucoin.com/_api/cms/articles"
    params = {"page": 1, "pageSize": 20}
    items = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        r = await client.get(url, params=params)
        data = r.json()
        for a in data.get("items", []):
            items.append({
                "exchange": "KuCoin",
                "title": a["title"],
                "url": "https://www.kucoin.com/news/" + a["slug"]
            })
    return items

# ================== MAIN ==================

async def main():
    state = load_state()
    checkers = [
        check_binance,
        check_bybit,
        check_mexc,
        check_gate,
        check_bingx,
        check_bitget,
        check_kucoin
    ]

    await send_telegram("🤖 Futures Listing/Delisting Bot запущено")

    while True:
        for checker in checkers:
            try:
                items = await checker()
                for item in items:
                    kind = classify(item["title"])
                    if not kind:
                        continue
                    h = make_hash(item["exchange"], item["title"])
                    if h in state:
                        continue
                    state[h] = True
                    text = (
                        f"🆕 {item['exchange']} FUTURES {kind}\n\n"
                        f"{item['title']}\n\n"
                        f"🔗 {item['url']}\n"
                        f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                    )
                    await send_telegram(text)
                    log.info(f"✅ {item['exchange']} {kind}")
            except Exception as e:
                log.error(e)
        save_state(state)
        log.info("✅ Check done")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())