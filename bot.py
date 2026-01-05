import asyncio
import json
import os
from datetime import datetime
import httpx
from bs4 import BeautifulSoup

STATE_FILE = "state.json"
TELEGRAM_BOT = "8556578094:AAHtu6Aglmqj-n_fBXgjmCQIee3vyiegOUw"
TELEGRAM_CHAT_ID = "@your_channel_or_chat_id"

EXCHANGES = ["binance", "bybit", "mexc", "gate", "bingx", "bitget", "kucoin"]

# ---------------- State Handling ----------------
def load_state():
    if not os.path.exists(STATE_FILE) or os.path.getsize(STATE_FILE) == 0:
        return {"listings": {}, "delistings": {}}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ---------------- Telegram ----------------
async def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=10)
        except Exception as e:
            print("Telegram send error:", e)

# ---------------- Fetch Functions ----------------
async def fetch_binance():
    url = "https://api.binance.com/bapi/composite/v1/public/cms/article/list/query"
    payload = {"pageSize": 10, "pageNo": 1, "category": "FUTURES_LISTINGS"}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=10)
            if r.status_code != 200 or not r.text.strip():
                print("Binance blocked or empty response")
                return []
            data = r.json()
            return data.get("data", {}).get("articles", [])
        except Exception as e:
            print("Binance fetch error:", e)
            return []

async def fetch_bybit():
    url = "https://www.bybit.com/derivatives/futures-announcements"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, timeout=10)
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, "html.parser")
            return [a.text.strip() for a in soup.select(".announcement-item-title")]
        except Exception as e:
            print("Bybit fetch error:", e)
            return []

async def fetch_mexc():
    url = "https://www.mexc.com/api/v2/futures/listings"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, timeout=10)
            if r.status_code != 200 or not r.text.strip():
                return []
            return r.json().get("data", [])
        except Exception as e:
            print("MEXC fetch error:", e)
            return []

# Stub functions for other exchanges
async def fetch_gate(): return []
async def fetch_bingx(): return []
async def fetch_bitget(): return []
async def fetch_kucoin(): return []

# ---------------- Generic Checker ----------------
async def check_exchange(name, fetch_fn, state):
    items = await fetch_fn()
    new_msgs = []

    for item in items:
        if isinstance(item, dict):
            uid = item.get("symbol") or item.get("title") or str(item)
        else:
            uid = str(item)
        if uid in state["listings"]:
            continue
        state["listings"][uid] = datetime.utcnow().isoformat()
        msg = f"🆕 {name.upper()} LISTING\n{uid}\n📅 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        new_msgs.append(msg)

    for msg in new_msgs:
        await send_telegram(msg)
    if new_msgs:
        print(f"✅ {name.upper()} LISTING sent {len(new_msgs)} messages")

# ---------------- Main Loop ----------------
async def main():
    state = load_state()
    tasks = [
        check_exchange("binance", fetch_binance, state),
        check_exchange("bybit", fetch_bybit, state),
        check_exchange("mexc", fetch_mexc, state),
        check_exchange("gate", fetch_gate, state),
        check_exchange("bingx", fetch_bingx, state),
        check_exchange("bitget", fetch_bitget, state),
        check_exchange("kucoin", fetch_kucoin, state),
    ]
    await asyncio.gather(*tasks)
    save_state(state)
    print(f"🆕 Check done {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    asyncio.run(main())