import os, json, hashlib, asyncio, logging, re, io
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser, httpx, pytz

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    from hazm import Normalizer as HazmNorm
    _hazm = HazmNorm()
    def nfa(t): return _hazm.normalize(t or "")
except ImportError:
    def nfa(t): return re.sub(r' +', ' ', (t or "").replace("ي","ی").replace("ك","ک")).strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("WarBot")

# ══════════════════════════════════════════════════════════════════════════
# تنظیمات
# ══════════════════════════════════════════════════════════════════════════
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ADMIN_CHAT_ID  = os.environ.get("ADMIN_CHAT_ID", "")

SEEN_FILE         = "seen.json"
STORIES_FILE      = "stories.json"
GEMINI_STATE_FILE = "gemini_state.json"
FLIGHT_ALERT_FILE = "flight_alerts.json"
RUN_STATE_FILE    = "run_state.json"
NITTER_CACHE_FILE = "nitter_cache.json"

# ── زمان‌بندی ─────────────────────────────────────────────────────────────
# هر اجرا فقط اخبار تازه بعد از اجرای قبلی را می‌بیند
CUTOFF_BUFFER_MIN  = 3    # buffer برای جلوگیری از miss
MAX_LOOKBACK_MIN   = 15   # حداکثر برگشت — متناسب با cron 10min
SEEN_TTL_HOURS     = 6
NITTER_CACHE_TTL   = 900

MAX_NEW_PER_RUN    = 30   # بیشتر برای اطمینان از از دست نرفتن خبر
MAX_MSG_LEN        = 4096
SEND_DELAY         = 0.5
JACCARD_THRESHOLD  = 0.72  # آزادتر — فقط خبرهای تقریباً یکسان حذف شوند
MAX_STORIES        = 120   # حافظه کوتاه‌تر → خبرهای تازه بیشتر
RSS_TIMEOUT        = 7.0
TG_TIMEOUT         = 10.0
TW_TIMEOUT         = 5.0
RICH_CARD_THRESHOLD = 7

TEHRAN_TZ = pytz.timezone("Asia/Tehran")

# ══════════════════════════════════════════════════════════════════════════
# منابع RSS
# ══════════════════════════════════════════════════════════════════════════
IRAN_FEEDS = [
    {"n":"🇮🇷 IRNA English",       "u":"https://en.irna.ir/rss"},
    {"n":"🇮🇷 Mehr News EN",        "u":"https://en.mehrnews.com/rss"},
    {"n":"🇮🇷 Tasnim News EN",      "u":"https://www.tasnimnews.com/en/rss"},
    {"n":"🇮🇷 Fars News EN",        "u":"https://www.farsnews.ir/rss"},
    {"n":"🇮🇷 Press TV",            "u":"https://www.presstv.ir/rss"},
    {"n":"🇮🇷 ISNA English",        "u":"https://en.isna.ir/rss"},
    {"n":"🇮🇷 Tehran Times",        "u":"https://www.tehrantimes.com/rss"},
    {"n":"🇮🇷 Iran International", "u":"https://www.iranintl.com/en/rss"},
    {"n":"🇮🇷 Iran Wire EN",        "u":"https://iranwire.com/en/feed/"},
    {"n":"🇮🇷 خبرگزاری تسنیم",      "u":"https://www.tasnimnews.com/fa/rss/feed/0/8/0"},
    {"n":"🇮🇷 خبرگزاری مهر",         "u":"https://www.mehrnews.com/rss"},
    {"n":"🇮🇷 خبرگزاری ایرنا",       "u":"https://www.irna.ir/rss"},
    {"n":"🇮🇷 خبرگزاری فارس",        "u":"https://www.farsnews.ir/rss/fa"},
    {"n":"🇮🇷 مشرق نیوز",             "u":"https://www.mashreghnews.ir/rss"},
    {"n":"🇮🇷 دفاع پرس",             "u":"https://www.defapress.ir/fa/rss"},
    # Google News — جست‌وجوهای دقیق فعلی (فوریه ۲۰۲۶)
    {"n":"🇮🇷 GNews Iran War",      "u":"https://news.google.com/rss/search?q=Iran+war+attack+military&hl=en-US&gl=US&ceid=US:en&num=15&tbs=qdr:d"},
    {"n":"🇮🇷 GNews IRGC",          "u":"https://news.google.com/rss/search?q=IRGC+Iran+Israel+US+military&hl=en-US&gl=US&ceid=US:en&num=15&tbs=qdr:d"},
    {"n":"🇮🇷 GNews ایران حمله",     "u":"https://news.google.com/rss/search?q=ایران+حمله+موشک+اسراییل+آمریکا&hl=fa&gl=IR&ceid=IR:fa&num=15&tbs=qdr:d"},
    {"n":"🇮🇷 GNews سپاه",          "u":"https://news.google.com/rss/search?q=سپاه+پاسداران+عملیات&hl=fa&gl=IR&ceid=IR:fa&num=10&tbs=qdr:d"},
]
ISRAEL_FEEDS = [
    {"n":"🇮🇱 Jerusalem Post",       "u":"https://www.jpost.com/rss/rssfeedsheadlines.aspx"},
    {"n":"🇮🇱 Times of Israel",      "u":"https://www.timesofisrael.com/feed/"},
    {"n":"🇮🇱 Israel Hayom EN",      "u":"https://www.israelhayom.com/feed/"},
    {"n":"🇮🇱 Arutz Sheva",          "u":"https://www.israelnationalnews.com/rss.aspx"},
    {"n":"🇮🇱 i24 News",             "u":"https://www.i24news.tv/en/rss"},
    {"n":"🇮🇱 GNews Israel Iran",    "u":"https://news.google.com/rss/search?q=Israel+Iran+attack+strike&hl=en-US&gl=US&ceid=US:en&num=15&tbs=qdr:d"},
    {"n":"🇮🇱 GNews IDF",            "u":"https://news.google.com/rss/search?q=IDF+military+operation+Iran&hl=en-US&gl=US&ceid=US:en&num=15&tbs=qdr:d"},
    {"n":"🇮🇱 GNews Iron Dome",      "u":"https://news.google.com/rss/search?q=Iron+Dome+Arrow+missile+defense&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
]
USA_FEEDS = [
    {"n":"🇺🇸 AP World",             "u":"https://feeds.apnews.com/rss/apf-WorldNews"},
    {"n":"🇺🇸 Reuters World",        "u":"https://feeds.reuters.com/reuters/worldNews"},
    {"n":"🇺🇸 Reuters Middle East",  "u":"https://feeds.reuters.com/reuters/MEonlineHeadlines"},
    {"n":"🇺🇸 CNN Middle East",      "u":"http://rss.cnn.com/rss/edition_meast.rss"},
    {"n":"🇺🇸 USNI News",            "u":"https://news.usni.org/feed"},
    {"n":"🇺🇸 Breaking Defense",     "u":"https://breakingdefense.com/feed/"},
    {"n":"🇺🇸 The War Zone",         "u":"https://www.twz.com/feed"},
    {"n":"🇺🇸 Defense News",         "u":"https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"n":"🇺🇸 Military Times",       "u":"https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    {"n":"🇺🇸 Long War Journal",     "u":"https://www.longwarjournal.org/feed"},
    {"n":"🇺🇸 GNews US Iran",        "u":"https://news.google.com/rss/search?q=US+military+Iran+strike+sanction&hl=en-US&gl=US&ceid=US:en&num=15&tbs=qdr:d"},
    {"n":"🇺🇸 GNews CENTCOM",        "u":"https://news.google.com/rss/search?q=CENTCOM+Middle+East+military+operation&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
    {"n":"🇺🇸 GNews Houthi",         "u":"https://news.google.com/rss/search?q=Houthi+Iran+Red+Sea+US+Navy&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
    {"n":"⚠️ GNews Nuclear",         "u":"https://news.google.com/rss/search?q=Iran+nuclear+uranium+IAEA+enrichment&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
]
EMBASSY_FEEDS = [
    {"n":"🏛️ US State Travel",      "u":"https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html.rss"},
    {"n":"🏛️ UK FCDO Iran",         "u":"https://www.gov.uk/foreign-travel-advice/iran.atom"},
    {"n":"🏛️ Embassy Evacuation",   "u":"https://news.google.com/rss/search?q=embassy+evacuation+Iran+warning+2026&hl=en-US&gl=US&ceid=US:en&num=10"},
]
INTL_FEEDS = [
    {"n":"🌐 BBC Middle East",  "u":"https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"n":"🌐 Al Jazeera",       "u":"https://www.aljazeera.com/xml/rss/all.xml"},
    {"n":"🌐 Middle East Eye",  "u":"https://www.middleeasteye.net/rss"},
    {"n":"🌐 Foreign Policy",   "u":"https://foreignpolicy.com/feed/"},
]

ALL_RSS_FEEDS = IRAN_FEEDS + ISRAEL_FEEDS + USA_FEEDS + EMBASSY_FEEDS + INTL_FEEDS
EMBASSY_SET   = {id(f) for f in EMBASSY_FEEDS}

# ══════════════════════════════════════════════════════════════════════════
# Twitter/X handles
# ══════════════════════════════════════════════════════════════════════════
TWITTER_HANDLES = [
    # ─── OSINT / Breaking — اولویت بالا ───────────────────────────────
    ("🔍 OSINTdefender",        "OSINTdefender"),
    ("🔍 IntelCrab",            "IntelCrab"),
    ("🔍 GeoConfirmed",         "GeoConfirmed"),
    ("🔍 WarMonitor",           "WarMonitor3"),
    ("🔍 AuroraIntel",          "AuroraIntel"),
    ("🔍 Faytuks",              "Faytuks"),
    ("🔍 Clash Report",         "clashreport"),
    ("🔍 Megatron",             "Megatron_Ron"),
    ("🔍 ELINT News",           "ELINTNews"),
    ("🔍 War Zone TW",          "TheWarZoneTW"),
    # ─── آمریکا دولتی / نظامی ─────────────────────────────────────────
    ("🇺🇸 CENTCOM",              "CENTCOM"),
    ("🇺🇸 DoD",                  "DeptofDefense"),
    ("🇺🇸 Natasha Bertrand",     "NatashaBertrand"),
    ("🇺🇸 Barak Ravid",          "BarakRavid"),
    ("🇺🇸 Idrees Ali",           "idreesali114"),
    ("🇺🇸 Jack Detsch",          "JackDetsch"),
    ("🇺🇸 Lara Seligman",        "laraseligman"),
    ("🇺🇸 Jim Sciutto",          "jimsciutto"),
    # ─── اسراییل ───────────────────────────────────────────────────────
    ("🇮🇱 IDF",                  "IDF"),
    ("🇮🇱 Israeli PM",           "IsraeliPM"),
    ("🇮🇱 Yossi Melman",         "yossi_melman"),
    ("🇮🇱 Seth Frantzman",       "sfrantzman"),
    ("🇮🇱 Emanuel Fabian",       "manniefabian"),
    ("🇮🇱 Anna Ahronheim",       "AAhronheim"),
    # ─── ایران / خاورمیانه ────────────────────────────────────────────
    ("🇮🇷 IranIntl EN",          "IranIntl_En"),
    ("🇮🇷 IRNA EN",              "IRNA_English"),
    ("🇮🇷 Press TV",             "PressTV"),
    ("🇮🇷 Farnaz Fassihi",       "farnazfassihi"),
    ("🇮🇷 Kasra Aarabi",         "KasraAarabi"),
    # ─── منطقه‌ای ──────────────────────────────────────────────────────
    ("🇸🇦 Al Arabiya Brk",       "AlArabiya_Brk"),
    ("🇶🇦 Al Jazeera EN",        "AlJazeeraEnglish"),
    ("🌐 Reuters Breaking",      "ReutersBreaking"),
    ("🌐 AP News",               "APnews"),
    ("🌐 BBC Breaking",          "BBCBreaking"),
    ("🌐 AFP News",              "AFPnews"),
    # ─── تحلیلگران ─────────────────────────────────────────────────────
    ("🔍 Ian Bremmer",           "ianbremmer"),
    ("🔍 Ellie Geranmayeh",      "EllieGeranmayeh"),
    ("🔍 Michael Knights",       "Mikeknightsiraq"),
    ("🔍 Aric Toler",            "AricToler"),
    ("⚠️ DEFCONLevel",           "DEFCONLevel"),
]

# ══════════════════════════════════════════════════════════════════════════
# کانال‌های تلگرام
# ══════════════════════════════════════════════════════════════════════════
TELEGRAM_CHANNELS = [
    # OSINT — اولویت بالا
    ("🔴 Middle East Spectator", "Middle_East_Spectator"),
    ("🔴 Intel Slava Z",         "intelslava"),
    ("🔴 ELINT News",            "ELINTNews"),
    ("🔴 Megatron OSINT",        "Megatron_Ron"),
    ("🔴 Disclose TV",           "disclosetv"),
    ("🔍 OSINTtechnical",        "Osinttechnical"),
    ("🔍 Iran OSINT",            "IranOSINT"),
    ("🔍 Aurora Intel",          "Aurora_Intel"),
    ("🔍 War Monitor",           "WarMonitor3"),
    # ایران فارسی
    ("🇮🇷 Iran Intl Persian",   "IranIntlPersian"),
    ("🇮🇷 تسنیم فارسی",          "tasnimnewsfa"),
    ("🇮🇷 مهر فارسی",             "mehrnews_fa"),
    ("🇮🇷 ایرنا فارسی",           "irnafarsi"),
    ("🇮🇷 Press TV",              "PressTVnews"),
    # اسراییل
    ("🇮🇱 Kann News",            "kann_news"),
    ("🇮🇱 Times of Israel",      "timesofisrael"),
    # منطقه
    ("🇸🇦 Al Arabiya Breaking",  "AlArabiya_Brk"),
    ("🇶🇦 Al Jazeera EN",        "AlJazeeraEnglish"),
    ("🇾🇲 Masirah TV",           "AlMasirahNet"),
    ("🇱🇧 Naharnet",             "Naharnet"),
    # بین‌المللی
    ("🌐 Reuters Breaking",      "ReutersBreaking"),
    ("🌐 AP News",               "APnews"),
    ("🌐 BBC Breaking",          "BBCBreaking"),
    ("🌐 OSINTdefender",         "OSINTdefender"),
    ("🌐 GeoConfirmed",          "GeoConfirmed"),
    ("🌐 IntelCrab",             "IntelCrab"),
]

# ══════════════════════════════════════════════════════════════════════════
# فیلتر موضوعی — آزاد: هر خبر درباره ایران، آمریکا یا اسراییل
# ══════════════════════════════════════════════════════════════════════════
IRAN_KW = [
    "iran","iranian","irgc","islamic republic","khamenei","tehran","persian gulf",
    "sepah","basij","quds force","rouhani","raisi","pezeshkian","zarif","araghchi",
    "ایران","سپاه","خامنه‌ای","تهران","جمهوری اسلامی","پزشکیان","ظریف","نطنز","فردو",
]
USA_KW = [
    "united states","us military","pentagon","centcom","white house","biden","trump",
    "us navy","us air force","us army","cia","state department","secretary of state",
    "u.s.","u.s. navy","u.s. military","u.s. forces","american forces","american military",
    "american troops","carrier strike","uss ", "rubio","austin","hegseth","blinken",
    "american carrier","us carrier","us warship","us troops","us forces","us base",
    "آمریکا","پنتاگون","کاخ سفید","بایدن","ترامپ","نیروی دریایی آمریکا","سیا","وزارت خارجه آمریکا",
]
ISRAEL_KW = [
    "israel","israeli","idf","netanyahu","tel aviv","mossad","iron dome","arrow",
    "iaf","israeli air force","knesset","bennett","herzog","gallant",
    "اسراییل","ارتش اسراییل","نتانیاهو","تل‌آویو","موساد","گنبد آهنین",
]
PROXY_KW = [
    "hamas","hezbollah","houthi","pij","islamic jihad","ansar allah",
    "حماس","حزب‌الله","حوثی","جهاد اسلامی","انصارالله",
]
HARD_EXCLUDE = [
    "football","soccer","basketball","olympic","sport","cooking","recipe",
    "fashion","celebrity","entertainment","music award","box office","nba","nfl",
    "فوتبال","سینما","موسیقی","آشپزی","مد و لباس",
]
EMBASSY_OVERRIDE = [
    "evacuate","leave immediately","travel warning","security alert","emergency",
    "تخلیه","فوری ترک","هشدار امنیتی","اضطرار",
]

def is_war_relevant(text, is_embassy=False, is_tg=False, is_tw=False):
    """
    فیلتر آزاد v18:
    هر خبری که شامل ایران، آمریکا یا اسراییل باشد — ارسال می‌شود
    (بدون نیاز به کلمه عمل/action)
    """
    txt = text.lower()
    # حذف قطعی
    if any(k in txt for k in HARD_EXCLUDE):
        return False
    # سفارت: همیشه pass
    if is_embassy and any(k in txt for k in EMBASSY_OVERRIDE):
        return True
    # بررسی حضور هر یک از سه طرف اصلی
    has_iran   = any(k in txt for k in IRAN_KW)
    has_usa    = any(k in txt for k in USA_KW)
    has_israel = any(k in txt for k in ISRAEL_KW)
    has_proxy  = any(k in txt for k in PROXY_KW)
    # هر خبر با حداقل یک طرف اصلی = ارسال
    return has_iran or has_usa or has_israel or has_proxy

# ══════════════════════════════════════════════════════════════════════════
# Twitter/X — Nitter (Feb 2026 verified instances)
# ══════════════════════════════════════════════════════════════════════════
# ترتیب بر اساس uptime از GitHub Actions (تست شده فوریه ۲۰۲۶)
NITTER_INSTANCES = [
    "https://xcancel.com",                    # ✅ آدرس اصلی — ریدایرکت به rss.xcancel.com
    "https://rss.xcancel.com",                # ✅ subdomain مستقیم
    "https://nitter.privacyredirect.com",     # ✅ اغلب کار می‌کند
    "https://nitter.tiekoetter.com",          # ✅ stable
    "https://nitter.poast.org",               # فعال
    "https://nitter.catsarch.com",            # فعال
    "https://lightbrd.com",                   # فعال
    "https://n.ramle.be",                     # backup
    "https://nitter.space",                   # backup
    "https://nitter.net",                     # backup
]
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rss.now.sh",
    "https://rss.shab.fun",
    "https://rsshub.moeyy.xyz",
    "https://rsshub.ktachibana.party",
    "https://rsshub-instance.zeabur.app",
    "https://rss.fatpandac.com",
    "https://rsshub.pseudoyu.com",
    "https://rsshub.mubibai.com",
    "https://rsshub.atgw.io",
]

NITTER_HDR = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}
COMMON_UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_nitter_pool: list[str]  = []
_rsshub_pool: list[str]  = []
_TW_SEMA: asyncio.Semaphore | None = None

def _load_nitter_cache() -> tuple[list, list, float]:
    try:
        if Path(NITTER_CACHE_FILE).exists():
            d = json.load(open(NITTER_CACHE_FILE))
            return d.get("nitter", []), d.get("rsshub", []), d.get("ts", 0.0)
    except: pass
    return [], [], 0.0

def _save_nitter_cache(nitter, rsshub):
    json.dump({"nitter": nitter, "rsshub": rsshub,
               "ts": datetime.now(timezone.utc).timestamp()},
              open(NITTER_CACHE_FILE, "w"))

def _is_rss(body: str, ct: str) -> bool:
    b = body[:600].lower()
    return ("xml" in ct) or ("<rss" in b) or ("<?xml" in b) or ("<feed" in b)

async def _try_rss(client: httpx.AsyncClient, url: str, timeout: float = TW_TIMEOUT) -> list:
    """
    RSS URL را fetch کرده entries برمی‌گرداند.
    follow_redirects=True مهم است (xcancel.com → rss.xcancel.com)
    """
    try:
        r = await client.get(url,
                             headers=NITTER_HDR,
                             follow_redirects=True,
                             timeout=httpx.Timeout(connect=5.0, read=timeout,
                                                   write=5.0, pool=5.0))
        if r.status_code not in (200, 304):
            return []
        ct = r.headers.get("content-type", "")
        body = r.text or ""
        if not _is_rss(body, ct):
            return []
        parsed = feedparser.parse(body)
        entries = getattr(parsed, "entries", []) or []
        return [e for e in entries if len((e.get("title") or "").strip()) > 3]
    except Exception:
        return []

async def _probe_instance(client: httpx.AsyncClient, url: str,
                          handle: str = "OSINTdefender") -> tuple | None:
    """
    بررسی اینکه یک instance واقعاً RSS برمی‌گرداند.
    مهم: فقط ساختار RSS را چک می‌کند، نه تعداد entries.
    """
    t0 = asyncio.get_running_loop().time()
    try:
        r = await client.get(f"{url}/{handle}/rss",
                             headers=NITTER_HDR,
                             follow_redirects=True,
                             timeout=httpx.Timeout(connect=5.0, read=7.0,
                                                   write=5.0, pool=5.0))
        if r.status_code not in (200, 304):
            return None
        ct   = r.headers.get("content-type", "")
        body = r.text or ""
        # فقط چک ساختار — نه entries
        if _is_rss(body, ct):
            ms = (asyncio.get_running_loop().time() - t0) * 1000
            return url, ms
    except Exception:
        pass
    return None

async def _probe_rsshub(client: httpx.AsyncClient, inst: str) -> tuple | None:
    t0 = asyncio.get_running_loop().time()
    try:
        r = await client.get(f"{inst}/twitter/user/OSINTdefender",
                             headers=NITTER_HDR,
                             follow_redirects=True,
                             timeout=httpx.Timeout(connect=5.0, read=8.0,
                                                   write=5.0, pool=5.0))
        if r.status_code in (200, 304) and _is_rss(r.text or "", r.headers.get("content-type","")):
            ms = (asyncio.get_running_loop().time() - t0) * 1000
            return inst, ms
    except Exception:
        pass
    return None

async def build_twitter_pools(client: httpx.AsyncClient):
    """Probe موازی — نتایج در cache ذخیره می‌شوند"""
    global _nitter_pool, _rsshub_pool
    if _nitter_pool or _rsshub_pool:
        return

    cached_n, cached_r, ts = _load_nitter_cache()
    age = datetime.now(timezone.utc).timestamp() - ts
    if age < NITTER_CACHE_TTL and cached_n:
        _nitter_pool = cached_n
        _rsshub_pool = cached_r
        log.info(f"𝕏 cache: Nitter={len(_nitter_pool)} RSSHub={len(_rsshub_pool)}")
        return

    log.info(f"𝕏 Probing {len(NITTER_INSTANCES)} Nitter + {len(RSSHUB_INSTANCES)} RSSHub...")
    sema = asyncio.Semaphore(10)
    async def sp(coro):
        async with sema:
            try: return await coro
            except: return None

    n = len(NITTER_INSTANCES)
    results = await asyncio.gather(
        *[sp(_probe_instance(client, u)) for u in NITTER_INSTANCES],
        *[sp(_probe_rsshub(client, u))  for u in RSSHUB_INSTANCES],
    )
    nok = sorted([r for r in results[:n]  if r], key=lambda x: x[1])
    rok = sorted([r for r in results[n:]  if r], key=lambda x: x[1])

    # اگه probe همه fail کردند → از کل لیست استفاده کن (ممکن است GitHub IP block نباشد)
    _nitter_pool = [u for u, _ in nok] or list(NITTER_INSTANCES)
    _rsshub_pool = [u for u, _ in rok]

    log.info(f"𝕏 Nitter کار می‌کند: {len([r for r in results[:n] if r])}/{n}")
    if nok:
        log.info(f"  بهترین: {nok[0][0].split('//')[-1]} ({nok[0][1]:.0f}ms)")
    _save_nitter_cache(_nitter_pool, _rsshub_pool)

async def fetch_twitter(client: httpx.AsyncClient, label: str, handle: str) -> list:
    """
    دریافت توییت‌ها — v19: اولویت RSSHub (پایدارتر از Nitter در 2026)
    1. RSSHub (بهترین نرخ موفقیت — ۱۰ instance)
    2. xcancel.com / rss.xcancel.com
    3. سایر Nitter instances از pool
    """
    sema = _TW_SEMA or asyncio.Semaphore(15)
    async with sema:
        # ── مرحله ۱: RSSHub — بالاترین نرخ موفقیت ────────────────
        for inst in (_rsshub_pool or RSSHUB_INSTANCES):
            e = await _try_rss(client, f"{inst}/twitter/user/{handle}", timeout=8.0)
            if e:
                log.debug(f"𝕏 {handle} ← RSSHub/{inst.split('//')[-1]} ({len(e)})")
                return [(x, f"𝕏 {label}", "tw", False) for x in e]

        # ── مرحله ۲: xcancel (دو URL) ────────────────────────────
        tried = set()
        for base in ("https://xcancel.com", "https://rss.xcancel.com"):
            u = f"{base}/{handle}/rss"
            tried.add(base)
            e = await _try_rss(client, u)
            if e:
                log.debug(f"𝕏 {handle} ← {base.split('//')[-1]} ({len(e)})")
                return [(x, f"𝕏 {label}", "tw", False) for x in e]

        # ── مرحله ۳: سایر Nitter instances ───────────────────────
        pool = _nitter_pool or NITTER_INSTANCES
        for inst in pool:
            if inst in tried: continue
            e = await _try_rss(client, f"{inst}/{handle}/rss")
            if e:
                log.debug(f"𝕏 {handle} ← {inst.split('//')[-1]} ({len(e)})")
                return [(x, f"𝕏 {label}", "tw", False) for x in e]

    log.debug(f"𝕏 {handle}: همه fail")
    return []

# ══════════════════════════════════════════════════════════════════════════
# ADS-B
# ══════════════════════════════════════════════════════════════════════════
ADSB_API     = "https://api.adsb.one/v2"
ADSB_REGIONS = [
    ("ایران",          32.4, 53.7, 250),
    ("خلیج‌فارس",     26.5, 52.0, 250),
    ("اسراییل/لبنان", 32.1, 35.2, 200),
    ("عراق",           33.3, 44.4, 250),
]
# فقط هواپیماهای جنگی و شناسایی — بدون ترابری (C17, KC135, C130, ...)
_COMBAT_TYPES   = {"F15","F16","F22","F35","F18","F14","SU35","SU30","MIG29",
                   "B52","B2","B1",        # بمب‌افکن‌ها
                   "E3","E8","E767","E737", # هشدار زودهنگام (AWACS)
                   "RC135","EP3","P8",      # شناسایی الکترونیک
                   "U2","SR71","RQ4",       # پهپاد/هواپیمای شناسایی ارتفاع بالا
                   "MQ9","MQ1","TB2","HESA",# پهپادهای مسلح
                   "A10","AV8","AC130",     # پشتیبانی نزدیک
                   "EA18","EA6",            # جنگ الکترونیک
                   }
_COMBAT_CALLSIGN = ["DOOM","BONE","BUCK","CIAO","JAKE","TORC","GRIM","HAVOC",
                    "GHOST","VIPER","EAGLE","RAPTOR","DEMON","REAPER","PREDATOR"]
_ADSB_SEEN    = set()

async def fetch_military_flights(client: httpx.AsyncClient) -> tuple[list, list]:
    """
    برمی‌گرداند: (msgs, aircraft_list)
    aircraft_list: [{"callsign","type","lat","lon","alt","gs","region"}, ...]
    """
    global _ADSB_SEEN
    msgs     = []
    aircraft = []
    try:
        try:
            if Path(FLIGHT_ALERT_FILE).exists():
                _ADSB_SEEN = set(json.load(open(FLIGHT_ALERT_FILE)).get("seen", []))
        except: pass

        for region, r_lat, r_lon, radius in ADSB_REGIONS:
            try:
                r = await client.get(f"{ADSB_API}/point/{r_lat}/{r_lon}/{radius}",
                                     timeout=httpx.Timeout(7.0),
                                     headers={"Accept": "application/json"})
                if r.status_code != 200: continue
                for ac in (r.json().get("ac") or []):
                    hex_id   = (ac.get("hex") or ac.get("icao","")).upper()
                    callsign = (ac.get("flight") or ac.get("callsign","")).strip()
                    cat      = (ac.get("category") or "").upper()
                    atype    = (ac.get("t") or ac.get("type","")).upper()
                    ac_lat   = ac.get("lat") or ac.get("latitude")
                    ac_lon   = ac.get("lon") or ac.get("longitude")
                    is_combat = (
                        any(atype.startswith(m) for m in _COMBAT_TYPES)
                        or any(callsign.startswith(p) for p in _COMBAT_CALLSIGN)
                        or cat in ("A5", "A6", "A7")  # ICAO military/UAV categories
                    )
                    if not is_combat: continue
                    uid = f"{hex_id}_{callsign}"
                    if uid in _ADSB_SEEN: continue
                    _ADSB_SEEN.add(uid)
                    alt = ac.get("alt_baro") or ac.get("alt", 0)
                    gs  = ac.get("gs") or ac.get("speed", 0)
                    msgs.append(
                        f"✈️ <b>تحرک نظامی — {region}</b>\n"
                        f"نوع: <code>{atype or '?'}</code>  کال‌ساین: <code>{callsign or hex_id}</code>\n"
                        f"ارتفاع: {alt:,} ft  سرعت: {gs} kt"
                    )
                    if ac_lat and ac_lon:
                        aircraft.append({
                            "callsign": callsign or hex_id,
                            "type":     atype or "?",
                            "lat":      float(ac_lat),
                            "lon":      float(ac_lon),
                            "alt":      alt,
                            "gs":       gs,
                            "region":   region,
                        })
            except Exception as e:
                log.debug(f"ADS-B {region}: {e}")

        json.dump({"seen": list(_ADSB_SEEN)[-300:]}, open(FLIGHT_ALERT_FILE, "w"))
    except Exception as e:
        log.warning(f"ADS-B: {e}")
    return msgs, aircraft


def make_flight_map(aircraft: list) -> "io.BytesIO | None":
    """
    نقشه دقیق خاورمیانه با موقعیت هواپیماهای نظامی
    مرزهای تقریبی کشورها + شبکه مختصات + برچسب
    """
    if not PIL_OK or not aircraft:
        return None
    try:
        W, H    = 1200, 800
        PAD_L   = 50    # فضای سمت چپ برای درجات
        PAD_B   = 30    # فضای پایین
        PAD_T   = 50    # هدر
        MAP_W   = W - PAD_L
        MAP_H   = H - PAD_T - PAD_B

        # محدوده جغرافیایی — خاورمیانه کامل
        LAT_MIN, LAT_MAX =  16.0, 43.0
        LON_MIN, LON_MAX =  26.0, 65.0

        def gp(lat, lon):
            """geo to pixel"""
            x = PAD_L + int((lon - LON_MIN) / (LON_MAX - LON_MIN) * MAP_W)
            y = PAD_T + int((LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * MAP_H)
            return max(0, min(W-1, x)), max(0, min(H-1, y))

        # ── رنگ‌ها ─────────────────────────────────────────────────────
        C_OCEAN  = (8,  28,  52)
        C_LAND   = (32, 45,  55)
        C_LAND2  = (38, 52,  62)   # رنگ متفاوت برای تمایز
        C_BORDER = (80, 110, 140)
        C_GRID   = (22, 35,  48)
        C_GRID_L = (40, 58,  72)
        C_PLANE  = (255, 70,  50)
        C_PLANE2 = (255, 180, 50)   # هواپیمای دوم
        C_LABEL  = (210, 230, 250)
        C_DIM    = (100, 130, 155)
        C_ACCENT = (255, 160, 30)
        C_HEAD   = (12,  18,  28)

        img = Image.new("RGB", (W, H), C_OCEAN)
        drw = ImageDraw.Draw(img)

        # ── فونت ───────────────────────────────────────────────────────
        try:
            F14 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            F12 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            F11 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
            FB  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
            FBL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        except:
            F14 = F12 = F11 = FB = FBL = ImageFont.load_default()

        # ── شبکه مختصات ───────────────────────────────────────────────
        for lat in range(17, 44, 2):
            y = gp(lat, LON_MIN)[1]
            drw.line([(PAD_L, y), (W, y)], fill=C_GRID, width=1)
            drw.text((2, y - 7), f"{lat}°", fill=C_DIM, font=F11)
        for lat in range(20, 44, 5):
            y = gp(lat, LON_MIN)[1]
            drw.line([(PAD_L, y), (W, y)], fill=C_GRID_L, width=1)

        for lon in range(28, 65, 2):
            x = gp(LAT_MIN, lon)[0]
            drw.line([(x, PAD_T), (x, H - PAD_B)], fill=C_GRID, width=1)
        for lon in range(30, 65, 5):
            x = gp(LAT_MIN, lon)[0]
            drw.line([(x, PAD_T), (x, H - PAD_B)], fill=C_GRID_L, width=1)
            drw.text((x - 8, H - PAD_B + 5), f"{lon}°", fill=C_DIM, font=F11)

        # ── مرزهای کشورها (پلیگون‌های تقریبی polygon) ─────────────────
        # فرمت: [(lon, lat), ...] — مختصات جغرافیایی
        COUNTRIES = {
            "IRAN": {
                "color": (38, 52, 62),
                "pts": [
                    (44.0,37.0),(44.8,39.2),(45.5,39.6),(46.0,39.0),(47.0,39.5),
                    (48.0,40.0),(49.0,40.2),(50.0,40.0),(51.0,40.8),(52.0,41.0),
                    (53.0,41.5),(54.0,41.2),(55.0,41.0),(56.0,40.5),(57.0,40.0),
                    (58.0,39.5),(59.0,38.0),(60.0,37.0),(61.0,36.5),(61.5,35.0),
                    (61.0,34.0),(60.5,33.0),(60.0,31.5),(59.5,30.5),(58.5,29.5),
                    (57.5,28.0),(57.0,27.0),(56.5,27.0),(56.0,27.0),(55.0,26.5),
                    (54.0,26.5),(53.5,27.0),(53.0,26.5),(52.5,27.0),(52.0,27.0),
                    (51.5,27.5),(51.0,28.0),(50.5,28.5),(50.0,29.0),(49.5,29.5),
                    (49.0,30.0),(48.5,30.5),(48.0,31.5),(47.5,32.0),(47.0,33.0),
                    (46.5,33.5),(46.0,34.0),(45.5,35.0),(45.0,36.0),(44.5,36.5),
                    (44.0,37.0)
                ]
            },
            "IRAQ": {
                "color": (36, 50, 60),
                "pts": [
                    (38.8,33.4),(39.5,33.8),(40.0,34.2),(41.0,34.7),(42.0,35.2),
                    (43.0,36.0),(44.0,37.0),(44.5,36.5),(45.0,36.0),(45.5,35.0),
                    (46.0,34.0),(46.5,33.5),(47.0,33.0),(47.5,32.0),(48.0,31.5),
                    (48.5,30.5),(47.5,30.0),(47.0,29.5),(46.5,29.2),(46.0,29.0),
                    (44.7,29.2),(43.5,29.5),(42.0,30.5),(41.0,31.5),(40.0,32.0),
                    (39.0,32.5),(38.8,33.4)
                ]
            },
            "SYRIA": {
                "color": (34, 48, 58),
                "pts": [
                    (35.7,36.8),(36.0,36.5),(36.5,36.8),(37.0,36.5),(38.0,36.8),
                    (39.0,36.5),(40.0,36.8),(41.0,37.5),(42.0,37.2),(42.5,37.0),
                    (43.0,36.0),(42.0,35.2),(41.0,34.7),(40.0,34.2),(39.5,33.8),
                    (38.8,33.4),(38.0,33.5),(37.5,33.3),(37.0,33.5),(36.5,33.5),
                    (36.0,33.0),(35.8,33.5),(35.5,34.0),(35.7,35.0),(35.7,36.8)
                ]
            },
            "TURKEY": {
                "color": (36, 50, 60),
                "pts": [
                    (26.0,41.0),(27.0,41.5),(28.0,41.8),(29.0,41.5),(30.0,41.5),
                    (31.0,41.5),(32.0,42.0),(33.0,42.0),(34.0,42.0),(35.0,42.0),
                    (36.0,41.5),(37.0,41.5),(38.0,40.5),(39.0,40.5),(40.0,40.5),
                    (41.0,40.0),(42.0,40.5),(43.0,40.5),(44.0,40.0),(44.5,39.8),
                    (44.0,39.2),(43.0,38.5),(42.0,38.5),(41.0,38.5),(40.0,38.0),
                    (39.0,37.5),(38.0,37.0),(37.0,37.0),(36.5,36.8),(36.0,36.5),
                    (35.7,36.8),(35.5,36.5),(35.0,36.5),(34.5,37.0),(34.0,37.0),
                    (32.0,37.0),(30.0,36.5),(28.0,37.0),(26.5,38.0),(26.0,39.0),
                    (26.0,41.0)
                ]
            },
            "SAUDI": {
                "color": (34, 46, 56),
                "pts": [
                    (36.5,29.5),(37.0,29.0),(38.0,28.0),(39.0,27.0),(40.0,26.0),
                    (41.0,25.0),(42.0,24.5),(43.0,24.0),(44.0,23.5),(45.0,23.0),
                    (46.0,22.5),(47.0,22.0),(48.0,21.5),(49.0,21.0),(50.0,20.5),
                    (51.0,20.0),(52.0,19.5),(53.0,19.0),(54.0,18.5),(55.0,18.0),
                    (56.0,18.5),(56.0,20.0),(55.0,22.0),(54.0,24.0),(53.0,25.0),
                    (52.0,26.0),(51.0,27.0),(50.5,28.5),(50.0,29.0),(49.5,29.5),
                    (49.0,30.0),(48.5,30.5),(48.0,31.5),(47.5,32.0),(47.0,31.5),
                    (46.5,31.0),(46.0,29.0),(44.7,29.2),(43.5,29.5),(42.0,30.5),
                    (41.0,31.5),(40.0,32.0),(39.0,32.5),(38.8,33.4),(38.0,33.5),
                    (37.5,32.0),(37.0,31.0),(36.8,30.0),(36.5,29.5)
                ]
            },
            "ISRAEL_PAL": {
                "color": (40, 55, 68),
                "pts": [
                    (34.3,31.3),(34.5,31.0),(34.9,30.0),(35.1,29.5),(35.0,29.0),
                    (34.8,28.5),(34.5,29.5),(34.0,30.5),(33.8,31.0),(34.0,31.5),
                    (34.3,31.3)
                ]
            },
            "LEBANON": {
                "color": (36, 52, 64),
                "pts": [
                    (35.1,33.0),(35.7,34.0),(36.5,34.0),(36.6,33.5),(36.0,33.3),
                    (35.5,33.0),(35.1,33.0)
                ]
            },
            "JORDAN": {
                "color": (34, 48, 58),
                "pts": [
                    (34.9,30.0),(35.0,32.0),(35.5,33.0),(36.0,33.3),(36.5,33.5),
                    (36.6,33.5),(37.0,33.5),(38.0,33.5),(38.8,33.4),(39.0,32.5),
                    (39.0,31.5),(38.5,30.5),(37.5,30.0),(36.8,30.0),(36.5,29.5),
                    (36.0,29.5),(35.5,29.5),(35.2,29.6),(35.1,29.5),(34.9,30.0)
                ]
            },
            "YEMEN": {
                "color": (32, 45, 54),
                "pts": [
                    (42.5,16.5),(43.5,16.0),(44.5,15.5),(45.0,15.0),(45.5,14.5),
                    (46.0,14.0),(47.0,14.5),(48.0,14.0),(49.0,14.5),(50.0,15.0),
                    (51.0,16.0),(52.0,17.0),(53.0,17.5),(54.0,17.8),(55.0,17.5),
                    (55.5,16.5),(55.0,16.0),(54.5,15.5),(53.5,16.0),(52.5,17.0),
                    (51.5,17.0),(50.5,16.5),(49.5,16.0),(48.5,16.0),(47.5,16.5),
                    (46.5,17.0),(45.5,17.5),(44.5,17.5),(43.5,17.0),(42.5,16.5)
                ]
            },
            "UAE_OMAN": {
                "color": (34, 48, 58),
                "pts": [
                    (51.5,24.0),(52.5,24.5),(53.0,25.0),(54.0,25.5),(55.0,26.0),
                    (56.0,26.5),(57.0,27.0),(57.5,22.5),(56.5,22.0),(55.5,22.0),
                    (55.0,23.0),(54.0,24.0),(53.0,23.5),(52.5,23.5),(51.5,24.0)
                ]
            },
        }

        # رسم کشورها
        for country, info in COUNTRIES.items():
            pts_geo = info["pts"]
            if not pts_geo: continue
            pts_px = [gp(lat, lon) for lon, lat in pts_geo]
            drw.polygon(pts_px, fill=info["color"], outline=C_BORDER)

        # ── نام کشورها ─────────────────────────────────────────────────
        LABELS = [
            (32.5, 53.0, "IRAN",    C_LABEL),
            (33.3, 44.4, "IRAQ",    C_DIM),
            (35.0, 38.5, "SYRIA",   C_DIM),
            (31.5, 35.0, "ISRAEL",  C_DIM),
            (25.0, 45.0, "SAUDI",   C_DIM),
            (24.5, 54.5, "UAE",     C_DIM),
            (15.5, 48.0, "YEMEN",   C_DIM),
            (32.0, 36.0, "JORDAN",  C_DIM),
            (33.5, 36.2, "LEBANON", C_DIM),
            (39.0, 35.0, "TURKEY",  C_DIM),
            (26.5, 51.5, "GULF",    (60, 100, 140)),
        ]
        for r_lat, r_lon, name, color in LABELS:
            if LAT_MIN <= r_lat <= LAT_MAX and LON_MIN <= r_lon <= LON_MAX:
                px, py = gp(r_lat, r_lon)
                drw.text((px, py), name, fill=color, font=F12)

        # ── خلیج فارس (آبی‌تر) ──────────────────────────────────────
        gulf_pts = [gp(lat, lon) for lon, lat in [
            (48.0,30.0),(50.0,29.5),(52.0,28.5),(54.0,27.5),(56.0,27.0),
            (57.0,26.0),(57.0,25.0),(55.0,24.5),(53.0,24.0),(51.0,24.0),
            (50.0,24.5),(49.0,25.5),(48.0,27.0),(48.0,30.0)
        ]]
        drw.polygon(gulf_pts, fill=(12, 40, 72), outline=None)

        # ── دریای سرخ ───────────────────────────────────────────────
        red_sea_pts = [gp(lat, lon) for lon, lat in [
            (32.5,30.0),(33.0,28.0),(34.0,26.0),(35.0,24.0),(36.0,22.0),
            (37.0,20.0),(38.0,18.0),(39.0,17.5),(40.0,17.0),(43.0,16.0),
            (43.0,17.0),(41.0,18.5),(40.0,20.0),(39.0,22.0),(38.0,24.0),
            (37.5,26.0),(37.0,28.0),(36.5,30.0),(32.5,30.0)
        ]]
        drw.polygon(red_sea_pts, fill=(10, 36, 65), outline=None)

        # ── دریای مدیترانه ───────────────────────────────────────────
        med_pts = [gp(lat, lon) for lon, lat in [
            (26.0,36.5),(30.0,36.0),(32.0,34.5),(34.0,33.0),(35.7,36.8),
            (34.5,37.0),(32.0,37.0),(30.0,36.5),(28.0,37.0),(26.5,38.0),
            (26.0,36.5)
        ]]
        drw.polygon(med_pts, fill=(10, 36, 65), outline=None)

        # ── هواپیماهای نظامی ──────────────────────────────────────────
        plane_colors = [C_PLANE, C_PLANE2, (80, 200, 120), (180, 80, 255)]
        placed = []

        for idx, ac in enumerate(aircraft):
            lat, lon = ac["lat"], ac["lon"]
            if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                continue
            px, py = gp(lat, lon)

            # جلوگیری از تداخل
            shift = 0
            for ppx, ppy in placed:
                if abs(px - ppx) < 20 and abs(py - ppy) < 20:
                    py -= 25
                    break
            placed.append((px, py))

            pc = plane_colors[idx % len(plane_colors)]

            # دایره پس‌زمینه درخشان
            drw.ellipse([(px-18, py-18), (px+18, py+18)],
                        fill=(pc[0]//4, pc[1]//4, pc[2]//4), outline=pc, width=2)
            # مثلث هواپیما
            tri = [(px, py-12), (px-8, py+8), (px+8, py+8)]
            drw.polygon(tri, fill=pc, outline=(255,255,255))
            # نقطه مرکزی
            drw.ellipse([(px-3, py-3), (px+3, py+3)], fill=(255,255,255))

            # خط راهنما به برچسب
            lx = px + 22
            drw.line([(px+12, py), (lx-2, py)], fill=pc, width=1)

            # برچسب پس‌زمینه
            label   = f"{ac['callsign']} / {ac['type']}"
            alt_txt = f"alt:{int(ac['alt'])//1000 if ac['alt'] else '?'}k  {ac['gs']}kt"
            drw.rectangle([(lx-2, py-14), (lx+170, py+18)],
                          fill=(12, 18, 28), outline=pc)
            drw.text((lx+2, py-13), label,   fill=pc,    font=FB)
            drw.text((lx+2, py+2),  alt_txt, fill=C_DIM, font=F11)

        # ── هدر ─────────────────────────────────────────────────────
        drw.rectangle([(0, 0), (W, PAD_T - 2)], fill=C_HEAD)
        drw.rectangle([(0, PAD_T - 2), (W, PAD_T)], fill=C_ACCENT)
        now_str = datetime.now(TEHRAN_TZ).strftime("%H:%M  %Y/%m/%d")
        drw.text((10, 8),
                 f"✈  Military Flights — Middle East  |  {now_str}  |  {len(aircraft)} aircraft tracked",
                 fill=C_ACCENT, font=FB)

        # ── فوتر ────────────────────────────────────────────────────
        drw.rectangle([(0, H - PAD_B), (W, H)], fill=C_HEAD)
        drw.text((10, H - PAD_B + 6), "Source: ADS-B Exchange  |  WarBot v17",
                 fill=C_DIM, font=F11)

        # ── legend ──────────────────────────────────────────────────
        lx, ly = W - 200, PAD_T + 10
        drw.rectangle([(lx-5, ly-5), (W-5, ly + len(aircraft)*22 + 10)],
                      fill=(10, 15, 25), outline=C_BORDER)
        for i, ac in enumerate(aircraft):
            pc = plane_colors[i % len(plane_colors)]
            drw.rectangle([(lx, ly + i*22), (lx+12, ly + i*22 + 12)], fill=pc)
            drw.text((lx+16, ly + i*22 - 2),
                     f"{ac['callsign']} – {ac['region']}", fill=C_LABEL, font=F11)

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        buf.seek(0)
        return buf

    except Exception as e:
        log.warning(f"flight_map error: {e}")
        import traceback; log.debug(traceback.format_exc())
        return None

# ══════════════════════════════════════════════════════════════════════════
# RSS + Telegram fetch
# ══════════════════════════════════════════════════════════════════════════
async def fetch_rss(client: httpx.AsyncClient, feed: dict) -> list:
    """RSS با conditional GET (ETag/If-Modified-Since)"""
    try:
        hdrs = dict(COMMON_UA)
        hdrs["Accept"] = "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8"
        if feed.get("_etag"):      hdrs["If-None-Match"]     = feed["_etag"]
        if feed.get("_last_mod"):  hdrs["If-Modified-Since"] = feed["_last_mod"]
        r = await client.get(feed["u"], timeout=httpx.Timeout(RSS_TIMEOUT), headers=hdrs)
        if r.status_code == 304: return []
        if r.status_code != 200: return []
        if r.headers.get("ETag"):          feed["_etag"]     = r.headers["ETag"]
        if r.headers.get("Last-Modified"): feed["_last_mod"] = r.headers["Last-Modified"]
        entries = feedparser.parse(r.text).entries or []
        is_emb  = id(feed) in EMBASSY_SET
        return [(e, feed["n"], "rss", is_emb) for e in entries]
    except: return []

async def fetch_telegram_channel(client: httpx.AsyncClient, label: str,
                                  handle: str, cutoff: datetime) -> list:
    """
    scrape t.me/s/{handle} — فقط پیام‌های بعد از cutoff
    """
    url  = f"https://t.me/s/{handle}"
    hdrs = {
        "User-Agent": "TelegramBot (like TwitterBot)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Cache-Control": "no-cache",
    }
    try:
        r = await client.get(url, timeout=httpx.Timeout(TG_TIMEOUT), headers=hdrs)
        if r.status_code not in (200, 301, 302): return []
        soup = BeautifulSoup(r.text, "html.parser")
        msgs = soup.select(".tgme_widget_message_wrap")
        if not msgs: return []
        results = []
        for msg in msgs[-30:]:
            txt_el = msg.select_one(".tgme_widget_message_text")
            text   = txt_el.get_text(" ", strip=True) if txt_el else ""
            if not text or len(text) < 15: continue
            time_el  = msg.select_one("time")
            dt_str   = time_el.get("datetime", "") if time_el else ""
            entry_dt = None
            if dt_str:
           
