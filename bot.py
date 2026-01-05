import asyncio
import json
import hashlib
from datetime import datetime, timezone
import httpx

# ========== CONFIG ==========
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
STATE_FILE = "state.json"
CHECK_INTERVAL = 300  # секунд між перевірками
EXCHANGES = ["Binance", "Bybit", "MEXC", "Gate.io", "BingX", "Bitget", "KuCoin"]

# ============================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"hashes": []}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

async def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})

def make_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()

async def fetch_json(url, headers=None, method="GET", data=None):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            if method == "GET":
                r = await client.get(url, headers=headers)
            else:
                r = await client.post(url, headers=headers, data=data)
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

# ==================== EXCHANGE CHECKS ====================

async def check_mexc(state):
    url = "https://www.mexc.com/open/api/v2/announcement/list"  # приклад API
    data = await fetch_json(url)
    if not data or "data" not in data:
        return
    for item in data["data"]:
        text = f"🆕 MEXC {item['type'].upper()}\n{item['title']}\n📅 {item['time']}"
        h = make_hash(text)
        if h not in state["hashes"]:
            await send_telegram(text)
            state["hashes"].append(h)

async def check_binance(state):
    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    headers = {"Content-Type": "application/json"}
    payload = {"page":1,"rows":50,"category":"Futures_Listing"}
    data = await fetch_json(url, headers=headers, method="POST", data=json.dumps(payload))
    if not data or "data" not in data or "articles" not in data["data"]:
        print("Binance blocked or empty response")
        return
    for item in data["data"]["articles"]:
        text = f"🆕 Binance {item['type'].upper()}\n{item['title']}\n📅 {item['publishTime']}"
        h = make_hash(text)
        if h not in state["hashes"]:
            await send_telegram(text)
            state["hashes"].append(h)

async def check_bybit(state):
    url = "https://api.bybit.com/v2/public/announcement"  # приклад
    data = await fetch_json(url)
    if not data or "result" not in data:
        return
    for item in data["result"]:
        text = f"🆕 Bybit {item['category'].upper()}\n{item['title']}\n📅 {item['created_at']}"
        h = make_hash(text)
        if h not in state["hashes"]:
            await send_telegram(text)
            state["hashes"].append(h)

async def check_gate(state):
    url = "https://api.gate.io/api2/1/announcement/futures"
    data = await fetch_json(url)
    if not data:
        return
    for item in data:
        text = f"🆕 Gate.io {item['type'].upper()}\n{item['title']}\n📅 {item['time']}"
        h = make_hash(text)
        if h not in state["hashes"]:
            await send_telegram(text)
            state["hashes"].append(h)

async def check_bingx(state):
    url = "https://www.bingx.com/api/v1/announcement/futures"
    data = await fetch_json(url)
    if not data:
        return
    for item in data.get("data", []):
        text = f"🆕 BingX {item['type'].upper()}\n{item['title']}\n📅 {item['time']}"
        h = make_hash(text)
        if h not in state["hashes"]:
            await send_telegram(text)
            state["hashes"].append(h)

async def check_bitget(state):
    url = "https://api.bitget.com/api/mix/v1/announcement/list"
    data = await fetch_json(url)
    if not data or "data" not in data:
        return
    for item in data["data"]:
        text = f"🆕 Bitget {item['type'].upper()}\n{item['title']}\n📅 {item['time']}"
        h = make_hash(text)
        if h not in state["hashes"]:
            await send_telegram(text)
            state["hashes"].append(h)

async def check_kucoin(state):
    url = "https://api.kucoin.com/api/v1/announcement/futures"
    data = await fetch_json(url)
    if not data or "items" not in data:
        return
    for item in data["items"]:
        text = f"🆕 KuCoin {item['type'].upper()}\n{item['title']}\n📅 {item['publishTime']}"
        h = make_hash(text)
        if h not in state["hashes"]:
            await send_telegram(text)
            state["hashes"].append(h)

# ==================== MAIN LOOP ====================

async def main():
    while True:
        state = load_state()
        await asyncio.gather(
            check_binance(state),
            check_bybit(state),
            check_mexc(state),
            check_gate(state),
            check_bingx(state),
            check_bitget(state),
            check_kucoin(state)
        )
        save_state(state)
        print(f"🆕 Check done {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())