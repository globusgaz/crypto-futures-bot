import asyncio
import aiohttp
import json
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError
import logging

# ============ НАЛАШТУВАННЯ ============
TELEGRAM_BOT_TOKEN = "8556578094:AAHtu6Aglmqj-n_fBXgjmCQIee3vyiegOUw"
TELEGRAM_CHAT_ID = "535763958"

# ============ ЛОГУВАННЯ ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ ПЕРЕВІРКА MEXC ============
async def check_mexc(session):
    try:
        url = "https://www.mexc.com/api/platform/announcement/list?page_num=1&page_size=20"
        async with session.get(url, timeout=15) as response:
            if response.status == 200:
                data = await response.json()
                print("\n=== MEXC ANNOUNCEMENTS ===")
                for item in data.get('data', {}).get('list', []):
                    title = item.get('title', '')
                    print(f"Title: {title}")
                    print(f"ID: {item.get('id')}")
                    print(f"Date: {datetime.fromtimestamp(item.get('publish_time', 0)).strftime('%Y-%m-%d %H:%M')}")
                    print("---")
                return data.get('data', {}).get('list', [])
    except Exception as e:
        logger.error(f"MEXC error: {e}")
    return []

# ============ ПЕРЕВІРКА BINANCE ============
async def check_binance(session):
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20"
        async with session.get(url, timeout=15) as response:
            if response.status == 200:
                data = await response.json()
                print("\n=== BINANCE ANNOUNCEMENTS ===")
                for article in data.get('data', {}).get('articles', []):
                    title = article.get('title', '')
                    print(f"Title: {title}")
                    print(f"ID: {article.get('id')}")
                    print(f"Date: {datetime.fromtimestamp(article.get('releaseDate', 0) / 1000).strftime('%Y-%m-%d %H:%M')}")
                    print("---")
                return data.get('data', {}).get('articles', [])
    except Exception as e:
        logger.error(f"Binance error: {e}")
    return []

# ============ ПЕРЕВІРКА BYBIT ============
async def check_bybit(session):
    try:
        url = "https://api.bybit.com/v5/announcements/index?locale=en-US&type=new_crypto&page=1&limit=20"
        async with session.get(url, timeout=15) as response:
            if response.status == 200:
                data = await response.json()
                print("\n=== BYBIT ANNOUNCEMENTS ===")
                for item in data.get('result', {}).get('list', []):
                    title = item.get('title', '')
                    print(f"Title: {title}")
                    print(f"ID: {item.get('id')}")
                    print(f"Date: {datetime.fromtimestamp(item.get('dateTimestamp', 0) / 1000).strftime('%Y-%m-%d %H:%M')}")
                    print("---")
                return data.get('result', {}).get('list', [])
    except Exception as e:
        logger.error(f"Bybit error: {e}")
    return []

# ============ ГОЛОВНА ФУНКЦІЯ ============
async def main():
    print("🔍 ТЕСТОВИЙ РЕЖИМ - Показую всі анонси які бот бачить\n")
    
    async with aiohttp.ClientSession() as session:
        print("Перевіряю MEXC...")
        await check_mexc(session)
        
        print("\nПеревіряю Binance...")
        await check_binance(session)
        
        print("\nПеревіряю Bybit...")
        await check_bybit(session)
    
    print("\n✅ Тест завершено!")

if __name__ == "__main__":
    asyncio.run(main())
