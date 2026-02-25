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

SEEN_FILE         = "seen.json"
STORIES_FILE      = "stories.json"
GEMINI_STATE_FILE = "gemini_state.json"
FLIGHT_ALERT_FILE = "flight_alerts.json"
RUN_STATE_FILE    = "run_state.json"
NITTER_CACHE_FILE = "nitter_cache.json"

# ── زمان‌بندی ─────────────────────────────────────────────────────────────
# مهم‌ترین تغییر v17: cutoff = last_run - BUFFER_MIN
# هر اجرا فقط اخبار تازه بعد از اجرای قبلی را می‌بیند
CUTOFF_BUFFER_MIN  = 3    # buffer برای جلوگیری از miss شدن
MAX_LOOKBACK_MIN   = 15   # حداکثر برگشت به عقب (اولین اجرا یا بعد crash)
SEEN_TTL_HOURS     = 6    # seen.json فقط ۶ ساعت نگه می‌داره
NITTER_CACHE_TTL   = 900  # ۱۵ دقیقه (کوتاه‌تر → نوسازی سریع‌تر)

MAX_NEW_PER_RUN    = 25   # حداکثر خبر per run
MAX_MSG_LEN        = 4096
SEND_DELAY         = 0.6  # ثانیه بین پیام‌ها
JACCARD_THRESHOLD  = 0.38
RSS_TIMEOUT        = 7.0
TG_TIMEOUT         = 10.0
TW_TIMEOUT         = 5.0  # کوتاه‌تر → fail faster → handle بعدی
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
    {"n":"🇮🇷 Radio Farda",         "u":"https://www.radiofarda.com/api/zoyqvpemr"},
    {"n":"🇮🇷 Iran Wire EN",        "u":"https://iranwire.com/en/feed/"},
    {"n":"🇮🇷 خبرگزاری تسنیم",      "u":"https://www.tasnimnews.com/fa/rss/feed/0/8/0"},
    {"n":"🇮🇷 خبرگزاری مهر",         "u":"https://www.mehrnews.com/rss"},
    {"n":"🇮🇷 خبرگزاری ایرنا",       "u":"https://www.irna.ir/rss"},
    {"n":"🇮🇷 خبرگزاری فارس",        "u":"https://www.farsnews.ir/rss/fa"},
    {"n":"🇮🇷 مشرق نیوز",             "u":"https://www.mashreghnews.ir/rss"},
    {"n":"🇮🇷 دفاع پرس",             "u":"https://www.defapress.ir/fa/rss"},
    {"n":"🇮🇷 سپاه نیوز",             "u":"https://www.sepahnews.com/rss"},
    {"n":"🇮🇷 GNews IRGC EN",        "u":"https://news.google.com/rss/search?q=IRGC+Iran+Israel+attack+war&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇷 GNews جنگ ایران",      "u":"https://news.google.com/rss/search?q=ایران+اسراییل+جنگ+حمله&hl=fa&gl=IR&ceid=IR:fa&num=15"},
    {"n":"🇮🇷 GNews سپاه موشک",      "u":"https://news.google.com/rss/search?q=سپاه+موشک+حمله+اسراییل&hl=fa&gl=IR&ceid=IR:fa&num=15"},
    {"n":"🇮🇷 GNews خامنه‌ای",        "u":"https://news.google.com/rss/search?q=خامنه‌ای+بیانیه+جنگ&hl=fa&gl=IR&ceid=IR:fa&num=10"},
]
ISRAEL_FEEDS = [
    {"n":"🇮🇱 Jerusalem Post",       "u":"https://www.jpost.com/rss/rssfeedsheadlines.aspx"},
    {"n":"🇮🇱 Times of Israel",      "u":"https://www.timesofisrael.com/feed/"},
    {"n":"🇮🇱 TOI Iran",             "u":"https://www.timesofisrael.com/topic/iran/feed/"},
    {"n":"🇮🇱 Israel Hayom EN",      "u":"https://www.israelhayom.com/feed/"},
    {"n":"🇮🇱 Arutz Sheva",          "u":"https://www.israelnationalnews.com/rss.aspx"},
    {"n":"🇮🇱 i24 News",             "u":"https://www.i24news.tv/en/rss"},
    {"n":"🇮🇱 Israel Defense",       "u":"https://www.israeldefense.co.il/en/rss.xml"},
    {"n":"🇮🇱 Netanyahu Iran GNews", "u":"https://news.google.com/rss/search?q=Netanyahu+Iran+attack+order+war&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 IDF Iran GNews",       "u":"https://news.google.com/rss/search?q=IDF+operation+Iran+strike+missile&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 Iron Dome GNews",      "u":"https://news.google.com/rss/search?q=Iron+Dome+Arrow+missile+intercept+Iran&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 Mossad Iran GNews",    "u":"https://news.google.com/rss/search?q=Mossad+Iran+covert+operation&hl=en-US&gl=US&ceid=US:en&num=15"},
]
USA_FEEDS = [
    {"n":"🇺🇸 AP Top News",          "u":"https://feeds.apnews.com/rss/apf-topnews"},
    {"n":"🇺🇸 AP World",             "u":"https://feeds.apnews.com/rss/apf-WorldNews"},
    {"n":"🇺🇸 Reuters World",        "u":"https://feeds.reuters.com/reuters/worldNews"},
    {"n":"🇺🇸 Reuters Middle East",  "u":"https://feeds.reuters.com/reuters/MEonlineHeadlines"},
    {"n":"🇺🇸 CNN Middle East",      "u":"http://rss.cnn.com/rss/edition_meast.rss"},
    {"n":"🇺🇸 Pentagon DoD",         "u":"https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"n":"🇺🇸 USNI News",            "u":"https://news.usni.org/feed"},
    {"n":"🇺🇸 Breaking Defense",     "u":"https://breakingdefense.com/feed/"},
    {"n":"🇺🇸 The War Zone",         "u":"https://www.twz.com/feed"},
    {"n":"🇺🇸 Foreign Policy",       "u":"https://foreignpolicy.com/feed/"},
    {"n":"🇺🇸 Defense News",         "u":"https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"n":"🇺🇸 Military Times",       "u":"https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    {"n":"🇺🇸 US Strike Iran GNews", "u":"https://news.google.com/rss/search?q=United+States+strike+bomb+Iran+military&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇺🇸 US Navy Iran GNews",   "u":"https://news.google.com/rss/search?q=US+Navy+carrier+Iran+Persian+Gulf&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇺🇸 CENTCOM GNews",        "u":"https://news.google.com/rss/search?q=CENTCOM+Iran+Iraq+military+operation&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🔍 Long War Journal",      "u":"https://www.longwarjournal.org/feed"},
    {"n":"⚠️ IAEA Iran GNews",       "u":"https://news.google.com/rss/search?q=IAEA+Iran+nuclear+uranium&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"⚠️ Red Sea Houthi GNews",  "u":"https://news.google.com/rss/search?q=Houthi+Iran+Red+Sea+attack+US&hl=en-US&gl=US&ceid=US:en&num=15"},
]
EMBASSY_FEEDS = [
    {"n":"🏛️ US Virtual Embassy",   "u":"https://ir.usembassy.gov/feed/"},
    {"n":"🏛️ US State Travel",      "u":"https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html.rss"},
    {"n":"🏛️ UK FCDO Iran",         "u":"https://www.gov.uk/foreign-travel-advice/iran.atom"},
    {"n":"🏛️ Embassy Evacuations",  "u":"https://news.google.com/rss/search?q=embassy+evacuation+Iran+Tehran+warning&hl=en-US&gl=US&ceid=US:en&num=10"},
]
INTL_FEEDS = [
    {"n":"🌐 BBC Middle East",  "u":"https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"n":"🌐 Al Jazeera",       "u":"https://www.aljazeera.com/xml/rss/all.xml"},
    {"n":"🌐 Middle East Eye",  "u":"https://www.middleeasteye.net/rss"},
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
# فیلتر موضوعی
# ══════════════════════════════════════════════════════════════════════════
IRAN_KEYWORDS = [
    "iran","iranian","irgc","islamic republic","khamenei","tehran","persian",
    "sepah","basij","quds force","rouhani","raisi","pezeshkian",
    "ایران","سپاه","خامنه‌ای","تهران","جمهوری اسلامی","پزشکیان",
]
OPPONENT_KEYWORDS = [
    "israel","israeli","idf","netanyahu","us military","united states","pentagon",
    "centcom","nato","hamas","hezbollah","houthi","saudi","uae",
    "اسراییل","آمریکا","پنتاگون","نتانیاهو","حماس","حزب‌الله","حوثی",
]
ACTION_KEYWORDS = [
    "attack","strike","missile","bomb","war","kill","dead","casualties","nuclear",
    "sanction","threat","intercept","drone","explosion","airstrike","operation",
    "deploy","troops","invasion","retaliat","escalat","alert","warning",
    "حمله","موشک","کشته","جنگ","هسته‌ای","تحریم","تهدید","عملیات",
    "انفجار","پهپاد","پدافند","رهگیری","تجاوز","آماده‌باش","اعلام جنگ",
]
HARD_EXCLUDE = [
    "football","soccer","basketball","olympic","sports","cooking",
    "fashion","celebrity","entertainment","music","award",
    "فوتبال","سینما","موسیقی","ورزش",
]
EMBASSY_OVERRIDE = [
    "evacuate","leave immediately","travel warning","security alert","emergency",
    "تخلیه","فوری ترک","هشدار","اضطرار",
]

def is_war_relevant(text, is_embassy=False, is_tg=False, is_tw=False):
    txt = text.lower()
    if is_embassy and any(k in txt for k in EMBASSY_OVERRIDE): return True
    if any(k in txt for k in HARD_EXCLUDE): return False
    hi = any(k in txt for k in IRAN_KEYWORDS)
    ho = any(k in txt for k in OPPONENT_KEYWORDS)
    ha = any(k in txt for k in ACTION_KEYWORDS)
    if is_tg or is_tw: return (hi or ho) and ha
    return hi and ho and ha

# ══════════════════════════════════════════════════════════════════════════
# Twitter/X — Nitter + RSSHub
# ══════════════════════════════════════════════════════════════════════════
# Nitter instances — معتبرترین در ۲۰۲۶
# xcancel.com بیشترین uptime دارد
NITTER_INSTANCES = [
    "https://xcancel.com",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.tiekoetter.com",
    "https://nitter.space",
    "https://n.ramle.be",
    "https://nitter.catsarch.com",
]
# RSSHub instances — fallback
RSSHUB_INSTANCES = [
    "https://rsshub.rss.now.sh",
    "https://rss.shab.fun",
    "https://rsshub.moeyy.xyz",
]

NITTER_HDR = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
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
    return ("xml" in ct) or ("<rss" in body[:400]) or body.lstrip()[:6].startswith("<?xml")

async def _try_rss(client: httpx.AsyncClient, url: str, timeout: float = TW_TIMEOUT) -> list:
    """GET یک URL RSS — خروجی: list از entries یا []"""
    try:
        r = await client.get(url, headers=NITTER_HDR,
                             timeout=httpx.Timeout(connect=3.0, read=timeout,
                                                   write=3.0, pool=3.0))
        if r.status_code != 200: return []
        if not _is_rss(r.text, r.headers.get("content-type", "")): return []
        entries = feedparser.parse(r.text).entries
        return [e for e in entries if len(e.get("title", "").strip()) > 5]
    except: return []

async def _probe_nitter(client: httpx.AsyncClient, inst: str) -> tuple | None:
    t0 = asyncio.get_running_loop().time()
    e  = await _try_rss(client, f"{inst}/CENTCOM/rss", timeout=4.0)
    if e:
        return inst, (asyncio.get_running_loop().time() - t0) * 1000
    return None

async def _probe_rsshub(client: httpx.AsyncClient, inst: str) -> tuple | None:
    t0 = asyncio.get_running_loop().time()
    e  = await _try_rss(client, f"{inst}/twitter/user/CENTCOM", timeout=5.0)
    if e:
        return inst, (asyncio.get_running_loop().time() - t0) * 1000
    return None

async def build_twitter_pools(client: httpx.AsyncClient):
    """
    Probe Nitter + RSSHub موازی — نتیجه در کش ۱۵ دقیقه‌ای
    """
    global _nitter_pool, _rsshub_pool
    if _nitter_pool or _rsshub_pool:
        return

    cached_n, cached_r, ts = _load_nitter_cache()
    age = datetime.now(timezone.utc).timestamp() - ts
    if age < NITTER_CACHE_TTL and (cached_n or cached_r):
        _nitter_pool = cached_n
        _rsshub_pool = cached_r
        log.info(f"𝕏 pool از cache: Nitter={len(_nitter_pool)} RSSHub={len(_rsshub_pool)}")
        return

    log.info(f"𝕏 Probing {len(NITTER_INSTANCES)} Nitter + {len(RSSHUB_INSTANCES)} RSSHub...")
    sema = asyncio.Semaphore(8)
    async def sp(coro):
        async with sema:
            try: return await coro
            except: return None

    n = len(NITTER_INSTANCES)
    results = await asyncio.gather(
        *[sp(_probe_nitter(client, u)) for u in NITTER_INSTANCES],
        *[sp(_probe_rsshub(client, u)) for u in RSSHUB_INSTANCES],
    )
    nok = sorted([r for r in results[:n] if r], key=lambda x: x[1])
    rok = sorted([r for r in results[n:] if r], key=lambda x: x[1])

    _nitter_pool = [u for u, _ in nok]  or NITTER_INSTANCES[:3]
    _rsshub_pool = [u for u, _ in rok]

    if nok: log.info(f"  Nitter best: {nok[0][0].split('//')[-1]} ({nok[0][1]:.0f}ms)")
    if rok: log.info(f"  RSSHub best: {rok[0][0].split('//')[-1]} ({rok[0][1]:.0f}ms)")
    log.info(f"𝕏 Nitter:{len(_nitter_pool)} RSSHub:{len(_rsshub_pool)}")
    _save_nitter_cache(_nitter_pool, _rsshub_pool)

async def fetch_twitter(client: httpx.AsyncClient, label: str, handle: str) -> list:
    """
    دریافت توییت‌های یک handle — سه مرحله:
    1. Nitter (سریع‌ترین instance از probe)
    2. RSSHub
    3. xcancel.com مستقیم
    semaphore کلی جلوگیری از flood به instances
    """
    sema = _TW_SEMA or asyncio.Semaphore(20)
    async with sema:
        # مرحله ۱: Nitter
        pool = _nitter_pool or NITTER_INSTANCES
        start = abs(hash(handle)) % len(pool)
        for inst in (pool * 2)[start: start + min(3, len(pool))]:
            e = await _try_rss(client, f"{inst}/{handle}/rss")
            if e:
                log.debug(f"𝕏 {handle} ← Nitter/{inst.split('//')[-1]}")
                return [(x, f"𝕏 {label}", "tw", False) for x in e]

        # مرحله ۲: RSSHub
        for inst in (_rsshub_pool or RSSHUB_INSTANCES[:1]):
            e = await _try_rss(client, f"{inst}/twitter/user/{handle}")
            if e:
                log.debug(f"𝕏 {handle} ← RSSHub/{inst.split('//')[-1]}")
                return [(x, f"𝕏 {label}", "tw", False) for x in e]

        # مرحله ۳: xcancel.com مستقیم
        e = await _try_rss(client, f"https://xcancel.com/{handle}/rss")
        if e:
            log.debug(f"𝕏 {handle} ← xcancel direct")
            return [(x, f"𝕏 {label}", "tw", False) for x in e]

    log.debug(f"𝕏 {handle}: همه روش‌ها fail")
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
_MIL_TYPES    = {"B52","B2","B1","F15","F16","F22","F35","F18","E3","E8","RC135","U2","P8","MQ9","RQ4","C17","KC135"}
_CALLSIGN_PFX = ["DOOM","BONE","BUCK","CIAO","JAKE","TORC","GRIM","HAVOC","GHOST"]
_ADSB_SEEN    = set()

async def fetch_military_flights(client: httpx.AsyncClient) -> list:
    global _ADSB_SEEN
    msgs = []
    try:
        try:
            if Path(FLIGHT_ALERT_FILE).exists():
                _ADSB_SEEN = set(json.load(open(FLIGHT_ALERT_FILE)).get("seen", []))
        except: pass
        for region, lat, lon, radius in ADSB_REGIONS:
            try:
                r = await client.get(f"{ADSB_API}/point/{lat}/{lon}/{radius}",
                                     timeout=httpx.Timeout(7.0),
                                     headers={"Accept": "application/json"})
                if r.status_code != 200: continue
                for ac in (r.json().get("ac") or []):
                    hex_id   = (ac.get("hex") or ac.get("icao","")).upper()
                    callsign = (ac.get("flight") or ac.get("callsign","")).strip()
                    cat      = (ac.get("category") or "").upper()
                    t        = (ac.get("t") or ac.get("type","")).upper()
                    is_mil   = (any(t.startswith(m) for m in _MIL_TYPES)
                                or any(callsign.startswith(p) for p in _CALLSIGN_PFX)
                                or "A5" in cat)
                    if not is_mil: continue
                    uid = f"{hex_id}_{callsign}"
                    if uid in _ADSB_SEEN: continue
                    _ADSB_SEEN.add(uid)
                    alt = ac.get("alt_baro") or ac.get("alt", 0)
                    gs  = ac.get("gs") or ac.get("speed", 0)
                    msgs.append(f"✈️ <b>تحرک نظامی — {region}</b>\n"
                                f"نوع: <code>{t or '?'}</code>  کال‌ساین: <code>{callsign or hex_id}</code>\n"
                                f"ارتفاع: {alt:,} ft  سرعت: {gs} kt")
            except Exception as e:
                log.debug(f"ADS-B {region}: {e}")
        json.dump({"seen": list(_ADSB_SEEN)[-300:]}, open(FLIGHT_ALERT_FILE, "w"))
    except Exception as e:
        log.warning(f"ADS-B: {e}")
    return msgs

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
                try: entry_dt = datetime.fromisoformat(dt_str.replace("Z","+00:00"))
                except: pass
            # فقط پیام‌های تازه‌تر از cutoff
            if entry_dt and entry_dt < cutoff: continue
            link_el = msg.select_one("a.tgme_widget_message_date")
            link    = link_el.get("href","") if link_el else f"https://t.me/{handle}"
            results.append(({
                "title":   text[:300],
                "summary": text[:800],
                "link":    link,
                "_tg_dt":  entry_dt,
            }, label, "tg", False))
        return results
    except Exception as e:
        log.debug(f"TG {handle}: {e}"); return []

async def fetch_all(client: httpx.AsyncClient, cutoff: datetime) -> list:
    """
    واکشی موازی همه منابع
    cutoff برای Telegram پاس داده می‌شه (RSS از is_fresh در main فیلتر می‌شه)
    """
    await build_twitter_pools(client)

    rss_t = [fetch_rss(client, f) for f in ALL_RSS_FEEDS]
    tg_t  = [fetch_telegram_channel(client, l, h, cutoff) for l, h in TELEGRAM_CHANNELS]
    tw_t  = [fetch_twitter(client, l, h) for l, h in TWITTER_HANDLES]

    all_res = await asyncio.gather(*rss_t, *tg_t, *tw_t, return_exceptions=True)

    out = []; rss_ok = tg_ok = tw_ok = 0
    n_rss = len(ALL_RSS_FEEDS); n_tg = len(TELEGRAM_CHANNELS)
    for i, res in enumerate(all_res):
        if not isinstance(res, list): continue
        out.extend(res)
        if   i < n_rss:          rss_ok += bool(res)
        elif i < n_rss + n_tg:   tg_ok  += bool(res)
        else:                     tw_ok  += bool(res)

    log.info(f"  📡 RSS:{rss_ok}/{len(ALL_RSS_FEEDS)} "
             f" 📢 TG:{tg_ok}/{len(TELEGRAM_CHANNELS)} "
             f" 𝕏:{tw_ok}/{len(TWITTER_HANDLES)}")
    return out

# ══════════════════════════════════════════════════════════════════════════
# ابزار متن
# ══════════════════════════════════════════════════════════════════════════
def clean_html(t): return re.sub(r"<[^>]+>", " ", t or "").strip()
def trim(t, n):
    t = t.strip()
    return t if len(t) <= n else t[:n-1] + "…"
def make_id(entry):
    k = entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(k.encode()).hexdigest()
def esc(t):
    return re.sub(r"([<>&])", lambda m: {"<":"&lt;",">":"&gt;","&":"&amp;"}[m.group()], t)

def format_dt(entry) -> str:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            dt = datetime(*t[:6], tzinfo=timezone.utc).astimezone(TEHRAN_TZ)
            return dt.strftime("%H:%M تهران")
        tg_dt = entry.get("_tg_dt")
        if tg_dt:
            return tg_dt.astimezone(TEHRAN_TZ).strftime("%H:%M تهران")
    except: pass
    return ""

def is_fresh(entry, cutoff: datetime) -> bool:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t: return datetime(*t[:6], tzinfo=timezone.utc) >= cutoff
        tg_dt = entry.get("_tg_dt")
        if tg_dt: return tg_dt >= cutoff
        return True  # بدون timestamp → پاس بده (seen.json فیلتر می‌کنه)
    except: return True

# ══════════════════════════════════════════════════════════════════════════
# Dedup
# ══════════════════════════════════════════════════════════════════════════
_VIOLENCE_CODES  = {"MSL","AIR","ATK","KIA","DEF","EXP"}
_POLITICAL_CODES = {"THR","DIP","SAN","NUC","SPY","STM"}

def _stem(word):
    w = word.lower()
    for suf in ("ing","ed","tion","ment","er","ها","های","\u200cها"):
        if w.endswith(suf) and len(w) > len(suf)+3: return w[:-len(suf)]
    return w

def _bag(text):
    return {_stem(w) for w in re.findall(r"[\w\u0600-\u06FF]{3,}", text.lower())}

def _entity_triple(title):
    txt = title.lower()
    actors = (
        ["iran","irgc","khamenei","سپاه","ایران"],
        ["israel","idf","netanyahu","اسراییل"],
        ["us ","usa","centcom","pentagon","آمریکا"],
        ["hamas","حماس"], ["hezbollah","حزب‌الله"], ["houthi","حوثی"],
    )
    action_cats = {
        "MSL": ["missile","rocket","ballistic","موشک","پهپاد"],
        "AIR": ["airstrike","bombing","بمباران"],
        "ATK": ["attack","strike","حمله"],
        "KIA": ["killed","dead","casualties","کشته","شهید"],
        "DEF": ["intercept","iron dome","رهگیری"],
        "EXP": ["explosion","blast","انفجار"],
        "THR": ["threat","warn","تهدید"],
        "SAN": ["sanction","تحریم"],
        "NUC": ["nuclear","uranium","هسته‌ای"],
    }
    actor1, actor2, act = "", "", ""
    for i, grp in enumerate(actors):
        if any(a in txt for a in grp):
            if not actor1: actor1 = str(i)
            elif not actor2: actor2 = str(i)
    for code, kws in action_cats.items():
        if any(k in txt for k in kws): act = code; break
    return actor1, actor2, act

def is_story_dup(title: str, stories: list) -> bool:
    bag1 = _bag(title)
    if not bag1: return False
    a1, a2, act1 = _entity_triple(title)
    for prev_t, prev_bag, prev_triple in stories:
        pa, pb, pact = prev_triple
        if act1 and pact and act1 in _VIOLENCE_CODES and pact in _VIOLENCE_CODES:
            if a1 == pa and a2 == pb: return True
        if act1 and pact and act1 in _POLITICAL_CODES and pact in _POLITICAL_CODES:
            if a1 == pa: return True
        union = bag1 | prev_bag
        if union and len(bag1 & prev_bag) / len(union) >= JACCARD_THRESHOLD:
            return True
    return False

def register_story(title, stories):
    stories.append((title, _bag(title), _entity_triple(title)))
    return stories[-300:]

# ══════════════════════════════════════════════════════════════════════════
# seen.json — با TTL — فقط ارسال‌شده‌ها
# ══════════════════════════════════════════════════════════════════════════
def load_seen() -> set:
    cutoff_ts = datetime.now(timezone.utc).timestamp() - SEEN_TTL_HOURS * 3600
    try:
        if Path(SEEN_FILE).exists():
            raw = json.load(open(SEEN_FILE))
            if isinstance(raw, dict):
                return {k for k, v in raw.items() if v > cutoff_ts}
            elif isinstance(raw, list):
                # migrate از فرمت قدیم — فقط ۵۰۰ تا آخر
                return set(raw[-500:])
    except: pass
    return set()

def save_seen(seen: set):
    now_ts    = datetime.now(timezone.utc).timestamp()
    cutoff_ts = now_ts - SEEN_TTL_HOURS * 3600
    try:
        existing = {}
        if Path(SEEN_FILE).exists():
            raw = json.load(open(SEEN_FILE))
            if isinstance(raw, dict):
                existing = {k: v for k, v in raw.items() if v > cutoff_ts}
    except: existing = {}
    for eid in seen:
        if eid not in existing: existing[eid] = now_ts
    if len(existing) > 5000:
        existing = dict(sorted(existing.items(), key=lambda x: x[1], reverse=True)[:5000])
    json.dump(existing, open(SEEN_FILE, "w"))

# ══════════════════════════════════════════════════════════════════════════
# run_state — last_run برای cutoff هوشمند
# ══════════════════════════════════════════════════════════════════════════
def load_run_state() -> datetime:
    """آخرین زمان اجرا — برای محاسبه cutoff"""
    try:
        if Path(RUN_STATE_FILE).exists():
            d   = json.load(open(RUN_STATE_FILE))
            ts  = d.get("last_run", 0)
            if ts:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
    except: pass
    # اولین اجرا: MAX_LOOKBACK_MIN به عقب
    return datetime.now(timezone.utc) - timedelta(minutes=MAX_LOOKBACK_MIN)

def save_run_state():
    existing = {}
    try:
        if Path(RUN_STATE_FILE).exists():
            existing = json.load(open(RUN_STATE_FILE))
    except: pass
    existing["last_run"] = datetime.now(timezone.utc).timestamp()
    json.dump(existing, open(RUN_STATE_FILE, "w"))

def load_stories() -> list:
    try:
        if Path(STORIES_FILE).exists(): return json.load(open(STORIES_FILE))
    except: pass
    return []

def save_stories(stories):
    json.dump(stories[-300:], open(STORIES_FILE, "w"))

# ══════════════════════════════════════════════════════════════════════════
# Gemini ترجمه
# ══════════════════════════════════════════════════════════════════════════
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

TRANSLATE_PROMPT = """تو یه خبرنگار جنگی حرفه‌ای هستی. این خبرها رو به فارسی برگردون.

قوانین:
۱. فارسی روان و کامل — هیچ چیز حذف نشود
۲. نقل‌قول‌ها را عین‌العین با گیومه: «جمله گفته‌شده»
۳. اسامی دقیق: Netanyahu=نتانیاهو، Khamenei=خامنه‌ای، IRGC=سپاه، IDF=ارتش اسراییل
۴. آمار و تاریخ را حفظ کن
۵. اگه خبر فارسی است: فقط ویرایش کن بدون تغییر محتوا

فرمت خروجی:
###ITEM_0###
[ترجمه فارسی کامل]
###ITEM_1###
[ترجمه فارسی کامل]

===خبرها===
{items}"""

async def translate_batch(client: httpx.AsyncClient, articles: list) -> list:
    if not GEMINI_API_KEY or not articles: return articles
    items_txt = "".join(
        f"###ITEM_{i}###\nTITLE: {t[:400]}\nBODY: {s[:600]}\n"
        for i, (t, s) in enumerate(articles)
    )
    state = {}
    try:
        if Path(GEMINI_STATE_FILE).exists():
            state = json.load(open(GEMINI_STATE_FILE))
    except: pass
    models = state.get("models_order", GEMINI_MODELS)
    base   = "https://generativelanguage.googleapis.com/v1beta/models"
    for model in models:
        try:
            r = await client.post(
                f"{base}/{model}:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": TRANSLATE_PROMPT.format(items=items_txt)}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192}
                },
                timeout=httpx.Timeout(30.0)
            )
            if r.status_code in (429, 503): continue
            if r.status_code != 200: continue
            text_out = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            results  = list(articles)
            for i, (orig_t, orig_s) in enumerate(articles):
                m = re.search(rf"###ITEM_{i}###\s*(.*?)(?=###ITEM_|\Z)", text_out, re.DOTALL)
                if m:
                    tr = m.group(1).strip()
                    if len(tr) > 10: results[i] = (tr, orig_s)
            return results
        except Exception as e:
            log.debug(f"Gemini {model}: {e}"); continue
    return articles

# ══════════════════════════════════════════════════════════════════════════
# Sentiment
# ══════════════════════════════════════════════════════════════════════════
BREAKING_KEYWORDS = [
    "breaking","urgent","alert","just in","explosion","airstrike","killed","dead",
    "war","attack","strike","nuclear","bomb","missile","invasion",
    "حمله","کشته","انفجار","شهید","موشک","فوری","خبر فوری","اعلام جنگ",
]
IMPORTANCE_BOOST = {
    "💀":4, "🔴":3, "💥":3, "🚀":3, "☢️":3,
    "✈️":2, "🚢":2, "🛡️":2, "🕵️":2,
    "🔥":1, "💰":1, "⚠️":1,
}

SENTIMENT_RULES = [
    ("💀", ["killed","dead","casualties","fatalities","wounded","martyred","massacre"],
           ["کشته","شهید","تلفات","کشتار","مجروح"]),
    ("🔴", ["attack","struck","assault","launched attack","opened fire","bombed","targeted"],
           ["حمله","ضربه","مورد هدف","حمله کرد"]),
    ("💥", ["explosion","blast","detonation","explode","blew up"],
           ["انفجار","منفجر","ترکید"]),
    ("✈️", ["airstrike","air strike","air raid","warplane","f-35","f-15","b-52","f-16"],
           ["حمله هوایی","بمباران","جنگنده"]),
    ("🚀", ["missile","rocket","ballistic","cruise missile","drone strike","hypersonic"],
           ["موشک","پهپاد","موشک بالستیک","راکت"]),
    ("☢️", ["nuclear","uranium","enrichment","natanz","fordow","centrifuge","iaea"],
           ["هسته‌ای","اورانیوم","غنی‌سازی","نطنز","فردو","سانتریفیوژ"]),
    ("🚢", ["navy","naval","warship","aircraft carrier","strait of hormuz","red sea"],
           ["نیروی دریایی","ناو","تنگه هرمز","دریای سرخ"]),
    ("🕵️", ["intelligence","mossad","cia","spy","covert","assassination","sabotage","cyber"],
           ["جاسوسی","موساد","خرابکاری","ترور","سایبری"]),
    ("🛡️", ["intercept","shot down","iron dome","air defense","patriot"],
           ["رهگیری","پدافند","گنبد آهنین","سرنگون"]),
    ("🔥", ["escalat","tension","brink of war","retaliat","provocation"],
           ["تشدید","تنش","تلافی","آستانه جنگ"]),
    ("💰", ["sanction","embargo","swift","freeze assets"],
           ["تحریم","محاصره اقتصادی"]),
    ("⚠️", ["threat","warn","warning","ultimatum","red line","will respond"],
           ["تهدید","هشدار","خط قرمز","اولتیماتوم"]),
    ("🤝", ["negotiation","talks","deal","diplomacy","ceasefire","agreement"],
           ["مذاکره","توافق","آتش‌بس","دیپلماسی"]),
    ("📜", ["statement","declared","announced","press conference","spokesperson"],
           ["بیانیه","اعلام","نشست خبری","سخنگو"]),
]

def analyze_sentiment(text: str) -> list:
    txt = text.lower()
    found = []
    for icon, en_kws, fa_kws in SENTIMENT_RULES:
        if any(kw in txt for kw in en_kws) or any(kw in txt for kw in fa_kws):
            found.append(icon)
        if len(found) >= 3: break
    return found or ["📰"]

def calc_importance(title: str, body: str, icons: list, stype: str) -> int:
    txt = (title + " " + body).lower()
    score = sum(IMPORTANCE_BOOST.get(ic, 0) for ic in icons)
    if any(k in txt for k in BREAKING_KEYWORDS): score += 2
    if stype == "tw" and score > 0: score += 1
    return min(score, 10)

def sentiment_bar(icons): return "  ".join(icons)

# ══════════════════════════════════════════════════════════════════════════
# Telegram ارسال
# ══════════════════════════════════════════════════════════════════════════
def _tgapi(path: str) -> str:
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{path}"

async def tg_send_text(client: httpx.AsyncClient, text: str) -> bool:
    text = text[:MAX_MSG_LEN]
    for attempt in range(3):
        try:
            r = await client.post(_tgapi("sendMessage"),
                json={"chat_id": CHANNEL_ID, "text": text,
                      "parse_mode": "HTML", "disable_web_page_preview": False},
                timeout=httpx.Timeout(15.0))
            d = r.json()
            if r.status_code == 200 and d.get("ok"): return True
            if d.get("error_code") == 429:
                wait = d.get("parameters", {}).get("retry_after", 20)
                await asyncio.sleep(wait)
            elif attempt < 2:
                await asyncio.sleep(3)
        except Exception as e:
            log.warning(f"TG send: {e}")
            if attempt < 2: await asyncio.sleep(5)
    return False

async def tg_send_photo(client: httpx.AsyncClient, buf: io.BytesIO,
                         caption: str) -> bool:
    caption = caption[:1024]
    try:
        buf.seek(0)
        r = await client.post(_tgapi("sendPhoto"),
            data={"chat_id": CHANNEL_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("card.jpg", buf, "image/jpeg")},
            timeout=httpx.Timeout(20.0))
        return r.status_code == 200 and r.json().get("ok", False)
    except Exception as e:
        log.warning(f"TG photo: {e}"); return False

# ══════════════════════════════════════════════════════════════════════════
# PIL کارت خبری
# ══════════════════════════════════════════════════════════════════════════
BG_DARK  = (14, 16, 22)
BG_BAR   = (22, 26, 34)
FG_WHITE = (235, 237, 242)
FG_GREY  = (120, 132, 148)
ACCENT_MAP = {
    "🇮🇷":(180,40,40), "🇮🇱":(30,90,180), "🇺🇸":(40,80,160),
    "🔍":(60,130,80), "🌐":(100,60,130), "🏛️":(140,100,40),
}
ICON_BG = {
    "💀":(140,20,20),"🔴":(180,30,30),"💥":(190,80,10),
    "✈️":(20,90,160),"🚀":(100,20,160),"☢️":(0,130,50),
    "🚢":(10,80,140),"🕵️":(60,55,70),"🛡️":(20,110,80),
    "🔥":(180,60,0),"💰":(130,110,0),"⚠️":(160,110,0),
    "🤝":(20,120,100),"📜":(60,80,100),"📰":(45,58,72),
}

def _get_accent(src, urgent):
    if urgent: return (210, 40, 40)
    for k, v in ACCENT_MAP.items():
        if src.startswith(k) or k in src: return v
    return (80, 110, 140)

def _wrap(text, chars):
    words, lines_out, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= chars: cur = (cur + " " + w).strip()
        else:
            if cur: lines_out.append(cur)
            cur = w
    if cur: lines_out.append(cur)
    return lines_out

def _fonts():
    try:
        bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        reg  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        sm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        return bold, reg, sm
    except:
        d = ImageFont.load_default(); return d, d, d

def make_news_card(headline, fa_text, src, dt_str,
                   urgent=False, sentiment_icons=None):
    if not PIL_OK: return None
    try:
        W, H = 960, 310
        acc = _get_accent(src, urgent)
        img = Image.new("RGB", (W, H), BG_DARK)
        drw = ImageDraw.Draw(img)
        F_H, F_B, F_sm = _fonts()

        drw.rectangle([(0,0),(W,5)], fill=acc)
        drw.rectangle([(0,5),(W,58)], fill=BG_BAR)
        drw.rectangle([(0,58),(W,61)], fill=acc)
        drw.text((18,18), src[:55],     font=F_sm, fill=acc)
        drw.text((W-170,18), dt_str[:25], font=F_sm, fill=FG_GREY)

        display = fa_text if (fa_text and len(fa_text) > 5) else headline
        y = 72
        for line in _wrap(display, 50)[:4]:
            drw.text((W-18, y), line, font=F_H, fill=FG_WHITE, anchor="ra")
            y += 30

        drw.rectangle([(0,H-56),(W,H)], fill=BG_BAR)
        drw.rectangle([(0,H-58),(W,H-56)], fill=acc)
        x_pos = 16
        for ico in (sentiment_icons or ["📰"])[:4]:
            bg = ICON_BG.get(ico, (50,65,75))
            drw.rounded_rectangle([(x_pos-2,H-52),(x_pos+38,H-6)], radius=7, fill=bg)
            drw.text((x_pos+2,H-50), ico, font=F_H, fill=(255,255,255))
            x_pos += 50

        if urgent: drw.rectangle([(0,61),(5,H-58)], fill=acc)

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        buf.seek(0)
        return buf
    except Exception as e:
        log.debug(f"card: {e}"); return None

# Article fetcher برای خبرهای مهم
_ARTICLE_SEL = [
    "article","[class*='article-body']","[class*='story-body']",
    ".entry-content",".post-content","[itemprop='articleBody']",
]

async def fetch_article_text(client: httpx.AsyncClient, url: str) -> str:
    if not url or "t.me" in url: return ""
    try:
        r = await client.get(url, timeout=httpx.Timeout(7.0), headers=COMMON_UA,
                             follow_redirects=True)
        if r.status_code != 200: return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup.find_all(["script","style","nav","header","footer","aside"]):
            tag.decompose()
        for sel in _ARTICLE_SEL:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(" ", strip=True)
                if len(txt) > 150: return txt[:1000]
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p") if len(p.get_text()) > 60]
        return " ".join(paras)[:1000] if paras else ""
    except: return ""

# ══════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════
async def main():
    global _TW_SEMA
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID نیست!"); return

    # ── semaphore Twitter ─────────────────────────────────────────────
    _TW_SEMA = asyncio.Semaphore(20)  # ۲۰ handle همزمان

    # ── cutoff هوشمند ────────────────────────────────────────────────
    # = آخرین اجرا - BUFFER → فقط اخبار واقعاً تازه
    last_run   = load_run_state()
    cutoff     = last_run - timedelta(minutes=CUTOFF_BUFFER_MIN)
    # حداکثر MAX_LOOKBACK_MIN به عقب (برای اجرای اول / بعد از crash)
    max_cutoff = datetime.now(timezone.utc) - timedelta(minutes=MAX_LOOKBACK_MIN)
    cutoff     = max(cutoff, max_cutoff)

    seen    = load_seen()
    stories = load_stories()

    log.info("=" * 65)
    log.info(f"🚀 WarBot v17  |  {datetime.now(TEHRAN_TZ).strftime('%H:%M تهران')}")
    log.info(f"   📡 {len(ALL_RSS_FEEDS)} RSS  📢 {len(TELEGRAM_CHANNELS)} TG  𝕏 {len(TWITTER_HANDLES)} TW")
    log.info(f"   PIL:{'✅' if PIL_OK else '❌'}  seen:{len(seen)}")
    log.info(f"   ⏱ cutoff={cutoff.astimezone(TEHRAN_TZ).strftime('%H:%M')} تهران"
             f"  (last_run={last_run.astimezone(TEHRAN_TZ).strftime('%H:%M')})")
    log.info("=" * 65)

    limits = httpx.Limits(max_connections=100, max_keepalive_connections=30)
    async with httpx.AsyncClient(follow_redirects=True, limits=limits) as client:

        # ── ADS-B + fetch موازی ───────────────────────────────────────
        flight_task = asyncio.create_task(fetch_military_flights(client))
        raw_task    = asyncio.create_task(fetch_all(client, cutoff))
        flight_msgs, raw = await asyncio.gather(flight_task, raw_task)
        log.info(f"📥 {len(raw)} آیتم خام  ✈️ {len(flight_msgs)} تحرک")

        # ── پردازش ───────────────────────────────────────────────────
        collected = []
        sent_ids  = set()
        cnt_old = cnt_irrel = cnt_url = cnt_story = 0

        for entry, src_name, src_type, is_emb in raw:
            eid = make_id(entry)

            # لایه ۱: قبلاً ارسال شده؟
            if eid in seen:
                cnt_url += 1; continue

            # لایه ۲: در پنجره زمانی؟ (TG قبلاً فیلتر شده، RSS اینجا)
            if not is_fresh(entry, cutoff):
                cnt_old += 1; continue

            # لایه ۳: مرتبط با جنگ؟
            t    = clean_html(entry.get("title", ""))
            s    = clean_html(entry.get("summary") or entry.get("description") or "")
            full = f"{t} {s}"
            if not is_war_relevant(full, is_embassy=is_emb,
                                   is_tg=(src_type=="tg"), is_tw=(src_type=="tw")):
                cnt_irrel += 1; continue

            # لایه ۴: story تکراری؟
            if is_story_dup(t, stories):
                seen.add(eid)   # story-dup → به seen اضافه (برای هر run تکرار نشه)
                cnt_story += 1; continue

            collected.append((eid, entry, src_name, src_type, is_emb))
            stories = register_story(t, stories)

        log.info(
            f"📊 قدیمی:{cnt_old}  نامرتبط:{cnt_irrel}  "
            f"dup:{cnt_url}  story-dup:{cnt_story}  ✅ {len(collected)} خبر"
        )

        # قدیمی‌ترین اول، حداکثر MAX_NEW_PER_RUN
        collected = list(reversed(collected))
        if len(collected) > MAX_NEW_PER_RUN:
            log.warning(f"⚠️ {len(collected)} → {MAX_NEW_PER_RUN} (برش داده شد)")
            collected = collected[-MAX_NEW_PER_RUN:]

        # ── ADS-B ────────────────────────────────────────────────────
        for msg in flight_msgs[:3]:
            await tg_send_text(client, msg)
            await asyncio.sleep(0.5)

        if not collected:
            log.info("💤 خبر جنگی جدیدی نیست")
            save_seen(seen); save_stories(stories); save_run_state()
            return

        # ── ترجمه Gemini ──────────────────────────────────────────────
        arts_in = [
            (trim(clean_html(e.get("title", "")), 400),
             trim(clean_html(e.get("summary") or e.get("description") or ""), 600))
            for _, e, _, _, _ in collected
        ]
        if GEMINI_API_KEY:
            log.info(f"🌐 ترجمه {len(arts_in)} خبر...")
            translations = await translate_batch(client, arts_in)
        else:
            translations = arts_in

        # ── ارسال ─────────────────────────────────────────────────────
        sent = 0
        for i, (eid, entry, src_name, stype, is_emb) in enumerate(collected):
            fa, _    = translations[i]
            en_title = arts_in[i][0]
            en_body  = arts_in[i][1]
            link     = entry.get("link", "")
            dt_str   = format_dt(entry)
            display  = fa if (fa and fa != en_title and len(fa) > 5) else en_title
            urgent   = any(w in (fa + en_title).lower() for w in [
                "attack","strike","killed","bomb","explosion","nuclear",
                "حمله","کشته","انفجار","موشک","شهید","هسته‌ای",
            ])

            sentiment_icons = analyze_sentiment(f"{fa} {en_title} {en_body}")
            s_bar      = sentiment_bar(sentiment_icons)
            importance = calc_importance(en_title, en_body, sentiment_icons, stype)
            src_icon   = "🏛️" if is_emb else ("𝕏" if stype=="tw" else ("📢" if stype=="tg" else "📡"))

            log.info(f"  → [{stype}] imp={importance}  {en_title[:60]}")

            card_sent = False
            if PIL_OK:
                buf = make_news_card(en_title,
                                     fa if (fa and fa != en_title) else "",
                                     src_name, dt_str, urgent, sentiment_icons)
                if buf:
                    cap  = f"{s_bar}\n\n<b>{esc(display)}</b>"
                    # body فقط اگه اطلاعات اضافه دارد
                    if en_body and len(en_body) > 40 and en_body.lower() not in en_title.lower():
                        cap += f"\n\n<i>{esc(trim(en_body, 600))}</i>"
                    cap += f"\n\n{src_icon} <b>{esc(src_name)}</b>  {dt_str}"
                    if await tg_send_photo(client, buf, cap):
                        card_sent = True

            if not card_sent:
                parts = [s_bar, f"<b>{esc(display)}</b>"]
                if en_body and len(en_body) > 40 and en_body.lower() not in en_title.lower():
                    parts += ["", f"<i>{esc(trim(en_body, 700))}</i>"]
                parts += ["", f"─── {src_icon} <b>{esc(src_name)}</b>  {dt_str}"]
                if await tg_send_text(client, "\n".join(parts)):
                    card_sent = True

            if card_sent:
                sent_ids.add(eid); sent += 1
                log.info(f"    ✅ ارسال شد")
            await asyncio.sleep(SEND_DELAY)

        # فقط ارسال‌شده‌ها به seen
        seen.update(sent_ids)
        save_seen(seen); save_stories(stories); save_run_state()
        log.info(f"🏁 {sent}/{len(collected)} خبر  seen:{len(seen)}")


if __name__ == "__main__":
    asyncio.run(main())
