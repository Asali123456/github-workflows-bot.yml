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
RUN_STATE_FILE    = "run_state.json"
NITTER_CACHE_FILE = "nitter_cache.json"

# ── زمان‌بندی و حلقه دائمی ─────────────────────────────────────────────────
CUTOFF_BUFFER_MIN  = 4    # overlap — چند دقیقه قبل از آخرین اجرا نگاه کن
MAX_LOOKBACK_MIN   = 90   # حداکثر برگشت (برای اولین اجرا / crash)
SEEN_TTL_HOURS     = 6
NITTER_CACHE_TTL   = 900

LOOP_INTERVAL_SEC  = 60   # هر ۶۰ ثانیه — کافی برای fetch همه منابع
# در GitHub Actions: bot را ۳۵۰ دقیقه اجرا کن، Actions هر ۶ ساعت restart می‌کند
# برای اجرای محلی (CI=False): بی‌نهایت
_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
BOT_MAX_RUNTIME_MIN = 350 if _CI else 99999

MAX_NEW_PER_RUN    = 50   # هر چرخه حداکثر ۵۰ خبر
MAX_MSG_LEN        = 4096
SEND_DELAY         = 0.3
JACCARD_THRESHOLD  = 0.62  # آزاد — فقط خبرهای تقریباً یکسان رد شوند
MAX_STORIES        = 150   # کمتر = dedup محدودتر = خبر بیشتر
RSS_TIMEOUT        = 8.0
TG_TIMEOUT         = 10.0
TW_TIMEOUT         = 6.0
RICH_CARD_THRESHOLD = 5

TEHRAN_TZ = pytz.timezone("Asia/Tehran")

# ══════════════════════════════════════════════════════════════════════════
# منابع RSS — Feb 27 2026 — مذاکرات ژنو دور سوم / آستانه جنگ
# ══════════════════════════════════════════════════════════════════════════

IRAN_FEEDS = [
    # ─── فارسی ─────────────────────────────────────────────────────────
    {"n":"🇮🇷 ایرنا",          "u":"https://www.irna.ir/rss"},
    {"n":"🇮🇷 تسنیم",         "u":"https://www.tasnimnews.com/fa/rss/feed/0/8/0"},
    {"n":"🇮🇷 مهر",           "u":"https://www.mehrnews.com/rss"},
    {"n":"🇮🇷 فارس",          "u":"https://www.farsnews.ir/rss/fa"},
    {"n":"🇮🇷 مشرق",          "u":"https://www.mashreghnews.ir/rss"},
    {"n":"🇮🇷 دفاع پرس",      "u":"https://www.defapress.ir/fa/rss"},
    {"n":"🇮🇷 YJC",           "u":"https://www.yjc.ir/fa/rss/allnews"},
    # ─── انگلیسی ───────────────────────────────────────────────────────
    {"n":"🇮🇷 IRNA EN",       "u":"https://en.irna.ir/rss"},
    {"n":"🇮🇷 Mehr EN",       "u":"https://en.mehrnews.com/rss"},
    {"n":"🇮🇷 Tasnim EN",     "u":"https://www.tasnimnews.com/en/rss/feed/0/8/0"},
    {"n":"🇮🇷 Press TV",      "u":"https://www.presstv.ir/rss"},
    {"n":"🇮🇷 Tehran Times",  "u":"https://www.tehrantimes.com/rss"},
    {"n":"🇮🇷 Iran Intl EN",  "u":"https://www.iranintl.com/en/rss"},
    {"n":"🇮🇷 Iran Wire",     "u":"https://iranwire.com/en/feed/"},
    {"n":"🇮🇷 Radio Farda",   "u":"https://en.radiofarda.com/api/zqpqetrruqo"},
    # ─── Google News فارسی — امروز ─────────────────────────────────────
    {"n":"📰 GN ژنو امروز",   "u":"https://news.google.com/rss/search?q=ایران+مذاکرات+ژنو+عراقچی+ویتکوف&hl=fa&gl=IR&ceid=IR:fa&num=15&tbs=qdr:d"},
    {"n":"📰 GN سپاه امروز",  "u":"https://news.google.com/rss/search?q=سپاه+پاسداران+حمله+موشک+هسته‌ای&hl=fa&gl=IR&ceid=IR:fa&num=10&tbs=qdr:d"},
    {"n":"📰 GN اعتراض ایران","u":"https://news.google.com/rss/search?q=اعتراضات+ایران+سرکوب+خامنه‌ای+۱۴۰۴&hl=fa&gl=IR&ceid=IR:fa&num=10&tbs=qdr:d"},
]

ISRAEL_FEEDS = [
    {"n":"🇮🇱 Times of Israel","u":"https://www.timesofisrael.com/feed/"},
    {"n":"🇮🇱 Jerusalem Post", "u":"https://rss.jpost.com/rss/rssfeedsheadlines"},
    {"n":"🇮🇱 Haaretz EN",     "u":"https://www.haaretz.com/srv/haaretz-latest-articles.rss"},
    {"n":"🇮🇱 Israel Hayom",   "u":"https://www.israelhayom.com/feed/"},
    {"n":"🇮🇱 i24 News",       "u":"https://www.i24news.tv/en/rss"},
    # ─── Google News انگلیسی ────────────────────────────────────────────
    {"n":"📰 GN Netanyahu",   "u":"https://news.google.com/rss/search?q=Netanyahu+Iran+nuclear+deal+war+2026&hl=en-US&gl=US&ceid=US:en&num=15&tbs=qdr:d"},
    {"n":"📰 GN IDF Iran",    "u":"https://news.google.com/rss/search?q=IDF+Israel+Iran+strike+military&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
]

USA_FEEDS = [
    # ─── خبرگزاری‌ها ───────────────────────────────────────────────────
    {"n":"🇺🇸 AP World",        "u":"https://apnews.com/hub/world-news.rss"},
    {"n":"🇺🇸 AP Middle East",  "u":"https://apnews.com/hub/middle-east.rss"},
    {"n":"🇺🇸 AP Nuclear",      "u":"https://apnews.com/hub/nuclear-weapons.rss"},
    {"n":"🇺🇸 NBC World",       "u":"https://feeds.nbcnews.com/feeds/worldnews"},
    {"n":"🇺🇸 PBS NewsHour",    "u":"https://www.pbs.org/newshour/feed"},
    # ─── نظامی/دفاعی ────────────────────────────────────────────────────
    {"n":"🇺🇸 USNI News",       "u":"https://news.usni.org/feed"},
    {"n":"🇺🇸 Breaking Defense","u":"https://breakingdefense.com/feed/"},
    {"n":"🇺🇸 The War Zone",    "u":"https://www.twz.com/feed"},
    {"n":"🇺🇸 Defense News",    "u":"https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"n":"🇺🇸 Stars & Stripes", "u":"https://www.stripes.com/rss/arc/outboundfeeds/news/"},
    {"n":"🇺🇸 CTP-ISW Iran",    "u":"https://www.criticalthreats.org/feed"},
    {"n":"🇺🇸 Long War Journal","u":"https://www.longwarjournal.org/feed"},
    # ─── تحلیل/سیاست ─────────────────────────────────────────────────────
    {"n":"🇺🇸 Foreign Policy",  "u":"https://foreignpolicy.com/feed/"},
    {"n":"🇺🇸 CFR",             "u":"https://www.cfr.org/rss/feeds/news.xml"},
    {"n":"🇺🇸 Axios World",     "u":"https://api.axios.com/feed/"},
    # ─── Google News — بحران امروز ─────────────────────────────────────
    {"n":"📰 GN Witkoff Geneva","u":"https://news.google.com/rss/search?q=Witkoff+Kushner+Iran+nuclear+Geneva+talks&hl=en-US&gl=US&ceid=US:en&num=15&tbs=qdr:d"},
    {"n":"📰 GN Trump Iran war","u":"https://news.google.com/rss/search?q=Trump+Iran+military+strike+war+2026&hl=en-US&gl=US&ceid=US:en&num=15&tbs=qdr:d"},
    {"n":"📰 GN USS Lincoln",   "u":"https://news.google.com/rss/search?q=USS+Abraham+Lincoln+carrier+Iran+Persian+Gulf&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
    {"n":"📰 GN Vance Iran",    "u":"https://news.google.com/rss/search?q=Vance+Rubio+Hegseth+Iran+military+nuclear&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
    {"n":"📰 GN Hormuz",        "u":"https://news.google.com/rss/search?q=Strait+Hormuz+Iran+US+navy+oil&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
]

EMBASSY_FEEDS = [
    # تخلیه دیپلمات‌ها — وضعیت امروز حاد است
    {"n":"🏛️ US State Dept",   "u":"https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html.rss"},
    {"n":"🏛️ UK FCDO",         "u":"https://www.gov.uk/foreign-travel-advice/iran.atom"},
    {"n":"📰 GN Evacuation",   "u":"https://news.google.com/rss/search?q=embassy+evacuation+diplomats+Iran+Lebanon+2026&hl=en-US&gl=US&ceid=US:en&num=10&tbs=qdr:d"},
]

INTL_FEEDS = [
    {"n":"🌐 BBC Middle East", "u":"https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"n":"🌐 Al Jazeera",      "u":"https://www.aljazeera.com/xml/rss/all.xml"},
    {"n":"🌐 Middle East Eye", "u":"https://www.middleeasteye.net/rss"},
    {"n":"🌐 The Guardian ME", "u":"https://www.theguardian.com/world/middleeast/rss"},
    {"n":"🌐 MEI",             "u":"https://www.mei.edu/rss.xml"},
]


ALL_RSS_FEEDS = IRAN_FEEDS + ISRAEL_FEEDS + USA_FEEDS + EMBASSY_FEEDS + INTL_FEEDS
EMBASSY_SET   = {id(f) for f in EMBASSY_FEEDS}

# ══════════════════════════════════════════════════════════════════════════
# Twitter/X handles
# ══════════════════════════════════════════════════════════════════════════
TWITTER_HANDLES = [
    # ─── OSINT / Breaking — اولویت بالا ───────────────────────────────
    # ❌ "OSINTdefender" اشتباه بود — handle واقعی @sentdefender است
    ("🔍 OSINTdefender",        "sentdefender"),
    ("🔍 OSINTtechnical",       "Osinttechnical"),
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
    ("🔴 Clash Report",          "ClashReport"),
    ("🔴 Megatron OSINT",        "Megatron_Ron"),
    ("🔴 Disclose TV",           "disclosetv"),
    ("🔍 OSINTtechnical",        "Osinttechnical"),
    ("🔍 Aurora Intel",          "Aurora_Intel"),
    ("🔍 War Monitor",           "WarMonitor3"),
    # ایران فارسی
    # ❌ "IranIntlPersian" اشتباه بود — handle واقعی @IranintlTV است (۱ میلیون عضو)
    ("🇮🇷 Iran Intl Persian",   "IranintlTV"),
    ("🇮🇷 تسنیم فارسی",          "tasnimnewsfa"),
    ("🇮🇷 مهر فارسی",             "mehrnews_fa"),
    ("🇮🇷 ایرنا فارسی",           "irnafarsi"),
    ("🇮🇷 Press TV",              "PressTVnews"),
    ("🇮🇷 ایکس‌نیوز فارسی",         "FarsiOfficialx"),
    ("🇮🇷 BBC PERSIAN",              "bbcpersian"),
    # اسراییل
    ("🇮🇱 Kann News",            "israelhayomofficial"),
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
    ("🌐 GeoConfirmed",          "GeoConfirmed"),
    ("🌐 IntelCrab",             "IntelCrab"),
]

# ══════════════════════════════════════════════════════════════════════════
# کلیدواژه‌های ۲۷ فوریه ۲۰۲۶ — فقط جنگ ایران/آمریکا/اسراییل
# منطق AND: ایران به تنهایی کافی نیست — باید طرف مقابل یا موضوع جنگی باشد
# ══════════════════════════════════════════════════════════════════════════

# ─── کلیدواژه‌های نظامی/هسته‌ای ایران که به تنهایی کافی‌اند ──────────────────
# (فقط اگه این‌ها باشند، بدون نیاز به آمریکا/اسراییل → pass)
IRAN_MILITARY_KW = [
    # سازمان‌های نظامی
    "irgc","sepah","quds force","basij military","irgc navy","irgc aerospace",
    "سپاه پاسداران","سپاه قدس","بسیج","نیروی هوافضا سپاه",
    # موشک و پهپاد
    "ballistic missile iran","iran missile","iran drone attack","shahab",
    "fateh missile","kheybar","emad","khorramshahr","paveh","arash drone",
    "shahed drone","shahed-136","mohajer","gaza","soumar cruise missile",
    "موشک بالستیک","موشک ایران","پهپاد شاهد","پهپاد مهاجر","موشک خیبر",
    "موشک فتح","موشک کروز","کروز ایران",
    # تأسیسات هسته‌ای (اهداف احتمالی حمله)
    "natanz","fordow","arak heavy water","isfahan nuclear","parchin",
    "نطنز","فردو","اراک","پارچین","اصفهان هسته‌ای",
    # برنامه هسته‌ای
    "uranium enrichment iran","iran centrifuge","iran nuclear","60 percent",
    "90 percent enrichment","weapons grade uranium","nuclear breakout iran",
    "rebuild natanz","iran nuclear weapon","iran bomb",
    "غنی‌سازی اورانیوم","سانتریفیوژ ایران","بمب هسته‌ای ایران","اورانیوم ۹۰ درصد",
    # عملیات نظامی مستقیم
    "irgc attack","iran attack","iran strike","iran fires","iran launches",
    "iran naval","iran warship","iran speedboat","iran intercept",
    "حمله سپاه","حمله ایران","ایران شلیک کرد","ناو ایران",
    # تحریم نظامی/نفتی
    "iran oil sanctions","iran oil embargo","iran oil exports blocked",
    "تحریم نفت ایران","نفت ایران تحریم",
    # جنگ ژوئن ۲۰۲۵ — پیامدها
    "twelve-day war","iran-israel war aftermath","iran reconstitute",
    "iran rebuild nuclear","post-war iran","iran nuclear ruins",
    "جنگ دوازده روزه","ایران پس از جنگ","بازسازی تأسیسات ایران",
]

# ─── آمریکا — تیم ترامپ ۲۰۲۶ ──────────────────────────────────────────────
USA_KW = [
    # شخصیت‌های اصلی
    "trump","donald trump","white house administration",
    "jd vance","vice president vance",
    "marco rubio","secretary rubio",                     # وزیر خارجه
    "pete hegseth","defense secretary hegseth",          # وزیر دفاع
    "scott bessent","treasury secretary bessent",
    "tulsi gabbard","dni gabbard",                       # رئیس اطلاعات
    # مذاکره‌کنندگان هسته‌ای ۲۰۲۶ (بحران جاری)
    "steve witkoff","witkoff","trump envoy iran",
    "jared kushner","kushner iran",
    "special envoy iran","us iran negotiations",
    "iran nuclear deal 2026","trump iran deal",
    # نظامی
    "pentagon","centcom","us military iran","us navy iran",
    "us air force iran","us forces middle east",
    "carrier strike group","uss abraham lincoln","lincoln carrier",
    "uss gerald r ford","gerald ford carrier","uss dwight eisenhower",
    "b-52 iran","b-2 bomber iran","f-35 iran",
    "gbu-57","mop bomb","bunker buster iran",
    "al udeid","al-udeid air base","diego garcia iran",
    # تهدید/هشدار ۲۰۲۶
    "trump threatens iran","us threatens iran","trump ultimatum iran",
    "us strike iran","us attack iran","us bomb iran",
    "trump warn iran","final warning iran",
    # تحریم
    "iran sanctions 2026","maximum pressure iran","us treasury iran",
    "trump sanctions iran","oil sanction iran","china iran tariff",
    "secondary sanctions iran","snap-back sanctions",
    # سیاست
    "war authorization iran","aumf iran","congress iran war",
    "senate iran","state of the union iran",
    # فارسی
    "ترامپ","پنتاگون","کاخ سفید","ویتکوف","کوشنر","روبیو","هگست","ونس","بسنت","گبارد",
    "ناو آبراهام لینکلن","ناو جرالد فورد","ناو هواپیمابر آمریکا",
    "تحریم ایران","فشار حداکثری","ضربه آمریکا","حمله آمریکا به ایران",
    "پایگاه العدید","بمب‌افکن B52","جنگنده F35",
]

# ─── اسراییل — رهبری + نظامی ۲۰۲۶ ────────────────────────────────────────
ISRAEL_KW = [
    # کلمات پایه
    "israel","israeli",
    # رهبری
    "netanyahu","benjamin netanyahu","pm netanyahu",
    "eyal zamir","idf chief zamir",
    "bezalel smotrich","smotrich",
    "itamar ben gvir","ben gvir",
    "israel katz",
    # نظامی
    "idf","mossad operation","shin bet","aman intelligence",
    "israeli air force","iaf strike","israeli airstrike",
    "israeli strike iran","israel bomb iran","israel attack iran",
    "iron dome","arrow 3","arrow-3 missile","david's sling",
    "israel iran war","israel iran military",
    "operation against iran","israel warns iran",
    # فارسی
    "اسراییل","نتانیاهو","موساد","گنبد آهنین","ارتش اسراییل",
    "نیروی هوایی اسراییل","حمله اسراییل به ایران","ضربه اسراییل",
    "اسموتریچ","بن‌گویر","وزیر دفاع اسراییل",
]

# ─── پروکسی‌ها + میانجیان ۲۰۲۶ ───────────────────────────────────────────
PROXY_KW = [
    # پروکسی‌های ایران — کلمات ساده (مهم: باید match کنند)
    "houthi","ansar allah","hamas","hezbollah","kataib",
    "pij","islamic jihad","popular mobilization",
    "حوثی","انصارالله","حماس","حزب‌الله","کتائب","جهاد اسلامی",
    # عبارات مرکب
    "houthi attack","houthi missile","houthi drone","houthi red sea",
    "houthi ship","hezbollah attack","hezbollah missile","hamas attack",
    "حوثی دریای سرخ","حوثی موشک","حمله حماس","حمله حزب‌الله",
    # میانجیان هسته‌ای ۲۰۲۶
    "badr al-busaidi","al-busaidi","grossi","iaea iran",
    "iran iaea","iran nuclear inspection","iran iaea deal",
    "oman mediation","عمان مذاکرات","گروسی","آژانس اتمی ایران",
    "بازرسی آژانس","مذاکرات عمان",
]

# ─── موضوعات بحران ۲۰۲۶ — برای AND logic با "ایران/iran" ─────────────────
WAR_CONTEXT_KW = [
    # کلمات پایه جنگی — با ایران/اسراییل/آمریکا → pass
    "war","attack","strike","airstrike","bombing","nuclear",
    "military","missile","weapon","threat","conflict","crisis",
    "sanction","invasion","escalation","retaliation","offensive",
    "جنگ","حمله","ضربه","هسته","نظامی","موشک","تهدید","بحران","تحریم",
    # مذاکرات هسته‌ای فعال (بحران جاری فوریه ۲۰۲۶)
    "geneva talks iran","vienna talks iran","nuclear framework iran",
    "iran nuclear agreement","iran deal framework",
    "iran nuclear talks","nuclear negotiations iran",
    "fourth round","fifth round talks","iran negotiations",
    "مذاکرات ژنو","مذاکرات وین","چارچوب هسته‌ای","مذاکرات هسته‌ای",
    "توافق هسته‌ای","بسته پیشنهادی هسته‌ای",
    # تنش و حمله
    "strike iran","attack iran","bomb iran",
    "military strike iran","us strike iran","israel strike iran",
    "حمله به ایران","ضربه به ایران","بمباران ایران",
    # آستانه جنگ
    "war iran","iran war","iran conflict","iran military crisis",
    "last chance iran","iran ultimatum","countdown iran",
    "iran war clock","iran deadline",
    "جنگ با ایران","بحران ایران","اتمام حجت ایران",
    # تنگه هرمز
    "strait of hormuz iran","hormuz closure","hormuz blockade",
    "تنگه هرمز","بستن هرمز","انسداد هرمز",
    # تحریم‌های کلیدی
    "iran oil sanctions","iran sanctions","iran nuclear sanctions",
    "تحریم ایران","تحریم هسته‌ای",
]

# ─── حذف قطعی — اخبار کاملاً بی‌ربط ──────────────────────────────────────
HARD_EXCLUDE = [
    # ورزش
    "nba","nfl","nhl","mlb","premier league","la liga","serie a",
    "football match","soccer game","basketball game","world cup",
    "olympic games","marathon race","tennis tournament","golf tournament",
    "فوتبال","بسکتبال","والیبال","کشتی","المپیک","لیگ برتر",
    # سرگرمی/فرهنگ
    "box office","grammy","grammy awards","oscar","oscar ceremony","film festival",
    "music video","celebrity news","reality show","fashion week",
    "سینما","موسیقی","جوایز فیلم","فشن","سریال",
    # اقتصاد داخلی بی‌ربط
    "bitcoin","cryptocurrency","crypto market","ethereum","blockchain",
    "stock market crash","dow jones","nasdaq","s&p 500",
    "بیت‌کوین","ارز دیجیتال","بورس",
    # بلایای طبیعی
    "earthquake disaster","flood victims","hurricane damage","wildfire",
    "زلزله","سیل","آتشفشان",
    # سیاست داخلی ایران بی‌ربط به جنگ
    "iran economy inflation","iran domestic","iran parliament vote",
    "iran budget law","iran judiciary","iran court ruling",
    "iran road accident","iran plane crash","iran traffic",
    "تورم ایران","بودجه داخلی","مجلس ایران بودجه","دادگاه داخلی ایران",
    "تصادف جاده","سانحه هوایی داخلی",
]

EMBASSY_OVERRIDE = [
    "evacuate","leave immediately","travel warning level 4",
    "warden message","embassy closed","consulate closed emergency",
    "us citizens leave","withdraw diplomats",
    "تخلیه","فوری ترک","هشدار سفارت","دیپلمات‌ها خارج",
]

# ─── فیلتر اصلی با منطق AND برای ایران ────────────────────────────────────
def is_war_relevant(text: str, is_embassy=False, is_tg=False, is_tw=False) -> bool:
    """
    فیلتر ۲۰۲۶ — آگاه به منبع:

    Twitter/Telegram = منابع curated اختصاصی جنگ:
      → فقط HARD_EXCLUDE رد می‌شود، بقیه pass

    RSS = منابع عمومی (شامل اخبار داخلی ایران):
      → فیلتر AND: باید ایران + طرف مقابل/موضوع جنگی باشد
      → اخبار صرفاً داخلی ایران رد می‌شوند
    """
    txt = text.lower()

    # ── حذف قطعی (همه منابع) ─────────────────────────────────────────────
    if any(k in txt for k in HARD_EXCLUDE):
        return False

    # ── سفارت + هشدار فوری ───────────────────────────────────────────────
    if is_embassy and any(k in txt for k in EMBASSY_OVERRIDE):
        return True

    # ── Twitter/Telegram: منابع curated — فیلتر سبک ─────────────────────
    # این اکانت‌ها خودشان فقط اخبار جنگ پوست می‌دهند
    # فقط بررسی می‌کنیم که حداقل یک کلمه مرتبط داشته باشد
    if is_tw or is_tg:
        has_any = (
            any(k in txt for k in IRAN_MILITARY_KW) or
            any(k in txt for k in USA_KW) or
            any(k in txt for k in ISRAEL_KW) or
            any(k in txt for k in PROXY_KW) or
            any(k in txt for k in WAR_CONTEXT_KW) or
            "iran" in txt or "iranian" in txt or "ایران" in txt or
            "irgc" in txt or "sepah" in txt or "سپاه" in txt or
            "tehran" in txt or "تهران" in txt or
            "israel" in txt or "اسراییل" in txt or
            "nuclear" in txt or "هسته" in txt or
            "missile" in txt or "موشک" in txt or
            "trump" in txt or "ترامپ" in txt or
            "netanyahu" in txt or "نتانیاهو" in txt or
            "war" in txt or "attack" in txt or "strike" in txt or
            "حمله" in txt or "جنگ" in txt
        )
        return has_any

    # ── RSS: فیلتر AND — جلوگیری از اخبار کاملاً داخلی ایران ─────────────
    has_iran_mil  = any(k in txt for k in IRAN_MILITARY_KW)
    has_iran_name = ("iran" in txt or "iranian" in txt or "ایران" in txt
                     or "تهران" in txt or "خامنه" in txt or "پزشکیان" in txt
                     or "عراقچی" in txt or "irgc" in txt or "tehran" in txt
                     or "سپاه" in txt or "نطنز" in txt or "فردو" in txt)
    has_usa       = any(k in txt for k in USA_KW)
    has_israel    = any(k in txt for k in ISRAEL_KW)
    has_war_ctx   = any(k in txt for k in WAR_CONTEXT_KW)
    has_proxy     = any(k in txt for k in PROXY_KW)

    # موضوعات نظامی/هسته‌ای ایران → همیشه pass
    if has_iran_mil:
        return True

    # پروکسی → pass (حوثی/حماس/حزب‌الله)
    if has_proxy:
        return True

    # ایران + طرف مقابل یا موضوع جنگ → pass
    if has_iran_name and (has_usa or has_israel or has_war_ctx):
        return True

    # آمریکا + اسراییل → pass
    if has_usa and has_israel:
        return True

    # آمریکا یا اسراییل + موضوع جنگی → pass
    if (has_usa or has_israel) and has_war_ctx:
        return True

    # ایران به تنهایی بدون موضوع جنگی → REJECT (تورم/ترافیک/بودجه داخلی)
    return False

# ══════════════════════════════════════════════════════════════════════════
# Twitter/X — Feb 2026 — ترتیب اولویت از بالاترین uptime در GitHub Actions
# ══════════════════════════════════════════════════════════════════════════
# نکته مهم: اکثر Nitter instances در GitHub Actions IPs بلاک هستند
# RSSHub معمولاً قابل‌اعتمادتر است — از آن ابتدا استفاده می‌کنیم
RSSHUB_INSTANCES = [
    "https://rsshub.app",               # ✅ اصلی — پایدارترین
    "https://rsshub.rss.now.sh",       # ✅ mirror
    "https://rss.shab.fun",            # backup
    "https://rsshub.moeyy.xyz",        # backup
    "https://hub.slar.ru",             # backup
]
NITTER_INSTANCES = [
    "https://rss.xcancel.com",         # ✅ subdomain مستقیم
    "https://xcancel.com",             # ✅ redirect
    "https://nitter.poast.org",        # ✅ اغلب در CI کار می‌کند
    "https://nitter.privacyredirect.com",
    "https://nitter.tiekoetter.com",
    "https://lightbrd.com",
    "https://nitter.catsarch.com",
    "https://n.ramle.be",
    "https://nitter.space",
    "https://nitter.net",
    "https://nitter.it",
    "https://nitter.unixfox.eu",
]

NITTER_HDR = {
    "User-Agent": "Mozilla/5.0 (compatible; Feedfetcher-Google; +http://www.google.com/feedfetcher.html)",
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
    """
    در این نسخه: probe حذف شد.
    همه fetch_twitter مستقیم RSSHub → Nitter را امتحان می‌کنند.
    فقط cache را می‌خوانیم که آخرین instance موفق را بیاد داشته باشد.
    """
    global _nitter_pool, _rsshub_pool
    cached_n, cached_r, ts = _load_nitter_cache()
    age = datetime.now(timezone.utc).timestamp() - ts
    # اگه cache جدید است: آخرین instance موفق را اول بگذار
    if age < NITTER_CACHE_TTL:
        if cached_r: _rsshub_pool = cached_r + [i for i in RSSHUB_INSTANCES if i not in cached_r]
        if cached_n: _nitter_pool = cached_n + [i for i in NITTER_INSTANCES if i not in cached_n]
    if not _rsshub_pool: _rsshub_pool = list(RSSHUB_INSTANCES)
    if not _nitter_pool: _nitter_pool = list(NITTER_INSTANCES)
    log.info(f"𝕏 pools: RSSHub={len(_rsshub_pool)} Nitter={len(_nitter_pool)}")

async def fetch_twitter(client: httpx.AsyncClient, label: str, handle: str) -> list:
    """
    دریافت توییت‌ها:
    1. RSSHub (پایدارتر در GitHub Actions CI)
    2. Nitter instances
    اولین نتیجه موفق ذخیره می‌شود تا دفعه بعد اول امتحان شود.
    """
    sema = _TW_SEMA or asyncio.Semaphore(15)
    async with sema:
        # ── RSSHub اول (در CI بهتر کار می‌کند) ─────────────────────────
        for inst in (_rsshub_pool or RSSHUB_INSTANCES):
            for path in (f"/twitter/user/{handle}", f"/x/user/{handle}"):
                e = await _try_rss(client, f"{inst}{path}", timeout=8.0)
                if e:
                    log.debug(f"𝕏 {handle} ← RSSHub {inst.split('//')[-1]} ({len(e)})")
                    # این instance را به اول cache بفرست
                    _update_pool_cache(inst, is_rsshub=True)
                    return [(x, f"𝕏 {label}", "tw", False) for x in e]

        # ── Nitter ──────────────────────────────────────────────────────
        for inst in (_nitter_pool or NITTER_INSTANCES):
            e = await _try_rss(client, f"{inst}/{handle}/rss", timeout=6.0)
            if e:
                log.debug(f"𝕏 {handle} ← Nitter {inst.split('//')[-1]} ({len(e)})")
                _update_pool_cache(inst, is_rsshub=False)
                return [(x, f"𝕏 {label}", "tw", False) for x in e]

    log.debug(f"𝕏 {handle}: همه fail")
    return []

def _update_pool_cache(working_inst: str, is_rsshub: bool):
    """instance موفق را به اول لیست cache می‌برد"""
    global _nitter_pool, _rsshub_pool
    if is_rsshub:
        pool = [working_inst] + [i for i in _rsshub_pool if i != working_inst]
        _rsshub_pool = pool
        json.dump({"nitter": _nitter_pool, "rsshub": pool,
                   "ts": datetime.now(timezone.utc).timestamp()},
                  open(NITTER_CACHE_FILE, "w"))
    else:
        pool = [working_inst] + [i for i in _nitter_pool if i != working_inst]
        _nitter_pool = pool
        json.dump({"nitter": pool, "rsshub": _rsshub_pool,
                   "ts": datetime.now(timezone.utc).timestamp()},
                  open(NITTER_CACHE_FILE, "w"))

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
    scrape t.me/s/{handle} — واکشی پیام‌های کانال‌های عمومی تلگرام
    از چند User-Agent مختلف استفاده می‌کند تا احتمال موفقیت بالا برود
    """
    url = f"https://t.me/s/{handle}"
    # user agents مختلف برای bypass rate limiting
    ua_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "TelegramBot (like TwitterBot) 2.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
    ]
    hdrs = {
        "User-Agent": ua_list[hash(handle) % len(ua_list)],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    try:
        r = await client.get(url, timeout=httpx.Timeout(TG_TIMEOUT),
                             headers=hdrs, follow_redirects=True)
        if r.status_code not in (200, 301, 302):
            log.debug(f"TG {handle}: HTTP {r.status_code}")
            return []

        html = r.text
        if not html or len(html) < 500:
            log.debug(f"TG {handle}: empty response")
            return []

        soup = BeautifulSoup(html, "html.parser")

        # selector اصلی Telegram web
        msgs = soup.select(".tgme_widget_message_wrap")
        if not msgs:
            # fallback: selector قدیمی‌تر
            msgs = soup.select(".tgme_widget_message")

        if not msgs:
            log.debug(f"TG {handle}: no messages found ({len(html)} bytes)")
            return []

        results = []
        for msg in msgs[-40:]:  # آخرین ۴۰ پیام
            # متن پیام — چند selector مختلف
            txt_el = (msg.select_one(".tgme_widget_message_text")
                      or msg.select_one(".tgme_widget_message_bubble .js-message_text")
                      or msg.select_one("[data-post]"))
            text = txt_el.get_text(" ", strip=True) if txt_el else ""

            # پاکسازی whitespace زیاد
            text = re.sub(r'\s+', ' ', text).strip()
            if not text or len(text) < 10:
                continue

            # زمان پیام
            time_el  = msg.select_one("time[datetime]")
            dt_str   = time_el.get("datetime", "") if time_el else ""
            entry_dt = None
            if dt_str:
                try:
                    entry_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            # فیلتر زمانی
            if entry_dt and entry_dt < cutoff:
                continue

            # لینک پیام
            link_el = (msg.select_one("a.tgme_widget_message_date")
                       or msg.select_one("a[href*='t.me']"))
            link = link_el.get("href", "") if link_el else f"https://t.me/{handle}"

            # عنوان = اولین جمله متن
            first_line = text.split('\n')[0][:300].strip()
            title = first_line if first_line else text[:200]

            results.append(({
                "title":   title,
                "summary": text[:1000],
                "link":    link,
                "_tg_dt":  entry_dt,
            }, label, "tg", False))

        log.debug(f"TG {handle}: {len(results)} messages")
        return results

    except Exception as e:
        log.debug(f"TG {handle}: {e}")
        return []

async def fetch_all(client: httpx.AsyncClient, cutoff: datetime) -> list:
    """
    واکشی موازی همه منابع — ترتیب: Twitter اول، سپس Telegram، سپس RSS
    Twitter اول چون breaking news سریع‌تر در X منتشر می‌شود
    """
    await build_twitter_pools(client)

    # ترتیب ارسال: Twitter اول → RSS → Telegram
    # (همه موازی fetch می‌شوند ولی نتایج به این ترتیب پردازش می‌شوند)
    tw_t  = [fetch_twitter(client, l, h) for l, h in TWITTER_HANDLES]
    rss_t = [fetch_rss(client, f) for f in ALL_RSS_FEEDS]
    tg_t  = [fetch_telegram_channel(client, l, h, cutoff) for l, h in TELEGRAM_CHANNELS]

    all_res = await asyncio.gather(*tw_t, *rss_t, *tg_t, return_exceptions=True)

    out = []; tw_ok = rss_ok = tg_ok = 0
    n_tw  = len(TWITTER_HANDLES)
    n_rss = len(ALL_RSS_FEEDS)
    for i, res in enumerate(all_res):
        if not isinstance(res, list): continue
        out.extend(res)
        if   i < n_tw:              tw_ok  += bool(res)
        elif i < n_tw + n_rss:      rss_ok += bool(res)
        else:                        tg_ok  += bool(res)

    log.info(f"  𝕏:{tw_ok}/{len(TWITTER_HANDLES)}"
             f"  📡 RSS:{rss_ok}/{len(ALL_RSS_FEEDS)}"
             f"  📢 TG:{tg_ok}/{len(TELEGRAM_CHANNELS)}")
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
    for item in stories:
        if not (isinstance(item, (list, tuple)) and len(item) == 3):
            continue
        _, prev_bag_raw, prev_triple = item
        prev_bag = set(prev_bag_raw) if isinstance(prev_bag_raw, list) else prev_bag_raw
        pa, pb, pact = prev_triple
        if act1 and pact and act1 in _VIOLENCE_CODES and pact in _VIOLENCE_CODES:
            if a1 == pa and a2 == pb: return True
        if act1 and pact and act1 in _POLITICAL_CODES and pact in _POLITICAL_CODES:
            if a1 == pa: return True
        union = bag1 | prev_bag
        if union and len(bag1 & prev_bag) / len(union) >= JACCARD_THRESHOLD:
            return True
    return False

def register_story(title: str, stories: list) -> list:
    stories.append([title, list(_bag(title)), list(_entity_triple(title))])
    return stories[-MAX_STORIES:]

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
        if Path(STORIES_FILE).exists():
            raw = json.load(open(STORIES_FILE))
            # migrate فرمت قدیم (2-tuple) به جدید (3-tuple)
            result = []
            for item in raw:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    title = item[0]
                    result.append([title, list(_bag(title)), list(_entity_triple(title))])
                elif isinstance(item, (list, tuple)) and len(item) == 3:
                    result.append(item)
            return result
    except: pass
    return []

def save_stories(stories):
    json.dump(stories[-MAX_STORIES:], open(STORIES_FILE, "w"))

# ══════════════════════════════════════════════════════════════════════════
# ترجمه — Gemini اول، MyMemory رایگان fallback
# ══════════════════════════════════════════════════════════════════════════
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

# تشخیص متن فارسی
def _is_farsi(text: str) -> bool:
    fa_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    return fa_chars / max(len(text), 1) > 0.3

# ترجمه رایگان یک متن از انگلیسی به فارسی با MyMemory
async def _translate_mymemory(client: httpx.AsyncClient, text: str) -> str:
    """MyMemory API — رایگان، بدون کلید، تا ۵۰۰۰ کاراکتر در روز"""
    if not text or _is_farsi(text):
        return text
    try:
        url = "https://api.mymemory.translated.net/get"
        r = await client.get(url,
            params={"q": text[:500], "langpair": "en|fa", "de": "warbot@github.com"},
            timeout=httpx.Timeout(8.0))
        if r.status_code == 200:
            data = r.json()
            tr = data.get("responseData", {}).get("translatedText", "")
            # MyMemory گاهی MYMEMORY WARNING برمی‌گرداند
            if tr and "MYMEMORY WARNING" not in tr and len(tr) > 5:
                return tr
    except Exception as e:
        log.debug(f"MyMemory: {e}")
    return text

GEMINI_PROMPT = """تو یک خبرنگار جنگی حرفه‌ای هستی. این خبرهای نظامی را به فارسی ترجمه کن.

دقیقاً این ساختار را رعایت کن:
###ITEM_0###
T: [عنوان فارسی در یک خط]
B: [متن فارسی کامل]
###ITEM_1###
T: [عنوان فارسی]
B: [متن فارسی]

قوانین:
- اسامی: Netanyahu=نتانیاهو، Khamenei=خامنه‌ای، IRGC=سپاه، IDF=ارتش اسراییل، CENTCOM=ستاد مرکزی آمریکا
- اعداد، آمار، مکان‌ها را دقیق نگه‌دار
- اگه خبر فارسیه: فقط پاکیزه‌سازی کن

===خبرها===
{items}"""

async def _translate_gemini(client: httpx.AsyncClient, articles: list) -> list | None:
    """ترجمه با Gemini — None اگه fail شد"""
    if not GEMINI_API_KEY:
        return None
    items_txt = "".join(
        f"###ITEM_{i}###\nEN_TITLE: {t[:300]}\nEN_BODY: {s[:400]}\n\n"
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
                    "contents": [{"parts": [{"text": GEMINI_PROMPT.format(items=items_txt)}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192}
                },
                timeout=httpx.Timeout(40.0)
            )
            if r.status_code == 429:
                log.warning(f"Gemini {model}: rate-limit"); continue
            if r.status_code != 200:
                log.warning(f"Gemini {model}: HTTP {r.status_code} — {r.text[:200]}"); continue

            text_out = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            log.info(f"🌐 Gemini {model} OK")

            results = list(articles)
            ok_count = 0
            for i, (orig_t, orig_s) in enumerate(articles):
                blk = re.search(rf"###ITEM_{i}###\s*(.*?)(?=###ITEM_\d+###|\Z)", text_out, re.DOTALL)
                if not blk: continue
                block   = blk.group(1)
                t_match = re.search(r"^T:\s*(.+)$", block, re.MULTILINE)
                b_match = re.search(r"^B:\s*([\s\S]+?)$", block, re.MULTILINE)
                fa_t = t_match.group(1).strip() if t_match else ""
                fa_b = b_match.group(1).strip() if b_match else ""
                # fallback: همه block را عنوان بگیر
                if not fa_t:
                    fa_t = block.strip().split('\n')[0]
                if len(fa_t) > 5:
                    results[i] = (fa_t, fa_b or orig_s)
                    ok_count += 1
            log.info(f"🌐 ترجمه: {ok_count}/{len(articles)} خبر")
            # مدل کارآمد را اول بگذار
            state["models_order"] = [model] + [m for m in models if m != model]
            json.dump(state, open(GEMINI_STATE_FILE, "w"))
            return results
        except Exception as e:
            log.warning(f"Gemini {model}: {e}"); continue
    return None

async def translate_batch(client: httpx.AsyncClient, articles: list) -> list:
    """
    ترجمه با اولویت:
    1. Gemini (اگه API key داریم)
    2. MyMemory رایگان (فقط عنوان)
    3. متن اصلی (بدون ترجمه)
    """
    if not articles:
        return []

    results = list(articles)

    # ── مرحله ۱: Gemini ───────────────────────────────────────────────
    if GEMINI_API_KEY:
        log.info(f"🌐 Gemini: ترجمه {len(articles)} خبر...")
        gemini_res = await _translate_gemini(client, articles)
        if gemini_res:
            return gemini_res
        log.warning("🌐 Gemini fail — fallback به MyMemory")
    else:
        log.info("🌐 GEMINI_API_KEY تنظیم نشده — استفاده از MyMemory رایگان")

    # ── مرحله ۲: MyMemory — عنوان را ترجمه می‌کند ───────────────────
    log.info(f"🌐 MyMemory: ترجمه {len(articles)} عنوان...")
    sema = asyncio.Semaphore(5)

    async def _tr(orig_t, orig_s):
        async with sema:
            if _is_farsi(orig_t):
                return (orig_t, orig_s)
            fa_t = await _translate_mymemory(client, orig_t)
            return (fa_t, orig_s)

    translated = await asyncio.gather(*[_tr(t, s) for t, s in articles])
    ok = sum(1 for i, (fa, _) in enumerate(translated) if fa != articles[i][0])
    log.info(f"🌐 MyMemory: {ok}/{len(articles)} ترجمه شد")
    return list(translated)

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

# ══════════════════════════════════════════════════════════════════════════
# دریافت تصویر اصلی خبر از سایت (og:image تصویر مقاله — نه لوگو)
# ══════════════════════════════════════════════════════════════════════════
# دریافت تصویر اصلی خبر (نه لوگو — عکس مقاله)
# ══════════════════════════════════════════════════════════════════════════
# دریافت تصویر اصلی مقاله (نه لوگو — عکس اصلی خبر)
# ══════════════════════════════════════════════════════════════════════════

# URL‌هایی که احتمال بالای لوگو دارند
_SKIP_IMG_PATTERNS = [
    "logo","icon","favicon","sprite","avatar","placeholder",
    "default","blank","spacer","1x1","pixel","brand","masthead",
    "no-image","no-photo","profile","author","byline","signature",
    "/ad/","/ads/","banner","promo","subscribe","newsletter",
]
# CSS selector های ordered برای پیدا کردن تصویر اصلی خبر
_IMG_SELECTORS = [
    # ساختارهای article استاندارد
    "article figure img",
    "article .featured-image img",
    "article .hero-image img",
    "[class*='article-image'] img",
    "[class*='news-image'] img",
    "[class*='story-image'] img",
    "[class*='featured-img'] img",
    "[class*='lead-image'] img",
    "[class*='post-image'] img",
    "[class*='entry-image'] img",
    # ساختارهای ایرانی
    ".detail-media img",
    ".news-photo img",
    ".content-media img",
    ".article-img img",
    ".body img",
    # عمومی‌تر
    "figure img",
    "picture source",
    "picture img",
    ".content img",
    "article img",
]

async def fetch_article_image(client: httpx.AsyncClient, url: str) -> "io.BytesIO | None":
    """
    تصویر اصلی مقاله:
    ۱. CSS selectors برای یافتن تصویر خبر در متن مقاله
    ۲. og:image / twitter:image فقط اگه عرض ≥ ۶۰۰ باشد
    ۳. فیلتر لوگو: حجم < ۱۵KB یا ابعاد < ۵۰۰×۲۸۰ یا ratio < 1.3 → رد
    """
    if not url or len(url) < 10:
        return None
    skip_domains = ("t.me", "twitter.com", "x.com", "google.com/rss",
                    "feeds.reuters", "feeds.bbci", "feed.", "rss.")
    if any(d in url for d in skip_domains):
        return None

    try:
        r = await client.get(url,
            timeout=httpx.Timeout(10.0),
            headers={**COMMON_UA,
                     "Accept": "text/html,*/*;q=0.8",
                     "Sec-Fetch-Dest": "document"},
            follow_redirects=True)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # ── ساخت لیست کاندیدا ───────────────────────────────────────
        candidates: list[tuple[str, int]] = []  # (url, priority)

        # Priority 1: CSS selector های article/news
        for sel in _IMG_SELECTORS:
            for el in soup.select(sel)[:3]:
                src = None
                if el.name == "source":
                    src = el.get("srcset", "").split(" ")[0]
                else:
                    # srcset → بزرگ‌ترین
                    ss = el.get("srcset", "")
                    if ss:
                        parts = [p.strip().split(" ") for p in ss.split(",") if p.strip()]
                        best = sorted(parts, key=lambda x: int(x[1].rstrip("w")) if len(x)>1 and x[1].rstrip("w").isdigit() else 0, reverse=True)
                        if best: src = best[0][0]
                    if not src:
                        src = el.get("src") or el.get("data-src") or el.get("data-lazy-src")
                if src and not src.startswith("data:"):
                    candidates.append((src, 10))

        # Priority 2: og:image
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            candidates.append((og["content"], 5))

        # og:image:width بررسی
        og_w = soup.find("meta", property="og:image:width")
        if og_w:
            try:
                w = int(og_w.get("content", 0))
                if w < 500 and candidates:
                    # og:image کوچک است → اولویت پایین‌تر
                    candidates = [(u, p-3 if u == og.get("content") else p) for u, p in candidates]
            except: pass

        # Priority 3: twitter:image
        for name in ("twitter:image", "twitter:image:src"):
            tw = soup.find("meta", attrs={"name": name})
            if tw and tw.get("content"):
                candidates.append((tw["content"], 4)); break

        if not candidates:
            return None

        # ── فیلتر و دانلود ──────────────────────────────────────────
        from urllib.parse import urlparse
        base_p = urlparse(r.url)  # URL نهایی (بعد از redirect)

        # مرتب از اولویت بالا
        candidates.sort(key=lambda x: -x[1])
        tried_urls = set()

        for img_url, _ in candidates[:8]:
            # نرمال‌سازی URL
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                img_url = f"{base_p.scheme}://{base_p.netloc}{img_url}"
            elif not img_url.startswith("http"):
                continue

            # حذف query string برای مقایسه
            clean_url = img_url.lower().split("?")[0]

            # فیلتر الگوهای لوگو در URL
            if any(p in clean_url for p in _SKIP_IMG_PATTERNS):
                log.debug(f"🖼 skip-url: {img_url[:60]}")
                continue

            if img_url in tried_urls:
                continue
            tried_urls.add(img_url)

            # دانلود
            try:
                ir = await client.get(img_url,
                    timeout=httpx.Timeout(12.0),
                    headers={**COMMON_UA, "Accept": "image/*,*/*;q=0.5"},
                    follow_redirects=True)
                if ir.status_code != 200:
                    continue
            except Exception as de:
                log.debug(f"🖼 dl-err: {de}"); continue

            raw   = ir.content
            ctype = ir.headers.get("content-type", "")

            # حجم کم → لوگو
            if len(raw) < 15_000:
                log.debug(f"🖼 skip-small: {len(raw)}B")
                continue

            # چک نوع تصویر
            is_img = (
                ctype.startswith("image/") or
                raw[:3]  == b'\xff\xd8\xff' or
                raw[:8]  == b'\x89PNG\r\n\x1a\n' or
                raw[:6]  in (b'GIF87a', b'GIF89a') or
                raw[:4]  == b'RIFF' or
                raw[:4]  == b'WEBP'
            )
            if not is_img:
                continue

            # PIL: بررسی ابعاد و resize
            if PIL_OK:
                try:
                    tmp = Image.open(io.BytesIO(raw))
                    w, h = tmp.size
                    # عرض < ۵۰۰ یا ارتفاع < ۲۸۰ → لوگو/بنر
                    if w < 500 or h < 280:
                        log.debug(f"🖼 skip-dim: {w}×{h}")
                        continue
                    # نسبت < 1.3 → احتمالاً مربع یا عمودی = لوگو
                    ratio = w / max(h, 1)
                    if ratio < 1.3:
                        log.debug(f"🖼 skip-ratio: {ratio:.2f} ({w}×{h})")
                        continue
                    img_rgb = tmp.convert("RGB")
                    if w > 1600 or h > 1000:
                        img_rgb.thumbnail((1600, 1000), Image.LANCZOS)
                    out = io.BytesIO()
                    img_rgb.save(out, "JPEG", quality=88, optimize=True)
                    out.seek(0)
                    log.info(f"🖼 ✅ {w}×{h} r={ratio:.1f}  {img_url[:55]}")
                    return out
                except Exception as pe:
                    log.debug(f"🖼 PIL-err: {pe}"); continue
            else:
                buf = io.BytesIO(raw); buf.seek(0)
                return buf

        return None

    except Exception as e:
        log.debug(f"fetch_img {url[:55]}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════
# یک چرخه fetch → filter → send
# ══════════════════════════════════════════════════════════════════════════
async def _run_cycle(client: httpx.AsyncClient,
                     seen: set, stories: list,
                     cutoff: datetime) -> tuple:
    """
    یک چرخه کامل.
    برمی‌گرداند: (seen, stories, cutoff_for_next)
    """
    cycle_start = datetime.now(timezone.utc)
    save_run_state()

    # ── fetch موازی ──────────────────────────────────────────────────────
    raw = await fetch_all(client, cutoff)
    log.info(f"  📥 {len(raw)} آیتم خام")

    # ── پردازش ───────────────────────────────────────────────────────────
    collected = []
    cnt_old = cnt_irrel = cnt_dup = cnt_story = 0

    for entry, src_name, src_type, is_emb in raw:
        eid = make_id(entry)
        if eid in seen:                         cnt_dup   += 1; continue
        if not is_fresh(entry, cutoff):         cnt_old   += 1; continue
        t   = clean_html(entry.get("title",""))
        s   = clean_html(entry.get("summary") or entry.get("description") or "")
        if not is_war_relevant(f"{t} {s}", is_embassy=is_emb,
                               is_tg=(src_type=="tg"), is_tw=(src_type=="tw")):
            cnt_irrel += 1; continue
        if is_story_dup(t, stories):            cnt_story += 1; continue
        collected.append((eid, entry, src_name, src_type, is_emb))
        stories = register_story(t, stories)

    log.info(f"  📊 قدیمی:{cnt_old} نامرتبط:{cnt_irrel} dup:{cnt_dup} story:{cnt_story} ✅{len(collected)}")

    collected = list(reversed(collected))[:MAX_NEW_PER_RUN]

    if not collected:
        log.info("  💤 خبر جدیدی نیست")
        save_seen(seen); save_stories(stories)
        return seen, stories, cycle_start

    # ── ترجمه ────────────────────────────────────────────────────────────
    arts_in = [
        (trim(clean_html(e.get("title","")), 400),
         trim(clean_html(e.get("summary") or e.get("description") or ""), 600))
        for _, e, _, _, _ in collected
    ]
    log.info(f"  🌐 ترجمه {len(arts_in)} خبر...")
    translations = await translate_batch(client, arts_in)

    # ── ارسال ────────────────────────────────────────────────────────────
    sent = 0
    for i, (eid, entry, src_name, stype, is_emb) in enumerate(collected):
        fa_title, fa_body = translations[i]
        en_title = arts_in[i][0]
        link     = entry.get("link","")
        dt_str   = format_dt(entry)

        title_is_fa = _is_farsi(fa_title) if fa_title else False
        orig_is_fa  = _is_farsi(en_title)
        if not title_is_fa and not orig_is_fa:
            log.info(f"  ⏭ skip(noFA): {en_title[:50]}"); continue

        display = fa_title.strip() if title_is_fa else en_title.strip()
        body_fa = ""
        if fa_body and _is_farsi(fa_body) and len(fa_body) > 15:
            body_fa = fa_body.strip()
        elif _is_farsi(arts_in[i][1]):
            body_fa = arts_in[i][1].strip()

        s_bar = sentiment_bar(analyze_sentiment(f"{fa_title} {fa_body} {en_title}"))
        cap   = [s_bar, f"<b>{esc(display)}</b>"]
        if body_fa and body_fa[:50] not in display[:50]:
            cap += ["", esc(trim(body_fa, 800))]
        if dt_str: cap.append(f"\n🕐 {dt_str}")
        caption = "\n".join(cap)

        done = False
        if link and stype == "rss":
            img = await fetch_article_image(client, link)
            if img:
                ok = await tg_send_photo(client, img, caption[:1024])
                if ok: done = True; log.info("    📸 تصویر+فارسی")

        if not done:
            ok = await tg_send_text(client, caption)
            if ok: done = True; log.info("    ✉️ متن فارسی")

        if done:
            seen.add(eid); sent += 1
        await asyncio.sleep(SEND_DELAY)

    save_seen(seen); save_stories(stories)
    log.info(f"  🏁 {sent}/{len(collected)} ارسال  seen:{len(seen)}")
    return seen, stories, cycle_start


# ══════════════════════════════════════════════════════════════════════════
# main — حلقه دائمی
# ══════════════════════════════════════════════════════════════════════════
async def main():
    global _TW_SEMA
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID تنظیم نشده!"); return

    _TW_SEMA = asyncio.Semaphore(20)

    # cutoff اولیه
    last_run = load_run_state()
    now_utc  = datetime.now(timezone.utc)
    cutoff   = last_run - timedelta(minutes=CUTOFF_BUFFER_MIN)
    if cutoff < now_utc - timedelta(minutes=MAX_LOOKBACK_MIN):
        cutoff = now_utc - timedelta(minutes=MAX_LOOKBACK_MIN)

    seen    = load_seen()
    stories = load_stories()

    mode = "GitHub CI" if _CI else "محلی — بی‌نهایت"
    log.info("=" * 70)
    log.info(f"🚀 WarBot v20 | {datetime.now(TEHRAN_TZ).strftime('%H:%M تهران %Y/%m/%d')}")
    log.info(f"   mode={mode}  max={BOT_MAX_RUNTIME_MIN}min  interval={LOOP_INTERVAL_SEC}s")
    log.info(f"   📡 {len(ALL_RSS_FEEDS)} RSS  📢 {len(TELEGRAM_CHANNELS)} TG  𝕏 {len(TWITTER_HANDLES)} TW")
    log.info(f"   seen:{len(seen)}  stories:{len(stories)}  PIL:{'✅' if PIL_OK else '❌'}")
    log.info("=" * 70)

    wall_start = datetime.now(timezone.utc)
    loop_n     = 0
    limits     = httpx.Limits(max_connections=100, max_keepalive_connections=30)

    async with httpx.AsyncClient(follow_redirects=True, limits=limits) as client:
        await build_twitter_pools(client)

        while True:
            loop_n += 1
            elapsed_min = (datetime.now(timezone.utc) - wall_start).total_seconds() / 60
            log.info(f"\n{'━'*55}")
            log.info(f"  ⟳ Loop #{loop_n}  elapsed={elapsed_min:.1f}min"
                     f"  {datetime.now(TEHRAN_TZ).strftime('%H:%M تهران')}")

            t0 = datetime.now(timezone.utc)
            try:
                seen, stories, next_cutoff = await _run_cycle(
                    client, seen, stories, cutoff)
                # cutoff بعدی = شروع این cycle - buffer
                cutoff = next_cutoff - timedelta(minutes=CUTOFF_BUFFER_MIN)
            except Exception as e:
                log.error(f"  ❌ cycle error: {e}")
                import traceback; log.debug(traceback.format_exc())

            took = (datetime.now(timezone.utc) - t0).total_seconds()
            log.info(f"  ⏱ cycle took {took:.0f}s")

            # بررسی exit برای CI
            elapsed_min = (datetime.now(timezone.utc) - wall_start).total_seconds() / 60
            if elapsed_min >= BOT_MAX_RUNTIME_MIN:
                log.info(f"  ⏹ CI timeout ({BOT_MAX_RUNTIME_MIN}min) — خروج سالم")
                break

            # صبر تا cycle بعدی
            wait = max(5.0, LOOP_INTERVAL_SEC - took)
            log.info(f"  💤 {wait:.0f}s تا چرخه بعدی...")
            await asyncio.sleep(wait)


if __name__ == "__main__":
    asyncio.run(main())
