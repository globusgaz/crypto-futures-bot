# bot.py
import asyncio, httpx, json, hashlib, os
from datetime import datetime, timezone

# --- Telegram config ---
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# --- State file ---
STATE_FILE = "state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"hashes": []}
    return {"hashes": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def hash_item(title, date):
    return hashlib.sha256(f"{title}|{date}".encode()).hexdigest()

async def send_telegram(message):
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            await client.post(TG_API, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
        except Exception as e:
            print(f"Telegram send error: {e}")

# --- Exchanges ---
async def check_binance(state):
    url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    headers = {"User-Agent": "Mozilla/5.0"}
    payload = {"page":1,"rows":10,"category":"Futures Listing"}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            data = r.json()
        except Exception:
            print("Binance blocked or empty response")
            return

    for item in data.get("data", {}).get("articles", []):
        title = item.get("title")
        date = item.get("publishTime", 0)
        date_str = datetime.fromtimestamp(date/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        h = hash_item(title, date_str)
        if h not in state["hashes"]:
            state["hashes"].append(h)
            await send_telegram(f"🆕 BINANCE FUTURES\n{title}\n📅 {date_str}")

async def check_bybit(state):
    url = "https://api.bybit.com/v2/public/symbols"
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(url)
            data = r.json()
        except Exception:
            print("Bybit API blocked → fallback HTML")
            return

    for sym in data.get("result", []):
        title = f"{sym.get('name')} {sym.get('status')}"
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        h = hash_item(title, date_str)
        if h not in state["hashes"]:
            state["hashes"].append(h)
            await send_telegram(f"🆕 BYBIT FUTURES\n{title}\n📅 {date_str}")

async def check_mexc(state):
    url = "https://www.mexc.com/open/api/v2/market/announcement"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url)
        data = r.json()
    for item in data.get("data", []):
        title = item.get("title")
        date_str = item.get("date")
        h = hash_item(title, date_str)
        if h not in state["hashes"]:
            state["hashes"].append(h)
            await send_telegram(f"🆕 MEXC FUTURES\n{title}\n📅 {date_str}")

# --- Stub functions for other exchanges (Gate.io, BingX, Bitget, KuCoin) ---
async def check_gate(state):
    # Example stub
    return

async def check_bingx(state):
    return

async def check_bitget(state):
    return

async def check_kucoin(state):
    return

# --- Main loop ---
async def main():
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

if __name__ == "__main__":
    asyncio.run(main())