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
import os  # для змінних середовища

# ============ НАЛАШТУВАННЯ ============
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = 600  # 10 хвилин

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані через змінні середовища!")

# ============ ЛОГУВАННЯ ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
        json.dump(state, f, indent=2)

def generate_hash(title, date):
    return hashlib.md5(f"{title}_{date}".encode()).hexdigest()

def is_futures_announcement(title):
    title_lower = title.lower()
    futures_keywords = [
        'perpetual', 'perp', 'usdt-m', 'usdⓢ-m', 'usdt perpetual',
        'coin-m', 'delivery', 'usdc perpetual', 'futures',
        'quarterly', 'swap', 'contract', 'usdt-margined'
    ]
    spot_only = 'spot' in title_lower and all(k not in title_lower for k in futures_keywords)
    return any(keyword in title_lower for keyword in futures_keywords) and not spot_only

def is_listing(title):
    title_lower = title.lower()
    listing_keywords = ['list', 'listing', 'launch', 'new listing', 'will list', 'to list']
    delisting_keywords = ['delist', 'delisting', 'remove', 'removal']
    if any(word in title_lower for word in delisting_keywords):
        return False
    return any(word in title_lower for word in listing_keywords)

def is_delisting(title):
    title_lower = title.lower()
    delisting_keywords = ['delist', 'delisting', 'remove', 'removal', 'will delist', 'to delist']
    return any(word in title_lower for word in delisting_keywords)

# ================== ФУНКЦІЇ ДЛЯ БІРЖ ==================
async def check_binance(session):
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with session.get(url, headers=headers, timeout=15) as response:
            data = await response.json()
            announcements = []
            for article in data.get('data', {}).get('catalogs', [{}])[0].get('articles', []):
                title = article.get('title', '')
                if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                    date = datetime.fromtimestamp(article.get('releaseDate', 0)/1000).strftime('%Y-%m-%d %H:%M')
                    ann_type = 'DELISTING' if is_delisting(title) else 'LISTING'
                    announcements.append({
                        'hash': generate_hash(title, date),
                        'title': title,
                        'url': f"https://www.binance.com/en/support/announcement/{article.get('code')}",
                        'date': date,
                        'type': ann_type
                    })
            return announcements
    except Exception as e:
        logger.error(f"Binance error: {e}")
        return []

async def check_bybit(session):
    try:
        url = "https://api.bybit.com/v5/announcements/index?locale=en-US&type=new_crypto&page=1&limit=20"
        async with session.get(url, timeout=15) as response:
            data = await response.json()
            announcements = []
            for item in data.get('result', {}).get('list', []):
                title = item.get('title', '')
                if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                    date = datetime.fromtimestamp(item.get('dateTimestamp', 0)/1000).strftime('%Y-%m-%d %H:%M')
                    ann_type = 'DELISTING' if is_delisting(title) else 'LISTING'
                    announcements.append({
                        'hash': generate_hash(title, date),
                        'title': title,
                        'url': item.get('url', ''),
                        'date': date,
                        'type': ann_type
                    })
            return announcements
    except Exception as e:
        logger.error(f"Bybit error: {e}")
        return []

async def check_mexc(session):
    try:
        url = "https://www.mexc.com/announcements/new-listings"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with session.get(url, headers=headers, timeout=20) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'html.parser')
            announcements = []
            for link in soup.find_all('a', href=re.compile('/announcements/')):
                title = link.get_text(strip=True)
                title_lower = title.lower()
                is_futures = ('futures' in title_lower or 'usdt-m' in title_lower or 'perpetual' in title_lower)
                if is_futures and (is_listing(title) or is_delisting(title)):
                    href = link.get('href', '')
                    ann_type = 'DELISTING' if is_delisting(title) else 'LISTING'
                    announcements.append({
                        'hash': generate_hash(title, datetime.now().strftime('%Y-%m-%d')),
                        'title': title,
                        'url': f"https://www.mexc.com{href}" if href.startswith('/') else href,
                        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                        'type': ann_type
                    })
                    if len(announcements) >= 15: break
            return announcements
    except Exception as e:
        logger.error(f"MEXC error: {e}")
        return []

async def check_gateio(session):
    try:
        url = "https://www.gate.io/announcements"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with session.get(url, headers=headers, timeout=20) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'html.parser')
            announcements = []
            for link in soup.find_all('a'):
                title = link.get_text(strip=True)
                if len(title) > 20 and ('perpetual' in title.lower() or 'futures' in title.lower()) and (is_listing(title) or is_delisting(title)):
                    href = link.get('href', '')
                    ann_type = 'DELISTING' if is_delisting(title) else 'LISTING'
                    announcements.append({
                        'hash': generate_hash(title, datetime.now().strftime('%Y-%m-%d')),
                        'title': title,
                        'url': f"https://www.gate.io{href}" if href.startswith('/') else href,
                        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                        'type': ann_type
                    })
                    if len(announcements) >= 3: break
            return announcements
    except Exception as e:
        logger.error(f"Gate.io error: {e}")
        return []

async def check_bingx(session, state, silent=False):
    try:
        url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
        async with session.get(url, timeout=15) as response:
            data = await response.json()
            contracts = data.get('data', [])
            if 'known_pairs' not in state: state['known_pairs'] = {}
            if 'bingx' not in state['known_pairs']: state['known_pairs']['bingx'] = []
            current_symbols = [c.get('symbol','') for c in contracts if c.get('status')==1]
            if silent:
                state['known_pairs']['bingx'] = current_symbols
                return []
            announcements = []
            old_symbols = set(state['known_pairs']['bingx'])
            new_symbols = set(current_symbols)
            listings = new_symbols - old_symbols
            for symbol in listings:
                title = f"New Listing: {symbol} Perpetual"
                announcements.append({
                    'hash': generate_hash(title, datetime.now().strftime('%Y-%m-%d')),
                    'title': title,
                    'url': f"https://bingx.com/en-us/futures/{symbol.replace('-','')}",
                    'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'type': 'LISTING'
                })
            delistings = old_symbols - new_symbols
            for symbol in delistings:
                title = f"Delisting: {symbol} Removed"
                announcements.append({
                    'hash': generate_hash(title, datetime.now().strftime('%Y-%m-%d')),
                    'title': title,
                    'url': "https://bingx.com/en-us/futures/",
                    'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'type': 'DELISTING'
                })
            state['known_pairs']['bingx'] = current_symbols
            return announcements
    except Exception as e:
        if not silent: logger.error(f"BingX error: {e}")
        return []

async def check_bitget(session, state, silent=False):
    try:
        url = "https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with session.get(url, headers=headers, timeout=15) as response:
            data = await response.json()
            tickers = data.get('data', [])
            if 'known_pairs' not in state: state['known_pairs'] = {}
            if 'bitget' not in state['known_pairs']: state['known_pairs']['bitget'] = []
            current_symbols = [t.get('symbol','') for t in tickers]
            if silent:
                state['known_pairs']['bitget'] = current_symbols
                return []
            announcements = []
            old_symbols = set(state['known_pairs']['bitget'])
            new_symbols = set(current_symbols)
            listings = new_symbols - old_symbols
            for symbol in list(listings)[:10]:
                title = f"New Listing: {symbol} Perpetual"
                announcements.append({
                    'hash': generate_hash(title, datetime.now().strftime('%Y-%m-%d')),
                    'title': title,
                    'url': f"https://www.bitget.com/futures/usdt/{symbol}",
                    'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'type': 'LISTING'
                })
            delistings = old_symbols - new_symbols
            for symbol in list(delistings)[:10]:
                title = f"Delisting: {symbol} Removed"
                announcements.append({
                    'hash': generate_hash(title, datetime.now().strftime('%Y-%m-%d')),
                    'title': title,
                    'url': "https://www.bitget.com/futures/",
                    'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'type': 'DELISTING'
                })
            state['known_pairs']['bitget'] = current_symbols
            return announcements
    except Exception as e:
        if not silent: logger.error(f"Bitget error: {e}")
        return []

# ============ ВІДПРАВКА ПОВІДОМЛЕННЯ ============
async def send_telegram_message(bot, exchange, announcement):
    emoji = "🆕" if announcement.get('type')=='LISTING' else "⚠️"
    type_text = "LISTING" if announcement.get('type')=='LISTING' else "DELISTING"
    message = f"{emoji} <b>{exchange} FUTURES {type_text}</b>\n\n"
    message += f"📰 <b>{announcement['title']}</b>\n\n"
    message += f"📅 {announcement['date']}\n"
    message += f"🔗 <a href=\"{announcement['url']}\">Читати повністю</a>"
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML', disable_web_page_preview=True)
        logger.info(f"✅ {exchange} {type_text}")
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")

# ============ ГОЛОВНА ФУНКЦІЯ ============
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    state = load_state()
    logger.info("🤖 Бот запущено!")

    if state['first_run']:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🤖 Бот запущено!\n\n📋 Ініціалізація...\n🆕 Лістинги\n⚠️ Делістинги")
        async with aiohttp.ClientSession() as session:
            binance = await check_binance(session)
            bybit = await check_bybit(session)
            mexc = await check_mexc(session)
            gateio = await check_gateio(session)
            await check_bingx(session, state, silent=True)
            await check_bitget(session, state, silent=True)
            for ann in binance + bybit + mexc + gateio:
                state['seen_hashes'].append(ann['hash'])
            state['first_run'] = False
            save_state(state)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="✅ Готово!\n\n🔔 Моніторю: Binance, Bybit, MEXC, Gate.io, BingX, Bitget")
        logger.info("✅ Ініціалізація завершена")

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                binance = await check_binance(session)
                bybit = await check_bybit(session)
                mexc = await check_mexc(session)
                gateio = await check_gateio(session)
                bingx = await check_bingx(session, state)
                bitget = await check_bitget(session, state)
                all_announcements = binance + bybit + mexc + gateio + bingx + bitget
                new_found = False
                for ann in all_announcements:
                    if ann['hash'] not in state['seen_hashes']:
                        url = ann['url'].lower()
                        exchange = 'BINANCE' if 'binance' in url else \
                                   'BYBIT' if 'bybit' in url else \
                                   'MEXC' if 'mexc' in url else \
                                   'GATE.IO' if 'gate' in url else \
                                   'BINGX' if 'bingx' in url else 'BITGET'
                        await send_telegram_message(bot, exchange, ann)
                        state['seen_hashes'].append(ann['hash'])
                        new_found = True
                        await asyncio.sleep(1)
                if len(state['seen_hashes']) > 300:
                    state['seen_hashes'] = state['seen_hashes'][-300:]
                save_state(state)
                if new_found:
                    logger.info(f"🆕 Нові зміни {datetime.now().strftime('%H:%M:%S')}")
                else:
                    logger.info(f"✅ Перевірка {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            logger.error(f"Error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())