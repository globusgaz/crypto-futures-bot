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

# ======= ФУНКЦІЇ ДЛЯ КОЖНОЇ БІРЖІ (Binance, Bybit, MEXC, Gate.io, BingX, Bitget) =======
# Сюди вставляємо всі твої функції check_binance, check_bybit, check_mexc, check_gateio, check_bingx, check_bitget
# Їх можна скопіпастити з твого оригінального коду, без змін, крім виклику TELEGRAM_BOT_TOKEN та CHAT_ID через os.getenv
# Також вставляємо функцію send_telegram_message як у твоєму коді

# ============ ВІДПРАВКА ПОВІДОМЛЕННЯ ============
async def send_telegram_message(bot, exchange, announcement):
    emoji = "🆕" if announcement.get('type') == 'LISTING' else "⚠️"
    type_text = "LISTING" if announcement.get('type') == 'LISTING' else "DELISTING"
    
    message = f"{emoji} <b>{exchange} FUTURES {type_text}</b>\n\n"
    message += f"📰 <b>{announcement['title']}</b>\n\n"
    message += f"📅 {announcement['date']}\n"
    message += f"🔗 <a href=\"{announcement['url']}\">Читати повністю</a>"
    
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        logger.info(f"✅ {exchange} {type_text}")
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")

# ============ ГОЛОВНА ФУНКЦІЯ ============
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    state = load_state()
    
    logger.info("🤖 Бот запущено!")
    
    if state['first_run']:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, 
            text="🤖 Бот запущено!\n\n📋 Ініціалізація...\n🆕 Лістинги\n⚠️ Делістинги"
        )
        
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
        
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="✅ Готово!\n\n🔔 Моніторю:\n• Binance\n• Bybit\n• MEXC\n• Gate.io\n• BingX\n• Bitget"
        )
        logger.info("✅ Ініціалізація завершена")
    
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                binance = await check_binance(session)
                bybit = await check_bybit(session)
                mexc = await check_mexc(session)
                gateio = await check_gateio(session)
                bingx = await check_bingx(session, state, silent=False)
                bitget = await check_bitget(session, state, silent=False)
                
                all_announcements = binance + bybit + mexc + gateio + bingx + bitget
                
                new_found = False
                
                for ann in all_announcements:
                    if ann['hash'] not in state['seen_hashes']:
                        url = ann['url'].lower()
                        if 'binance' in url:
                            exchange = 'BINANCE'
                        elif 'bybit' in url:
                            exchange = 'BYBIT'
                        elif 'mexc' in url:
                            exchange = 'MEXC'
                        elif 'gate' in url:
                            exchange = 'GATE.IO'
                        elif 'bingx' in url:
                            exchange = 'BINGX'
                        else:
                            exchange = 'BITGET'
                        
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