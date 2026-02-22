"""
╔══════════════════════════════════════════════════════════════════════════╗
║        🛡️ Military Intel Bot v9 — FULLY FIXED                            ║
║                                                                          ║
║  باگ‌های رفع‌شده:                                                         ║
║  ✅ Bug1: Cutoff ثابت ۱۷ دقیقه → Cutoff دینامیک (۲ ساعت)               ║
║  ✅ Bug2: Nitter کاملاً مرده → RSSHub با ۵ instance fallback            ║
║  ✅ Bug3: ۱۷ URL مرده → جایگزین‌های تست‌شده                              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os, json, hashlib, asyncio, logging, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser, httpx, pytz

# ── Hazm برای نرمال‌سازی فارسی ──
try:
    from hazm import Normalizer as HazmNorm
    _hazm = HazmNorm()
    def nfa(t): return _hazm.normalize(t or "")
except ImportError:
    def nfa(t): return re.sub(r' +', ' ', (t or "").replace("ي","ی").replace("ك","ک")).strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("MilBot")

# ════════════════════════════════════════════════════════════════
# تنظیمات
# ════════════════════════════════════════════════════════════════
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SEEN_FILE       = "seen.json"
MAX_NEW_PER_RUN = 20
MAX_MSG_LEN     = 4096
SEND_DELAY      = 2
TEHRAN_TZ       = pytz.timezone("Asia/Tehran")

# ════════════════════════════════════════════════════════════════
# ✅ FIX 1 — CUTOFF دینامیک (نه ثابت!)
# ════════════════════════════════════════════════════════════════
# مشکل قبلی: cutoff ثابت ۲۳:۴۸ UTC بود، بات ۰۰:۰۵ اجرا شد
# → فقط ۱۷ دقیقه پنجره → همه خبرها رد شدند!
#
# راه‌حل: cutoff = "همین الان منهای ۲ ساعت"
# seen.json ضد تکرار است → هیچ خبری دوبار نمی‌رود
# ۲ ساعت = پنجره ایمن که هم خبرهای جدید می‌گیرد هم قدیمی‌ها رد می‌شن

def get_cutoff() -> datetime:
    """Cutoff دینامیک: همیشه ۲ ساعت قبل از الان"""
    return datetime.now(timezone.utc) - timedelta(hours=2)

# ════════════════════════════════════════════════════════════════
# ─── ۱. فیدهای RSS — URLهای تست‌شده و به‌روز ──────────────
# ════════════════════════════════════════════════════════════════
RSS_FEEDS = [

    # ══ خبرگزاری‌های بزرگ ══
    {"name": "🌐 Reuters World",       "url": "https://feeds.reuters.com/reuters/worldNews"},
    {"name": "🌐 Reuters Top",         "url": "https://feeds.reuters.com/reuters/topNews"},
    {"name": "🌐 AP Top",              "url": "https://feeds.apnews.com/rss/apf-topnews"},
    {"name": "🌐 AP World",            "url": "https://feeds.apnews.com/rss/apf-WorldNews"},
    {"name": "🌐 AP Military",         "url": "https://apnews.com/hub/military-and-defense?format=rss"},
    {"name": "🌐 Bloomberg Politics",  "url": "https://feeds.bloomberg.com/politics/news.rss"},
    {"name": "🌐 WSJ World",           "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"},
    # ✅ NYT — مسیر صحیح
    {"name": "🌐 NYT World",           "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.rss"},
    {"name": "🌐 NYT Middle East",     "url": "https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.rss"},
    {"name": "🌐 CNN Middle East",     "url": "http://rss.cnn.com/rss/edition_meast.rss"},
    {"name": "🌐 CNN World",           "url": "http://rss.cnn.com/rss/edition_world.rss"},
    # ✅ BBC — با redirect خودکار کار می‌کند
    {"name": "🌐 BBC Middle East",     "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"name": "🌐 BBC World",           "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "🌐 Al Jazeera",          "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "🌐 Fox News World",      "url": "https://moxie.foxnews.com/google-publisher/world.xml"},
    {"name": "🌐 Politico NatSec",     "url": "https://rss.politico.com/defense.xml"},
    {"name": "🌐 Politico Politics",   "url": "https://rss.politico.com/politics-news.xml"},
    # ✅ The Hill — با redirect کار می‌کند
    {"name": "🌐 The Hill",            "url": "https://thehill.com/news/feed/"},
    {"name": "🌐 Foreign Policy",      "url": "https://foreignpolicy.com/feed/"},
    {"name": "🌐 Foreign Affairs",     "url": "https://www.foreignaffairs.com/rss.xml"},
    {"name": "🌐 The Intercept",       "url": "https://theintercept.com/feed/?rss=1"},
    {"name": "🌐 Middle East Eye",     "url": "https://www.middleeasteye.net/rss"},

    # ══ اکسیوس — از طریق Google News (API مرده) ══
    # ✅ Axios API ها همه 404 شدند — جایگزین Google News
    {"name": "📰 Axios (GNews)",       "url": "https://news.google.com/rss/search?q=site:axios.com+national+security+iran+israel&hl=en-US&gl=US&ceid=US:en"},
    {"name": "📰 Axios World (GNews)", "url": "https://news.google.com/rss/search?q=site:axios.com+military+iran+israel+war&hl=en-US&gl=US&ceid=US:en"},

    # ══ آمریکا نظامی ══
    # ✅ Pentagon — با redirect
    {"name": "🇺🇸 Pentagon",           "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    # CENTCOM RSS — 403 در بعضی مواقع، Google News جایگزین
    {"name": "🇺🇸 CENTCOM (GNews)",    "url": "https://news.google.com/rss/search?q=CENTCOM+site:centcom.mil&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🇺🇸 USNI News",          "url": "https://news.usni.org/feed"},
    {"name": "🇺🇸 Breaking Defense",   "url": "https://breakingdefense.com/feed/"},
    {"name": "🇺🇸 Defense News",       "url": "https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Military Times",     "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    # ✅ Stars & Stripes — URL جدید
    {"name": "🇺🇸 Stars & Stripes",    "url": "https://www.stripes.com/feed"},
    {"name": "🇺🇸 C4ISRNET",           "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/"},
    # ✅ The War Zone — URL جدید
    {"name": "🇺🇸 The War Zone",       "url": "https://www.thedrive.com/the-war-zone/feed"},
    {"name": "🇺🇸 War on Rocks",       "url": "https://warontherocks.com/feed/"},
    {"name": "🇺🇸 Task & Purpose",     "url": "https://taskandpurpose.com/feed/"},

    # ══ اسراییل ══
    # ✅ IDF — URL جدید
    {"name": "🇮🇱 IDF (GNews)",        "url": "https://news.google.com/rss/search?q=IDF+site:idf.il&hl=en-US&gl=US&ceid=US:en"},
    # ✅ JP Military → JP All (Military مرده)
    {"name": "🇮🇱 Jerusalem Post",     "url": "https://www.jpost.com/rss/rssfeedsheadlines.aspx"},
    {"name": "🇮🇱 Times of Israel",    "url": "https://www.timesofisrael.com/feed/"},
    # ✅ Haaretz → از Google News (403 مستقیم)
    {"name": "🇮🇱 Haaretz (GNews)",    "url": "https://news.google.com/rss/search?q=site:haaretz.com+iran+israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🇮🇱 Israel Hayom",       "url": "https://www.israelhayom.com/feed/"},
    # ✅ Ynetnews — URL صحیح
    {"name": "🇮🇱 Ynetnews",           "url": "https://www.ynetnews.com/RSS/EnglishFeed.xml"},
    {"name": "🇮🇱 i24 News",           "url": "https://www.i24news.tv/en/rss"},
    # ✅ Arutz Sheva — URL جدید
    {"name": "🇮🇱 Arutz Sheva",        "url": "https://www.israelnationalnews.com/rss.aspx"},

    # ══ ایران ══
    {"name": "🇮🇷 Iran International", "url": "https://www.iranintl.com/en/rss"},
    # ✅ Radio Farda — URL جدید
    {"name": "🇮🇷 Radio Farda",        "url": "https://www.rferl.org/api/epiqeguqiup"},

    # ══ تحلیلی / OSINT ══
    # ✅ ISW → از Google News (403 مستقیم)
    {"name": "🔍 ISW (GNews)",         "url": "https://news.google.com/rss/search?q=site:understandingwar.org&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🔍 Long War Journal",    "url": "https://www.longwarjournal.org/feed"},
    {"name": "🔍 Bellingcat",          "url": "https://www.bellingcat.com/feed/"},
    {"name": "🔍 OSINT Defender",      "url": "https://osintdefender.com/feed/"},
    # ✅ RAND — URL جدید
    {"name": "🔍 RAND Defense",        "url": "https://www.rand.org/topics/defense-and-security.xml"},
    # ✅ Lawfare → GNews
    {"name": "🔍 Lawfare (GNews)",     "url": "https://news.google.com/rss/search?q=site:lawfaremedia.org+iran+israel&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🔍 Just Security",       "url": "https://www.justsecurity.org/feed/"},
]

# ════════════════════════════════════════════════════════════════
# ─── ۲. Google News — ۲۰ جستجوی هدفمند ────────────────────
# ════════════════════════════════════════════════════════════════
GOOGLE_QUERIES = [
    ("⚔️ Iran Israel War",      "Iran Israel war attack strike"),
    ("⚔️ Iran Airstrike",       "Iran airstrike bomb explosion"),
    ("⚔️ US Iran Military",     "United States Iran military IRGC"),
    ("⚔️ IDF Operation",        "IDF military operation strike"),
    ("⚔️ Iran Nuclear",         "Iran nuclear IAEA uranium enrichment"),
    ("⚔️ Iran Missile Drone",   "Iran ballistic missile drone attack"),
    ("⚔️ Hezbollah IDF",        "Hezbollah IDF Lebanon border strike"),
    ("⚔️ Strait Hormuz",        "Strait Hormuz tanker navy seized"),
    ("⚔️ IRGC Attack",          "IRGC Revolutionary Guard base attack"),
    ("⚔️ Israel Strike Syria",  "Israel airstrike Syria Iraq Iran"),
    ("⚔️ Mossad Operation",     "Mossad covert operation intelligence"),
    ("⚔️ Khamenei Netanyahu",   "Khamenei Netanyahu war threat"),
    ("⚔️ US Navy Gulf",         "US carrier strike group Persian Gulf"),
    ("⚔️ Iron Dome",            "Iron Dome Patriot Arrow intercept missile"),
    ("⚔️ Iran Sanctions",       "Iran sanctions oil SWIFT 2026"),
    ("⚔️ Red Sea Houthis",      "Red Sea Houthi attack ship missile"),
    ("⚔️ Gaza Deal 2026",       "Gaza ceasefire Hamas IDF deal 2026"),
    ("⚔️ Iran Proxy Militia",   "Iran proxy militia Iraq Syria US base"),
    ("⚔️ Nuclear Escalation",   "nuclear military escalation Middle East"),
    ("⚔️ Trump Iran Israel",    "Trump Iran Israel military policy"),
]

def gnews(q):
    return f"https://news.google.com/rss/search?q={q.replace(' ','+')}&hl=en-US&gl=US&ceid=US:en&num=15"

GOOGLE_FEEDS = [{"name": n, "url": gnews(q), "is_google": True} for n, q in GOOGLE_QUERIES]

# ════════════════════════════════════════════════════════════════
# ─── ۳. توییتر/X — ✅ FIX 2: RSSHub (جایگزین Nitter مرده) ──
# ════════════════════════════════════════════════════════════════
#
# مشکل: Nitter.poast.org → 403, nitter.kavin.rocks → 502
# راه‌حل: RSSHub — چند instance عمومی برای fallback
#
# RSSHub instances عمومی (ترتیب اولویت):
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://hub.slarker.me",
    "https://rsshub.feeded.app",
    "https://rsshub.woodland.cafe",
]

TWITTER_ACCOUNTS = [
    # ── OSINT / اطلاعات ──
    ("🔍 OSINT Defender",       "OSINTdefender"),
    ("🔍 Intel Crab",           "IntelCrab"),
    ("🔍 War Monitor",          "WarMonitor3"),
    ("🔍 Conflicts.media",      "Conflicts"),
    ("🔍 Aurora Intel",         "AuroraIntel"),
    ("🔍 GeoConfirmed",         "GeoConfirmed"),

    # ── Axios خبرنگاران ──
    ("📰 Axios: Barak Ravid",   "BarakRavid"),       # اسراییل/امنیت ملی
    ("📰 Axios: Alex Ward",     "alexward1961"),      # امنیت ملی
    ("📰 Axios: Zach Basu",     "ZachBasu"),

    # ── Reuters خبرنگاران ──
    ("📰 Reuters: Idrees Ali",  "idreesali114"),      # Pentagon
    ("📰 Reuters: Phil Stewart","phil_stewart_"),
    ("📰 Reuters: Jonathan L",  "JLanday"),

    # ── NYT خبرنگاران ──
    ("📰 NYT: Farnaz Fassihi",  "farnazfassihi"),    # ایران/خاورمیانه
    ("📰 NYT: Eric Schmitt",    "EricSchmittNYT"),    # امنیت ملی
    ("📰 NYT: Helene Cooper",   "helenecooper"),      # Pentagon

    # ── WaPo خبرنگاران ──
    ("📰 WaPo: Dan Lamothe",    "DanLamothe"),

    # ── Politico / FP خبرنگاران ──
    ("📰 Politico: Lara S",     "laraseligman"),
    ("📰 FP: Jack Detsch",      "JackDetsch"),
    ("📰 FP: Robbie Gramer",    "RobbieGramer"),
    ("📰 NatashaBertrand",      "NatashaBertrand"),

    # ── رسمی ──
    ("🇮🇱 IDF Official",        "IDF"),
    ("🇺🇸 CENTCOM",             "CENTCOM"),
    ("🇺🇸 Dept of Defense",     "DeptofDefense"),

    # ── تحلیلگران اسراییل ──
    ("🇮🇱 Yossi Melman",        "yossi_melman"),
    ("🇮🇱 Seth Frantzman",      "sfrantzman"),
    ("🇮🇱 Avi Issacharoff",     "AviIssacharoff"),

    # ── ایران ──
    ("🇮🇷 Iran Intl English",   "IranIntl_En"),

    # ── منطقه‌ای ──
    ("🌐 Joyce Karam",          "Joyce_Karam"),
    ("🌐 Ragip Soylu",          "ragipsoylu"),

    # ── هشدار ──
    ("⚠️ DEFCON Level",         "DEFCONLevel"),
    ("⚠️ Arms Control Wonk",    "ArmsControlWonk"),
]

def get_twitter_feeds():
    feeds = []
    for name, handle in TWITTER_ACCOUNTS:
        # همه RSSHub instance ها به عنوان fallback
        urls = [f"{inst}/twitter/user/{handle}" for inst in RSSHUB_INSTANCES]
        feeds.append({
            "name": f"𝕏 {name}",
            "twitter_handle": handle,
            "twitter_urls": urls,   # ← لیست URL برای امتحان
        })
    return feeds

TWITTER_FEEDS = get_twitter_feeds()
ALL_FEEDS = RSS_FEEDS + GOOGLE_FEEDS  # Twitter جداگانه fetch می‌شود

# ════════════════════════════════════════════════════════════════
# فیلترها
# ════════════════════════════════════════════════════════════════
KEYWORDS = [
    "سپاه","موشک","جنگ","حمله","اسراییل","آمریکا","ایران","هسته‌ای","پهپاد","نظامی",
    "iran","irgc","khamenei","tehran","revolutionary guard","nuclear",
    "israel","idf","mossad","tel aviv","netanyahu",
    "hamas","hezbollah","houthi","ansarallah",
    "pentagon","centcom","us forces","us military","us base","american",
    "strike","airstrike","missile","ballistic","drone","uav",
    "attack","bomb","explosion","assassination","operation",
    "warship","carrier","navy","air force","troops",
    "persian gulf","strait of hormuz","red sea","middle east",
    "iron dome","arrow","patriot","hypersonic",
    "uranium","enrichment","natanz","fordo","iaea",
    "intelligence","cia","covert","sanction","embargo",
    "gaza","west bank","lebanon","syria","iraq","yemen","bahrain",
    "trump","rubio","waltz","war","conflict","escalat","deploy",
]

def is_fresh(entry: dict) -> bool:
    """✅ FIX: Cutoff دینامیک — ۲ ساعت اخیر"""
    cutoff = get_cutoff()
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t:
            return False   # بدون تاریخ = رد
        dt = datetime(*t[:6], tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if dt < cutoff:
            return False
        return True
    except:
        return False

def is_relevant(entry: dict, is_twitter: bool = False) -> bool:
    text = " ".join([
        str(entry.get("title", "")),
        str(entry.get("summary", "")),
        str(entry.get("description", "")),
    ]).lower()
    if is_twitter:
        tw_kw = ["iran","israel","idf","irgc","strike","war","attack","missile",
                 "drone","military","nuclear","hezbollah","hamas","houthi",
                 "centcom","pentagon","gaza","lebanon","tehran","netanyahu","khamenei"]
        return any(k in text for k in tw_kw)
    return any(k in text for k in KEYWORDS)

# ════════════════════════════════════════════════════════════════
# دریافت فیدها
# ════════════════════════════════════════════════════════════════
async def fetch_one_rss(client: httpx.AsyncClient, cfg: dict) -> list:
    url = cfg["url"]
    try:
        r = await client.get(url, timeout=httpx.Timeout(12.0),
                             headers={"User-Agent": "Mozilla/5.0 MilNewsBot/9.0"})
        if r.status_code == 200:
            entries = feedparser.parse(r.text).entries
            if entries:
                return entries
    except:
        pass
    return []

async def fetch_one_twitter(client: httpx.AsyncClient, cfg: dict) -> tuple[list, str]:
    """✅ FIX: RSSHub با fallback — همه instance ها امتحان می‌شوند"""
    for url in cfg["twitter_urls"]:
        try:
            r = await client.get(url, timeout=httpx.Timeout(10.0),
                                 headers={"User-Agent": "Mozilla/5.0 MilNewsBot/9.0"})
            if r.status_code == 200:
                entries = feedparser.parse(r.text).entries
                if entries:
                    log.debug(f"  𝕏 {cfg['twitter_handle']} ← {url.split('/')[2]}")
                    return entries, cfg["name"]
        except:
            continue
    return [], cfg["name"]

async def fetch_all(client: httpx.AsyncClient) -> list:
    # RSS و Google News همزمان
    rss_tasks = [fetch_one_rss(client, cfg) for cfg in ALL_FEEDS]
    rss_results = await asyncio.gather(*rss_tasks, return_exceptions=True)

    out = []
    for i, res in enumerate(rss_results):
        if isinstance(res, list):
            for entry in res:
                out.append((entry, ALL_FEEDS[i], False))

    # Twitter همزمان
    tw_tasks = [fetch_one_twitter(client, cfg) for cfg in TWITTER_FEEDS]
    tw_results = await asyncio.gather(*tw_tasks, return_exceptions=True)

    tw_ok = 0
    for res in tw_results:
        if isinstance(res, tuple):
            entries, name = res
            for entry in entries:
                fake_cfg = {"name": name}
                out.append((entry, fake_cfg, True))
            if entries:
                tw_ok += 1

    log.info(f"  𝕏 توییتر: {tw_ok}/{len(TWITTER_FEEDS)} اکانت موفق")
    return out

# ════════════════════════════════════════════════════════════════
# ترجمه با Gemini
# ════════════════════════════════════════════════════════════════
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

async def translate(client: httpx.AsyncClient, title: str, summary: str) -> tuple[str, str]:
    if not GEMINI_API_KEY or len(title.strip()) < 3:
        return title, summary

    prompt = f"""وظیفه: ترجمه دقیق خبر نظامی به فارسی روان.
زبان ورودی: هر زبانی (انگلیسی، عبری، عربی...)
خروجی: فقط فارسی — بدون توضیح، بدون پرانتز

قوانین:
۱. فقط ترجمه، هیچ چیز اضافه
۲. اسامی خاص را حفظ کن (نتانیاهو، خامنه‌ای، ناتو، IRGC...)
۳. لحن رسمی خبرگزاری
۴. اگر متن کوتاه است، ترجمه کوتاه بنویس

فرمت دقیق:
عنوان: [ترجمه]
---
متن: [ترجمه]

===
عنوان: {title[:400]}
متن: {summary[:700]}"""

    for attempt in range(2):
        try:
            r = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.05, "maxOutputTokens": 1024}
                },
                timeout=httpx.Timeout(25.0)
            )
            if r.status_code == 200:
                raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                raw = re.sub(r'^(عنوان|متن):\s*', '', raw, flags=re.MULTILINE)
                raw = raw.replace("**", "").replace("*", "")
                parts = raw.split("---", 1)
                if len(parts) == 2:
                    return nfa(parts[0].strip()), nfa(parts[1].strip())
                return nfa(raw.strip()), ""
            elif r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 20))
                log.warning(f"⏳ Gemini rate limit {wait}s")
                await asyncio.sleep(wait)
            else:
                log.debug(f"Gemini {r.status_code}")
                break
        except Exception as e:
            log.debug(f"Gemini: {e}")
            if attempt == 0:
                await asyncio.sleep(3)

    return title, summary

# ════════════════════════════════════════════════════════════════
# ابزارها
# ════════════════════════════════════════════════════════════════
def clean_html(text: str) -> str:
    if not text: return ""
    return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

def make_id(entry: dict) -> str:
    key = entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(key.encode("utf-8")).hexdigest()

def make_title_id(title: str) -> str:
    """ضد تکرار بر اساس عنوان — از چند منبع مختلف"""
    t = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', title.lower())
    return "t:" + hashlib.md5(t[:200].encode("utf-8")).hexdigest()

def format_dt(entry: dict) -> str:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            dt = datetime(*t[:6], tzinfo=timezone.utc).astimezone(TEHRAN_TZ)
            return dt.strftime("🕐 %H:%M  |  📅 %Y/%m/%d")
    except: pass
    return ""

def esc(t: str) -> str:
    return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def trim(t: str, n: int = 700) -> str:
    t = re.sub(r'\s+', ' ', t).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"

# ════════════════════════════════════════════════════════════════
# حافظه
# ════════════════════════════════════════════════════════════════
def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f: return set(json.load(f))
        except: pass
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-12000:], f)

# ════════════════════════════════════════════════════════════════
# تلگرام
# ════════════════════════════════════════════════════════════════
TGAPI = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_send(client: httpx.AsyncClient, text: str) -> bool:
    for attempt in range(4):
        try:
            r = await client.post(f"{TGAPI}/sendMessage", json={
                "chat_id": CHANNEL_ID,
                "text": text[:MAX_MSG_LEN],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=httpx.Timeout(15.0))
            data = r.json()
            if data.get("ok"): return True
            if data.get("error_code") == 429:
                wait = data.get("parameters", {}).get("retry_after", 20)
                log.warning(f"⏳ TG rate limit {wait}s")
                await asyncio.sleep(wait)
            elif data.get("error_code") in (400, 403):
                log.error(f"TG fatal: {data.get('description')}")
                return False
            else:
                await asyncio.sleep(5)
        except Exception as e:
            log.warning(f"TG #{attempt+1}: {e}")
            await asyncio.sleep(8)
    return False

# ════════════════════════════════════════════════════════════════
# حلقه اصلی
# ════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID تنظیم نشده!"); return

    seen = load_seen()
    cutoff = get_cutoff()
    tehran_cutoff = cutoff.astimezone(TEHRAN_TZ).strftime('%Y/%m/%d %H:%M')
    log.info(f"🚀 {len(RSS_FEEDS)+len(GOOGLE_FEEDS)} RSS/GNews + {len(TWITTER_FEEDS)} توییتر")
    log.info(f"📅 Cutoff: آخر ۲ ساعت ({tehran_cutoff} تهران به بعد)")
    log.info(f"💾 حافظه: {len(seen)} خبر قبلی")

    async with httpx.AsyncClient(follow_redirects=True) as client:

        # ── دریافت همزمان ──
        log.info("⏬ دریافت همزمان...")
        raw = await fetch_all(client)
        log.info(f"📥 {len(raw)} آیتم خام")

        # ── فیلتر ──
        collected = []
        title_seen = set()
        old_count = 0
        irrel_count = 0

        for entry, cfg, is_tw in raw:
            eid = make_id(entry)
            if eid in seen:
                continue
            if not is_fresh(entry):
                seen.add(eid)
                old_count += 1
                continue
            if not is_relevant(entry, is_twitter=is_tw):
                seen.add(eid)
                irrel_count += 1
                continue
            raw_title = clean_html(entry.get("title", ""))
            tid = make_title_id(raw_title)
            if tid in title_seen:
                seen.add(eid)
                continue
            title_seen.add(tid)
            collected.append((eid, entry, cfg, is_tw))

        log.info(f"📊 فیلتر: {old_count} قدیمی | {irrel_count} نامرتبط | {len(collected)} جدید")

        # محدود کردن به MAX_NEW_PER_RUN (قدیمی‌ترین اول)
        collected = list(reversed(collected))
        if len(collected) > MAX_NEW_PER_RUN:
            log.warning(f"⚠️ {len(collected)} → محدود به {MAX_NEW_PER_RUN}")
            collected = collected[-MAX_NEW_PER_RUN:]

        # ── ترجمه و ارسال ──
        sent = 0
        for eid, entry, cfg, is_tw in collected:
            en_title = trim(clean_html(entry.get("title", "")), 300)
            en_sum   = trim(clean_html(entry.get("summary") or entry.get("description") or ""), 700)
            link     = entry.get("link", "")
            dt       = format_dt(entry)
            icon     = "𝕏" if is_tw else "📡"

            log.info(f"🔄 {en_title[:55]}...")
            fa_title, fa_sum = await translate(client, en_title, en_sum)

            # ساخت پیام
            lines = [f"🔴 <b>{esc(fa_title)}</b>", ""]
            if fa_sum and len(fa_sum) > 10 and fa_sum.lower() not in fa_title.lower():
                lines += [esc(fa_sum), ""]
            lines += ["─────────────", f"📌 <i>{esc(en_title)}</i>"]
            if dt:    lines.append(dt)
            lines.append(f"{icon} <b>{cfg['name']}</b>")
            if link:  lines.append(f'🔗 <a href="{link}">منبع</a>')

            if await tg_send(client, "\n".join(lines)):
                seen.add(eid)
                sent += 1
                log.info("  ✅ ارسال شد")
            else:
                log.error("  ❌ ارسال ناموفق")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"🏁 پایان | {sent}/{len(collected)} خبر ارسال شد")

if __name__ == "__main__":
    asyncio.run(main())
