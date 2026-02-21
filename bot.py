"""
🛡️ Military Intel Bot — با ترجمه فارسی خودکار
Iran · Israel · USA | RSS + Google News + Twitter/X (Nitter)
"""

import os, json, hashlib, time, re, logging, asyncio
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import feedparser, httpx, pytz
from deep_translator import GoogleTranslator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("MilBot")

BOT_TOKEN       = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID      = os.environ.get("CHANNEL_ID", "")
SEEN_FILE       = "seen.json"
MAX_NEW_PER_RUN = 30
SEND_DELAY      = 3
MAX_MSG_LEN     = 4000
TEHRAN_TZ       = pytz.timezone("Asia/Tehran")
translator      = GoogleTranslator(source='auto', target='fa')

# ── ترجمه ─────────────────────────────────────────────────────
def is_persian(text):
    return len(re.findall(r'[\u0600-\u06FF]', text)) > len(text) * 0.3

def translate_to_persian(text, max_chars=4500):
    if not text or not text.strip() or is_persian(text):
        return text
    text = text[:max_chars]
    for attempt in range(3):
        try:
            result = translator.translate(text)
            if result and result.strip():
                return result.strip()
        except Exception as e:
            log.debug(f"ترجمه خطا (تلاش {attempt+1}): {e}")
            time.sleep(1.5)
    return text

# ── فیدهای RSS ───────────────────────────────────────────────
RSS_FEEDS = [
    {"name": "🇺🇸 Pentagon",          "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"name": "🇺🇸 CENTCOM",           "url": "https://www.centcom.mil/RSS/"},
    {"name": "🇺🇸 USNI News",         "url": "https://news.usni.org/feed"},
    {"name": "🇺🇸 Stars & Stripes",   "url": "https://www.stripes.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "🇺🇸 Military Times",    "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Defense News",      "url": "https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Breaking Defense",  "url": "https://breakingdefense.com/feed/"},
    {"name": "🇺🇸 The War Zone",      "url": "https://www.thedrive.com/feeds/the-war-zone"},
    {"name": "🇺🇸 War on Rocks",      "url": "https://warontherocks.com/feed/"},
    {"name": "🇺🇸 C4ISRNET",          "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/"},
    {"name": "🇮🇱 IDF Official",      "url": "https://www.idf.il/en/mini-sites/idf-spokesperson-english/feed/"},
    {"name": "🇮🇱 Jerusalem Post",    "url": "https://www.jpost.com/rss/rssfeedsmilitary.aspx"},
    {"name": "🇮🇱 Times of Israel",   "url": "https://www.timesofisrael.com/feed/"},
    {"name": "🇮🇱 Haaretz",           "url": "https://www.haaretz.com/cmlink/1.4455099"},
    {"name": "🇮🇱 Israel Hayom",      "url": "https://www.israelhayom.com/feed/"},
    {"name": "🇮🇱 Ynetnews",          "url": "https://www.ynetnews.com/category/3082/feed"},
    {"name": "🇮🇱 i24 News",          "url": "https://www.i24news.tv/en/rss"},
    {"name": "🇮🇱 Arutz Sheva",       "url": "https://www.israelnationalnews.com/Rss.aspx/news"},
    {"name": "🇮🇷 Iran International","url": "https://www.iranintl.com/en/rss"},
    {"name": "🇮🇷 Radio Farda",       "url": "https://www.radiofarda.com/api/zmqpqopvp"},
    {"name": "🌐 Al-Monitor",         "url": "https://www.al-monitor.com/rss.xml"},
    {"name": "🌐 Middle East Eye",    "url": "https://www.middleeasteye.net/rss"},
    {"name": "🌐 Reuters World",      "url": "https://feeds.reuters.com/reuters/worldNews"},
    {"name": "🌐 BBC Middle East",    "url": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"name": "🌐 AP Defense",         "url": "https://apnews.com/hub/military-and-defense?format=rss"},
    {"name": "🌐 Foreign Policy",     "url": "https://foreignpolicy.com/feed/"},
    {"name": "🌐 ISW",                "url": "https://www.understandingwar.org/rss.xml"},
    {"name": "🌐 Long War Journal",   "url": "https://www.longwarjournal.org/feed"},
    {"name": "🌐 Bellingcat",         "url": "https://www.bellingcat.com/feed/"},
    {"name": "🌐 OSINT Defender",     "url": "https://osintdefender.com/feed/"},
    {"name": "🌐 Lawfare",            "url": "https://www.lawfaremedia.org/feed"},
    {"name": "🌐 Axios NatSec",       "url": "https://api.axios.com/feed/national-security"},
]

# ── گوگل نیوز ─────────────────────────────────────────────────
GOOGLE_NEWS_QUERIES = [
    ("⚔️ Iran Israel War",      "Iran Israel war attack strike"),
    ("⚔️ Iran USA Military",    "Iran United States military IRGC"),
    ("⚔️ Iran Nuclear",         "Iran nuclear deal bomb missile"),
    ("⚔️ IDF Operation",        "IDF military operation Gaza Lebanon"),
    ("⚔️ Iran Sanctions",       "Iran sanctions SWIFT oil embargo"),
    ("⚔️ Middle East Conflict", "Middle East military conflict attack"),
    ("⚔️ Hezbollah IRGC",       "Hezbollah IRGC proxy militia Lebanon"),
    ("⚔️ Strait of Hormuz",     "Strait Hormuz oil tanker navy ship"),
    ("⚔️ Iran Drone Missile",   "Iran drone missile ballistic hypersonic"),
    ("⚔️ Israel Airstrike",     "Israel airstrike bomb Syria Iraq Iran"),
    ("⚔️ US Navy 5th Fleet",    "US Navy 5th fleet carrier Bahrain Gulf"),
    ("⚔️ Mossad CIA Operation", "Mossad CIA intelligence operation covert"),
    ("⚔️ Khamenei Netanyahu",   "Khamenei Netanyahu war threat"),
    ("⚔️ CENTCOM Operations",   "CENTCOM US forces Middle East operations"),
    ("⚔️ Iron Dome F-35",       "Iron Dome F-35 Arrow Patriot Israel defense"),
]

def google_news_url(q):
    return f"https://news.google.com/rss/search?q={q.replace(' ','+')}&hl=en-US&gl=US&ceid=US:en&num=20"

GOOGLE_FEEDS = [{"name": name, "url": google_news_url(q), "is_google": True} for name, q in GOOGLE_NEWS_QUERIES]

# ── توییتر/Nitter ──────────────────────────────────────────────
TWITTER_ACCOUNTS = [
    ("🔍 OSINT Defender",   "OSINTdefender"),
    ("🔍 Intel Crab",       "IntelCrab"),
    ("🔍 War Monitor",      "WarMonitor3"),
    ("🔍 Conflicts",        "Conflicts"),
    ("🔍 Aurora Intel",     "AuroraIntel"),
    ("🔍 Jake Hanrahan",    "Jake_Hanrahan"),
    ("🇮🇱 IDF",            "IDF"),
    ("🇮🇱 Barak Ravid",    "BarakRavid"),
    ("🇮🇱 Yossi Melman",   "yossi_melman"),
    ("🇮🇱 Seth Frantzman",  "sfrantzman"),
    ("🇮🇷 Iran Intl Eng",  "IranIntl_En"),
    ("🇮🇷 Farnaz Fassihi", "farnazfassihi"),
    ("🇺🇸 CENTCOM",        "CENTCOM"),
    ("🇺🇸 Lara Seligman",  "laraseligman"),
    ("🇺🇸 Jack Detsch",    "JackDetsch"),
    ("🇺🇸 Dan Lamothe",    "DanLamothe"),
    ("🌐 Joyce Karam",      "Joyce_Karam"),
    ("🌐 Lindsey Snell",    "LindseySnell"),
    ("🌐 Ragip Soylu",      "ragipsoylu"),
    ("⚠️ DEFCON Level",    "DEFCONLevel"),
    ("⚠️ Arms Control",    "ArmsControlWonk"),
]

NITTER_MIRRORS = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

NITTER_FEEDS = [
    {"name": f"𝕏 {name}", "url": f"{NITTER_MIRRORS[0]}/{handle}/rss", "nitter_handle": handle}
    for name, handle in TWITTER_ACCOUNTS
]

ALL_FEEDS = RSS_FEEDS + GOOGLE_FEEDS + NITTER_FEEDS

# ── فیلتر ─────────────────────────────────────────────────────
KEYWORDS = [
    "iran","irgc","khamenei","tehran","revolutionary guard","nuclear",
    "israel","idf","mossad","tel aviv","netanyahu","gaza","west bank",
    "hezbollah","hamas","houthi","ansarallah","pentagon","centcom",
    "strike","airstrike","missile","ballistic","drone","uav","attack",
    "bomb","explosion","assassination","operation","warship","carrier",
    "navy","air force","persian gulf","strait of hormuz","red sea",
    "middle east","syria","iraq","lebanon","yemen","bahrain",
    "iron dome","arrow","patriot","f-35","hypersonic","uranium",
    "enrichment","centrifuge","fordo","natanz","cia","covert","sanctions",
    "سپاه","موشک","جنگ","حمله","اسراییل","آمریکا","ایران","هسته‌ای",
]

def is_relevant(entry, is_twitter=False):
    if is_twitter:
        return True
    text = " ".join([str(entry.get("title","")), str(entry.get("summary",""))]).lower()
    return any(kw in text for kw in KEYWORDS)

# ── ابزارها ───────────────────────────────────────────────────
def clean_html(text):
    if not text:
        return ""
    return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

def truncate(text, n=800):
    return text[:n].rsplit(" ",1)[0] + "…" if len(text) > n else text

def make_id(entry):
    key = entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(key.encode("utf-8")).hexdigest()

def format_dt(entry):
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            dt = datetime(*t[:6], tzinfo=timezone.utc).astimezone(TEHRAN_TZ)
            return dt.strftime("🕐 %H:%M  |  📅 %Y/%m/%d")
    except:
        pass
    return ""

def esc(text):
    return text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def build_message(entry, source, is_twitter=False):
    raw_title   = clean_html(entry.get("title","")).strip()
    raw_summary = clean_html(entry.get("summary") or entry.get("description") or "").strip()
    link        = entry.get("link","")
    dt          = format_dt(entry)

    title_fa   = esc(translate_to_persian(raw_title, 300))
    summary_fa = ""
    if raw_summary:
        summary_fa = esc(translate_to_persian(truncate(raw_summary, 800), 800))

    icon = "𝕏" if is_twitter else "📡"
    lines = [f"<b>{title_fa}</b>", ""]
    if summary_fa and summary_fa != title_fa:
        lines += [summary_fa, ""]
    if dt:
        lines.append(dt)
    lines.append(f"{icon} <b>{source}</b>")
    if link:
        lines.append(f'🔗 <a href="{link}">منبع اصلی</a>')
    return "\n".join(lines)

# ── حافظه ─────────────────────────────────────────────────────
def load_seen():
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f:
                return set(json.load(f))
        except:
            pass
    return set()

def save_seen(seen):
    with open(SEEN_FILE,"w") as f:
        json.dump(list(seen)[-8000:], f)

# ── فیلد فیدها ────────────────────────────────────────────────
def fetch_feed(cfg):
    handle = cfg.get("nitter_handle")
    if handle:
        for mirror in NITTER_MIRRORS:
            try:
                p = feedparser.parse(f"{mirror}/{handle}/rss", request_headers={"User-Agent":"MilNewsBot/3.0"})
                if p.entries:
                    return p.entries
            except:
                continue
        return []
    try:
        p = feedparser.parse(cfg["url"], request_headers={"User-Agent":"MilNewsBot/3.0"})
        return p.entries or []
    except:
        return []

# ── تلگرام ────────────────────────────────────────────────────
TGAPI = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_send(client, text):
    for attempt in range(4):
        try:
            r = await client.post(f"{TGAPI}/sendMessage", json={
                "chat_id": CHANNEL_ID,
                "text": text[:MAX_MSG_LEN],
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }, timeout=25)
            data = r.json()
            if data.get("ok"):
                return True
            if data.get("error_code") == 429:
                await asyncio.sleep(data.get("parameters",{}).get("retry_after",35))
            else:
                log.error(f"TG: {data}")
                await asyncio.sleep(5)
        except Exception as e:
            log.warning(f"TG attempt {attempt+1}: {e}")
            await asyncio.sleep(8)
    return False

async def send_startup(client):
    now = datetime.now(TEHRAN_TZ).strftime("%Y/%m/%d  %H:%M")
    await tg_send(client,
        f"🛡️ <b>Military Intel Bot — آنلاین</b>\n\n"
        f"⏰ {now}\n"
        f"📡 <b>{len(RSS_FEEDS)}</b> منبع RSS نظامی\n"
        f"📰 <b>{len(GOOGLE_FEEDS)}</b> جستجوی Google News\n"
        f"𝕏 <b>{len(TWITTER_ACCOUNTS)}</b> خبرنگار Twitter\n"
        f"🌐 ترجمه خودکار به فارسی: فعال ✅\n\n"
        "#شروع #military_bot"
    )

# ── حلقه اصلی ─────────────────────────────────────────────────
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID تنظیم نشده!")
        return

    is_first_run = not Path(SEEN_FILE).exists()
    seen = load_seen()
    log.info(f"🚀 شروع | {len(seen)} آیتم در حافظه")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        if is_first_run:
            await send_startup(client)

        collected = []
        for cfg in ALL_FEEDS:
            is_tw = bool(cfg.get("nitter_handle"))
            entries = fetch_feed(cfg)
            count = 0
            for entry in entries:
                eid = make_id(entry)
                if eid in seen:
                    continue
                if not is_relevant(entry, is_twitter=is_tw):
                    seen.add(eid)
                    continue
                collected.append((eid, entry, cfg, is_tw))
                count += 1
            if count:
                log.info(f"  📥 {cfg['name']}: {count} جدید")

        if len(collected) > MAX_NEW_PER_RUN:
            collected = collected[-MAX_NEW_PER_RUN:]

        sent = 0
        for eid, entry, cfg, is_tw in collected:
            log.info(f"  🔄 ترجمه: {entry.get('title','')[:55]}")
            msg = build_message(entry, cfg["name"], is_tw)
            ok = await tg_send(client, msg)
            if ok:
                seen.add(eid)
                sent += 1
                log.info(f"  ✅ ارسال شد")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"✔️ پایان | {sent}/{len(collected)} ارسال شد")

if __name__ == "__main__":
    asyncio.run(main())
