"""
╔══════════════════════════════════════════════════════════════════════════╗
║        🛡️ Military Intel Bot v8 — Fixed + Expanded + Hazm               ║
║   Iran · Israel · USA  |  70+ منبع  |  Gemini AI  |  ترجمه فارسی       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os, json, hashlib, asyncio, logging, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser, httpx, pytz

# Hazm برای نرمال‌سازی فارسی خروجی AI
try:
    from hazm import Normalizer as HazmNormalizer
    _hazm = HazmNormalizer()
    def normalize_fa(text: str) -> str:
        return _hazm.normalize(text)
except ImportError:
    def normalize_fa(text: str) -> str:
        text = text.replace("ي", "ی").replace("ك", "ک")
        return re.sub(r'  +', ' ', text).strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("MilBot")

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SEEN_FILE       = "seen.json"
MAX_NEW_PER_RUN = 20     # با ۱۰ دقیقه interval کافیه
MAX_MSG_LEN     = 4096
SEND_DELAY      = 2
TEHRAN_TZ       = pytz.timezone("Asia/Tehran")

# ساعت ۳:۱۸ تهران (UTC+3:30) = ۲۳:۴۸ UTC روز ۲۱ فوریه
# هیچ خبری قبل از این لحظه ارسال نمی‌شود — سخت‌گیرانه
NEWS_CUTOFF = datetime(2026, 2, 21, 23, 48, 0, tzinfo=timezone.utc)

RSS_FEEDS = [
    {"name": "🌐 Reuters World",       "url": "https://feeds.reuters.com/reuters/worldNews"},
    {"name": "🌐 Reuters Top",         "url": "https://feeds.reuters.com/reuters/topNews"},
    {"name": "🌐 AP Top News",         "url": "https://feeds.apnews.com/rss/apf-topnews"},
    {"name": "🌐 AP World",            "url": "https://feeds.apnews.com/rss/apf-WorldNews"},
    {"name": "🌐 AP Military",         "url": "https://apnews.com/hub/military-and-defense?format=rss"},
    {"name": "🌐 Bloomberg Politics",  "url": "https://feeds.bloomberg.com/politics/news.rss"},
    {"name": "🌐 WSJ World",           "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"},
    {"name": "🌐 NYT World",           "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.rss"},
    {"name": "🌐 CNN Middle East",     "url": "http://rss.cnn.com/rss/edition_meast.rss"},
    {"name": "🌐 CNN World",           "url": "http://rss.cnn.com/rss/edition_world.rss"},
    {"name": "🌐 BBC Middle East",     "url": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"name": "🌐 BBC World",           "url": "http://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "🌐 Al Jazeera English",  "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "🌐 Fox News World",      "url": "https://moxie.foxnews.com/google-publisher/world.xml"},
    {"name": "🌐 Politico NatSec",    "url": "https://rss.politico.com/defense.xml"},
    {"name": "🌐 Politico Politics",  "url": "https://rss.politico.com/politics-news.xml"},
    {"name": "🌐 The Hill",           "url": "https://thehill.com/rss/syndicator/19110"},
    {"name": "📰 Axios NatSec",        "url": "https://api.axios.com/feed/national-security"},
    {"name": "📰 Axios World",         "url": "https://api.axios.com/feed/world"},
    {"name": "📰 Axios Top",           "url": "https://api.axios.com/feed/top-stories"},
    {"name": "📰 Axios Politics",      "url": "https://api.axios.com/feed/politics"},
    {"name": "🇺🇸 Pentagon",           "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"name": "🇺🇸 CENTCOM",            "url": "https://www.centcom.mil/RSS/"},
    {"name": "🇺🇸 USNI News",          "url": "https://news.usni.org/feed"},
    {"name": "🇺🇸 Breaking Defense",   "url": "https://breakingdefense.com/feed/"},
    {"name": "🇺🇸 Defense News",       "url": "https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Military Times",     "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Stars and Stripes",  "url": "https://www.stripes.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "🇺🇸 C4ISRNET",           "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 The War Zone",       "url": "https://www.thedrive.com/feeds/the-war-zone"},
    {"name": "🇺🇸 War on the Rocks",   "url": "https://warontherocks.com/feed/"},
    {"name": "🇺🇸 Task & Purpose",     "url": "https://taskandpurpose.com/feed/"},
    {"name": "🇺🇸 Janes",              "url": "https://www.janes.com/feeds/news"},
    {"name": "🇮🇱 IDF Official",       "url": "https://www.idf.il/en/mini-sites/idf-spokesperson-english/feed/"},
    {"name": "🇮🇱 Jerusalem Post",     "url": "https://www.jpost.com/rss/rssfeedsmilitary.aspx"},
    {"name": "🇮🇱 Jerusalem Post All", "url": "https://www.jpost.com/rss/rssfeedsheadlines.aspx"},
    {"name": "🇮🇱 Times of Israel",    "url": "https://www.timesofisrael.com/feed/"},
    {"name": "🇮🇱 Haaretz English",    "url": "https://www.haaretz.com/cmlink/1.4455099"},
    {"name": "🇮🇱 Israel Hayom",       "url": "https://www.israelhayom.com/feed/"},
    {"name": "🇮🇱 Ynetnews",           "url": "https://www.ynetnews.com/category/3082/feed"},
    {"name": "🇮🇱 i24 News",           "url": "https://www.i24news.tv/en/rss"},
    {"name": "🇮🇱 Arutz Sheva",        "url": "https://www.israelnationalnews.com/Rss.aspx/news"},
    {"name": "🇮🇷 Iran International", "url": "https://www.iranintl.com/en/rss"},
    {"name": "🇮🇷 Radio Farda",        "url": "https://www.radiofarda.com/api/zmqpqopvp"},
    {"name": "🌐 Al-Monitor ME",       "url": "https://www.al-monitor.com/rss.xml"},
    {"name": "🌐 Middle East Eye",     "url": "https://www.middleeasteye.net/rss"},
    {"name": "🌐 Arab News",           "url": "https://www.arabnews.com/rss.xml"},
    {"name": "🔍 ISW",                 "url": "https://www.understandingwar.org/rss.xml"},
    {"name": "🔍 Long War Journal",    "url": "https://www.longwarjournal.org/feed"},
    {"name": "🔍 Bellingcat",          "url": "https://www.bellingcat.com/feed/"},
    {"name": "🔍 OSINT Defender",      "url": "https://osintdefender.com/feed/"},
    {"name": "🔍 Lawfare Blog",        "url": "https://www.lawfaremedia.org/feed"},
    {"name": "🔍 Foreign Policy",      "url": "https://foreignpolicy.com/feed/"},
    {"name": "🔍 Foreign Affairs",     "url": "https://www.foreignaffairs.com/rss.xml"},
    {"name": "🔍 RAND Security",       "url": "https://www.rand.org/topics/defense-and-security.xml"},
    {"name": "🔍 Just Security",       "url": "https://www.justsecurity.org/feed/"},
]

GOOGLE_NEWS_QUERIES = [
    ("⚔️ Iran Israel War",          "Iran Israel war attack strike today"),
    ("⚔️ Iran Airstrike",           "Iran airstrike bomb explosion 2026"),
    ("⚔️ US Iran Military",         "United States Iran military IRGC 2026"),
    ("⚔️ IDF Operation",            "IDF military operation strike 2026"),
    ("⚔️ Iran Nuclear 2026",        "Iran nuclear IAEA uranium enrichment 2026"),
    ("⚔️ Iran Drone Missile",       "Iran ballistic missile drone attack"),
    ("⚔️ Hezbollah IDF",            "Hezbollah IDF Lebanon border strike"),
    ("⚔️ Strait Hormuz",            "Strait Hormuz tanker navy seized"),
    ("⚔️ IRGC CENTCOM",             "IRGC Revolutionary Guard CENTCOM base"),
    ("⚔️ Israel Airstrike",         "Israel F-35 airstrike Syria Iraq Iran"),
    ("⚔️ Mossad CIA",               "Mossad CIA covert operation"),
    ("⚔️ Khamenei Netanyahu",       "Khamenei Netanyahu war threat"),
    ("⚔️ US Carrier Gulf",          "US carrier strike group Persian Gulf"),
    ("⚔️ Iron Dome Intercept",      "Iron Dome Patriot Arrow intercept missile"),
    ("⚔️ Iran Sanctions 2026",      "Iran sanctions 2026 oil SWIFT"),
    ("⚔️ Red Sea Houthis",          "Red Sea Houthi attack ship missile"),
    ("⚔️ Gaza Ceasefire 2026",      "Gaza ceasefire Hamas IDF deal 2026"),
    ("⚔️ Iran Proxy Iraq",          "Iran proxy militia Iraq Syria US base attack"),
    ("⚔️ DEFCON Nuclear",           "DEFCON nuclear military escalation"),
    ("⚔️ Trump Iran Policy",        "Trump Iran Israel military policy 2026"),
]

def gnews(q): return f"https://news.google.com/rss/search?q={q.replace(' ','+')}&hl=en-US&gl=US&ceid=US:en&num=15"
GOOGLE_FEEDS = [{"name": n, "url": gnews(q), "is_google": True} for n, q in GOOGLE_NEWS_QUERIES]

TWITTER_ACCOUNTS = [
    ("🔍 OSINT Defender",      "OSINTdefender"),
    ("🔍 Intel Crab",          "IntelCrab"),
    ("🔍 War Monitor",         "WarMonitor3"),
    ("🔍 Conflicts.media",     "Conflicts"),
    ("🔍 Aurora Intel",        "AuroraIntel"),
    ("🔍 Jake Hanrahan",       "Jake_Hanrahan"),
    ("🔍 GeoConfirmed",        "GeoConfirmed"),
    ("📰 Axios: Barak Ravid",  "BarakRavid"),
    ("📰 Axios: Alex Ward",    "alexward1961"),
    ("📰 Axios: Zach Basu",    "ZachBasu"),
    ("📰 Reuters: Idrees Ali", "idreesali114"),
    ("📰 Reuters: Phil Stewart","phil_stewart_"),
    ("📰 NYT: Farnaz Fassihi", "farnazfassihi"),
    ("📰 NYT: Eric Schmitt",   "EricSchmittNYT"),
    ("📰 NYT: Helene Cooper",  "helenecooper"),
    ("📰 WaPo: Dan Lamothe",   "DanLamothe"),
    ("📰 Politico: Lara S",    "laraseligman"),
    ("📰 FP: Jack Detsch",     "JackDetsch"),
    ("📰 FP: Robbie Gramer",   "RobbieGramer"),
    ("📰 NatashaBertrand",     "NatashaBertrand"),
    ("🇮🇱 IDF Official",       "IDF"),
    ("🇮🇱 Yossi Melman",       "yossi_melman"),
    ("🇮🇱 Seth Frantzman",     "sfrantzman"),
    ("🇮🇱 Avi Issacharoff",    "AviIssacharoff"),
    ("🇮🇱 Ben Caspit",         "BenCaspit"),
    ("🇮🇷 Iran Intl English",  "IranIntl_En"),
    ("🇮🇷 Radio Farda",        "RadioFarda_"),
    ("🇺🇸 CENTCOM",            "CENTCOM"),
    ("🇺🇸 Dept of Defense",    "DeptofDefense"),
    ("🌐 Joyce Karam",         "Joyce_Karam"),
    ("🌐 Ragip Soylu",         "ragipsoylu"),
    ("🌐 Lindsey Snell",       "LindseySnell"),
    ("⚠️ DEFCON Level",        "DEFCONLevel"),
    ("⚠️ Arms Control Wonk",   "ArmsControlWonk"),
]

NITTER_MIRRORS = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

def get_twitter_feeds():
    return [{"name": f"𝕏 {n}", "url": f"{NITTER_MIRRORS[0]}/{h}/rss",
             "nitter_handle": h, "nitter_mirrors": NITTER_MIRRORS}
            for n, h in TWITTER_ACCOUNTS]

ALL_FEEDS = RSS_FEEDS + GOOGLE_FEEDS + get_twitter_feeds()

KEYWORDS = [
    "سپاه","موشک","جنگ","حمله","اسراییل","آمریکا","ایران","هسته‌ای","پهپاد","نظامی",
    "iran","irgc","khamenei","tehran","revolutionary guard","nuclear",
    "israel","idf","mossad","tel aviv","netanyahu","hamas","hezbollah","houthi",
    "pentagon","centcom","us forces","us military","us base","american",
    "strike","airstrike","missile","ballistic","drone","attack","bomb","explosion",
    "assassination","operation","warship","carrier","navy","air force",
    "persian gulf","strait of hormuz","red sea","middle east",
    "iron dome","arrow","patriot","hypersonic","uranium","enrichment","natanz","fordo",
    "intelligence","cia","covert","sanction","embargo",
    "gaza","west bank","lebanon","syria","iraq","yemen","bahrain",
    "trump","rubio","war","conflict","escalat","deploy","military",
]

def is_fresh(entry):
    """فقط خبرهای بعد از ۰۳:۱۸ تهران ۲۲ فوریه — سخت‌گیرانه"""
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t:
            return False  # خبر بدون تاریخ رد می‌شود
        dt = datetime(*t[:6], tzinfo=timezone.utc)
        return dt >= NEWS_CUTOFF
    except:
        return False  # در صورت خطا رد می‌شود

def is_relevant(entry, is_twitter=False):
    text = " ".join([str(entry.get("title","")), str(entry.get("summary","")),
                     str(entry.get("description",""))]).lower()
    if is_twitter:
        return any(k in text for k in ["iran","israel","idf","irgc","strike","war","attack",
                   "missile","drone","military","nuclear","hezbollah","hamas","houthi",
                   "centcom","pentagon","gaza","lebanon","tehran","netanyahu","khamenei"])
    return any(k in text for k in KEYWORDS)

async def fetch_one(client, cfg):
    handle = cfg.get("nitter_handle")
    mirrors = cfg.get("nitter_mirrors", []) if handle else []
    urls = [f"{m}/{handle}/rss" for m in mirrors] if mirrors else [cfg["url"]]
    for url in urls:
        try:
            r = await client.get(url, timeout=httpx.Timeout(10.0),
                                 headers={"User-Agent": "Mozilla/5.0 MilNewsBot/8.0"})
            if r.status_code == 200:
                entries = feedparser.parse(r.text).entries
                if entries: return entries
        except: pass
    return []

async def fetch_all(client):
    results = await asyncio.gather(*[fetch_one(client, cfg) for cfg in ALL_FEEDS], return_exceptions=True)
    out = []
    for i, res in enumerate(results):
        if isinstance(res, list):
            for entry in res:
                out.append((entry, ALL_FEEDS[i]))
    return out

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

async def translate(client, title, summary):
    """ترجمه به فارسی — هر زبانی (انگلیسی، عبری، عربی، ...) → فارسی روان خبری"""
    if not GEMINI_API_KEY or len(title) < 3:
        return title, summary

    prompt = f"""وظیفه: ترجمه دقیق خبر نظامی به فارسی
زبان ورودی: هر زبانی ممکن است (انگلیسی، عبری، عربی، ...)
خروجی: فقط فارسی روان و خبری — بدون هیچ توضیح، پرانتز، یا حاشیه

قوانین سخت:
۱. فقط ترجمه بنویس
۲. اسامی خاص را نگه دار (نتانیاهو، خامنه‌ای، سپاه، ناتو...)
۳. لحن رسمی خبرگزاری داشته باش
۴. اگر جمله‌ای ناقص است، کامل ترجمه کن

فرمت خروجی دقیقاً:
عنوان: [ترجمه عنوان]
---
متن: [ترجمه متن]

===ورودی===
عنوان: {title[:500]}
متن: {summary[:800]}"""

    for attempt in range(2):
        try:
            r = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.05, "maxOutputTokens": 1200}
                },
                timeout=httpx.Timeout(25.0)
            )
            if r.status_code == 200:
                raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                # پردازش خروجی
                raw = re.sub(r'^عنوان:\s*', '', raw, flags=re.MULTILINE)
                raw = re.sub(r'^متن:\s*', '', raw, flags=re.MULTILINE)
                parts = raw.split("---", 1)
                if len(parts) == 2:
                    fa_t = normalize_fa(parts[0].strip().replace("**",""))
                    fa_s = normalize_fa(parts[1].strip().replace("**",""))
                    return fa_t, fa_s
                else:
                    return normalize_fa(raw.strip()), ""
            elif r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 15))
                log.warning(f"⏳ Gemini rate limit — {wait}s")
                await asyncio.sleep(wait)
            elif r.status_code == 503:
                await asyncio.sleep(5)
            else:
                log.debug(f"Gemini {r.status_code}")
                break
        except Exception as e:
            log.debug(f"Gemini: {e}")
            if attempt == 0:
                await asyncio.sleep(3)

    return title, summary  # fallback: متن اصلی

def clean_html(text):
    if not text: return ""
    return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

def make_id(entry):
    """ID اصلی بر اساس لینک"""
    key = entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(key.encode("utf-8")).hexdigest()

def make_title_id(title: str) -> str:
    """ID ثانویه بر اساس عنوان — جلوگیری از خبر تکراری از منابع مختلف"""
    # پاک‌سازی و نرمال‌سازی عنوان برای مقایسه
    t = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', title.lower())
    return "t:" + hashlib.md5(t.encode("utf-8")).hexdigest()

def format_dt(entry):
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).astimezone(TEHRAN_TZ).strftime("🕐 %H:%M  |  📅 %Y/%m/%d")
    except: pass
    return ""

def esc(t): return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def trim(t, n=700): t=re.sub(r'\s+',' ',t).strip(); return t if len(t)<=n else t[:n].rsplit(" ",1)[0]+"…"

def load_seen():
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f: return set(json.load(f))
        except: pass
    return set()

def save_seen(seen):
    with open(SEEN_FILE,"w") as f: json.dump(list(seen)[-10000:], f)

TGAPI = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_send(client, text):
    for _ in range(4):
        try:
            r = await client.post(f"{TGAPI}/sendMessage", json={
                "chat_id": CHANNEL_ID, "text": text[:MAX_MSG_LEN],
                "parse_mode": "HTML", "disable_web_page_preview": True,
            }, timeout=httpx.Timeout(15.0))
            data = r.json()
            if data.get("ok"): return True
            if data.get("error_code") == 429:
                await asyncio.sleep(data.get("parameters",{}).get("retry_after",15))
            elif data.get("error_code") in (400, 403):
                log.error(f"TG fatal: {data.get('description')}"); return False
            else: await asyncio.sleep(5)
        except Exception as e:
            log.warning(f"TG: {e}"); await asyncio.sleep(8)
    return False

async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID تنظیم نشده!"); return

    seen = load_seen()
    tehran_cutoff = NEWS_CUTOFF.astimezone(TEHRAN_TZ).strftime("%Y/%m/%d %H:%M")
    log.info(f"🚀 {len(ALL_FEEDS)} منبع | {len(seen)} در حافظه")
    log.info(f"📅 Cutoff: {tehran_cutoff} تهران (فقط خبرهای بعد از این)")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        raw = await fetch_all(client)
        log.info(f"📥 {len(raw)} آیتم دریافت — فیلتر...")

        collected = []
        title_seen = set()  # dedup اضافی بر اساس عنوان — جلوگیری از خبر تکراری از چند منبع
        for entry, cfg in raw:
            eid = make_id(entry)
            if eid in seen: continue
            if not is_fresh(entry): seen.add(eid); continue
            is_tw = bool(cfg.get("nitter_handle"))
            if not is_relevant(entry, is_twitter=is_tw): seen.add(eid); continue
            # بررسی تکراری بودن عنوان
            raw_title = clean_html(entry.get("title",""))
            tid = make_title_id(raw_title)
            if tid in title_seen: seen.add(eid); continue
            title_seen.add(tid)
            collected.append((eid, entry, cfg, is_tw))

        collected = list(reversed(collected))
        if len(collected) > MAX_NEW_PER_RUN:
            collected = collected[-MAX_NEW_PER_RUN:]

        log.info(f"✅ {len(collected)} خبر جدید")
        sent = 0

        for eid, entry, cfg, is_tw in collected:
            en_title  = trim(clean_html(entry.get("title","")), 300)
            en_sum    = trim(clean_html(entry.get("summary") or entry.get("description") or ""), 700)
            link      = entry.get("link","")
            dt        = format_dt(entry)

            log.info(f"🔄 {en_title[:50]}...")
            fa_title, fa_sum = await translate(client, en_title, en_sum)

            icon = "𝕏" if is_tw else "📡"
            lines = [f"🔴 <b>{esc(fa_title)}</b>", ""]
            if fa_sum and len(fa_sum)>10 and fa_sum.lower() not in fa_title.lower():
                lines += [esc(fa_sum), ""]
            lines += ["──────────────", f"📌 <i>{esc(en_title)}</i>"]
            if dt: lines.append(dt)
            lines.append(f"{icon} <b>{cfg['name']}</b>")
            if link: lines.append(f'🔗 <a href="{link}">منبع</a>')

            if await tg_send(client, "\n".join(lines)):
                seen.add(eid); sent += 1; log.info("  ✅")
            else:
                log.error("  ❌")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"🏁 {sent}/{len(collected)} ارسال شد")

if __name__ == "__main__":
    asyncio.run(main())
