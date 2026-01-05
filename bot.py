import asyncio
import aiohttp
import json
from datetime import datetime, timezone
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
CHECK_INTERVAL = 600  # 10 хв

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані через змінні середовища!")

# ============ ЛОГУВАННЯ ============
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STATE_FILE = "bot_state.json"

# ============ СТЕЙТ ============
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"seen_hashes": [], "first_run": True, "known_pairs": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def generate_hash(title, date):
    return hashlib.md5(f"{title}_{date}".encode()).hexdigest()

# ============ HELPERS ============
def is_futures_announcement(title):
    title_lower = title.lower()
    keywords = ["perpetual","perp","usdt-m","coin-m","delivery","futures","swap","contract"]
    return any(k in title_lower for k in keywords)

def is_listing(title):
    title_lower = title.lower()
    listing_words = ["list","listing","launch","will list","to list","first in market"]
    delisting_words = ["delist","delisting","remove","removal","will delist","to delist"]
    if any(d in title_lower for d in delisting_words):
        return False
    return any(l in title_lower for l in listing_words)

def is_delisting(title):
    title_lower = title.lower()
    delisting_words = ["delist","delisting","remove","removal","will delist","to delist"]
    return any(d in title_lower for d in delisting_words)

# ============ БІРЖІ ============
async def check_binance(session):
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20"
        headers = {"User-Agent":"Mozilla/5.0"}
        async with session.get(url, headers=headers, timeout=15) as r:
            if r.status == 200 and r.headers.get("Content-Type","").startswith("application/json"):
                data = await r.json()
                announcements=[]
                for art in data.get("data",{}).get("catalogs",[{}])[0].get("articles",[]):
                    title = art.get("title","")
                    if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                        date = datetime.fromtimestamp(art.get("releaseDate",0)/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                        announcements.append({
                            "hash": generate_hash(title,date),
                            "title": title,
                            "url": f"https://www.binance.com/en/support/announcement/{art.get('code')}",
                            "date": date,
                            "type": "DELISTING" if is_delisting(title) else "LISTING"
                        })
                return announcements
            else:
                logger.warning(f"Binance blocked ({r.status})")
    except Exception as e:
        logger.error(f"Binance error: {e}")
    return []

async def check_bybit(session):
    try:
        url = "https://api.bybit.com/v5/announcement?type=futures"
        async with session.get(url, timeout=15) as r:
            if r.status==200 and r.headers.get("Content-Type","").startswith("application/json"):
                data = await r.json()
                announcements=[]
                for ann in data.get("result",[]):
                    title = ann.get("title","")
                    if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                        date = ann.get("date","")
                        announcements.append({
                            "hash": generate_hash(title,date),
                            "title": title,
                            "url": ann.get("url",""),
                            "date": date,
                            "type": "DELISTING" if is_delisting(title) else "LISTING"
                        })
                return announcements
            else:
                logger.warning("Bybit API blocked → fallback HTML")
                # fallback HTML (можна парсити, якщо потрібно)
    except Exception as e:
        logger.error(f"Bybit error: {e}")
    return []

async def check_mexc(session):
    try:
        url="https://www.mexc.com/announcement/new-listings"
        headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"}
        async with session.get(url, headers=headers, timeout=15) as r:
            if r.status==200:
                html = await r.text()
                soup = BeautifulSoup(html,"html.parser")
                announcements=[]
                for a in soup.find_all("a", href=re.compile("/announcements/")):
                    title = a.get_text(strip=True)
                    if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                        href=a.get("href","")
                        announcements.append({
                            "hash": generate_hash(title, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                            "title": title,
                            "url": f"https://www.mexc.com{href}" if href.startswith("/") else href,
                            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                            "type": "DELISTING" if is_delisting(title) else "LISTING"
                        })
                return announcements
    except Exception as e:
        logger.error(f"MEXC error: {e}")
    return []

async def check_gateio(session):
    try:
        url="https://www.gate.io/announcements"
        headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"}
        async with session.get(url, headers=headers, timeout=15) as r:
            if r.status==200:
                html = await r.text()
                soup = BeautifulSoup(html,"html.parser")
                announcements=[]
                for a in soup.find_all("a"):
                    title=a.get_text(strip=True)
                    if len(title)>20 and is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                        href=a.get("href","")
                        announcements.append({
                            "hash": generate_hash(title, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                            "title": title,
                            "url": f"https://www.gate.io{href}" if href.startswith("/") else href,
                            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                            "type": "DELISTING" if is_delisting(title) else "LISTING"
                        })
                return announcements
    except Exception as e:
        logger.error(f"Gate.io error: {e}")
    return []

async def check_bingx(session,state,silent=False):
    try:
        url="https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
        async with session.get(url, timeout=15) as r:
            data = await r.json()
            contracts=data.get("data",[])
            if 'bingx' not in state["known_pairs"]:
                state["known_pairs"]["bingx"]=[]
            current_symbols=[c.get("symbol","") for c in contracts if c.get("status")==1]
            if silent:
                state["known_pairs"]["bingx"]=current_symbols
                return []
            announcements=[]
            old=set(state["known_pairs"]["bingx"])
            new=set(current_symbols)
            for s in new-old:
                title=f"New Listing: {s} Perpetual"
                announcements.append({
                    "hash": generate_hash(title, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                    "title": title,
                    "url": f"https://bingx.com/en-us/futures/{s.replace('-','')}",
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "type":"LISTING"
                })
            for s in old-new:
                title=f"Delisting: {s} Removed"
                announcements.append({
                    "hash": generate_hash(title, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                    "title": title,
                    "url": "https://bingx.com/en-us/futures/",
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "type":"DELISTING"
                })
            state["known_pairs"]["bingx"]=current_symbols
            return announcements
    except Exception as e:
        if not silent:
            logger.error(f"BingX error: {e}")
    return []

async def check_bitget(session,state,silent=False):
    try:
        url="https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        async with session.get(url, timeout=15) as r:
            data = await r.json()
            tickers=data.get("data",[])
            if 'bitget' not in state["known_pairs"]:
                state["known_pairs"]["bitget"]=[]
            current_symbols=[t.get("symbol","") for t in tickers]
            if silent:
                state["known_pairs"]["bitget"]=current_symbols
                return []
            announcements=[]
            old=set(state["known_pairs"]["bitget"])
            new=set(current_symbols)
            for s in new-old:
                title=f"New Listing: {s} Perpetual"
                announcements.append({
                    "hash": generate_hash(title, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                    "title": title,
                    "url": f"https://www.bitget.com/futures/usdt/{s}",
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "type":"LISTING"
                })
            for s in old-new:
                title=f"Delisting: {s} Removed"
                announcements.append({
                    "hash": generate_hash(title, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                    "title": title,
                    "url": "https://www.bitget.com/futures/",
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "type":"DELISTING"
                })
            state["known_pairs"]["bitget"]=current_symbols
            return announcements
    except Exception as e:
        if not silent:
            logger.error(f"Bitget error: {e}")
    return []

async def check_kucoin(session,state,silent=False):
    try:
        url="https://futures.kucoin.com/_api/v1/announcement?type=futures"
        async with session.get(url, timeout=15) as r:
            data = await r.json()
            if "items" not in data:
                return []
            announcements=[]
            for a in data["items"]:
                title=a.get("title","")
                if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                    date=a.get("createdAt","")
                    announcements.append({
                        "hash": generate_hash(title,date),
                        "title": title,
                        "url": f"https://futures.kucoin.com/announcement/{a.get('id')}",
                        "date": date,
                        "type":"DELISTING" if is_delisting(title) else "LISTING"
                    })
            return announcements
    except Exception as e:
        logger.error(f"KuCoin error: {e}")
    return []

# ============ SEND MESSAGE ============
async def send_telegram_message(bot,exchange,announcements):
    if not announcements:
        return
    lines=[]
    for ann in announcements:
        emoji="🆕" if ann["type"]=="LISTING" else "⚠️"
        type_text=ann["type"]
        lines.append(f"{emoji} <b>{exchange} {type_text}</b>\n📰 {ann['title']}\n📅 {ann['date']}\n🔗 <a href='{ann['url']}'>Читати</a>")
    message="\n\n".join(lines)
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text=message,parse_mode="HTML",disable_web_page_preview=True)
        logger.info(f"✅ {exchange} {len(announcements)} announcements sent")
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")

# ============ MAIN ============
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    state = load_state()
    logger.info("🤖 Bot started")

    if state.get("first_run",True):
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text="🤖 Бот запущено!\n📋 Ініціалізація...")
        async with aiohttp.ClientSession() as session:
            # Silent initialization
            await check_bingx(session,state,silent=True)
            await check_bitget(session,state,silent=True)
            await check_kucoin(session,state,silent=True)
            state["first_run"]=False
            save_state(state)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text="✅ Ініціалізація завершена")

    while True:
        async with aiohttp.ClientSession() as session:
            tasks=[
                check_binance(session),
                check_bybit(session),
                check_mexc(session),
                check_gateio(session),
                check_bingx(session,state,silent=False),
                check_bitget(session,state,silent=False),
                check_kucoin(session,state,silent=False)
            ]
            results = await asyncio.gather(*tasks)
            all_announcements=[]
            for res in results:
                all_announcements.extend(res)

            # Фільтруємо дублі
            new_ann=[]
            for ann in all_announcements:
                if ann["hash"] not in state["seen_hashes"]:
                    new_ann.append(ann)
                    state["seen_hashes"].append(ann["hash"])
            if len(state["seen_hashes"])>300:
                state["seen_hashes"]=state["seen_hashes"][-300:]

            # Групуємо по біржах
            exch_map={}
            for ann in new_ann:
                url=ann["url"].lower()
                exch="BINANCE" if "binance" in url else \
                     "BYBIT"   if "bybit" in url   else \
                     "MEXC"    if "mexc" in url    else \
                     "GATE.IO" if "gate" in url    else \
                     "BINGX"   if "bingx" in url   else \
                     "KUCOIN"  if "kucoin" in url  else \
                     "BITGET"
                exch_map.setdefault(exch,[]).append(ann)

            for exch, anns in exch_map.items():
                await send_telegram_message(bot,exch,anns)

            save_state(state)
            if new_ann:
                logger.info(f"🆕 Нові зміни {datetime.now(timezone.utc).strftime('%H:%M:%S')}")
            else:
                logger.info(f"✅ Check {datetime.now(timezone.utc).strftime('%H:%M:%S')}")

        await asyncio.sleep(CHECK_INTERVAL)

if __name__=="__main__":
    asyncio.run(main())