import json
import time
import hashlib
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from datetime import datetime, timezone

# ================== CONFIG ==================
TELEGRAM_TOKEN = "PUT_YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "PUT_YOUR_CHAT_ID"
STATE_FILE = "state.json"
CHECK_INTERVAL = 120  # seconds

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FuturesBot/1.0)"
}

EXCHANGES = [
    "BINANCE",
    "BYBIT",
    "MEXC",
    "GATE",
    "BINGX",
    "BITGET",
    "KUCOIN"
]

bot = Bot(token=TELEGRAM_TOKEN)

# ================== STATE ==================
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"sent": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def is_sent(uid, state):
    return uid in state["sent"]

def mark_sent(uid, state):
    state["sent"].append(uid)

def uid_from_text(exchange, title, date):
    raw = f"{exchange}|{title}|{date}"
    return hashlib.sha256(raw.encode()).hexdigest()

# ================== TELEGRAM ==================
def send(msg):
    bot.send_message(chat_id=CHAT_ID, text=msg, disable_web_page_preview=True)

# ================== PARSER CORE ==================
def classify(text):
    t = text.lower()
    if "delist" in t or "remove" in t:
        return "DELISTING"
    if "list" in t or "launch" in t:
        return "LISTING"
    return None

def is_futures(text):
    t = text.lower()
    return any(x in t for x in ["future", "perpetual", "usdt-m", "contract"])

# ================== SCRAPERS ==================

def scrape_binance():
    url = "https://www.binance.com/en/support/announcement"
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not title:
            continue
        if not is_futures(title):
            continue
        kind = classify(title)
        if not kind:
            continue
        out.append(("BINANCE", title, kind, url))
    return out

def scrape_bybit():
    url = "https://announcements.bybit.com/en-US/"
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not title:
            continue
        if not is_futures(title):
            continue
        kind = classify(title)
        if not kind:
            continue
        out.append(("BYBIT", title, kind, url))
    return out

def scrape_mexc():
    url = "https://www.mexc.com/support/announcement"
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not title:
            continue
        if not is_futures(title):
            continue
        kind = classify(title)
        if not kind:
            continue
        out.append(("MEXC", title, kind, url))
    return out

def scrape_gate():
    url = "https://www.gate.io/announcements"
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not title:
            continue
        if not is_futures(title):
            continue
        kind = classify(title)
        if not kind:
            continue
        out.append(("GATE", title, kind, url))
    return out

def scrape_bingx():
    url = "https://bingx.com/en-us/support/"
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not title:
            continue
        if not is_futures(title):
            continue
        kind = classify(title)
        if not kind:
            continue
        out.append(("BINGX", title, kind, url))
    return out

def scrape_bitget():
    url = "https://www.bitget.com/en/support/articles"
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not title:
            continue
        if not is_futures(title):
            continue
        kind = classify(title)
        if not kind:
            continue
        out.append(("BITGET", title, kind, url))
    return out

def scrape_kucoin():
    url = "https://www.kucoin.com/news/categories/derivatives"
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a"):
        title = a.get_text(strip=True)
        if not title:
            continue
        if not is_futures(title):
            continue
        kind = classify(title)
        if not kind:
            continue
        out.append(("KUCOIN", title, kind, url))
    return out

SCRAPERS = [
    scrape_binance,
    scrape_bybit,
    scrape_mexc,
    scrape_gate,
    scrape_bingx,
    scrape_bitget,
    scrape_kucoin
]

# ================== MAIN LOOP ==================
def run():
    state = load_state()
    while True:
        for scraper in SCRAPERS:
            try:
                items = scraper()
                for ex, title, kind, link in items:
                    uid = uid_from_text(ex, title, link)
                    if is_sent(uid, state):
                        continue
                    msg = f"🆕 {ex} FUTURES {kind}\n\n{title}\n{link}"
                    send(msg)
                    mark_sent(uid, state)
            except Exception as e:
                print("ERROR:", e)

        save_state(state)
        print("✅ CHECK DONE", datetime.now(timezone.utc).isoformat())
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run()