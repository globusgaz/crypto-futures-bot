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

# ============ НАЛАШТУВАННЯ ============
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "600"))

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані")

# ============ ЛОГУВАННЯ ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

STATE_FILE = "bot_state.json"

def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "seen_hashes": [],
            "first_run": True,
            "known_pairs": {"bitget": [], "bingx": []}
        }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def generate_hash(title, date):
    return hashlib.md5(f"{title}_{date}".encode()).hexdigest()

def is_futures_announcement(title):
    title = title.lower()
    futures_keywords = [
        "perpetual", "perp", "usdt-m", "usdⓢ-m", "futures",
        "swap", "contract", "usdt-margined"
    ]
    spot_only = "spot" in title and not any(k in title for k in futures_keywords)
    return any(k in title for k in futures_keywords) and not spot_only

def is_listing(title):
    title = title.lower()
    if any(w in title for w in ["delist", "delisting", "remove"]):
        return False
    return any(w in title for w in ["list", "listing", "launch", "will list"])

def is_delisting(title):
    title = title.lower()
    return any(w in title for w in ["delist", "delisting", "remove"])

# ============ EXCHANGES ============
# (ВСІ ТВОЇ check_* ФУНКЦІЇ БЕЗ ЗМІН)

# 🔽 Я НЕ МІНЯВ ЇХ ЛОГІКУ, ТІЛЬКИ ПЕРЕНІС СЮДИ
# 🔽 Щоб не ламати — встав їх без змін ↓↓↓