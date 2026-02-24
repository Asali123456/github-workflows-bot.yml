import os, json, hashlib, asyncio, logging, re, random, io
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("WarBot")

# ──────────────────────────────────────────────────────────────────────────
# تنظیمات
# ──────────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SEEN_FILE         = "seen.json"
TITLE_HASH_FILE   = "title_hashes.json"
GEMINI_STATE_FILE = "gemini_state.json"
FLIGHT_ALERT_FILE = "flight_alerts.json"

MAX_NEW_PER_RUN   = 30
MAX_MSG_LEN       = 4096
SEND_DELAY        = 2
CUTOFF_HOURS      = 4
TG_CUTOFF_HOURS   = 1
JACCARD_THRESHOLD = 0.38   # کمتر = dedup قوی‌تر (cross-source)

# دسته‌های ماکرو برای dedup — هر عضو هر گروه با عضو دیگر = همون نوع رویداد
_VIOLENCE_CODES  = {"MSL","AIR","ATK","KIA","DEF","EXP"}   # حمله/تلفات/رهگیری
_POLITICAL_CODES = {"THR","DIP","SAN","NUC","SPY","STM"}   # تهدید/دیپلماسی/تحریم
TEHRAN_TZ         = pytz.timezone("Asia/Tehran")

def get_cutoff(h=None):
    return datetime.now(timezone.utc) - timedelta(hours=h or CUTOFF_HOURS)

# ──────────────────────────────────────────────────────────────────────────
# 🇮🇷  ایران  ──────────────────────────────────────────────────────────────
IRAN_FEEDS = [
    {"n":"🇮🇷 IRNA English",       "u":"https://en.irna.ir/rss"},
    {"n":"🇮🇷 Mehr News EN",        "u":"https://en.mehrnews.com/rss"},
    {"n":"🇮🇷 Tasnim News EN",      "u":"https://www.tasnimnews.com/en/rss"},
    {"n":"🇮🇷 Fars News EN",        "u":"https://www.farsnews.ir/rss"},
    {"n":"🇮🇷 Press TV",            "u":"https://www.presstv.ir/rss"},
    {"n":"🇮🇷 ISNA English",        "u":"https://en.isna.ir/rss"},
    {"n":"🇮🇷 Tehran Times",        "u":"https://www.tehrantimes.com/rss"},
    {"n":"🇮🇷 Iran Daily",          "u":"https://www.iran-daily.com/rss"},
    {"n":"🇮🇷 Iran Front Page",     "u":"https://ifpnews.com/feed"},
    {"n":"🇮🇷 Iran International",  "u":"https://www.iranintl.com/en/rss"},
    {"n":"🇮🇷 Radio Farda",         "u":"https://www.radiofarda.com/api/zoyqvpemr"},
    {"n":"🇮🇷 Iran Wire EN",        "u":"https://iranwire.com/en/feed/"},
    {"n":"🇮🇷 Kayhan London",       "u":"https://kayhan.london/feed/"},
    {"n":"🇮🇷 خبرگزاری تسنیم",      "u":"https://www.tasnimnews.com/fa/rss/feed/0/8/0"},
    {"n":"🇮🇷 خبرگزاری مهر",         "u":"https://www.mehrnews.com/rss"},
    {"n":"🇮🇷 خبرگزاری ایرنا",       "u":"https://www.irna.ir/rss"},
    {"n":"🇮🇷 خبرگزاری ایسنا",       "u":"https://www.isna.ir/rss"},
    {"n":"🇮🇷 خبرگزاری فارس",        "u":"https://www.farsnews.ir/rss/fa"},
    {"n":"🇮🇷 خبرگزاری دانشجو",      "u":"https://snn.ir/rss"},
    {"n":"🇮🇷 خبرگزاری میزان",        "u":"https://www.mizanonline.ir/rss"},
    {"n":"🇮🇷 باشگاه خبرنگاران",      "u":"https://www.yjc.ir/fa/rss/allnews"},
    {"n":"🇮🇷 خبر آنلاین",            "u":"https://www.khabaronline.ir/rss"},
    {"n":"🇮🇷 انتخاب",                "u":"https://www.entekhab.ir/rss"},
    {"n":"🇮🇷 مشرق نیوز",             "u":"https://www.mashreghnews.ir/rss"},
    {"n":"🇮🇷 تابناک",                "u":"https://www.tabnak.ir/fa/rss/allnews"},
    {"n":"🇮🇷 فرارو",                 "u":"https://fararu.com/rss"},
    {"n":"🇮🇷 آفتاب نیوز",            "u":"https://www.aftabnews.ir/rss"},
    {"n":"🇮🇷 عصر ایران",             "u":"https://www.asriran.com/fa/rss"},
    {"n":"🇮🇷 دیپلماسی ایرانی",       "u":"https://www.irdiplomacy.ir/fa/rss"},
    {"n":"🇮🇷 دفاع پرس",             "u":"https://www.defapress.ir/fa/rss"},
    {"n":"🇮🇷 سپاه نیوز",             "u":"https://www.sepahnews.com/rss"},
    {"n":"🇮🇷 صدای ارتش",            "u":"https://arteshara.ir/fa/rss"},
    {"n":"🇮🇷 آنا خبر",               "u":"https://www.ana.ir/rss"},
    {"n":"🇮🇷 GNews جنگ ایران FA",   "u":"https://news.google.com/rss/search?q=ایران+اسراییل+جنگ+حمله&hl=fa&gl=IR&ceid=IR:fa&num=15"},
    {"n":"🇮🇷 GNews سپاه موشک FA",   "u":"https://news.google.com/rss/search?q=سپاه+موشک+حمله+اسراییل&hl=fa&gl=IR&ceid=IR:fa&num=15"},
    {"n":"🇮🇷 GNews IRGC EN",        "u":"https://news.google.com/rss/search?q=IRGC+Iran+Israel+attack+war&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇷 GNews خامنه‌ای",        "u":"https://news.google.com/rss/search?q=خامنه‌ای+بیانیه+جنگ&hl=fa&gl=IR&ceid=IR:fa&num=10"},
]

# ──────────────────────────────────────────────────────────────────────────
# 🇮🇱  اسراییل  ──────────────────────────────────────────────────────────
ISRAEL_FEEDS = [
    {"n":"🇮🇱 Jerusalem Post",       "u":"https://www.jpost.com/rss/rssfeedsheadlines.aspx"},
    {"n":"🇮🇱 J-Post Military",      "u":"https://www.jpost.com/Rss/RssFeedsIsraelNews.aspx"},
    {"n":"🇮🇱 Times of Israel",      "u":"https://www.timesofisrael.com/feed/"},
    {"n":"🇮🇱 TOI Iran",             "u":"https://www.timesofisrael.com/topic/iran/feed/"},
    {"n":"🇮🇱 Israel Hayom EN",      "u":"https://www.israelhayom.com/feed/"},
    {"n":"🇮🇱 Arutz Sheva",          "u":"https://www.israelnationalnews.com/rss.aspx"},
    {"n":"🇮🇱 i24 News",             "u":"https://www.i24news.tv/en/rss"},
    {"n":"🇮🇱 All Israel News",      "u":"https://www.allisrael.com/feed"},
    {"n":"🇮🇱 Israel Defense",       "u":"https://www.israeldefense.co.il/en/rss.xml"},
    {"n":"🇮🇱 Begin-Sadat BESA",     "u":"https://besacenter.org/feed/"},
    {"n":"🇮🇱 Alma Research",        "u":"https://www.alma-org.com/feed/"},
    {"n":"🇮🇱 Haaretz GNews",        "u":"https://news.google.com/rss/search?q=site:haaretz.com+Iran+military+war&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇮🇱 Ynet GNews",           "u":"https://news.google.com/rss/search?q=site:ynetnews.com+Iran+military&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇮🇱 N12 GNews",            "u":"https://news.google.com/rss/search?q=site:mako.co.il+Iran+Israel+war&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n":"🇮🇱 Kan GNews",            "u":"https://news.google.com/rss/search?q=site:kan.org.il+Iran&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n":"🇮🇱 Netanyahu Iran GNews", "u":"https://news.google.com/rss/search?q=Netanyahu+Iran+attack+order+war&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 IDF Iran GNews",       "u":"https://news.google.com/rss/search?q=IDF+operation+Iran+strike+missile&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 Mossad Iran GNews",    "u":"https://news.google.com/rss/search?q=Mossad+Iran+covert+operation&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 Iron Dome GNews",      "u":"https://news.google.com/rss/search?q=Iron+Dome+Arrow+missile+intercept+Iran&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 Barak Ravid GNews",    "u":"https://news.google.com/rss/search?q=%22Barak+Ravid%22+Iran+Israel&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇮🇱 Yossi Melman GNews",   "u":"https://news.google.com/rss/search?q=%22Yossi+Melman%22+Iran+Mossad&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇮🇱 Hezbollah Israel",     "u":"https://news.google.com/rss/search?q=Hezbollah+attack+Israel+IDF&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 IAF Strike Iran",      "u":"https://news.google.com/rss/search?q=Israeli+Air+Force+IAF+strike+Iran&hl=en-US&gl=US&ceid=US:en"},
]

# ──────────────────────────────────────────────────────────────────────────
# 🇺🇸  آمریکا  ──────────────────────────────────────────────────────────────
USA_FEEDS = [
    {"n":"🇺🇸 AP Top News",          "u":"https://feeds.apnews.com/rss/apf-topnews"},
    {"n":"🇺🇸 AP World",             "u":"https://feeds.apnews.com/rss/apf-WorldNews"},
    {"n":"🇺🇸 Reuters World",        "u":"https://feeds.reuters.com/reuters/worldNews"},
    {"n":"🇺🇸 Reuters Middle East",  "u":"https://feeds.reuters.com/reuters/MEonlineHeadlines"},
    {"n":"🇺🇸 Bloomberg Politics",   "u":"https://feeds.bloomberg.com/politics/news.rss"},
    {"n":"🇺🇸 WSJ World",            "u":"https://feeds.a.dj.com/rss/RSSWorldNews.xml"},
    {"n":"🇺🇸 CNN Middle East",      "u":"http://rss.cnn.com/rss/edition_meast.rss"},
    {"n":"🇺🇸 CNN World",            "u":"http://rss.cnn.com/rss/edition_world.rss"},
    {"n":"🇺🇸 Fox News World",       "u":"https://moxie.foxnews.com/google-publisher/world.xml"},
    {"n":"🇺🇸 Politico Defense",     "u":"https://rss.politico.com/defense.xml"},
    {"n":"🇺🇸 Foreign Policy",       "u":"https://foreignpolicy.com/feed/"},
    {"n":"🇺🇸 Pentagon DoD",         "u":"https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"n":"🇺🇸 USNI News",            "u":"https://news.usni.org/feed"},
    {"n":"🇺🇸 Breaking Defense",     "u":"https://breakingdefense.com/feed/"},
    {"n":"🇺🇸 Defense News",         "u":"https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"n":"🇺🇸 Military Times",       "u":"https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    {"n":"🇺🇸 The War Zone",         "u":"https://www.twz.com/feed"},
    {"n":"🇺🇸 War on Rocks",         "u":"https://warontherocks.com/feed/"},
    {"n":"🇺🇸 NYT Iran GNews",       "u":"https://news.google.com/rss/search?q=site:nytimes.com+Iran+Israel+war+military&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇺🇸 WaPo Iran GNews",      "u":"https://news.google.com/rss/search?q=site:washingtonpost.com+Iran+Israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇺🇸 US Strike Iran GNews", "u":"https://news.google.com/rss/search?q=United+States+strike+bomb+Iran+military&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇺🇸 US Navy Iran GNews",   "u":"https://news.google.com/rss/search?q=US+Navy+carrier+Iran+Persian+Gulf&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇺🇸 Trump Iran GNews",     "u":"https://news.google.com/rss/search?q=Trump+Iran+attack+bomb+military&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇺🇸 CENTCOM GNews",        "u":"https://news.google.com/rss/search?q=CENTCOM+Iran+Iraq+military+operation&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇺🇸 Farnaz Fassihi",       "u":"https://news.google.com/rss/search?q=%22Farnaz+Fassihi%22+Iran+nuclear&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🔍 Long War Journal",      "u":"https://www.longwarjournal.org/feed"},
    {"n":"🔍 OSINTdefender",         "u":"https://osintdefender.com/feed/"},
    {"n":"🔍 Bellingcat",            "u":"https://www.bellingcat.com/feed/"},
    {"n":"⚠️ IAEA Iran GNews",       "u":"https://news.google.com/rss/search?q=IAEA+Iran+nuclear+uranium+bomb&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"⚠️ Red Sea Houthi GNews",  "u":"https://news.google.com/rss/search?q=Houthi+Iran+Red+Sea+attack+US&hl=en-US&gl=US&ceid=US:en&num=15"},
]

# ──────────────────────────────────────────────────────────────────────────
# 🏛️  سفارتخانه‌ها
# ──────────────────────────────────────────────────────────────────────────
EMBASSY_FEEDS = [
    {"n":"🏛️ US Virtual Embassy",   "u":"https://ir.usembassy.gov/feed/"},
    {"n":"🏛️ US State Travel",      "u":"https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html.rss"},
    {"n":"🏛️ UK FCDO Iran",         "u":"https://www.gov.uk/foreign-travel-advice/iran.atom"},
    {"n":"🏛️ UK FCDO Alerts",       "u":"https://www.gov.uk/foreign-travel-advice/iran/alerts.atom"},
    {"n":"🏛️ Embassy Evacuations",  "u":"https://news.google.com/rss/search?q=embassy+evacuation+Iran+Tehran+warning&hl=en-US&gl=US&ceid=US:en&num=10"},
    {"n":"🏛️ Iran Airspace",        "u":"https://news.google.com/rss/search?q=Iran+airspace+closure+flight+ban&hl=en-US&gl=US&ceid=US:en&num=10"},
]

# ──────────────────────────────────────────────────────────────────────────
# 🌐  بین‌المللی
# ──────────────────────────────────────────────────────────────────────────
INTL_FEEDS = [
    {"n":"🌐 BBC Middle East",  "u":"https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"n":"🌐 Al Jazeera",       "u":"https://www.aljazeera.com/xml/rss/all.xml"},
    {"n":"🌐 Middle East Eye",  "u":"https://www.middleeasteye.net/rss"},
    {"n":"🌐 Al-Monitor GNews", "u":"https://news.google.com/rss/search?q=site:al-monitor.com+Iran+Israel+war&hl=en-US&gl=US&ceid=US:en"},
    {"n":"⚠️ DEFCON Iran",      "u":"https://news.google.com/rss/search?q=DEFCON+nuclear+Iran+Israel+escalation&hl=en-US&gl=US&ceid=US:en"},
]

ALL_RSS_FEEDS = IRAN_FEEDS + ISRAEL_FEEDS + USA_FEEDS + EMBASSY_FEEDS + INTL_FEEDS
EMBASSY_SET = set(id(f) for f in EMBASSY_FEEDS)

# ──────────────────────────────────────────────────────────────────────────
# 📢  کانال‌های تلگرام — خاورمیانه، خلیج‌فارس، OSINT نظامی
# ──────────────────────────────────────────────────────────────────────────
TELEGRAM_CHANNELS = [
    # OSINT نظامی — برترین
    ("🔴 Middle East Spectator", "Middle_East_Spectator"),
    ("🔴 Intel Slava Z",         "intelslava"),
    ("🔴 ELINT News",            "ELINTNews"),
    ("🔴 Megatron OSINT",        "Megatron_Ron"),
    ("🔴 Disclose TV",           "disclosetv"),
    ("🔍 Military Milk",         "militarymilk"),
    ("🔍 OSINTtechnical",        "Osinttechnical"),
    ("🔍 Iran OSINT",            "IranOSINT"),
    ("🔍 Aurora Intel",          "Aurora_Intel"),
    ("🔍 War Monitor",           "WarMonitor3"),
    # ایران
    ("🇮🇷 Iran Intl Persian",   "IranIntlPersian"),
    ("🇮🇷 تسنیم فارسی",         "tasnimnewsfa"),
    ("🇮🇷 مهر فارسی",            "mehrnews_fa"),
    ("🇮🇷 ایرنا فارسی",          "irnafarsi"),
    ("🇮🇷 Press TV",             "PressTVnews"),
    ("🇮🇷 Radio Farda",          "radiofarda"),
    # اسراییل
    ("🇮🇱 Kann News",            "kann_news"),
    ("🇮🇱 Times of Israel",      "timesofisrael"),
    # خلیج‌فارس
    ("🇸🇦 Al Arabiya Breaking",  "AlArabiya_Brk"),
    ("🇶🇦 Al Jazeera EN",        "AlJazeeraEnglish"),
    ("🇦🇪 Sky News Arabia",      "SkyNewsArabia"),
    ("🇮🇶 Al Sumaria Iraq",      "alsumaria_tv"),
    # یمن
    ("🇾🇲 Masirah TV",           "AlMasirahNet"),
    ("🇾🇲 Saba News",            "sabaafp"),
    # لبنان
    ("🇱🇧 Naharnet",             "Naharnet"),
    ("🇱🇧 LBCI News",            "LBCI_News"),
    # ترکیه
    ("🇹🇷 Yeni Safak EN",        "YeniSafakEN"),
    ("🇹🇷 TRT World",            "TRTWorldnow"),
    # بین‌المللی
    ("🌐 Reuters Breaking",      "ReutersBreaking"),
    ("🌐 AP News",               "APnews"),
    ("🌐 BBC Breaking",          "BBCBreaking"),
    ("🌐 AFP News",              "AFPnews"),
    ("🌐 GeoConfirmed",          "GeoConfirmed"),
    ("🌐 IntelCrab",             "IntelCrab"),
    ("🌐 OSINTdefender",         "OSINTdefender"),
    ("🌐 War Zone",              "TheWarZoneTW"),
    ("🌐 OSINT Ukraine",         "osint_ukr"),
    ("🌐 Warfare Analysis",      "WarfareAnalysis"),
    ("🌐 Breaking Defense",      "BreakingDefenseNews"),
]

TG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
TG_HEADERS = {"User-Agent": TG_UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.5"}

# ──────────────────────────────────────────────────────────────────────────
# 𝕏  Twitter / Nitter
# ──────────────────────────────────────────────────────────────────────────
TWITTER_HANDLES = [
    # 🇮🇷 ایران — خبرنگار / تحلیلگر
    ("🇮🇷 IRNA EN",               "IRNA_English"),
    ("🇮🇷 IranIntl EN",           "IranIntl_En"),
    ("🇮🇷 Press TV",              "PressTV"),
    ("🇮🇷 Farnaz Fassihi",        "farnazfassihi"),       # نیویورک تایمز
    ("🇮🇷 Negar Mortazavi",       "NegarMortazavi"),
    ("🇮🇷 Ali Vaez",              "AliVaez"),             # مدیر پروژه ایران / ICG
    ("🇮🇷 Golnaz Esfandiari",     "GEsfandiari"),         # خبرنگار ارشد RFE/RL
    ("🇮🇷 Sina Toossi",           "SinaToossi"),          # تحلیلگر مرکز سیاست بین‌المللی
    ("🇮🇷 Holly Dagres",          "hdagres"),             # پژوهشگر شورای آتلانتیک
    ("🇮🇷 Saeed Ghasseminejad",   "SGhasseminejad"),      # مشاور ارشد FDD
    ("🇮🇷 Kasra Aarabi",          "KasraAarabi"),         # مدیر تحقیقات سپاه / UANI
    # 🇺🇸 آمریکا — دولتی / خبرنگار / تحلیلگر
    ("🇺🇸 CENTCOM",               "CENTCOM"),
    ("🇺🇸 DoD",                   "DeptofDefense"),
    ("🇺🇸 Marco Rubio",           "marcorubio"),
    ("🇺🇸 Natasha Bertrand",      "NatashaBertrand"),     # CNN
    ("🇺🇸 Barak Ravid",           "BarakRavid"),          # Axios
    ("🇺🇸 Idrees Ali",            "idreesali114"),        # Reuters
    ("🇺🇸 Lara Seligman",         "laraseligman"),        # Politico
    ("🇺🇸 Jack Detsch",           "JackDetsch"),          # Foreign Policy
    ("🇺🇸 Trita Parsi",           "tparsi"),              # بنیان‌گذار موسسه کوئینسی
    ("🇺🇸 Barbara Slavin",        "barbaraslavin1"),      # مرکز استیمسون
    ("🇺🇸 Ian Bremmer",           "ianbremmer"),          # رئیس گروه اوراسیا
    ("🇺🇸 Jim Sciutto",           "jimsciutto"),          # تحلیلگر ارشد امنیت ملی CNN
    ("🇺🇸 Michael Knights",       "Mikeknightsiraq"),     # موسسه واشنگتن
    # 🇪🇺 اروپا — اندیشکده / خبرنگار
    ("🇪🇺 Ellie Geranmayeh",      "EllieGeranmayeh"),     # ECFR — ارشدترین کارشناس ایران اروپا
    ("🇪🇺 Carl Bildt",            "carlbildt"),           # رئیس مشترک ECFR / نخست‌وزیر سابق سوئد
    ("🇪🇺 Julien Barnes-Dacey",   "jbarnesdacey"),        # مدیر برنامه خاورمیانه ECFR
    ("🇪🇺 Neil Quilliam",         "NeilQuilliam1"),       # کارشناس خاورمیانه / Chatham House
    # 🇮🇱 اسراییل — رسمی / خبرنگار
    ("🇮🇱 IDF",                   "IDF"),
    ("🇮🇱 Israeli PM",            "IsraeliPM"),
    ("🇮🇱 Yossi Melman",          "yossi_melman"),        # Mossad / امنیت
    ("🇮🇱 Seth Frantzman",        "sfrantzman"),          # Jerusalem Post
    ("🇮🇱 Amos Harel",            "AmosHarel"),           # خبرنگار ارشد نظامی Haaretz
    ("🇮🇱 Yaakov Katz",           "yaakovkatz"),          # سردبیر سابق JP / تحلیلگر نظامی
    ("🇮🇱 Anshel Pfeffer",        "AnshelPfeffer"),       # Haaretz / The Economist
    ("🇮🇱 Anna Ahronheim",        "AAhronheim"),          # خبرنگار نظامی
    ("🇮🇱 Emanuel Fabian",        "manniefabian"),        # Times of Israel
    ("🇮🇱 Tal Schneider",         "talschneider"),        # Times of Israel دیپلماسی
    # 🔍 OSINT / پایش
    ("🔍 OSINTdefender",          "OSINTdefender"),
    ("🔍 IntelCrab",              "IntelCrab"),
    ("🔍 WarMonitor",             "WarMonitor3"),
    ("🔍 GeoConfirmed",           "GeoConfirmed"),
    ("🔍 AuroraIntel",            "AuroraIntel"),
    ("🔍 Faytuks News",           "Faytuks"),             # پوشش سریع اخبار نظامی
    ("🔍 Clash Report",           "clashreport"),         # پوشش اخبار درگیری‌ها
    ("🔍 Aric Toler",             "AricToler"),           # NYT / عضو سابق Bellingcat
    ("⚠️ DEFCONLevel",            "DEFCONLevel"),
]

# ── لیست پایه (fallback اگه status.d420.de در دسترس نبود)
#    منبع: github.com/wiki/zedeus/nitter/Instances.md  — تأیید شده ۲۰۲۶
NITTER_FALLBACK = [
    "https://xcancel.com",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nitter.tiekoetter.com",
    "https://nuku.trabun.org",
    "https://nitter.catsarch.com",
]

NITTER_CACHE_FILE = "nitter_cache.json"
NITTER_CACHE_TTL  = 3600   # ۱ ساعت — بین run‌ها در git ذخیره می‌شه
NITTER_HDR = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
    "DNT": "1",
}

# ── pool در‌حافظه — یک‌بار در هر process اجرا ساخته می‌شه
_nitter_pool: list[str] = []

# ── Rate-limit control برای Nitter ──────────────────────────────────────
# حداکثر ۴ request همزمان به کل Nitter (نه per-instance)
# بدون delay → nitter instances rate-limit می‌کنند (معمولاً ≤3 req/s)
_NITTER_SEMA: asyncio.Semaphore | None = None   # در main() مقداردهی می‌شه
# Per-instance آخرین زمان request → جلوگیری از 2 req/s به یه instance
_NITTER_INST_LAST: dict[str, float] = {}

async def _nitter_get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """
    GET با rate-limit رعایت‌شده:
    - سمافور کلی (max 4 همزمان) — مقداردهی در main()
    - فاصله ≥ 0.8 ثانیه بین request‌های یه instance
    """
    global _NITTER_SEMA
    inst = "/".join(url.split("/")[:3])   # https://xcancel.com

    sema = _NITTER_SEMA if _NITTER_SEMA is not None else asyncio.Semaphore(4)
    async with sema:
        # فاصله per-instance
        loop = asyncio.get_event_loop()
        now  = loop.time()
        last = _NITTER_INST_LAST.get(inst, 0)
        gap  = now - last
        if gap < 0.8:
            await asyncio.sleep(0.8 - gap)
        _NITTER_INST_LAST[inst] = loop.time()

        try:
            return await client.get(url, headers=NITTER_HDR, timeout=httpx.Timeout(9.0))
        except Exception as e:
            log.debug(f"𝕏 _nitter_get: {type(e).__name__} — {url[:50]}")
            return None


    try:
        if Path(NITTER_CACHE_FILE).exists():
            d = json.load(open(NITTER_CACHE_FILE))
            return d.get("instances", []), d.get("ts", 0.0)
    except: pass
    return [], 0.0

def _save_nitter_disk(instances: list[str]):
    json.dump({"instances": instances, "ts": datetime.now(timezone.utc).timestamp()},
              open(NITTER_CACHE_FILE, "w"))

async def build_nitter_pool(client: httpx.AsyncClient) -> list[str]:
    """
    ساخت pool از Nitter instances — بدون probe (سریع)
    ۱. کش git (nitter_cache.json) — TTL=1h — بین run‌ها persist می‌شه
    ۲. status.d420.de API — مرتب بر اساس points (کار می‌کنه = بهتر)
    ۳. NITTER_FALLBACK — همیشه موجود
    زمان: < 2 ثانیه (فقط یه HTTP GET)
    """
    global _nitter_pool

    if _nitter_pool:
        return _nitter_pool

    # بررسی کش git
    cached, ts = _load_nitter_disk()
    age = datetime.now(timezone.utc).timestamp() - ts
    if cached and age < NITTER_CACHE_TTL:
        log.info(f"🔌 Nitter: {len(cached)} inst از cache (age={int(age//60)}m)")
        _nitter_pool = cached
        return cached

    # واکشی از status.d420.de
    candidates: list[tuple[str, float]] = []
    try:
        r = await client.get(
            "https://status.d420.de/api/v1/instances",
            headers={"User-Agent": "WarBot/14"},
            timeout=httpx.Timeout(8.0)
        )
        if r.status_code == 200:
            for inst in r.json():
                url  = inst.get("url", "").rstrip("/")
                pts  = float(inst.get("points", 0))
                up   = inst.get("healthy", inst.get("up", False))
                if url.startswith("https://") and (up or pts > 30):
                    candidates.append((url, pts))
            candidates.sort(key=lambda x: x[1], reverse=True)
            log.info(f"🔌 status.d420.de: {len(candidates)} working inst")
    except Exception as e:
        log.warning(f"🔌 status.d420.de: {e} — fallback")

    # merge با fallback
    result_urls: list[str] = [u for u, _ in candidates[:10]]
    known = set(result_urls)
    for fb in NITTER_FALLBACK:
        if fb not in known:
            result_urls.append(fb)

    if not result_urls:
        result_urls = NITTER_FALLBACK.copy()

    _save_nitter_disk(result_urls)
    _nitter_pool = result_urls
    log.info(f"🔌 Nitter pool: {len(result_urls)} instances")
    return result_urls


# ──────────────────────────────────────────────────────────────────────────
# ✈️  ADS-B — ردیابی پروازهای نظامی
# ──────────────────────────────────────────────────────────────────────────
ADSB_API = "https://api.adsb.one/v2"
ADSB_REGIONS = [
    ("ایران",         32.4, 53.7, 250),
    ("خلیج‌فارس",    26.5, 52.0, 250),
    ("اسراییل/لبنان",32.1, 35.2, 200),
    ("عراق",          33.3, 44.4, 250),
    ("دریای سرخ",    15.0, 43.0, 250),
]
MIL_CALLSIGN_PREFIXES = {
    "RCH":"C-17 (حمل نظامی)","LAGR":"RQ-4 Global Hawk","REDEYE":"KC-135 سوخت‌رسان",
    "DUKE":"AC-130 Gunship","ROCKY":"B-52","VADER":"F-22","GRIM":"B-1B",
    "RACER":"B-2 Spirit","JAKE":"F-15E","REACH":"C-17","STEEL":"KC-46",
    "OASIS":"E-3 AWACS","COBRA":"RC-135 شناسایی","SPAR":"هواپیمای VIP",
    "SAM":"Air Force One","IRON":"F-16","ASLAN":"F-35",
}
SPECIAL_AC_TYPES = {"B52":"بمب‌افکن B-52","B1":"بمب‌افکن B-1","B2":"بمب‌افکن B-2 مخفی",
                    "F35":"جنگنده F-35","F22":"جنگنده F-22","KC135":"سوخت‌رسان KC-135",
                    "KC46":"سوخت‌رسان KC-46","E3":"AWACS","RC135":"شناسایی RC-135",
                    "RQ4":"پهپاد Global Hawk","MQ9":"پهپاد Reaper","C17":"C-17",
                    "P8":"P-8 Poseidon","C5":"C-5 Galaxy"}

def load_flight_alerts() -> dict:
    try:
        if Path(FLIGHT_ALERT_FILE).exists():
            d = json.load(open(FLIGHT_ALERT_FILE))
            cutoff = datetime.now(timezone.utc).timestamp() - 3600
            return {k:v for k,v in d.items() if v.get("t",0) > cutoff}
    except: pass
    return {}

def save_flight_alerts(d): json.dump(d, open(FLIGHT_ALERT_FILE,"w"))

async def fetch_military_flights(client: httpx.AsyncClient) -> list[dict]:
    known  = load_flight_alerts()
    alerts = []
    hdrs   = {"User-Agent":"WarBot/13"}

    for region, lat, lon, radius in ADSB_REGIONS:
        url = f"{ADSB_API}/point/{lat}/{lon}/{radius}"
        try:
            r = await client.get(url, headers=hdrs, timeout=httpx.Timeout(12.0))
            if r.status_code != 200: continue
            aircraft = r.json().get("ac", [])

            for ac in aircraft:
                db_flags = ac.get("dbFlags", 0)
                is_mil   = bool(db_flags & 1)
                typ      = (ac.get("t") or "").upper()
                call     = (ac.get("flight") or "").strip().upper()
                icao     = ac.get("hex","")
                if not icao: continue

                interesting_t = any(s in typ for s in SPECIAL_AC_TYPES)
                interesting_c = any(call.startswith(p) for p in MIL_CALLSIGN_PREFIXES)

                if not (is_mil or interesting_t or interesting_c):
                    continue

                uid = f"{icao}_{int(datetime.now(timezone.utc).timestamp()//1800)}"
                if uid in known: continue

                alt  = ac.get("alt_baro","?")
                spd  = int(ac.get("gs",0))
                lat2 = ac.get("lat",0)
                lon2 = ac.get("lon",0)
                hdg  = int(ac.get("track") or ac.get("true_heading") or 0)
                emrg = ac.get("emergency","none")
                sq   = ac.get("squawk","")
                reg  = ac.get("r","")

                type_desc = SPECIAL_AC_TYPES.get(typ, MIL_CALLSIGN_PREFIXES.get(call[:4],"هواپیمای نظامی"))
                emrg_txt  = " 🚨 اورژانس!" if emrg not in ("none","") else ""

                msg = (
                    f"✈️ <b>تحرک نظامی — {region}</b>{emrg_txt}\n"
                    f"▸ نوع: <b>{type_desc}</b>\n"
                    f"▸ کال‌ساین: {call or 'نامعلوم'}"+(f"  |  رجیستری: {reg}" if reg else "")+"\n"
                    f"▸ ارتفاع: {alt if isinstance(alt,str) else f'{int(alt):,} ft'}"
                    f"  |  سرعت: {spd} kt"+(f"  |  هدینگ: {hdg}°" if hdg else "")+"\n"
                    f"▸ موقعیت: {lat2:.2f}°N, {lon2:.2f}°E\n"
                    +(f"▸ اسکواک: {sq}" if sq and sq not in ("0000","7777","2000") else "")
                    +f"\n🔗 <a href='https://globe.adsbexchange.com/?icao={icao}'>ADS-B Exchange</a>"
                )

                known[uid] = {"t": datetime.now(timezone.utc).timestamp()}
                alerts.append(msg)
                if len(alerts) >= 4: break

        except Exception as e: log.debug(f"ADS-B {region}: {e}")

    save_flight_alerts(known)
    return alerts

# ──────────────────────────────────────────────────────────────────────────
# 🎨  کارت گرافیکی PIL
# ──────────────────────────────────────────────────────────────────────────
ACCENT_MAP = {
    "🇮🇷":(0,100,170),"🇮🇱":(0,90,200),"🇺🇸":(178,34,52),
    "🏛️":(100,70,180),"✈️":(10,130,110),"🔴":(210,40,40),
    "⚠️":(210,150,0), "🌐":(40,110,170),"🔍":(70,90,100),
    "𝕏": (15,15,15),  "📢":(50,140,200),"📡":(60,120,60),
}
BG_DARK  = (14,16,22)
BG_BAR   = (22,26,34)
FG_WHITE = (235,237,242)
FG_GREY  = (120,132,148)

def _get_accent(src:str, urgent:bool) -> tuple:
    if urgent: return (210,40,40)
    for k,v in ACCENT_MAP.items():
        if src.startswith(k) or k in src: return v
    return (80,110,140)

def _wrap_text(text:str, chars:int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur)+len(w)+1 <= chars: cur=(cur+" "+w).strip()
        else:
            if cur: lines.append(cur)
            cur=w
    if cur: lines.append(cur)
    return lines

def make_news_card(headline:str, fa_text:str, src:str, dt_str:str,
                   link:str="", urgent:bool=False,
                   sentiment_icons:list|None=None) -> io.BytesIO | None:
    """PIL کارت خبری — هدر رنگی + متن + نوار احساسات در پایین"""
    if not PIL_OK: return None
    try:
        W, H = 960, 310
        acc = _get_accent(src, urgent)
        img = Image.new("RGB", (W,H), BG_DARK)
        drw = ImageDraw.Draw(img)

        # نوار رنگی بالا
        drw.rectangle([(0,0),(W,5)], fill=acc)
        # هدر
        drw.rectangle([(0,5),(W,58)], fill=BG_BAR)
        # خط جداکننده اکسنت
        drw.rectangle([(0,58),(W,61)], fill=acc)

        try:
            F_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",14)
            F_H  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",21)
            F_em = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",20)
        except:
            F_sm=F_H=F_em=ImageFont.load_default()

        # منبع در هدر
        drw.text((18,18), src[:50], font=F_sm, fill=acc)
        drw.text((W-170,18), dt_str[:25], font=F_sm, fill=FG_GREY)

        # متن اصلی (راست‌چین برای فارسی)
        y = 72
        body = fa_text if (fa_text and fa_text!=headline and len(fa_text)>5) else headline
        for line in _wrap_text(body, 50)[:3]:
            drw.text((W-18, y), line, font=F_H, fill=FG_WHITE, anchor="ra")
            y += 34

        # ── نوار احساسات (پایین کارت)
        drw.rectangle([(0, H-56),(W, H)], fill=BG_BAR)
        drw.rectangle([(0, H-58),(W, H-56)], fill=acc)   # خط جداکننده

        ICON_BG: dict[str,tuple] = {
            "💀":(140,20,20),  "🔴":(180,30,30),  "💥":(190,80,10),
            "✈️":(20,90,160),  "🚀":(100,20,160), "☢️":(0,130,50),
            "🚢":(10,80,140),  "🕵️":(60,55,70),   "🛡️":(20,110,80),
            "🔥":(180,60,0),   "💰":(130,110,0),  "⚠️":(160,110,0),
            "🤝":(20,120,100), "📜":(60,80,100),  "📰":(45,58,72),
        }
        icons = sentiment_icons or ["📰"]
        x_pos = 16
        for ico in icons[:4]:
            bg = ICON_BG.get(ico, (50,65,75))
            drw.rounded_rectangle(
                [(x_pos-2, H-52),(x_pos+38, H-6)],
                radius=7, fill=bg)
            drw.text((x_pos+2, H-50), ico, font=F_em, fill=(255,255,255))
            x_pos += 50

        # نشانگر فوریت (نوار چپ)
        if urgent:
            drw.rectangle([(0,61),(5,H-58)], fill=acc)

        buf = io.BytesIO()
        img.save(buf,"JPEG",quality=88)
        buf.seek(0)
        return buf
    except Exception as e:
        log.debug(f"PIL card: {e}")
        return None



# ──────────────────────────────────────────────────────────────────────────
# 🎯  فیلتر جنگ
# ──────────────────────────────────────────────────────────────────────────
IRAN_KEYWORDS = [
    "iran","irgc","khamenei","tehran","iranian","revolutionary guard",
    "pasadaran","quds force","sepah","پاسداران","سپاه","ایران","خامنه‌ای",
    "hezbollah","hamas","houthi","ansarallah","حزب‌الله","حماس","حوثی",
    "pezeshkian","araghchi","zarif","قالیباف","آراقچی","ایرانی",
]
OPPONENT_KEYWORDS = [
    "israel","idf","mossad","netanyahu","tel aviv","israeli","اسراییل","نتانیاهو",
    "united states","us forces","pentagon","centcom","american","آمریکا","واشنگتن",
    "trump","rubio","us military","us navy","us air force",
    "white house","state department","کاخ سفید","آمریکایی",
]
ACTION_KEYWORDS = [
    "attack","strike","airstrike","bomb","missile","rocket","drone","war",
    "conflict","military","kill","assassin","explosion","blast","threat",
    "escalat","retaliat","nuclear","weapon","sanction","intercept",
    "shot down","destroy","invade","operation","deploy","offensive",
    "حمله","موشک","بمب","پهپاد","انفجار","جنگ","عملیات","تهدید",
    "کشته","ضربه","هسته‌ای","تحریم","تلافی","سرنگون","استقرار",
]
EMBASSY_OVERRIDE = [
    "travel advisory","security alert","leave iran","evacuate","do not travel",
    "airspace clos","flight suspend","flight ban","هشدار سفارت","ترک ایران",
]
HARD_EXCLUDE = [
    "sport","football","soccer","olympic","basketball","tennis","wrestling",
    "weather","earthquake","flood","drought","volcano","quake",
    "covid","corona","vaccine","pharmacy","hospital alone",
    "music","concert","cinema","film","actor","actress","fashion","cooking",
    "کشتی","فوتبال","ورزش","موسیقی","سینما","واکسن","زلزله","آب‌وهوا",
]

def is_war_relevant(text:str, is_embassy=False, is_tg=False, is_tw=False) -> bool:
    txt = text.lower()
    if is_embassy and any(k in txt for k in EMBASSY_OVERRIDE): return True
    if any(k in txt for k in HARD_EXCLUDE): return False
    hi = any(k in txt for k in IRAN_KEYWORDS)
    ho = any(k in txt for k in OPPONENT_KEYWORDS)
    ha = any(k in txt for k in ACTION_KEYWORDS)
    if is_tg or is_tw: return (hi or ho) and ha
    return hi and ho and ha

def is_fresh(entry: dict, cutoff: datetime) -> bool:
    """بررسی تازگی آیتم نسبت به cutoff بلادرنگ"""
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc) >= cutoff
        tg_dt = entry.get("_tg_dt")
        if tg_dt:
            return tg_dt >= cutoff
        # بدون تاریخ → بررسی URL hash کافیه (seen.json تکرار جلوگیری می‌کنه)
        return True
    except:
        return True



# ──────────────────────────────────────────────────────────────────────────
# 🧹  Dedup — سه‌لایه‌ای
#
#  لایه ۱: URL hash (seen.json)      — O(1) — تکراری کامل
#  لایه ۲: Entity Triple matching    — O(n) — تکراری معنایی (WHO+ACTION+TARGET)
#  لایه ۳: Stemmed Jaccard fallback  — O(n) — وقتی triple کوچیکه
# ──────────────────────────────────────────────────────────────────────────

# نگاشت entity → canonical code  (2 حرفی = actor، 3+ حرفی = event-type)
WHO_MAP = {
    # ایران و نیروهای نیابتی
    "iran":"IR","iranian":"IR","irgc":"IR","sepah":"IR","khamenei":"IR",
    "pasadaran":"IR","revolutionary guard":"IR","quds force":"IR",
    "ایران":"IR","ایرانی":"IR","سپاه":"IR","خامنه‌ای":"IR","پاسداران":"IR",
    "hezbollah":"HZ","حزب‌الله":"HZ","حزب الله":"HZ","نصرالله":"HZ",
    "hamas":"HA","حماس":"HA","sinwar":"HA",
    "houthi":"HT","حوثی":"HT","ansarallah":"HT","انصارالله":"HT",
    "pij":"PI","جهاد اسلامی":"PI",
    # اسراییل
    "israel":"IL","idf":"IL","israeli":"IL","mossad":"IL","netanyahu":"IL",
    "tsahal":"IL","shin bet":"IL","aman":"IL","halevi":"IL",
    "اسراییل":"IL","اسرائیل":"IL","نتانیاهو":"IL","موساد":"IL","ارتش اسرائیل":"IL",
    # آمریکا
    "united states":"US","us army":"US","us navy":"US","us air force":"US",
    "us marine":"US","us forces":"US",
    "usa":"US","american":"US","america":"US","centcom":"US","pentagon":"US",
    "trump":"US","rubio":"US","austin":"US","milley":"US",
    "آمریکا":"US","آمریکایی":"US","ترامپ":"US","سنتکام":"US","پنتاگون":"US",
    # دیگر بازیگران مرتبط
    "russia":"RU","russian":"RU","putin":"RU","روسیه":"RU","پوتین":"RU",
    "saudi":"SA","riyadh":"SA","عربستان":"SA","سعودی":"SA",
    "iaea":"IA","آژانس":"IA","گروسی":"IA",
}

ACTION_MAP = {
    # موشک / پهپاد
    "missile":"MSL","missiles":"MSL","rocket":"MSL","rockets":"MSL",
    "ballistic":"MSL","cruise missile":"MSL","hypersonic":"MSL",
    "drone":"MSL","uav":"MSL","shaheed":"MSL","shahed":"MSL",
    "launch":"MSL","launched":"MSL","fire":"MSL","fires":"MSL","fired":"MSL",
    "موشک":"MSL","راکت":"MSL","پهپاد":"MSL","شلیک":"MSL","پرتاب":"MSL",
    # حمله هوایی
    "airstrike":"AIR","airstrikes":"AIR","air strike":"AIR","air raid":"AIR",
    "bombing":"AIR","bombed":"AIR","warplane":"AIR","jet":"AIR","f-35":"AIR",
    "b-52":"AIR","b-1":"AIR","b-2":"AIR","f-15":"AIR","f-16":"AIR",
    "بمباران":"AIR","حمله هوایی":"AIR","جنگنده":"AIR",
    # حمله عمومی / عملیات
    "strike":"ATK","struck":"ATK","attack":"ATK","attacked":"ATK",
    "assault":"ATK","operation":"ATK","offensive":"ATK",
    "order":"ATK","orders":"ATK","target":"ATK","targeted":"ATK",
    "حمله":"ATK","ضربه":"ATK","عملیات":"ATK","هدف":"ATK","زد":"ATK",
    # کشته / تلفات
    "kill":"KIA","killed":"KIA","dead":"KIA","death":"KIA","casualties":"KIA",
    "assassinat":"KIA","martyr":"KIA","martyred":"KIA","fatalities":"KIA",
    "کشته":"KIA","شهید":"KIA","تلفات":"KIA","مرگ":"KIA","ترور":"KIA",
    # دفاع / رهگیری
    "intercept":"DEF","intercepted":"DEF","shot down":"DEF","shoot down":"DEF",
    "iron dome":"DEF","arrow":"DEF","david sling":"DEF","air defense":"DEF",
    "s-300":"DEF","s-400":"DEF","patriot":"DEF",
    "رهگیری":"DEF","سرنگون":"DEF","پدافند":"DEF","گنبد آهنین":"DEF",
    # تهدید
    "threat":"THR","threatens":"THR","threaten":"THR","warn":"THR","warning":"THR",
    "ultimatum":"THR","red line":"THR","consequences":"THR",
    "تهدید":"THR","هشدار":"THR","خط قرمز":"THR",
    # تحریم
    "sanction":"SAN","sanctions":"SAN","embargo":"SAN","freeze":"SAN",
    "تحریم":"SAN","تحریم‌ها":"SAN","محاصره":"SAN",
    # هسته‌ای
    "nuclear":"NUC","uranium":"NUC","natanz":"NUC","fordow":"NUC",
    "arak":"NUC","enrichment":"NUC","centrifuge":"NUC","plutonium":"NUC",
    "هسته‌ای":"NUC","نطنز":"NUC","فردو":"NUC","اراک":"NUC","اورانیوم":"NUC",
    # مذاکره / دیپلماسی
    "negotiat":"DIP","ceasefire":"DIP","deal":"DIP","diplomacy":"DIP",
    "talks":"DIP","agreement":"DIP","truce":"DIP",
    "مذاکره":"DIP","آتش‌بس":"DIP","توافق":"DIP","دیپلماسی":"DIP",
}

_STOP_EN = {"the","a","an","is","in","of","to","and","or","for","on","at",
            "by","with","from","that","this","has","are","was","were","it","not","but","be","been"}
_STOP_FA = {"در","و","از","به","با","را","که","این","آن","یا","هم","نیز","هر","اما","اگه","اگر"}

def _stem(w: str) -> str:
    """Stemming ساده انگلیسی"""
    for sfx in ("tion","ment","ing","ness","ity","ies","ed","es","s"):
        if w.endswith(sfx) and len(w) - len(sfx) > 3:
            return w[:-len(sfx)]
    return w

def _extract_triple(text: str) -> frozenset:
    """استخراج (WHO, ACTION) از متن — برای تطبیق معنایی"""
    full = re.sub(r"[^\w\u0600-\u06FF\s]", " ", text.lower())
    actors  = set()
    actions = set()
    # multi-word match اول (مهم‌تر)
    for phrase, code in sorted(WHO_MAP.items(),    key=lambda x: -len(x[0])):
        if phrase in full: actors.add(code)
    for phrase, code in sorted(ACTION_MAP.items(), key=lambda x: -len(x[0])):
        if phrase in full: actions.add(code)
    return frozenset(actors | actions)

def _stemmed_tokens(text: str) -> set:
    text = re.sub(r"[^\w\u0600-\u06FF\s]", " ", text.lower())
    stop = _STOP_EN | _STOP_FA
    return {_stem(w) for w in text.split() if w and w not in stop and len(w) > 2}

def _stemmed_jaccard(a: str, b: str) -> float:
    s1, s2 = _stemmed_tokens(a), _stemmed_tokens(b)
    return len(s1 & s2) / len(s1 | s2) if s1 and s2 else 0.0

def is_duplicate_story(title_a: str, title_b: str) -> bool:
    """
    تشخیص تکراری بودن خبر بین دو خبرگزاری مختلف
    سه لایه:
    1. Entity triple — actor مشترک + macro-category مشترک
    2. Entity triple — actor مشترک + هر event code مشترک
    3. Stemmed Jaccard ≥ JACCARD_THRESHOLD (fallback)
    """
    ta = _extract_triple(title_a)
    tb = _extract_triple(title_b)

    if len(ta) >= 2 and len(tb) >= 2:
        actors_a = {x for x in ta if len(x) == 2}
        actors_b = {x for x in tb if len(x) == 2}
        evts_a   = {x for x in ta if len(x) == 3}
        evts_b   = {x for x in tb if len(x) == 3}

        if actors_a & actors_b:
            # لایه ۱: macro-category — "fires missiles" vs "launches attack" = همون رویداد
            macro_a = bool(evts_a & _VIOLENCE_CODES) + bool(evts_a & _POLITICAL_CODES)
            macro_b = bool(evts_b & _VIOLENCE_CODES) + bool(evts_b & _POLITICAL_CODES)
            if macro_a and macro_b:
                v_match = bool(evts_a & _VIOLENCE_CODES) and bool(evts_b & _VIOLENCE_CODES)
                p_match = bool(evts_a & _POLITICAL_CODES) and bool(evts_b & _POLITICAL_CODES)
                if v_match or p_match:
                    return True

            # لایه ۲: exact event code match
            if evts_a & evts_b:
                return True

    # لایه ۳: Stemmed Jaccard
    return _stemmed_jaccard(title_a, title_b) >= JACCARD_THRESHOLD


# ── ذخیره‌سازی story fingerprint‌ها
# هر آیتم: {"fps": [fp1,fp2,...], "t": timestamp}
# fp = frozenset → list برای JSON

STORY_FILE = "stories.json"
STORY_TTL  = 7200   # 2 ساعت (مناسب برای پوشش اخبار جنگی)

def load_stories() -> list[dict]:
    try:
        if Path(STORY_FILE).exists():
            data = json.load(open(STORY_FILE))
            cutoff = datetime.now(timezone.utc).timestamp() - STORY_TTL
            return [x for x in data if x.get("t", 0) > cutoff]
    except: pass
    return []

def save_stories(records: list[dict]):
    json.dump(records[-4000:], open(STORY_FILE, "w"))

def is_story_dup(title: str, stories: list[dict]) -> bool:
    """بررسی تکراری بودن در برابر همه داستان‌های اخیر"""
    for s in stories:
        if is_duplicate_story(title, s.get("title", "")):
            return True
    return False

def register_story(title: str, stories: list[dict]) -> list[dict]:
    """ثبت داستان جدید در لیست"""
    stories.append({"title": title, "t": datetime.now(timezone.utc).timestamp()})
    return stories



# ──────────────────────────────────────────────────────────────────────────
# دریافت داده
# ──────────────────────────────────────────────────────────────────────────
COMMON_UA = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; rv:121.0) Gecko/20100101 Firefox/121.0 WarBot/13"}

async def fetch_rss(client:httpx.AsyncClient, feed:dict) -> list:
    try:
        r = await client.get(feed["u"], timeout=httpx.Timeout(12.0), headers=COMMON_UA)
        if r.status_code==200:
            entries = feedparser.parse(r.text).entries or []
            is_emb = id(feed) in EMBASSY_SET
            return [(e, feed["n"], "rss", is_emb) for e in entries]
    except: pass
    return []

async def fetch_telegram_channel(client:httpx.AsyncClient, label:str, handle:str) -> list:
    url = f"https://t.me/s/{handle}"
    try:
        r = await client.get(url, timeout=httpx.Timeout(12.0), headers=TG_HEADERS)
        if r.status_code not in (200,301,302): return []
        soup = BeautifulSoup(r.text,"html.parser")
        msgs = soup.select(".tgme_widget_message_wrap")
        if not msgs: return []

        results = []
        cutoff  = get_cutoff(TG_CUTOFF_HOURS)

        for msg in msgs[-20:]:
            txt_el = msg.select_one(".tgme_widget_message_text")
            text   = txt_el.get_text(" ",strip=True) if txt_el else ""
            if not text or len(text)<15: continue

            time_el  = msg.select_one("time")
            dt_str   = time_el.get("datetime","") if time_el else ""
            entry_dt = None
            if dt_str:
                try: entry_dt = datetime.fromisoformat(dt_str.replace("Z","+00:00"))
                except: pass

            if entry_dt and entry_dt < cutoff: continue

            link_el = msg.select_one("a.tgme_widget_message_date")
            link    = link_el.get("href","") if link_el else f"https://t.me/{handle}"

            entry = {"title":text[:200],"summary":text[:600],"link":link,"_tg_dt":entry_dt}
            results.append((entry, label, "tg", False))

        return results
    except Exception as e:
        log.debug(f"TG {handle}: {e}")
        return []

async def fetch_twitter(client: httpx.AsyncClient, label: str, handle: str) -> list:
    """
    دریافت RSS توییتر با rate-limit رعایت‌شده:
    - سمافور کلی: max 4 همزمان (از _NITTER_SEMA)
    - per-instance: ≥ 0.8s فاصله
    - rotation بر اساس hash handle → توزیع بار
    - حداکثر ۵ instance امتحان
    """
    pool = _nitter_pool or NITTER_FALLBACK
    if not pool:
        return []

    start   = abs(hash(handle)) % len(pool)
    ordered = (pool * 2)[start: start + min(5, len(pool))]

    for inst in ordered:
        url = f"{inst}/{handle}/rss"
        r   = await _nitter_get(client, url)
        if r is None:
            continue

        if r.status_code == 429:
            log.debug(f"𝕏 {handle}@{inst.split('//')[-1]}: rate-limited (429)")
            continue
        if r.status_code != 200:
            log.debug(f"𝕏 {handle}@{inst.split('//')[-1]}: HTTP {r.status_code}")
            continue

        body   = r.text
        ct     = r.headers.get("content-type", "")
        is_rss = ("xml" in ct) or body.lstrip()[:6].startswith("<?xml") or ("<rss" in body[:500])
        if not is_rss:
            log.debug(f"𝕏 {handle}@{inst.split('//')[-1]}: HTML not RSS")
            continue

        entries = feedparser.parse(body).entries
        valid   = [e for e in entries if len(e.get("title", "").strip()) > 5]
        if valid:
            log.debug(f"𝕏 ✅ {handle}: {len(valid)} tweets از {inst.split('//')[-1]}")
            return [(e, f"𝕏 {label}", "tw", False) for e in valid]

    log.debug(f"𝕏 ✗ {handle}: همه instances fail")
    return []




async def fetch_all(client: httpx.AsyncClient) -> list:
    # ── مرحله ۱: ساخت Nitter pool قبل از همه task‌ها (بدون race condition)
    log.info("🔌 ساخت Nitter pool...")
    await build_nitter_pool(client)
    pool_size = len(_nitter_pool)
    log.info(f"🔌 {pool_size} instance فعال برای {len(TWITTER_HANDLES)} handle")

    # ── مرحله ۲: همه task‌ها موازی
    rss_t = [fetch_rss(client, f) for f in ALL_RSS_FEEDS]
    tg_t  = [fetch_telegram_channel(client, l, h) for l, h in TELEGRAM_CHANNELS]
    tw_t  = [fetch_twitter(client, l, h) for l, h in TWITTER_HANDLES]

    all_res = await asyncio.gather(*rss_t, *tg_t, *tw_t, return_exceptions=True)

    out = []; rss_ok = tg_ok = tw_ok = 0
    n_rss = len(ALL_RSS_FEEDS); n_tg = len(TELEGRAM_CHANNELS)

    for i, res in enumerate(all_res):
        if not isinstance(res, list): continue
        out.extend(res)
        if i < n_rss:            rss_ok += bool(res)
        elif i < n_rss + n_tg:   tg_ok  += bool(res)
        else:                     tw_ok  += bool(res)

    log.info(f"  📡 RSS:{rss_ok}/{len(ALL_RSS_FEEDS)}  📢 TG:{tg_ok}/{len(TELEGRAM_CHANNELS)}  𝕏:{tw_ok}/{len(TWITTER_HANDLES)}")
    return out


# ──────────────────────────────────────────────────────────────────────────
# Gemini 7 مدل
# ──────────────────────────────────────────────────────────────────────────
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_POOL = [
    {"id":"gemini-2.5-flash-lite",                 "rpd":1000,"tier":1},
    {"id":"gemini-2.5-flash-lite-preview-09-2025", "rpd":1000,"tier":1},
    {"id":"gemini-2.5-flash",                      "rpd": 250,"tier":2},
    {"id":"gemini-2.5-flash-preview-09-2025",      "rpd": 250,"tier":2},
    {"id":"gemini-3-flash-preview",                "rpd": 100,"tier":3},
    {"id":"gemini-2.5-pro",                        "rpd": 100,"tier":3},
    {"id":"gemini-3-pro-preview",                  "rpd":  50,"tier":3},
]

def load_gstate():
    try:
        if Path(GEMINI_STATE_FILE).exists():
            s=json.load(open(GEMINI_STATE_FILE))
            if s.get("date")==datetime.now(timezone.utc).strftime("%Y-%m-%d"): return s
    except: pass
    return {"date":datetime.now(timezone.utc).strftime("%Y-%m-%d"),"usage":{},"fails":{}}

def save_gstate(s): json.dump(s,open(GEMINI_STATE_FILE,"w"))

def pick_models(s):
    r=[]
    for t in [1,2,3]:
        for m in GEMINI_POOL:
            if m["tier"]==t and s["usage"].get(m["id"],0)<m["rpd"] and s["fails"].get(m["id"],0)<3:
                r.append(m)
    return r or GEMINI_POOL

TRANSLATE_PROMPT = """تو یه خبرنگار جنگی حرفه‌ای هستی. خبرها رو به فارسی ساده و روان خلاصه کن.

قوانین سخت:
۱. فارسی ساده عامیانه — مثل اینکه به دوستت می‌گی
۲. یک جمله کوتاه (حداکثر دو) — خلاصه کامل خبر
۳. اسامی مهم: نتانیاهو، خامنه‌ای، سپاه، IDF، سنتکام...
۴. 🔴 = حمله/جنگ/کشته  ⚠️ = تهدید/موضع  🏛️ = سفارتخانه  ✈️ = تحرک هوایی  📢 = کانال تلگرام
۵. هیچ توضیح اضافه ندی
۶. پیام‌های عربی/فارسی تلگرامی رو دقیق ترجمه کن

مثال:
- "🔴 اسرائیل امشب با موشک به رآکتور فردو حمله کرد"
- "⚠️ خامنه‌ای: اگه آمریکا وارد جنگ بشه پایگاه‌هاشون هدفه"
- "🏛️ سفارت آمریکا: همه شهروندان آمریکایی ایران رو فوری ترک کنن"
- "✈️ بمب‌افکن B-52 در خلیج‌فارس رصد شد"

فرمت:
###ITEM_0###
[خلاصه فارسی]
###ITEM_1###
[خلاصه فارسی]

===خبرها===
{items}"""

async def translate_batch(client:httpx.AsyncClient, articles:list) -> list:
    if not GEMINI_API_KEY or not articles: return articles
    items_txt = "".join(f"###ITEM_{i}###\nTITLE: {t[:280]}\nBODY: {s[:350]}\n" for i,(t,s) in enumerate(articles))
    payload = {"contents":[{"parts":[{"text":TRANSLATE_PROMPT.format(items=items_txt)}]}],
               "generationConfig":{"temperature":0.1,"maxOutputTokens":8192}}
    state = load_gstate()

    for m in pick_models(state):
        mid=m["id"]; used=state["usage"].get(mid,0)
        url=f"{GEMINI_BASE}/{mid}:generateContent?key={GEMINI_API_KEY}"
        log.info(f"🌐 Gemini [{mid[:28]}] {used}/{m['rpd']}")
        for _ in range(2):
            try:
                r = await client.post(url, json=payload, timeout=httpx.Timeout(90.0))
                if r.status_code==200:
                    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    res = _parse_tr(raw, articles)
                    state["usage"][mid]=used+1; state["fails"][mid]=0
                    save_gstate(state)
                    return res
                elif r.status_code==429:
                    w=int(r.headers.get("Retry-After","30"))
                    state["fails"][mid]=state["fails"].get(mid,0)+1
                    await asyncio.sleep(min(w,15)); break
                else: break
            except asyncio.TimeoutError: break
            except: break

    save_gstate(state)
    return articles

def _parse_tr(raw:str, fallback:list) -> list:
    results=list(fallback)
    for m in re.finditer(r'###ITEM_(\d+)###\s*\n(.+?)(?=###ITEM_|\Z)',raw,re.DOTALL):
        idx=int(m.group(1)); text=m.group(2).strip().replace("**","").replace("*","")
        if 0<=idx<len(results) and text: results[idx]=(nfa(text),"")
    return results

# ──────────────────────────────────────────────────────────────────────────
# ابزارها
# ──────────────────────────────────────────────────────────────────────────
def clean_html(t:str) -> str:
    return BeautifulSoup(str(t or ""),"html.parser").get_text(" ",strip=True)

def make_id(entry:dict) -> str:
    k=entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(k.encode()).hexdigest()

def format_dt(entry:dict) -> str:
    try:
        t=entry.get("published_parsed") or entry.get("updated_parsed")
        if t: return datetime(*t[:6],tzinfo=timezone.utc).astimezone(TEHRAN_TZ).strftime("🕐 %H:%M  |  %d %b")
        tg_dt=entry.get("_tg_dt")
        if tg_dt: return tg_dt.astimezone(TEHRAN_TZ).strftime("🕐 %H:%M  |  %d %b")
    except: pass
    return datetime.now(TEHRAN_TZ).strftime("🕐 %H:%M")

def esc(t:str) -> str: return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def trim(t:str, n:int) -> str:
    t=re.sub(r'\s+',' ',t).strip()
    return t if len(t)<=n else t[:n].rsplit(" ",1)[0]+"…"

def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        try: return set(json.load(open(SEEN_FILE)))
        except: pass
    return set()

def save_seen(seen: set):
    json.dump(list(seen)[-30000:], open(SEEN_FILE, "w"))

# ── زمان آخرین اجرا برای cutoff بلادرنگ ──
RUN_STATE_FILE = "run_state.json"
REALTIME_BUFFER_MIN = 3    # ۳ دقیقه buffer برای جبران تأخیر RSS
MAX_LOOKBACK_MIN    = 20   # اگه اولین بار است، ۲۰ دقیقه به عقب برو

def load_last_run() -> datetime:
    """زمان آخرین اجرای موفق"""
    try:
        if Path(RUN_STATE_FILE).exists():
            d = json.load(open(RUN_STATE_FILE))
            ts = d.get("last_run", 0)
            if ts:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
    except: pass
    # اولین اجرا: ۲۰ دقیقه پیش
    return datetime.now(timezone.utc) - timedelta(minutes=MAX_LOOKBACK_MIN)

def save_last_run():
    json.dump({"last_run": datetime.now(timezone.utc).timestamp()}, open(RUN_STATE_FILE, "w"))

def get_realtime_cutoff() -> datetime:
    """
    cutoff بلادرنگ = آخرین اجرا - BUFFER
    حداکثر ۲۰ دقیقه به عقب (جلوگیری از پردازش بیش از حد)
    """
    last = load_last_run()
    cutoff_from_last = last - timedelta(minutes=REALTIME_BUFFER_MIN)
    cutoff_max = datetime.now(timezone.utc) - timedelta(minutes=MAX_LOOKBACK_MIN)
    return max(cutoff_from_last, cutoff_max)



# ──────────────────────────────────────────────────────────────────────────
# تلگرام
# ──────────────────────────────────────────────────────────────────────────
TGAPI=f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_send_text(client:httpx.AsyncClient, text:str) -> bool:
    for _ in range(4):
        try:
            r=await client.post(f"{TGAPI}/sendMessage", json={
                "chat_id":CHANNEL_ID,"text":text[:MAX_MSG_LEN],
                "parse_mode":"HTML","disable_web_page_preview":True,
            }, timeout=httpx.Timeout(15.0))
            d=r.json()
            if d.get("ok"): return True
            if d.get("error_code")==429: await asyncio.sleep(d.get("parameters",{}).get("retry_after",20))
            elif d.get("error_code") in (400,403): return False
            else: await asyncio.sleep(5)
        except Exception as e: log.warning(f"TG: {e}"); await asyncio.sleep(8)
    return False

async def tg_send_photo(client:httpx.AsyncClient, buf:io.BytesIO, caption:str) -> bool:
    try:
        r=await client.post(f"{TGAPI}/sendPhoto",
            data={"chat_id":CHANNEL_ID,"caption":caption[:1024],"parse_mode":"HTML"},
            files={"photo":("card.jpg",buf,"image/jpeg")},
            timeout=httpx.Timeout(30.0))
        return r.json().get("ok",False)
    except Exception as e: log.warning(f"TG photo: {e}"); return False

# ──────────────────────────────────────────────────────────────────────────
# 🎭  تحلیل احساسات و دسته‌بندی خبر با آیکون‌های گرافیکی
#
#  منطق اولویت‌بندی (از بالاترین به پایین‌ترین شدت):
#   ۱. تلفات انسانی  → 💀
#   ۲. حمله فعال     → 🔴
#   ۳. انفجار        → 💥
#   ۴. حمله هوایی    → ✈️
#   ۵. موشک/پهپاد    → 🚀
#   ۶. هسته‌ای       → ☢️
#   ۷. دریایی        → 🚢
#   ۸. اطلاعاتی      → 🕵️
#   ۹. دفاع/رهگیری   → 🛡️
#  ۱۰. تشدید         → 🔥
#  ۱۱. تحریم         → 💰
#  ۱۲. تهدید         → ⚠️
#  ۱۳. دیپلماسی      → 🤝
#  ۱۴. بیانیه        → 📜
# ──────────────────────────────────────────────────────────────────────────
SENTIMENT_RULES: list[tuple[str, list[str], list[str]]] = [
    # (icon, کلیدواژه‌های EN, کلیدواژه‌های FA)
    ("💀", ["killed","dead","casualties","deaths","fatalities","wounded","injure",
            "martyred","massacre","civilian death","body count"],
           ["کشته","شهید","شهدا","تلفات","کشتار","قربانی","مجروح","فوت"]),

    ("🔴", ["attack","struck","assault","offensive","launched attack","opened fire",
            "under attack","targeted","hit by","bombed"],
           ["حمله","ضربه","زده شد","حمله کرد","مورد هدف"]),

    ("💥", ["explosion","blast","detonation","explode","blew up","bomb went off",
            "shockwave","blast wave"],
           ["انفجار","منفجر","انفجار بزرگ","صدای انفجار","ترکید"]),

    ("✈️", ["airstrike","air strike","air raid","aerial bombardment","jet","fighter jet",
            "bombing raid","warplane","f-35","f-15","f-16","b-52","b-2","b-1"],
           ["حمله هوایی","بمباران","جنگنده","هواپیمای جنگی","هوایی"]),

    ("🚀", ["missile","rocket","ballistic","cruise missile","drone strike",
            "uav attack","unmanned","hypersonic","icbm","projectile"],
           ["موشک","پهپاد","موشک بالستیک","موشک کروز","پرتاب موشک","راکت"]),

    ("☢️", ["nuclear","uranium","enrichment","natanz","fordow","arak","centrifuge",
            "radioactive","dirty bomb","atomic","plutonium","iaea","npt"],
           ["هسته‌ای","اتمی","اورانیوم","غنی‌سازی","نطنز","فردو","اراک","سانتریفیوژ","هسته"]),

    ("🚢", ["navy","naval","warship","destroyer","aircraft carrier","frigate",
            "submarine","strait of hormuz","red sea","persian gulf patrol","coast guard"],
           ["نیروی دریایی","ناوچه","ناو","ناو هواپیمابر","تنگه هرمز","دریایی","خلیج فارس"]),

    ("🕵️", ["intelligence","mossad","cia","spy","covert","assassination","sabotage",
            "cyber attack","hacking","infiltrat","agent","operativ"],
           ["اطلاعاتی","جاسوسی","موساد","عملیات مخفی","خرابکاری","ترور","سایبری","نفوذ"]),

    ("🛡️", ["intercept","shot down","iron dome","arrow missile","david sling",
            "air defense","patriot","s-300","s-400","anti-missile","shoot down"],
           ["رهگیری","پدافند","گنبد آهنین","سرنگون کرد","سامانه موشکی","ضد موشک"]),

    ("🔥", ["escalat","escalation","tension","brink of war","imminent","standoff",
            "heighten","provocation","retaliat","tit for tat","cross the line"],
           ["تشدید","تنش","آستانه جنگ","تلافی","لبه پرتگاه","افزایش تنش"]),

    ("💰", ["sanction","embargo","freeze assets","economic pressure","export ban",
            "oil ban","swift","financial restriction","maximum pressure"],
           ["تحریم","تحریم‌ها","محاصره اقتصادی","فشار اقتصادی","مسدود کردن دارایی"]),

    ("⚠️", ["threat","warn","warning","ultimatum","red line","consequences",
            "take action","will respond","prepare for","on alert"],
           ["تهدید","هشدار","خط قرمز","اولتیماتوم","عواقب","آماده‌باش","واکنش نشان"]),

    ("🤝", ["negotiation","talks","deal","diplomacy","ceasefire","agreement",
            "summit","meeting","envoy","dialogue","diplomatic"],
           ["مذاکره","توافق","دیپلماسی","آتش‌بس","گفتگو","نشست","دیپلماتیک","میانجی"]),

    ("📜", ["statement","declared","announced","said","confirmed","denied",
            "press conference","official","spokesperson","briefing"],
           ["بیانیه","اعلام","اعلام کرد","تأیید کرد","نفی کرد","نشست خبری","سخنگو"]),
]

def analyze_sentiment(text: str) -> list[str]:
    """
    تحلیل متن خبر و برگرداندن لیست آیکون‌های احساسی
    - حداکثر ۳ آیکون برجسته‌ترین موضوعات
    - اولویت‌بندی بر اساس ترتیب قوانین (شدیدترین اول)
    """
    txt = text.lower()
    found: list[str] = []
    for icon, en_kws, fa_kws in SENTIMENT_RULES:
        if any(kw in txt for kw in en_kws) or any(kw in txt for kw in fa_kws):
            found.append(icon)
        if len(found) >= 3:
            break
    return found if found else ["📰"]  # پیش‌فرض: خبر معمولی

def sentiment_bar(icons: list[str]) -> str:
    """خط نمایش آیکون‌های احساسی"""
    return "  ".join(icons)


async def main():
    global _NITTER_SEMA
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID نیست!"); return

    # ── Nitter rate-limit semaphore (یه بار per run)
    _NITTER_SEMA = asyncio.Semaphore(4)   # max 4 Nitter request همزمان از کل 47 handle

    seen    = load_seen()
    stories = load_stories()
    cutoff  = get_realtime_cutoff()

    log.info("=" * 65)
    log.info(f"🚀 WarBot v14  |  {datetime.now(TEHRAN_TZ).strftime('%H:%M تهران')}")
    log.info(f"   📡 {len(ALL_RSS_FEEDS)} RSS  📢 {len(TELEGRAM_CHANNELS)} TG  𝕏 {len(TWITTER_HANDLES)} TW  ✈️ ADS-B")
    log.info(f"   🎨 PIL: {'✅' if PIL_OK else '❌'}  |  🧠 Triple+Stemmed dedup")
    log.info(f"   ⏱  cutoff: {cutoff.astimezone(TEHRAN_TZ).strftime('%H:%M')} تهران")
    log.info(f"   💾 seen:{len(seen)}  stories:{len(stories)}")
    log.info("=" * 65)

    limits = httpx.Limits(max_connections=60, max_keepalive_connections=20)
    async with httpx.AsyncClient(follow_redirects=True, limits=limits) as client:

        # ── ردیابی نظامی هوایی
        log.info("✈️ ADS-B ردیابی...")
        flight_msgs = await fetch_military_flights(client)
        log.info(f"  ✈️ {len(flight_msgs)} تحرک نظامی")

        # ── دریافت منابع (Nitter pool قبلاً داخل fetch_all ساخته می‌شه)
        log.info("⏬ دریافت منابع...")
        raw = await fetch_all(client)
        log.info(f"📥 {len(raw)} آیتم خام")

        # ── پردازش — سه لایه dedup
        collected = []
        cnt_old = cnt_irrel = cnt_url = cnt_story = 0

        for entry, src_name, src_type, is_emb in raw:
            eid = make_id(entry)

            # لایه ۱: URL hash
            if eid in seen:
                cnt_url += 1; continue

            # لایه ۲: تازگی (cutoff بلادرنگ)
            if not is_fresh(entry, cutoff):
                seen.add(eid); cnt_old += 1; continue

            t    = clean_html(entry.get("title", ""))
            s    = clean_html(entry.get("summary") or entry.get("description") or "")
            full = f"{t} {s}"

            # فیلتر موضوعی
            if not is_war_relevant(full, is_embassy=is_emb,
                                   is_tg=(src_type == "tg"), is_tw=(src_type == "tw")):
                seen.add(eid); cnt_irrel += 1; continue

            # لایه ۳: story dedup (entity triple + stemmed jaccard)
            if is_story_dup(t, stories):
                seen.add(eid); cnt_story += 1; continue

            collected.append((eid, entry, src_name, src_type, is_emb))
            stories = register_story(t, stories)

        log.info(
            f"📊 قدیمی:{cnt_old}  نامرتبط:{cnt_irrel}  "
            f"url-dup:{cnt_url}  story-dup:{cnt_story}  ✅ {len(collected)} خبر جنگی"
        )

        # قدیمی‌ترین اول — حداکثر MAX_NEW_PER_RUN
        collected = list(reversed(collected))
        if len(collected) > MAX_NEW_PER_RUN:
            log.warning(f"⚠️ {len(collected)} → {MAX_NEW_PER_RUN}")
            collected = collected[-MAX_NEW_PER_RUN:]

        # ── ارسال تحرکات هوایی (اولویت بالا)
        for msg in flight_msgs[:3]:
            await tg_send_text(client, msg)
            await asyncio.sleep(SEND_DELAY)

        if not collected:
            log.info("💤 خبر جنگی جدیدی نیست")
            save_seen(seen); save_stories(stories); save_last_run(); return

        # ── ترجمه Gemini
        arts_in = [
            (trim(clean_html(e.get("title", "")), 280),
             trim(clean_html(e.get("summary") or e.get("description") or ""), 350))
            for _, e, _, _, _ in collected
        ]
        if GEMINI_API_KEY:
            log.info(f"🌐 ترجمه {len(arts_in)} خبر...")
            translations = await translate_batch(client, arts_in)
        else:
            translations = arts_in

        # ── ارسال
        sent = 0
        for i, (eid, entry, src_name, stype, is_emb) in enumerate(collected):
            fa, _    = translations[i]
            en_title = arts_in[i][0]
            en_body  = arts_in[i][1]
            dt_str   = format_dt(entry)
            display  = fa if (fa and fa != en_title and len(fa) > 5) else en_title
            urgent   = any(w in (fa + en_title).lower() for w in
                           ["attack", "strike", "airstrike", "killed", "bomb",
                            "حمله", "کشته", "انفجار", "موشک", "بمباران"])

            # تحلیل احساسات
            sentiment_icons = analyze_sentiment(f"{fa} {en_title} {en_body}")
            s_bar = sentiment_bar(sentiment_icons)

            src_icon  = "🏛️" if is_emb else ("𝕏" if stype == "tw" else ("📢" if stype == "tg" else "📡"))
            card_sent = False

            if PIL_OK:
                buf = make_news_card(en_title, fa if fa != en_title else "",
                                     src_name, dt_str, "", urgent, sentiment_icons)
                if buf:
                    cap = f"{s_bar}\n\n<b>{esc(display)}</b>\n\n{src_icon} <b>{esc(src_name)}</b>  {dt_str}"
                    if await tg_send_photo(client, buf, cap):
                        card_sent = True

            if not card_sent:
                parts = [s_bar, f"<b>{esc(display)}</b>", "",
                         f"─── {src_icon} <b>{esc(src_name)}</b>"]
                if dt_str: parts.append(dt_str)
                if await tg_send_text(client, "\n".join(parts)):
                    card_sent = True

            if card_sent:
                seen.add(eid); sent += 1
                log.info(f"  ✅ [{stype}] {display[:60]}")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        save_stories(stories)
        save_last_run()
        log.info(f"🏁 {sent}/{len(collected)} خبر + {len(flight_msgs)} تحرک هوایی ارسال شد")



if __name__=="__main__":
    asyncio.run(main())
