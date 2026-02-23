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
JACCARD_THRESHOLD = 0.40
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

NITTER_INSTANCES = [
    "https://nitter.poast.org",           # پایدارترین — اول امتحان می‌شه
    "https://xcancel.com",                # پایدار با Cloudflare
    "https://twiiit.com",                 # پروکسی هوشمند → سرور فعال
    "https://nitter.cz",                  # ریدایرکت به سرور خوب
    "https://nitter.privacyredirect.com",
    "https://nitter.tiekoetter.com",
    "https://nuku.trabun.org",
    "https://nitter.catsarch.com",
]
NITTER_HDR = {"User-Agent": TG_UA, "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"}

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
                   link:str="", urgent:bool=False) -> io.BytesIO | None:
    if not PIL_OK: return None
    try:
        W, H = 960, 300
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
            F_b  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",17)
            F_xs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",12)
        except:
            F_sm=F_H=F_b=F_xs=ImageFont.load_default()

        # منبع در هدر
        drw.text((18,18), src[:50], font=F_sm, fill=acc)
        drw.text((W-170,18), dt_str[:25], font=F_sm, fill=FG_GREY)

        # متن اصلی
        y=76
        body = fa_text if (fa_text and fa_text!=headline and len(fa_text)>5) else headline
        for line in _wrap_text(body, 50)[:4]:
            drw.text((W-18, y), line, font=F_H, fill=FG_WHITE, anchor="ra")
            y+=34

        # پاورقی
        drw.rectangle([(0,H-42),(W,H)], fill=BG_BAR)
        if link:
            short = link[:70]+"…" if len(link)>70 else link
            drw.text((18,H-26), f"↗ {short}", font=F_xs, fill=FG_GREY)

        # نشانگر فوریت (نوار چپ)
        if urgent:
            drw.rectangle([(0,61),(5,H-42)], fill=acc)

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

def is_fresh(entry:dict, hours:float=None) -> bool:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t: return datetime(*t[:6], tzinfo=timezone.utc) >= get_cutoff(hours or CUTOFF_HOURS)
        tg_dt = entry.get("_tg_dt")
        if tg_dt: return tg_dt >= get_cutoff(hours or CUTOFF_HOURS)
        return True  # بدون تاریخ → پردازش می‌کنیم
    except: return True

# ──────────────────────────────────────────────────────────────────────────
# 🧹  Dedup معنایی Jaccard
# ──────────────────────────────────────────────────────────────────────────
STOPWORDS = {
    "the","a","an","is","in","of","to","and","or","for","on","at","by","with",
    "that","this","from","has","are","was","were","be","been","it","not","but",
    "در","و","از","به","با","را","که","این","آن","یا","هم","نیز","هر","اما",
}

def tokens(t:str) -> set:
    t = re.sub(r'[^\w\u0600-\u06FF\s]',' ',t.lower())
    return {w for w in t.split() if w and w not in STOPWORDS and len(w)>2}

def jaccard(a:str, b:str) -> float:
    s1,s2 = tokens(a),tokens(b)
    if not s1 or not s2: return 0.0
    return len(s1&s2)/len(s1|s2)

def load_title_hashes() -> list:
    try:
        if Path(TITLE_HASH_FILE).exists():
            d = json.load(open(TITLE_HASH_FILE))
            cutoff = datetime.now(timezone.utc).timestamp()-10800
            return [x for x in d if x.get("t",0)>cutoff]
    except: pass
    return []

def save_title_hashes(records:list): json.dump(records[-3000:], open(TITLE_HASH_FILE,"w"))

def is_semantic_dup(title:str, records:list) -> bool:
    return any(jaccard(title, r.get("txt","")) >= JACCARD_THRESHOLD for r in records)

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

async def fetch_twitter(client:httpx.AsyncClient, label:str, handle:str) -> list:
    instances = NITTER_INSTANCES.copy(); random.shuffle(instances[1:])
    for inst in instances[:4]:
        try:
            r = await client.get(f"{inst}/{handle}/rss", timeout=httpx.Timeout(9.0), headers=NITTER_HDR)
            if r.status_code==200 and len(r.text)>300:
                entries = feedparser.parse(r.text).entries
                if entries and entries[0].get("title"):
                    return [(e, f"𝕏 {label}", "tw", False) for e in entries]
        except: continue
    return []

async def fetch_all(client:httpx.AsyncClient) -> list:
    rss_t = [fetch_rss(client, f) for f in ALL_RSS_FEEDS]
    tg_t  = [fetch_telegram_channel(client, l, h) for l,h in TELEGRAM_CHANNELS]
    tw_t  = [fetch_twitter(client, l, h) for l,h in TWITTER_HANDLES]

    all_res = await asyncio.gather(*rss_t, *tg_t, *tw_t, return_exceptions=True)

    out=[]; rss_ok=tg_ok=tw_ok=0
    n_rss=len(ALL_RSS_FEEDS); n_tg=len(TELEGRAM_CHANNELS)

    for i,res in enumerate(all_res):
        if not isinstance(res,list): continue
        out.extend(res)
        if i<n_rss:          rss_ok+=bool(res)
        elif i<n_rss+n_tg:   tg_ok +=bool(res)
        else:                  tw_ok +=bool(res)

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

def save_seen(seen:set): json.dump(list(seen)[-25000:],open(SEEN_FILE,"w"))

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
# حلقه اصلی
# ──────────────────────────────────────────────────────────────────────────
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID نیست!"); return

    seen         = load_seen()
    title_hashes = load_title_hashes()

    log.info("="*65)
    log.info(f"🚀 WarBot v13  |  {datetime.now(TEHRAN_TZ).strftime('%H:%M تهران')}")
    log.info(f"   📡 {len(ALL_RSS_FEEDS)} RSS  📢 {len(TELEGRAM_CHANNELS)} TG  𝕏 {len(TWITTER_HANDLES)} TW  ✈️ ADS-B")
    log.info(f"   🎨 PIL: {'✅' if PIL_OK else '❌'}  |  🧠 Jaccard({JACCARD_THRESHOLD})")
    log.info(f"   💾 seen:{len(seen)}  hashes:{len(title_hashes)}")
    log.info("="*65)

    async with httpx.AsyncClient(follow_redirects=True) as client:

        # ── ردیابی نظامی هوایی
        log.info("✈️ ADS-B ردیابی...")
        flight_msgs = await fetch_military_flights(client)
        log.info(f"  ✈️ {len(flight_msgs)} تحرک نظامی")

        # ── دریافت منابع
        log.info("⏬ دریافت منابع...")
        raw = await fetch_all(client)
        log.info(f"📥 {len(raw)} آیتم خام")

        # ── پردازش
        collected = []
        old=irrel=url_dup=sem_dup=0

        for entry, src_name, src_type, is_emb in raw:
            eid = make_id(entry)
            if eid in seen: url_dup+=1; continue

            hours = TG_CUTOFF_HOURS if src_type=="tg" else CUTOFF_HOURS
            if not is_fresh(entry, hours): seen.add(eid); old+=1; continue

            t = clean_html(entry.get("title",""))
            s = clean_html(entry.get("summary") or entry.get("description") or "")
            full = f"{t} {s}"

            if not is_war_relevant(full, is_embassy=is_emb, is_tg=(src_type=="tg"), is_tw=(src_type=="tw")):
                seen.add(eid); irrel+=1; continue

            if is_semantic_dup(t, title_hashes): seen.add(eid); sem_dup+=1; continue

            collected.append((eid, entry, src_name, src_type, is_emb))
            title_hashes.append({"txt":t, "t":datetime.now(timezone.utc).timestamp()})

        log.info(f"📊 قدیمی:{old}  نامرتبط:{irrel}  url-dup:{url_dup}  sem-dup:{sem_dup}  ✅ {len(collected)} خبر جنگی")

        collected = list(reversed(collected))
        if len(collected)>MAX_NEW_PER_RUN:
            log.warning(f"⚠️ {len(collected)} → {MAX_NEW_PER_RUN}")
            collected = collected[-MAX_NEW_PER_RUN:]

        # ── ارسال تحرکات هوایی (اولویت)
        for msg in flight_msgs[:3]:
            await tg_send_text(client, msg)
            await asyncio.sleep(SEND_DELAY)

        if not collected:
            log.info("💤 خبر جنگی جدیدی نیست")
            save_seen(seen); save_title_hashes(title_hashes); return

        # ── ترجمه
        arts_in = [(trim(clean_html(e.get("title","")),280), trim(clean_html(e.get("summary") or e.get("description") or ""),350))
                   for _,e,_,_,_ in collected]
        if GEMINI_API_KEY:
            log.info(f"🌐 ترجمه {len(arts_in)} خبر...")
            translations = await translate_batch(client, arts_in)
        else:
            translations = arts_in

        # ── ارسال
        sent=0
        for i, (eid, entry, src_name, stype, is_emb) in enumerate(collected):
            fa, _   = translations[i]
            en_title = arts_in[i][0]
            link     = entry.get("link","")
            dt_str   = format_dt(entry)
            display  = fa if (fa and fa!=en_title and len(fa)>5) else en_title
            urgent   = any(w in (fa+en_title).lower() for w in
                          ["attack","strike","airstrike","killed","حمله","کشته","انفجار","موشک","bomb"])

            src_icon = "🏛️" if is_emb else ("𝕏" if stype=="tw" else ("📢" if stype=="tg" else "📡"))
            card_sent = False

            if PIL_OK:
                buf = make_news_card(en_title, fa if fa!=en_title else "", src_name, dt_str, link, urgent)
                if buf:
                    cap = f"<b>{esc(display)}</b>\n\n{src_icon} <b>{esc(src_name)}</b>  {dt_str}"
                    if await tg_send_photo(client, buf, cap):
                        card_sent=True

            if not card_sent:
                parts=[f"<b>{esc(display)}</b>","",f"─── {src_icon} <b>{esc(src_name)}</b>"]
                if dt_str: parts.append(dt_str)
                if urgent: parts.insert(0,"🔴")
                if await tg_send_text(client, "\n".join(parts)):
                    card_sent=True

            if card_sent:
                seen.add(eid); sent+=1
                log.info(f"  ✅ [{stype}] {display[:55]}")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        save_title_hashes(title_hashes)
        log.info(f"🏁 {sent}/{len(collected)} خبر + {len(flight_msgs)} تحرک هوایی ارسال شد")

if __name__=="__main__":
    asyncio.run(main())
