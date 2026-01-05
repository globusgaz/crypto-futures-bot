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
CHECK_INTERVAL = 600  # 10 хвилин

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані!")

# ============ ЛОГУВАННЯ ============
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STATE_FILE = "bot_state.json"

# =================== STATE ===================
def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "seen_hashes": [],
            "first_run": True,
            "known_pairs": {"bingx": [], "bitget": []}
        }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

# =================== HELPERS ===================
def generate_hash(exchange, title):
    return hashlib.sha256(f"{exchange}:{title.lower().strip()}".encode()).hexdigest()

def is_futures_announcement(title):
    title_lower = title.lower()
    keywords = ['perpetual','perp','usdt-m','coin-m','delivery','usdc perpetual','futures','quarterly','swap','contract','usdt-margined']
    spot_only = 'spot' in title_lower and all(k not in title_lower for k in keywords)
    return any(k in title_lower for k in keywords) and not spot_only

def is_listing(title):
    title_lower = title.lower()
    listing_keywords = ['list','listing','launch','new listing','will list','to list']
    delisting_keywords = ['delist','delisting','remove','removal']
    if any(word in title_lower for word in delisting_keywords):
        return False
    return any(word in title_lower for word in listing_keywords)

def is_delisting(title):
    title_lower = title.lower()
    delisting_keywords = ['delist','delisting','remove','removal','will delist','to delist']
    return any(word in title_lower for word in delisting_keywords)

# =================== EXCHANGES ===================
# 1. Binance (HTML fallback)
async def check_binance(session):
    url = "https://www.binance.com/en/support/announcement/futures"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
    announcements = []
    try:
        async with session.get(url, headers=headers, timeout=20) as r:
            if r.status != 200:
                logger.warning(f"Binance blocked ({r.status})")
                return []
            html = await r.text()
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                title = a.get_text(strip=True)
                href = a["href"]
                if not title or "futures" not in title.lower():
                    continue
                if not (is_listing(title) or is_delisting(title)):
                    continue
                full_url = "https://www.binance.com"+href if href.startswith("/") else href
                announcements.append({
                    "hash": generate_hash("BINANCE", title),
                    "title": title,
                    "url": full_url,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "type": "DELISTING" if is_delisting(title) else "LISTING"
                })
        logger.info(f"Binance(HTML): {len(announcements)}")
        return announcements
    except Exception as e:
        logger.error(f"Binance HTML error: {e}")
        return []

# 2. Bybit
async def check_bybit(session):
    url = "https://api.bybit.com/v5/announcements/index?locale=en-US&type=new_crypto&page=1&limit=20"
    announcements = []
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status == 200 and resp.headers.get('Content-Type','').startswith('application/json'):
                data = await resp.json()
                for item in data.get('result', {}).get('list', []):
                    title = item.get('title','')
                    if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                        date = datetime.fromtimestamp(item.get('dateTimestamp',0)/1000).strftime('%Y-%m-%d %H:%M')
                        announcements.append({
                            "hash": generate_hash("BYBIT", title),
                            "title": title,
                            "url": item.get('url',''),
                            "date": date,
                            "type": "DELISTING" if is_delisting(title) else "LISTING"
                        })
            else:
                logger.warning(f"Bybit API blocked → fallback HTML")
    except Exception as e:
        logger.error(f"Bybit error: {e}")
    return announcements

# 3. MEXC
async def check_mexc(session):
    url="https://www.mexc.com/announcements/new-listings"
    headers={'User-Agent':'Mozilla/5.0','Accept':'text/html'}
    announcements=[]
    try:
        async with session.get(url, headers=headers, timeout=20) as resp:
            if resp.status==200:
                text = await resp.text()
                soup = BeautifulSoup(text,'html.parser')
                for link in soup.find_all('a', href=re.compile('/announcements/')):
                    title = link.get_text(strip=True)
                    if len(title)<5: continue
                    if not is_futures_announcement(title): continue
                    if not (is_listing(title) or is_delisting(title)): continue
                    href = link.get('href','')
                    announcements.append({
                        "hash": generate_hash("MEXC", title),
                        "title": title,
                        "url": f"https://www.mexc.com{href}" if href.startswith('/') else href,
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "type": "DELISTING" if is_delisting(title) else "LISTING"
                    })
    except Exception as e:
        logger.error(f"MEXC error: {e}")
    logger.info(f"MEXC: {len(announcements)}")
    return announcements

# 4. Gate.io
async def check_gateio(session):
    url="https://www.gate.io/announcements"
    headers={'User-Agent':'Mozilla/5.0','Accept':'text/html'}
    announcements=[]
    try:
        async with session.get(url, headers=headers, timeout=20) as resp:
            if resp.status==200:
                text = await resp.text()
                soup = BeautifulSoup(text,'html.parser')
                for link in soup.find_all('a', href=True):
                    title = link.get_text(strip=True)
                    if len(title)<5: continue
                    if not is_futures_announcement(title): continue
                    if not (is_listing(title) or is_delisting(title)): continue
                    href = link.get('href','')
                    announcements.append({
                        "hash": generate_hash("GATE.IO", title),
                        "title": title,
                        "url": f"https://www.gate.io{href}" if href.startswith('/') else href,
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "type": "DELISTING" if is_delisting(title) else "LISTING"
                    })
    except Exception as e:
        logger.error(f"Gate.io error: {e}")
    logger.info(f"Gate.io: {len(announcements)}")
    return announcements

# 5. BingX
async def check_bingx(session, state, silent=False):
    url="https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status!=200: return []
            data = await resp.json()
            contracts = data.get('data',[])
            if 'known_pairs' not in state: state['known_pairs']={}
            if 'bingx' not in state['known_pairs']: state['known_pairs']['bingx']=[]
            current_symbols=[c.get('symbol','') for c in contracts if c.get('status')==1]
            if silent:
                state['known_pairs']['bingx']=current_symbols
                return []
            announcements=[]
            old_symbols=set(state['known_pairs']['bingx'])
            new_symbols=set(current_symbols)
            for s in new_symbols-old_symbols:
                title=f"New Listing: {s} Perpetual"
                announcements.append({
                    "hash": generate_hash("BINGX", title),
                    "title": title,
                    "url": f"https://bingx.com/en-us/futures/{s.replace('-','')}",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "type":"LISTING"
                })
            for s in old_symbols-new_symbols:
                title=f"Delisting: {s} Removed"
                announcements.append({
                    "hash": generate_hash("BINGX", title),
                    "title": title,
                    "url": "https://bingx.com/en-us/futures/",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "type":"DELISTING"
                })
            state['known_pairs']['bingx']=current_symbols
            return announcements
    except Exception as e:
        if not silent:
            logger.error(f"BingX error: {e}")
    return []

# 6. Bitget
async def check_bitget(session,state,silent=False):
    url="https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status!=200: return []
            data = await resp.json()
            tickers = data.get('data',[])
            if 'known_pairs' not in state: state['known_pairs']={}
            if 'bitget' not in state['known_pairs']: state['known_pairs']['bitget']=[]
            current_symbols=[t.get('symbol','') for t in tickers]
            if silent:
                state['known_pairs']['bitget']=current_symbols
                return []
            announcements=[]
            old_symbols=set(state['known_pairs']['bitget'])
            new_symbols=set(current_symbols)
            for s in list(new_symbols-old_symbols)[:10]:
                title=f"New Listing: {s} Perpetual"
                announcements.append({
                    "hash": generate_hash("BITGET", title),
                    "title": title,
                    "url": f"https://www.bitget.com/futures/usdt/{s}",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "type":"LISTING"
                })
            for s in list(old_symbols-new_symbols)[:10]:
                title=f"Delisting: {s} Removed"
                announcements.append({
                    "hash": generate_hash("BITGET", title),
                    "title": title,
                    "url": "https://www.bitget.com/futures/",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "type":"DELISTING"
                })
            state['known_pairs']['bitget']=current_symbols
            return announcements
    except Exception as e:
        if not silent:
            logger.error(f"Bitget error: {e}")
    return []

# 7. KuCoin
async def check_kucoin(session):
    url="https://futures.kucoin.com/_api/v1/announcement?type=futures"
    announcements=[]
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status!=200: return []
            data = await resp.json()
            for ann in data.get("items", []):
                title=ann.get("title","")
                if not is_futures_announcement(title): continue
                if not (is_listing(title) or is_delisting(title)): continue
                date=ann.get("createdAt","")
                announcements.append({
                    "hash": generate_hash("KUCOIN", title),
                    "title": title,
                    "url": f"https://futures.kucoin.com/announcement/{ann.get('id')}",
                    "date": date,
                    "type":"DELISTING" if is_delisting(title) else "LISTING"
                })
    except Exception as e:
        logger.error(f"KuCoin error: {e}")
    return announcements

# =================== TELEGRAM ===================
async def send_telegram_message(bot, exchange, announcement):
    emoji = "🆕" if announcement["type"]=="LISTING" else "⚠️"
    type_text = "LISTING" if announcement["type"]=="LISTING" else "DELISTING"
    message=f"{emoji} <b>{exchange} FUTURES {type_text}</b>\n\n"
    message+=f"📰 <b>{announcement['title']}</b>\n\n"
    message+=f"📅 {announcement['date']}\n"
    message+=f"🔗 <a href=\"{announcement['url']}\">Читати повністю</a>"
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text=message,parse_mode='HTML',disable_web_page_preview=True)
        logger.info(f"✅ {exchange} {type_text}")
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")

# =================== MAIN ===================
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    state = load_state()
    logger.info("🤖 Бот запущено!")

    if state['first_run']:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text="🤖 Бот запущено!\n\n📋 Ініціалізація...\n🆕 Лістинги\n⚠️ Делістинги")
        async with aiohttp.ClientSession() as session:
            await check_bingx(session,state,silent=True)
            await check_bitget(session,state,silent=True)
        state['first_run'] = False
        save_state(state)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text="✅ Готово!\n🔔 Моніторю 7 бірж")

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                binance = await check_binance(session)
                bybit   = await check_bybit(session)
                mexc    = await check_mexc(session)
                gateio  = await check_gateio(session)
                bingx   = await check_bingx(session,state)
                bitget  = await check_bitget(session,state)
                kucoin  = await check_kucoin(session)
                all_announcements = binance + bybit + mexc + gateio + bingx + bitget + kucoin

                new_found=False
                for ann in all_announcements:
                    if ann["hash"] not in state["seen_hashes"]:
                        url=ann["url"].lower()
                        exchange = ("BINANCE" if "binance" in url else
                                    "BYBIT"   if "bybit" in url else
                                    "MEXC"    if "mexc" in url else
                                    "GATE.IO" if "gate" in url else
                                    "BINGX"   if "bingx" in url else
                                    "KUCOIN"  if "kucoin" in url else
                                    "BITGET")
                        await send_telegram_message(bot, exchange, ann)
                        state["seen_hashes"].append(ann["hash"])
                        new_found=True
                        await asyncio.sleep(1)
                if len(state["seen_hashes"])>300:
                    state["seen_hashes"]=state["seen_hashes"][-300:]
                save_state(state)
                if new_found:
                    logger.info(f"🆕 Нові зміни {datetime.now().strftime('%H:%M:%S')}")
                else:
                    logger.info(f"✅ Перевірка {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            logger.error(f"Error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__=="__main__":
    asyncio.run(main())