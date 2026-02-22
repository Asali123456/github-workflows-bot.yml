"""
╔══════════════════════════════════════════════════════════════════════════╗
║        🛡️ Military Intel Bot v11 — FULLY REBUILT                        ║
║                                                                          ║
║  ✅ Fix1: Nitter از status.d420.de — 8 instance کار‌کرده               ║
║  ✅ Fix2: خبرگزاری‌های ایرانی (IRNA, Tasnim, Mehr, Fars, PressTV...)   ║
║  ✅ Fix3: فیلتر سخت — فقط جنگ ایران-آمریکا-اسراییل                     ║
║  ✅ Fix4: ترجمه عامیانه و خلاصه به سبک تلگرام                           ║
║  ✅ Fix5: توییت خبرنگاران و سیاستمداران ایرانی                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os, json, hashlib, asyncio, logging, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser, httpx, pytz

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

SEEN_FILE         = "seen.json"
GEMINI_STATE_FILE = "gemini_state.json"
MAX_NEW_PER_RUN   = 20
MAX_MSG_LEN       = 4096
SEND_DELAY        = 2
TEHRAN_TZ         = pytz.timezone("Asia/Tehran")
CUTOFF_HOURS      = 6

def get_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)

# ════════════════════════════════════════════════════════════════
# ─── ✅ Fix2: خبرگزاری‌های ایرانی + بین‌المللی
# ════════════════════════════════════════════════════════════════
RSS_FEEDS = [

    # ══ خبرگزاری‌های ایرانی ══
    {"name": "🇮🇷 IRNA",              "url": "https://www.irna.ir/rss/",                            "lang": "fa"},
    {"name": "🇮🇷 IRNA English",      "url": "https://en.irna.ir/rss/",                             "lang": "en"},
    {"name": "🇮🇷 Tasnim",            "url": "https://www.tasnimnews.com/fa/rss/feed/0/8/0",        "lang": "fa"},
    {"name": "🇮🇷 Tasnim English",    "url": "https://www.tasnimnews.com/en/rss/feed/0/8/0",        "lang": "en"},
    {"name": "🇮🇷 Mehr Agency",       "url": "https://en.mehrnews.com/rss",                         "lang": "en"},
    {"name": "🇮🇷 Mehr فارسی",        "url": "https://www.mehrnews.com/rss",                        "lang": "fa"},
    {"name": "🇮🇷 Fars Agency",       "url": "https://www.farsnews.ir/rss",                         "lang": "fa"},
    {"name": "🇮🇷 Fars English",      "url": "https://en.farsnews.ir/rss",                          "lang": "en"},
    {"name": "🇮🇷 Press TV",          "url": "https://www.presstv.ir/rss",                          "lang": "en"},
    {"name": "🇮🇷 Iran International","url": "https://www.iranintl.com/en/rss",                     "lang": "en"},
    {"name": "🇮🇷 Radio Farda",       "url": "https://www.radiofarda.com/api/zoyqvpemr",            "lang": "fa"},
    {"name": "🇮🇷 Nour News",         "url": "https://www.nournews.ir/fa/rss/",                     "lang": "fa"},

    # ══ اسراییل ══
    {"name": "🇮🇱 Jerusalem Post",    "url": "https://www.jpost.com/rss/rssfeedsheadlines.aspx",    "lang": "en"},
    {"name": "🇮🇱 Times of Israel",   "url": "https://www.timesofisrael.com/feed/",                 "lang": "en"},
    {"name": "🇮🇱 Israel Hayom",      "url": "https://www.israelhayom.com/feed/",                   "lang": "en"},
    {"name": "🇮🇱 Arutz Sheva",       "url": "https://www.israelnationalnews.com/rss.aspx",         "lang": "en"},
    {"name": "🇮🇱 i24 News",          "url": "https://www.i24news.tv/en/rss",                       "lang": "en"},
    {"name": "🇮🇱 Haaretz (GNews)",   "url": "https://news.google.com/rss/search?q=site:haaretz.com+iran+israel+war+military&hl=en-US&gl=US&ceid=US:en", "lang": "en"},
    {"name": "🇮🇱 IDF (GNews)",       "url": "https://news.google.com/rss/search?q=IDF+Israel+Defense+Forces+operation+strike+iran&hl=en-US&gl=US&ceid=US:en", "lang": "en"},

    # ══ آمریکا/بین‌الملل ══
    {"name": "🌐 Reuters World",      "url": "https://feeds.reuters.com/reuters/worldNews",         "lang": "en"},
    {"name": "🌐 AP Military",        "url": "https://apnews.com/hub/military-and-defense?format=rss", "lang": "en"},
    {"name": "🌐 AP World",           "url": "https://feeds.apnews.com/rss/apf-WorldNews",          "lang": "en"},
    {"name": "🌐 BBC Middle East",    "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml", "lang": "en"},
    {"name": "🌐 Al Jazeera",         "url": "https://www.aljazeera.com/xml/rss/all.xml",           "lang": "en"},
    {"name": "🌐 CNN Middle East",    "url": "http://rss.cnn.com/rss/edition_meast.rss",            "lang": "en"},
    {"name": "🌐 Fox News World",     "url": "https://moxie.foxnews.com/google-publisher/world.xml", "lang": "en"},
    {"name": "🌐 Middle East Eye",    "url": "https://www.middleeasteye.net/rss",                   "lang": "en"},
    {"name": "🌐 Bloomberg Politics", "url": "https://feeds.bloomberg.com/politics/news.rss",       "lang": "en"},
    {"name": "🌐 Foreign Policy",     "url": "https://foreignpolicy.com/feed/",                     "lang": "en"},
    {"name": "🌐 Politico NatSec",   "url": "https://rss.politico.com/defense.xml",                "lang": "en"},
    {"name": "🇺🇸 Breaking Defense",  "url": "https://breakingdefense.com/feed/",                   "lang": "en"},
    {"name": "🇺🇸 USNI News",         "url": "https://news.usni.org/feed",                          "lang": "en"},
    {"name": "🇺🇸 Defense News",      "url": "https://www.defensenews.com/arc/outboundfeeds/rss/",  "lang": "en"},
    {"name": "🇺🇸 The War Zone",      "url": "https://www.twz.com/feed",                            "lang": "en"},
    {"name": "🔍 Long War Journal",   "url": "https://www.longwarjournal.org/feed",                 "lang": "en"},
    {"name": "🔍 Bellingcat",         "url": "https://www.bellingcat.com/feed/",                    "lang": "en"},
    {"name": "🔍 OSINT Defender",     "url": "https://osintdefender.com/feed/",                     "lang": "en"},
    {"name": "🇸🇦 Al-Monitor ME",     "url": "https://news.google.com/rss/search?q=site:al-monitor.com+iran+israel+us+military&hl=en-US&gl=US&ceid=US:en", "lang": "en"},
]

# ════════════════════════════════════════════════════════════════
# Google News — جستجوهای هدفمند جنگ
# ════════════════════════════════════════════════════════════════
WAR_QUERIES = [
    ("⚔️ Iran Israel War",     "Iran Israel war attack strike"),
    ("⚔️ Iran US Military",    "United States Iran military attack"),
    ("⚔️ IRGC Strike",         "IRGC Revolutionary Guard attack strike"),
    ("⚔️ IDF Iran",            "IDF airstrike Iran nuclear"),
    ("⚔️ Iran Nuclear",        "Iran nuclear IAEA uranium fordo natanz"),
    ("⚔️ Iran Missile",        "Iran ballistic missile drone attack"),
    ("⚔️ Hezbollah War",       "Hezbollah IDF Lebanon war"),
    ("⚔️ US Base Attack",      "US military base Iraq Syria Iran attack"),
    ("⚔️ Strait Hormuz",       "Strait Hormuz tanker seized navy"),
    ("⚔️ Red Sea Houthis",     "Red Sea Houthi Yemen attack ship"),
    ("⚔️ Iran Sanctions War",  "Iran sanctions military war escalation"),
    ("⚔️ Gaza War 2026",       "Gaza Hamas IDF war 2026"),
    ("⚔️ Iran Proxy",          "Iran proxy militia attack US Israel"),
    ("⚔️ جنگ ایران اسراییل",   "جنگ ایران اسراییل آمریکا حمله"),
    ("⚔️ Iran Trump War",      "Trump Iran Israel military war threat"),
]

def gnews(q):
    return f"https://news.google.com/rss/search?q={q.replace(' ','+')}&hl=en-US&gl=US&ceid=US:en&num=15"

WAR_FEEDS = [{"name": n, "url": gnews(q)} for n, q in WAR_QUERIES]

# ════════════════════════════════════════════════════════════════
# ─── ✅ Fix1: Nitter — 8 instance کار‌کرده از status.d420.de
# ════════════════════════════════════════════════════════════════
# منبع: https://status.d420.de (تأیید شده ۲۲ فوریه ۲۰۲۶)
NITTER_INSTANCES = [
    "https://xcancel.com",               # ✅ US — بهترین
    "https://nitter.poast.org",          # ✅ US
    "https://nitter.privacyredirect.com",# ✅ Finland
    "https://nitter.tiekoetter.com",     # ✅ Germany
    "https://lightbrd.com",              # ✅ Turkey
    "https://nitter.space",              # ✅ US
    "https://nuku.trabun.org",           # ✅ Chile
    "https://nitter.catsarch.com",       # ✅ US/Germany
]

# ════════════════════════════════════════════════════════════════
# ─── ✅ Fix5: خبرنگاران و سیاستمداران — ایران + آمریکا + اسراییل
# ════════════════════════════════════════════════════════════════
TWITTER_ACCOUNTS = [

    # ── ایران — رسمی و سیاسی ──
    ("🇮🇷 باقری‌کنی",           "Bagheri_Kani",    "ir"),   # مذاکره‌کننده هسته‌ای
    ("🇮🇷 سخنگوی سپاه",         "IRGC_PRGC",       "ir"),   # سپاه
    ("🇮🇷 وزارت خارجه ایران",   "IRIMFA",          "ir"),   # وزارت خارجه
    ("🇮🇷 Press TV",             "PressTV",         "ir"),
    ("🇮🇷 IRNA English",         "IrnaEnglish",     "ir"),
    ("🇮🇷 Tasnim News",          "tasnimna",        "ir"),
    ("🇮🇷 Iran Intl English",    "IranIntl_En",     "ir"),
    ("🇮🇷 Nour News",            "NourNews_Ir",     "ir"),
    ("🇮🇷 رضا نصری",             "rezanasri",       "ir"),   # تحلیلگر حقوق بین‌الملل
    ("🇮🇷 هوشنگ امیراحمدی",     "hosseinami",      "ir"),   # استاد روابط بین‌الملل

    # ── اسراییل — رسمی و نظامی ──
    ("🇮🇱 IDF Official",         "IDF",             "il"),
    ("🇮🇱 یوآو گالانت",          "yoavgallant",    "il"),   # وزیر دفاع سابق
    ("🇮🇱 ست فرانتزمن",          "sfrantzman",      "il"),   # Jerusalem Post دفاع
    ("🇮🇱 یوسی ملمن",            "yossi_melman",    "il"),   # موساد/اطلاعات
    ("🇮🇱 آوی ایساخاروف",        "AviIssacharoff",  "il"),   # تحلیلگر نظامی
    ("🇮🇱 بن کاسپیت",            "BenCaspit",       "il"),   # تحلیلگر

    # ── آمریکا — رسمی ──
    ("🇺🇸 CENTCOM",              "CENTCOM",         "us"),
    ("🇺🇸 Dept of Defense",      "DeptofDefense",   "us"),
    ("🇺🇸 NatashaBertrand",      "NatashaBertrand", "us"),   # CNN امنیت ملی
    ("🇺🇸 Helene Cooper",        "helenecooper",    "us"),   # NYT Pentagon
    ("🇺🇸 Farnaz Fassihi",       "farnazfassihi",   "us"),   # NYT ایران
    ("🇺🇸 Barak Ravid",          "BarakRavid",      "us"),   # Axios اسراییل

    # ── OSINT / اطلاعات ──
    ("🔍 OSINT Defender",        "OSINTdefender",   "osint"),
    ("🔍 Intel Crab",            "IntelCrab",       "osint"),
    ("🔍 War Monitor",           "WarMonitor3",     "osint"),
    ("🔍 Conflicts.media",       "Conflicts",       "osint"),
    ("🔍 Aurora Intel",          "AuroraIntel",     "osint"),
    ("🔍 GeoConfirmed",          "GeoConfirmed",    "osint"),

    # ── خبرنگاران برتر ──
    ("📰 Idrees Ali (Reuters)",  "idreesali114",    "reporter"),  # Pentagon
    ("📰 Phil Stewart (Reuters)","phil_stewart_",   "reporter"),
    ("📰 Jack Detsch (FP)",      "JackDetsch",      "reporter"),
    ("📰 Joyce Karam (Arab News)","Joyce_Karam",    "reporter"),

    # ── هشدار ──
    ("⚠️ DEFCON Level",          "DEFCONLevel",     "alert"),
    ("⚠️ Arms Control Wonk",     "ArmsControlWonk", "alert"),
]

def get_nitter_feeds() -> list[dict]:
    feeds = []
    for name, handle, country in TWITTER_ACCOUNTS:
        # همه instances به عنوان fallback
        urls = [f"{inst}/{handle}/rss" for inst in NITTER_INSTANCES]
        feeds.append({
            "name":    f"𝕏 {name}",
            "handle":  handle,
            "country": country,
            "urls":    urls,
            "is_twitter": True,
        })
    return feeds

NITTER_FEEDS = get_nitter_feeds()
ALL_FEEDS    = RSS_FEEDS + WAR_FEEDS

# ════════════════════════════════════════════════════════════════
# ─── ✅ Fix3: فیلتر سخت — فقط جنگ ایران-آمریکا-اسراییل
# ════════════════════════════════════════════════════════════════
# باید حداقل یک کلمه از هر گروه وجود داشته باشد

# گروه ایران
IRAN_KW = {"iran","irgc","tehran","khamenei","sepah","سپاه","ایران","تهران","خامنه‌ای",
           "revolutionary guard","مقاومت","حشدالشعبی","حزب‌الله","حوثی",
           "نطنز","فردو","هسته‌ای","enrichment","natanz","fordo","iaea","nuclear",
           "hezbollah","houthi","ansarallah","hamas","فلسطین"}

# گروه آمریکا
US_KW = {"us ","usa","america","american","pentagon","centcom","us forces","us military",
         "us base","trump","rubio","آمریکا","امریکا","واشنگتن","پنتاگون","ترامپ",
         "white house","state department","secretary"}

# گروه اسراییل
ISRAEL_KW = {"israel","idf","mossad","netanyahu","tel aviv","اسراییل","اسرائیل","نتانیاهو",
             "mos","haifa","jerusalem","اورشلیم","تل‌آویو","صهیونیست","صهیونیسم"}

# کلمات جنگی — حتماً باید یکی از اینها باشد
WAR_KW = {"attack","strike","airstrike","missile","bomb","war","military","operation",
          "sanction","nuclear","drone","uav","حمله","حمله هوایی","موشک","جنگ","عملیات",
          "بمب","تحریم","نظامی","پهپاد","explosion","kill","assassin","نظامی","artillery",
          "escalat","deploy","troops","force","rocket","shell","invasion","blockade",
          "threat","ultimatum","siege","seized","seized","intercept","intercept"}

def is_war_relevant(entry: dict, is_twitter: bool = False) -> bool:
    """فیلتر سخت: باید جنگ بین ایران-آمریکا-اسراییل باشد"""
    text = " ".join([
        str(entry.get("title",   "")),
        str(entry.get("summary", "")),
        str(entry.get("description", "")),
    ]).lower()

    # حداقل یکی از هر طرف
    has_iran   = any(k in text for k in IRAN_KW)
    has_us     = any(k in text for k in US_KW)
    has_israel = any(k in text for k in ISRAEL_KW)
    has_war    = any(k in text for k in WAR_KW)

    if not has_war:
        return False

    # باید حداقل ۲ طرف از ۳ درگیر باشند
    sides = sum([has_iran, has_us, has_israel])
    if sides >= 2:
        return True

    # یا حداقل یک طرف با کلمه جنگی بسیار قوی
    if is_twitter and has_iran and has_war:
        return True
    if sides == 1 and has_war:
        # برای منابع ایرانی/اسراییلی، یک طرف کافیه
        source_name = entry.get("_source_name", "")
        if "ایران" in source_name or "Iran" in source_name or "Israel" in source_name:
            return True

    return False

def is_fresh(entry: dict) -> bool:
    cutoff = get_cutoff()
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t: return False
        return datetime(*t[:6], tzinfo=timezone.utc) >= cutoff
    except:
        return False

# ════════════════════════════════════════════════════════════════
# دریافت RSS
# ════════════════════════════════════════════════════════════════
async def fetch_one_rss(client: httpx.AsyncClient, cfg: dict) -> list:
    try:
        r = await client.get(cfg["url"], timeout=httpx.Timeout(12.0),
                             headers={"User-Agent": "Mozilla/5.0 MilNewsBot/11.0"})
        if r.status_code == 200:
            entries = feedparser.parse(r.text).entries
            for e in entries:
                e["_source_name"] = cfg["name"]
            return entries or []
    except: pass
    return []

# ════════════════════════════════════════════════════════════════
# ─── ✅ Fix1: Nitter با 8 instance fallback
# ════════════════════════════════════════════════════════════════
async def fetch_one_nitter(client: httpx.AsyncClient, cfg: dict) -> list:
    """تست هر instance به ترتیب — اولی که جواب داد کافیه"""
    for url in cfg["urls"]:
        try:
            r = await client.get(url, timeout=httpx.Timeout(10.0),
                                 headers={"User-Agent": "Mozilla/5.0 MilNewsBot/11.0"})
            if r.status_code == 200:
                entries = feedparser.parse(r.text).entries
                if entries:
                    log.debug(f"  𝕏 {cfg['handle']} ← {url.split('/')[2]}")
                    for e in entries:
                        e["_source_name"] = cfg["name"]
                    return entries
        except: continue
    return []

async def fetch_all(client: httpx.AsyncClient) -> list:
    # RSS + GNews همزمان
    rss_tasks = [fetch_one_rss(client, cfg) for cfg in ALL_FEEDS]
    rss_results = await asyncio.gather(*rss_tasks, return_exceptions=True)

    out = []
    for i, res in enumerate(rss_results):
        if isinstance(res, list):
            for entry in res:
                out.append((entry, ALL_FEEDS[i], False))

    # Nitter همزمان
    tw_tasks = [fetch_one_nitter(client, cfg) for cfg in NITTER_FEEDS]
    tw_results = await asyncio.gather(*tw_tasks, return_exceptions=True)

    tw_ok = 0
    for i, res in enumerate(tw_results):
        if isinstance(res, list) and res:
            tw_ok += 1
            for entry in res:
                out.append((entry, NITTER_FEEDS[i], True))

    log.info(f"  𝕏 Nitter: {tw_ok}/{len(NITTER_FEEDS)} اکانت موفق")
    return out

# ════════════════════════════════════════════════════════════════
# ─── ✅ Fix4: Gemini — خلاصه عامیانه + multi-model rotation
# ════════════════════════════════════════════════════════════════
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

GEMINI_MODEL_POOL = [
    {"id": "gemini-2.5-flash-lite",               "rpm": 15, "rpd": 1000, "tier": 1, "label": "Lite"},
    {"id": "gemini-2.5-flash-lite-preview-09-2025","rpm": 15, "rpd": 1000, "tier": 1, "label": "Lite-Preview"},
    {"id": "gemini-2.5-flash",                     "rpm": 10, "rpd":  250, "tier": 2, "label": "Flash"},
    {"id": "gemini-2.5-flash-preview-09-2025",     "rpm": 10, "rpd":  250, "tier": 2, "label": "Flash-Preview"},
    {"id": "gemini-3-flash-preview",               "rpm": 10, "rpd":  100, "tier": 3, "label": "G3-Flash"},
    {"id": "gemini-2.5-pro",                       "rpm":  5, "rpd":  100, "tier": 3, "label": "Pro"},
    {"id": "gemini-3-pro-preview",                 "rpm":  5, "rpd":   50, "tier": 3, "label": "G3-Pro"},
]

def load_gstate() -> dict:
    try:
        if Path(GEMINI_STATE_FILE).exists():
            s = json.load(open(GEMINI_STATE_FILE))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if s.get("date") != today:
                return _fresh_gstate(today)
            return s
    except: pass
    return _fresh_gstate(datetime.now(timezone.utc).strftime("%Y-%m-%d"))

def _fresh_gstate(today):
    return {"date": today, "usage": {m["id"]: 0 for m in GEMINI_MODEL_POOL},
            "failures": {m["id"]: 0 for m in GEMINI_MODEL_POOL}}

def save_gstate(s):
    with open(GEMINI_STATE_FILE, "w") as f: json.dump(s, f)

def pick_models(state: dict) -> list:
    ordered = []
    for tier in [1, 2, 3]:
        for m in GEMINI_MODEL_POOL:
            if m["tier"] == tier:
                rem = m["rpd"] - state["usage"].get(m["id"], 0)
                fails = state["failures"].get(m["id"], 0)
                if rem > 0 and fails < 3:
                    ordered.append(m)
    return ordered or GEMINI_MODEL_POOL

# ════════════════════════════════════════════════════════════════
# ✅ Fix4: Prompt جدید — خلاصه عامیانه به سبک تلگرام
# ════════════════════════════════════════════════════════════════
# مثال‌های واقعی برای هدایت مدل:
PROMPT_EXAMPLES = """
مثال ورودی:
  TITLE: IDF strikes Iranian weapons depot in Syria, killing 3 IRGC advisors
  BODY: Israeli forces carried out a series of airstrikes...

مثال خروجی:
  عنوان: 💥 اسراییل انبار تسلیحاتی سپاه در سوریه رو زد، ۳ مستشار کشته شدن
  خبر: ارتش اسراییل امشب چند تا هوایی زد تو سوریه و یه انبار اسلحه وابسته به سپاه رو منهدم کرد. ۳ نفر از مستشاران سپاه کشته شدن. این اتفاق بعد از...
"""

def build_prompt(articles: list[tuple[str, str]]) -> str:
    items = ""
    for i, (title, body) in enumerate(articles):
        items += f"###ITEM_{i}###\nTITLE: {title[:350]}\nBODY: {body[:450]}\n"

    return f"""تو یه خبرنگار ایرانی هستی که اخبار جنگ ایران-آمریکا-اسراییل رو برای کانال تلگرامی خلاصه می‌کنی.

سبک نوشتار:
- زبان عامیانه و روان فارسی (نه رسمی و سنگین)
- مثل یه دوست خبرنگار که داری بهش پیام می‌دی
- کوتاه و مستقیم، بدون مقدمه‌چینی
- اسامی مهم رو حفظ کن: نتانیاهو، خامنه‌ای، ترامپ، سپاه، ناتو، سنتکام...
- اعداد و آمار مهم رو ذکر کن

{PROMPT_EXAMPLES}

حالا {len(articles)} خبر زیر رو خلاصه کن:
فرمت دقیق:
###ITEM_0###
عنوان: [عنوان کوتاه با ایموجی مناسب]
خبر: [خلاصه ۲-۳ جمله عامیانه]
###ITEM_1###
عنوان: [...]
خبر: [...]

===
{items}"""

async def summarize_batch(client: httpx.AsyncClient,
                          articles: list[tuple[str,str]]) -> list[tuple[str,str]]:
    if not GEMINI_API_KEY or not articles:
        return articles

    prompt  = build_prompt(articles)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192}
    }

    state      = load_gstate()
    candidates = pick_models(state)

    for model in candidates:
        mid   = model["id"]
        label = model["label"]
        used  = state["usage"].get(mid, 0)
        rem   = model["rpd"] - used
        url   = f"{GEMINI_BASE}/{mid}:generateContent?key={GEMINI_API_KEY}"

        log.info(f"🌐 Gemini [{label}] — quota: {used}/{model['rpd']} ({rem} مانده)")

        for attempt in range(2):
            try:
                r = await client.post(url, json=payload, timeout=httpx.Timeout(90.0))

                if r.status_code == 200:
                    raw    = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    result = _parse_summary(raw, articles)
                    ok     = sum(1 for i,x in enumerate(result) if x != articles[i])
                    log.info(f"✅ [{label}]: {ok}/{len(articles)} خبر خلاصه شد")
                    state["usage"][mid]    = used + 1
                    state["failures"][mid] = 0
                    save_gstate(state)
                    return result

                elif r.status_code == 429:
                    retry = r.headers.get("Retry-After","")
                    wait  = int(retry) if retry.isdigit() else 20
                    log.warning(f"⏳ [{label}] 429 — {wait}s → مدل بعدی")
                    state["failures"][mid] = state["failures"].get(mid,0) + 1
                    await asyncio.sleep(min(wait, 15))
                    break

                elif r.status_code in (500, 503):
                    await asyncio.sleep(10)

                else:
                    log.warning(f"[{label}] HTTP {r.status_code}")
                    break

            except asyncio.TimeoutError:
                log.warning(f"⏳ [{label}] timeout")
                break
            except Exception as e:
                log.debug(f"[{label}]: {e}")
                break

    save_gstate(state)
    log.warning("⚠️ همه مدل‌ها شکست — متن اصلی")
    return articles

def _parse_summary(raw: str, fallback: list) -> list:
    results = list(fallback)
    pattern = re.compile(
        r'###ITEM_(\d+)###\s*\n'
        r'(?:عنوان|title)\s*:\s*(.+?)\s*\n'
        r'(?:خبر|body|text|متن)\s*:\s*(.+?)(?=###ITEM_|\Z)',
        re.IGNORECASE | re.DOTALL
    )
    for m in pattern.finditer(raw):
        idx  = int(m.group(1))
        fa_t = m.group(2).strip().replace("**","").replace("*","")
        fa_s = m.group(3).strip().replace("**","").replace("*","")
        if 0 <= idx < len(results) and fa_t:
            results[idx] = (nfa(fa_t), nfa(fa_s))
    return results

# ════════════════════════════════════════════════════════════════
# ابزارها
# ════════════════════════════════════════════════════════════════
def clean_html(t):
    if not t: return ""
    return BeautifulSoup(str(t), "html.parser").get_text(" ", strip=True)

def make_id(entry):
    key = entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(key.encode()).hexdigest()

def make_title_id(title):
    t = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', title.lower())
    return "t:" + hashlib.md5(t[:200].encode()).hexdigest()

def format_dt(entry):
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).astimezone(TEHRAN_TZ).strftime("🕐 %H:%M  |  📅 %Y/%m/%d")
    except: pass
    return ""

def esc(t): return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def trim(t, n):
    t = re.sub(r'\s+', ' ', t).strip()
    return t if len(t)<=n else t[:n].rsplit(" ",1)[0]+"…"

def load_seen():
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f: return set(json.load(f))
        except: pass
    return set()

def save_seen(seen):
    with open(SEEN_FILE,"w") as f: json.dump(list(seen)[-15000:], f)

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
                await asyncio.sleep(data.get("parameters",{}).get("retry_after",20))
            elif data.get("error_code") in (400,403):
                log.error(f"TG: {data.get('description')}"); return False
            else: await asyncio.sleep(5)
        except Exception as e:
            log.warning(f"TG: {e}"); await asyncio.sleep(8)
    return False

# ════════════════════════════════════════════════════════════════
# حلقه اصلی
# ════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID تنظیم نشده!"); return

    seen   = load_seen()
    cutoff = get_cutoff()
    log.info(f"🚀 {len(ALL_FEEDS)} RSS/GNews + {len(NITTER_FEEDS)} Nitter")
    log.info(f"📅 Cutoff: {CUTOFF_HOURS}h ({cutoff.astimezone(TEHRAN_TZ).strftime('%H:%M تهران')} به بعد)")
    log.info(f"💾 حافظه: {len(seen)} خبر قبلی")

    async with httpx.AsyncClient(follow_redirects=True) as client:

        # مرحله ۱: دریافت
        log.info("⏬ دریافت همزمان...")
        raw = await fetch_all(client)
        log.info(f"📥 {len(raw)} آیتم خام")

        # مرحله ۲: فیلتر سخت
        collected  = []
        title_seen = set()
        old_cnt = irrel_cnt = dup_cnt = 0

        for entry, cfg, is_tw in raw:
            eid = make_id(entry)
            if eid in seen: continue

            if not is_fresh(entry):
                seen.add(eid); old_cnt += 1; continue

            if not is_war_relevant(entry, is_twitter=is_tw):
                seen.add(eid); irrel_cnt += 1; continue

            raw_title = clean_html(entry.get("title",""))
            tid = make_title_id(raw_title)
            if tid in title_seen:
                seen.add(eid); dup_cnt += 1; continue

            title_seen.add(tid)
            collected.append((eid, entry, cfg, is_tw))

        log.info(f"📊 {old_cnt} قدیمی | {irrel_cnt} نامرتبط | {dup_cnt} تکراری | ✅ {len(collected)} جنگی")

        collected = list(reversed(collected))
        if len(collected) > MAX_NEW_PER_RUN:
            collected = collected[-MAX_NEW_PER_RUN:]

        if not collected:
            log.info("💤 هیچ خبر جنگی جدیدی نیست")
            save_seen(seen); return

        # مرحله ۳: خلاصه‌سازی دسته‌ای
        articles_in = []
        for eid, entry, cfg, is_tw in collected:
            en_t = trim(clean_html(entry.get("title","")), 300)
            en_s = trim(clean_html(entry.get("summary") or entry.get("description") or ""), 500)
            articles_in.append((en_t, en_s))

        log.info(f"📝 خلاصه‌سازی {len(articles_in)} خبر...")
        summaries = await summarize_batch(client, articles_in)

        # مرحله ۴: ارسال
        sent = 0
        for i, (eid, entry, cfg, is_tw) in enumerate(collected):
            en_title      = articles_in[i][0]
            fa_title, fa_body = summaries[i]
            link = entry.get("link","")
            dt   = format_dt(entry)
            icon = "𝕏" if is_tw else "📡"

            lines = [f"🔴 <b>{esc(fa_title)}</b>", ""]
            if fa_body and len(fa_body)>10:
                lines += [esc(fa_body), ""]
            lines.append("─────────────")
            if dt:   lines.append(dt)
            lines.append(f"{icon} <b>{cfg['name']}</b>")
            if link: lines.append(f'🔗 <a href="{link}">منبع</a>')

            if await tg_send(client, "\n".join(lines)):
                seen.add(eid); sent += 1
                log.info(f"  ✅ {fa_title[:55]}")
            else:
                log.error("  ❌ ارسال ناموفق")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"🏁 پایان | {sent}/{len(collected)} خبر ارسال شد")

if __name__ == "__main__":
    asyncio.run(main())
