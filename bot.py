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

# ============ SETTINGS ============
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = 600  # seconds

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID не задані!")

# ============ LOGGING ============
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

STATE_FILE = "bot_state.json"

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "seen_hashes": [],
            "first_run": True,
            "known_pairs": {
                "bingx": [],
                "bitget": []
            }
        }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def generate_hash(title, date):
    return hashlib.md5(f"{title}_{date}".encode()).hexdigest()

def is_futures_announcement(title):
    title_lower = title.lower()
    keywords = ["perpetual","perp","usdt-m","coin-m","delivery","futures","swap","contract"]
    return any(k in title_lower for k in keywords)

def is_listing(title):
    title_lower = title.lower()
    listing = ["list","listing","launch","will list","to list"]
    delisting = ["delist","delisting","remove","removal"]
    if any(d in title_lower for d in delisting):
        return False
    return any(l in title_lower for l in listing)

def is_delisting(title):
    title_lower = title.lower()
    delisting = ["delist","delisting","remove","removal","will delist","to delist"]
    return any(d in title_lower for d in delisting)

# ================= EXCHANGE CHECKS =================

async def check_binance(session):
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=20"
        headers = {"User-Agent":"Mozilla/5.0"}
        async with session.get(url, headers=headers, timeout=15) as r:
            if r.status == 200:
                data = await r.json()
                anns = []
                for a in data.get("data", {}).get("catalogs", [{}])[0].get("articles", []):
                    title = a.get("title","")
                    if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                        date = datetime.fromtimestamp(a.get("releaseDate",0)/1000).strftime("%Y-%m-%d %H:%M")
                        anns.append({
                            "hash": generate_hash(title,date),
                            "title": title,
                            "url": f"https://www.binance.com/en/support/announcement/{a.get('code')}",
                            "date": date,
                            "type": "DELISTING" if is_delisting(title) else "LISTING"
                        })
                return anns
            else:
                logger.warning(f"Binance blocked ({r.status})")
    except Exception as e:
        logger.error(f"Binance error: {e}")
    return []

async def check_bybit(session):
    anns=[]
    try:
        url="https://api.bybit.com/v5/announcements/index?locale=en-US&type=new_crypto&page=1&limit=20"
        async with session.get(url, timeout=15) as r:
            if r.status == 200 and r.headers.get("Content-Type","").startswith("application/json"):
                data = await r.json()
                for a in data.get("result", {}).get("list", []):
                    title = a.get("title","")
                    if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                        date = datetime.fromtimestamp(a.get("dateTimestamp",0)/1000).strftime("%Y-%m-%d %H:%M")
                        anns.append({
                            "hash": generate_hash(title,date),
                            "title": title,
                            "url": a.get("url",""),
                            "date": date,
                            "type":"DELISTING" if is_delisting(title) else "LISTING"
                        })
            else:
                logger.warning("Bybit API blocked → fallback HTML")
                # fallback HTML
                url_html="https://www.bybit.com/announcements"
                async with session.get(url_html, timeout=15) as r2:
                    text = await r2.text()
                    soup = BeautifulSoup(text,"html.parser")
                    for link in soup.find_all("a",href=re.compile("/announcements/")):
                        title = link.get_text(strip=True)
                        if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                            date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                            anns.append({
                                "hash": generate_hash(title,date),
                                "title": title,
                                "url": f"https://www.bybit.com{link.get('href')}",
                                "date": date,
                                "type":"DELISTING" if is_delisting(title) else "LISTING"
                            })
    except Exception as e:
        logger.error(f"Bybit error: {e}")
    return anns

async def check_mexc(session):
    anns=[]
    try:
        url="https://www.mexc.com/announcements/new-listings"
        async with session.get(url,timeout=15) as r:
            text = await r.text()
            soup = BeautifulSoup(text,"html.parser")
            for link in soup.find_all("a",href=re.compile("/announcements/")):
                title = link.get_text(strip=True)
                if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                    date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                    href = link.get("href","")
                    anns.append({
                        "hash": generate_hash(title,date),
                        "title": title,
                        "url": f"https://www.mexc.com{href}" if href.startswith("/") else href,
                        "date": date,
                        "type":"DELISTING" if is_delisting(title) else "LISTING"
                    })
    except Exception as e:
        logger.error(f"MEXC error: {e}")
    return anns

async def check_gateio(session):
    anns=[]
    try:
        url="https://www.gate.io/announcements"
        async with session.get(url,timeout=15) as r:
            text = await r.text()
            soup = BeautifulSoup(text,"html.parser")
            for link in soup.find_all("a"):
                title = link.get_text(strip=True)
                if len(title)>20 and is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                    href=link.get("href","")
                    anns.append({
                        "hash": generate_hash(title,date),
                        "title": title,
                        "url": f"https://www.gate.io{href}" if href.startswith("/") else href,
                        "date": date,
                        "type":"DELISTING" if is_delisting(title) else "LISTING"
                    })
    except Exception as e:
        logger.error(f"Gate.io error: {e}")
    return anns

# BingX & Bitget dynamic symbols
async def check_bingx(session,state,silent=False):
    anns=[]
    try:
        url="https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
        async with session.get(url,timeout=15) as r:
            data=await r.json()
            contracts=data.get("data",[])
            old_symbols=set(state['known_pairs'].get("bingx",[]))
            new_symbols=set(c.get("symbol","") for c in contracts if c.get("status")==1)
            if silent:
                state['known_pairs']['bingx']=list(new_symbols)
                return []
            for sym in new_symbols-old_symbols:
                title=f"New Listing: {sym} Perpetual"
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                anns.append({"hash":generate_hash(title,date),"title":title,"url":f"https://bingx.com/en-us/futures/{sym.replace('-','')}","date":date,"type":"LISTING"})
            for sym in old_symbols-new_symbols:
                title=f"Delisting: {sym} Removed"
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                anns.append({"hash":generate_hash(title,date),"title":title,"url":"https://bingx.com/en-us/futures/","date":date,"type":"DELISTING"})
            state['known_pairs']['bingx']=list(new_symbols)
    except Exception as e:
        if not silent:
            logger.error(f"BingX error: {e}")
    return anns

async def check_bitget(session,state,silent=False):
    anns=[]
    try:
        url="https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
        async with session.get(url,timeout=15) as r:
            data=await r.json()
            tickers=data.get("data",[])
            old_symbols=set(state['known_pairs'].get("bitget",[]))
            new_symbols=set(t.get("symbol","") for t in tickers)
            if silent:
                state['known_pairs']['bitget']=list(new_symbols)
                return []
            for sym in new_symbols-old_symbols:
                title=f"New Listing: {sym} Perpetual"
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                anns.append({"hash":generate_hash(title,date),"title":title,"url":f"https://www.bitget.com/futures/usdt/{sym}","date":date,"type":"LISTING"})
            for sym in old_symbols-new_symbols:
                title=f"Delisting: {sym} Removed"
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                anns.append({"hash":generate_hash(title,date),"title":title,"url":"https://www.bitget.com/futures/","date":date,"type":"DELISTING"})
            state['known_pairs']['bitget']=list(new_symbols)
    except Exception as e:
        if not silent:
            logger.error(f"Bitget error: {e}")
    return anns

async def check_kucoin(session):
    anns=[]
    try:
        url="https://futures.kucoin.com/_api/v1/announcement?type=futures"
        async with session.get(url,timeout=15) as r:
            data=await r.json()
            for a in data.get("items",[]):
                title = a.get("title","")
                if is_futures_announcement(title) and (is_listing(title) or is_delisting(title)):
                    date = a.get("createdAt","")
                    anns.append({
                        "hash": generate_hash(title,date),
                        "title": title,
                        "url": f"https://futures.kucoin.com/announcement/{a.get('id')}",
                        "date": date,
                        "type":"DELISTING" if is_delisting(title) else "LISTING"
                    })
    except Exception as e:
        logger.error(f"KuCoin error: {e}")
    return anns

# ================= SEND TELEGRAM =================
async def send_telegram(bot, exchange, ann):
    emoji="🆕" if ann["type"]=="LISTING" else "⚠️"
    msg=f"{emoji} <b>{exchange} FUTURES {ann['type']}</b>\n\n"
    msg+=f"📰 <b>{ann['title']}</b>\n\n📅 {ann['date']}\n🔗 <a href='{ann['url']}'>Читати повністю</a>"
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text=msg,parse_mode="HTML",disable_web_page_preview=True)
        logger.info(f"✅ {exchange} {ann['type']}")
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")

# ================= MAIN LOOP =================
async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    state = load_state()
    logger.info("🤖 Бот запущено!")
    if state["first_run"]:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text="🤖 Бот запущено!\n🔔 Моніторю 7 бірж FUTURES")
        async with aiohttp.ClientSession() as session:
            await check_bingx(session,state,silent=True)
            await check_bitget(session,state,silent=True)
            state["first_run"]=False
            save_state(state)
    while True:
        async with aiohttp.ClientSession() as session:
            tasks = [
                check_binance(session),
                check_bybit(session),
                check_mexc(session),
                check_gateio(session),
                check_bingx(session,state),
                check_bitget(session,state),
                check_kucoin(session)
            ]
            results = await asyncio.gather(*tasks)
            all_anns=[a for sub in results for a in sub]
            new_found=False
            for ann in all_anns:
                if ann["hash"] not in state["seen_hashes"]:
                    url=ann["url"].lower()
                    exchange="BINANCE" if "binance" in url else \
                             "BYBIT" if "bybit" in url else \
                             "MEXC" if "mexc" in url else \
                             "GATE.IO" if "gate" in url else \
                             "BINGX" if "bingx" in url else \
                             "BITGET" if "bitget" in url else \
                             "KUCOIN" if "kucoin" in url else "UNKNOWN"
                    await send_telegram(bot,exchange,ann)
                    state["seen_hashes"].append(ann["hash"])
                    new_found=True
                    await asyncio.sleep(1)
            # trim old hashes
            state["seen_hashes"]=state["seen_hashes"][-300:]
            save_state(state)
            if new_found:
                logger.info(f"🆕 Нові зміни {datetime.now(timezone.utc).strftime('%H:%M:%S')}")
            else:
                logger.info(f"✅ Перевірка {datetime.now(timezone.utc).strftime('%H:%M:%S')}")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__=="__main__":
    asyncio.run(main())