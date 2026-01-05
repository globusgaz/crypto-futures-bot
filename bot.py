import asyncio
import json
import hashlib
from datetime import datetime, timezone
import httpx
import os

# ==========================
# Налаштування
# ==========================
TELEGRAM_TOKEN = "ваш_telegram_bot_token"
TELEGRAM_CHAT_ID = "ваш_chat_id"

STATE_FILE = "state.json"

EXCHANGES = ["binance", "bybit", "mexc", "gate", "bingx", "bitget", "kucoin"]

# ==========================
# Завантаження/збереження стану
# ==========================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ==========================
# Відправка повідомлень у Telegram
# ==========================
async def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message})

# ==========================
# Утиліта для створення хешу лістингу
# ==========================
def listing_hash(exchange, symbol, event_type, date_str):
    s = f"{exchange}|{symbol}|{event_type}|{date_str}"
    return hashlib.md5(s.encode()).hexdigest()

# ==========================
# Перевірка лістингів на біржах
# ==========================
async def check_binance(state):
    async with httpx.AsyncClient() as client:
        try:
            # Приклад fallback, бо часто блокують
            r = await client.get("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query")
            if r.status_code != 200:
                print("Binance blocked or empty response")
                return
            data = r.json()
            for item in data.get("data", {}).get("articles", []):
                symbol = item.get("symbol")
                event_type = item.get("event_type", "listing")
                date_str = item.get("date")
                h = listing_hash("binance", symbol, event_type, date_str)
                if h not in state:
                    message = f"🆕 BINANCE {event_type.upper()}\n{symbol} {date_str}"
                    await send_telegram(message)
                    state[h] = True
        except Exception as e:
            print(f"Binance error: {e}")

async def check_bybit(state):
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("https://api.bybit.com/v2/public/symbols")
            data = r.json()
            for item in data.get("result", []):
                symbol = item.get("name")
                event_type = "listing"
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                h = listing_hash("bybit", symbol, event_type, date_str)
                if h not in state:
                    message = f"🆕 BYBIT {event_type.upper()}\n{symbol} {date_str}"
                    await send_telegram(message)
                    state[h] = True
        except Exception as e:
            print(f"Bybit error: {e}")

async def check_mexc(state):
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("https://www.mexc.com/api/v2/market/futures/list")
            data = r.json()
            for item in data.get("data", []):
                symbol = item.get("symbol")
                event_type = "listing"
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                h = listing_hash("mexc", symbol, event_type, date_str)
                if h not in state:
                    message = f"🆕 MEXC {event_type.upper()}\n{symbol} {date_str}"
                    await send_telegram(message)
                    state[h] = True
        except Exception as e:
            print(f"MEXC error: {e}")

async def check_gate(state):
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("https://api.gate.io/api2/1/futures/contracts")
            data = r.json()
            for item in data:
                symbol = item.get("name")
                event_type = "listing"
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                h = listing_hash("gate", symbol, event_type, date_str)
                if h not in state:
                    message = f"🆕 GATE {event_type.upper()}\n{symbol} {date_str}"
                    await send_telegram(message)
                    state[h] = True
        except Exception as e:
            print(f"Gate error: {e}")

async def check_bingx(state):
    # Приклад
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("https://bingx.com/api/v1/futures/list")
            data = r.json()
            for item in data.get("data", []):
                symbol = item.get("symbol")
                event_type = "listing"
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                h = listing_hash("bingx", symbol, event_type, date_str)
                if h not in state:
                    message = f"🆕 BINGX {event_type.upper()}\n{symbol} {date_str}"
                    await send_telegram(message)
                    state[h] = True
        except Exception as e:
            print(f"BingX error: {e}")

async def check_bitget(state):
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("https://api.bitget.com/api/futures/v1/contracts")
            data = r.json()
            for item in data.get("data", []):
                symbol = item.get("symbol")
                event_type = "listing"
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                h = listing_hash("bitget", symbol, event_type, date_str)
                if h not in state:
                    message = f"🆕 BITGET {event_type.upper()}\n{symbol} {date_str}"
                    await send_telegram(message)
                    state[h] = True
        except Exception as e:
            print(f"Bitget error: {e}")

async def check_kucoin(state):
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("https://api.kucoin.com/api/v1/contracts/active")
            data = r.json()
            for item in data.get("data", []):
                symbol = item.get("symbol")
                event_type = "listing"
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                h = listing_hash("kucoin", symbol, event_type, date_str)
                if h not in state:
                    message = f"🆕 KUCOIN {event_type.upper()}\n{symbol} {date_str}"
                    await send_telegram(message)
                    state[h] = True
        except Exception as e:
            print(f"KuCoin error: {e}")

# ==========================
# Основна функція
# ==========================
async def main():
    state = load_state()
    await asyncio.gather(
        check_binance(state),
        check_bybit(state),
        check_mexc(state),
        check_gate(state),
        check_bingx(state),
        check_bitget(state),
        check_kucoin(state),
    )
    save_state(state)
    print(f"🆕 Check done {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    asyncio.run(main())