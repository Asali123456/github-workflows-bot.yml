import os, json, hashlib, asyncio, logging, re, random
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("WarBot")

BOT_TOKEN       = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID      = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")

SEEN_FILE        = "seen.json"
GEMINI_STATE_FILE= "gemini_state.json"
MAX_NEW_PER_RUN  = 25
MAX_MSG_LEN      = 4096
SEND_DELAY       = 2
CUTOFF_HOURS     = 4      # ← ۵ دقیقه = نیاز به ۴-۶ ساعت برای feed‌های کند
TEHRAN_TZ        = pytz.timezone("Asia/Tehran")

def get_cutoff():
    return datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)

# ══════════════════════════════════════════════════════════════════════
# 🇮🇷  ۵۰ خبرگزاری و رسانه ایران
# ══════════════════════════════════════════════════════════════════════
IRAN_FEEDS = [
    # ── رسمی / دولتی (انگلیسی) ──
    {"n": "🇮🇷 IRNA English",        "u": "https://en.irna.ir/rss"},
    {"n": "🇮🇷 Mehr News EN",         "u": "https://en.mehrnews.com/rss"},
    {"n": "🇮🇷 Tasnim News EN",       "u": "https://www.tasnimnews.com/en/rss"},
    {"n": "🇮🇷 Fars News EN",         "u": "https://www.farsnews.ir/rss"},
    {"n": "🇮🇷 Press TV",             "u": "https://www.presstv.ir/rss"},
    {"n": "🇮🇷 ISNA English",         "u": "https://en.isna.ir/rss"},
    {"n": "🇮🇷 Tehran Times",         "u": "https://www.tehrantimes.com/rss"},
    {"n": "🇮🇷 Iran Daily",           "u": "https://www.iran-daily.com/rss"},
    {"n": "🇮🇷 IRIB World Svc EN",    "u": "https://en.irib.ir/rss"},
    {"n": "🇮🇷 Iran Front Page",      "u": "https://ifpnews.com/feed"},
    # ── مستقل / دیاسپورا ──
    {"n": "🇮🇷 Iran International",   "u": "https://www.iranintl.com/en/rss"},
    {"n": "🇮🇷 Radio Farda",          "u": "https://www.radiofarda.com/api/zoyqvpemr"},
    {"n": "🇮🇷 Iran Wire EN",         "u": "https://iranwire.com/en/feed/"},
    {"n": "🇮🇷 Kayhan London",        "u": "https://kayhan.london/feed/"},
    {"n": "🇮🇷 Iran Human Rights",    "u": "https://iranhr.net/en/feed/"},
    # ── فارسی — خبرگزاری‌های مهم ──
    {"n": "🇮🇷 خبرگزاری تسنیم",       "u": "https://www.tasnimnews.com/fa/rss/feed/0/8/0"},
    {"n": "🇮🇷 خبرگزاری مهر",          "u": "https://www.mehrnews.com/rss"},
    {"n": "🇮🇷 خبرگزاری ایرنا",        "u": "https://www.irna.ir/rss"},
    {"n": "🇮🇷 خبرگزاری ایسنا",        "u": "https://www.isna.ir/rss"},
    {"n": "🇮🇷 خبرگزاری فارس",         "u": "https://www.farsnews.ir/rss/fa"},
    {"n": "🇮🇷 خبرگزاری دانشجو",       "u": "https://snn.ir/rss"},
    {"n": "🇮🇷 خبرگزاری میزان",         "u": "https://www.mizanonline.ir/rss"},
    {"n": "🇮🇷 خبرگزاری برنا",          "u": "https://www.borna.news/rss"},
    {"n": "🇮🇷 خبرگزاری ایلنا",         "u": "https://www.ilna.ir/rss"},
    {"n": "🇮🇷 خبرگزاری صدا و سیما",    "u": "https://www.iribnews.ir/fa/rss"},
    # ── فارسی — پایگاه‌های خبری ──
    {"n": "🇮🇷 خبر آنلاین",             "u": "https://www.khabaronline.ir/rss"},
    {"n": "🇮🇷 انتخاب",                 "u": "https://www.entekhab.ir/rss"},
    {"n": "🇮🇷 مشرق نیوز",              "u": "https://www.mashreghnews.ir/rss"},
    {"n": "🇮🇷 تابناک",                 "u": "https://www.tabnak.ir/fa/rss/allnews"},
    {"n": "🇮🇷 فرارو",                  "u": "https://fararu.com/rss"},
    {"n": "🇮🇷 رجانیوز",               "u": "https://rajanews.com/rss"},
    {"n": "🇮🇷 اصفهان زیبا",           "u": "https://www.isfahanziba.ir/rss"},
    {"n": "🇮🇷 آفتاب نیوز",             "u": "https://www.aftabnews.ir/rss"},
    {"n": "🇮🇷 باشگاه خبرنگاران",       "u": "https://www.yjc.ir/fa/rss/allnews"},
    {"n": "🇮🇷 خبرفوری",               "u": "https://www.khabarfoori.com/rss"},
    {"n": "🇮🇷 عصر ایران",              "u": "https://www.asriran.com/fa/rss"},
    {"n": "🇮🇷 دیپلماسی ایرانی",        "u": "https://www.irdiplomacy.ir/fa/rss"},
    # ── نظامی / دفاعی ──
    {"n": "🇮🇷 دفاع پرس",              "u": "https://www.defapress.ir/fa/rss"},
    {"n": "🇮🇷 سپاه نیوز",              "u": "https://www.sepahnews.com/rss"},
    {"n": "🇮🇷 صدای ارتش",             "u": "https://arteshara.ir/fa/rss"},
    {"n": "🇮🇷 جنگ و صلح",             "u": "https://www.iranianwarfare.com/feed/"},
    {"n": "🇮🇷 آنا خبر (نظامی)",        "u": "https://www.ana.ir/rss"},
    # ── گوگل نیوز — ایران فارسی (backup) ──
    {"n": "🇮🇷 گوگل‌نیوز ایران جنگ",    "u": "https://news.google.com/rss/search?q=ایران+اسراییل+جنگ+حمله&hl=fa&gl=IR&ceid=IR:fa&num=15"},
    {"n": "🇮🇷 گوگل‌نیوز سپاه حمله",    "u": "https://news.google.com/rss/search?q=سپاه+موشک+حمله+اسراییل+آمریکا&hl=fa&gl=IR&ceid=IR:fa&num=15"},
    {"n": "🇮🇷 گوگل‌نیوز IRGC EN",      "u": "https://news.google.com/rss/search?q=IRGC+Iran+Israel+attack+war&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇮🇷 خامنه‌ای بیانیه",        "u": "https://news.google.com/rss/search?q=خامنه‌ای+بیانیه+جنگ&hl=fa&gl=IR&ceid=IR:fa&num=10"},
    {"n": "🇮🇷 IFPNews Iran War",        "u": "https://news.google.com/rss/search?q=site:ifpnews.com+Iran+Israel+military&hl=en-US&gl=US&ceid=US:en"},
]

# ══════════════════════════════════════════════════════════════════════
# 🇮🇱  ۵۰ خبرگزاری و رسانه اسراییل
# ══════════════════════════════════════════════════════════════════════
ISRAEL_FEEDS = [
    # ── انگلیسی — اصلی ──
    {"n": "🇮🇱 Jerusalem Post",        "u": "https://www.jpost.com/rss/rssfeedsheadlines.aspx"},
    {"n": "🇮🇱 J-Post Military",       "u": "https://www.jpost.com/Rss/RssFeedsIsraelNews.aspx"},
    {"n": "🇮🇱 Times of Israel",       "u": "https://www.timesofisrael.com/feed/"},
    {"n": "🇮🇱 TOI Iran",              "u": "https://www.timesofisrael.com/topic/iran/feed/"},
    {"n": "🇮🇱 TOI Breaking",          "u": "https://www.timesofisrael.com/blogs/liveblog/feed/"},
    {"n": "🇮🇱 Haaretz EN",            "u": "https://news.google.com/rss/search?q=site:haaretz.com+Iran+military+war&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Israel Hayom EN",       "u": "https://www.israelhayom.com/feed/"},
    {"n": "🇮🇱 Arutz Sheva / INN",     "u": "https://www.israelnationalnews.com/rss.aspx"},
    {"n": "🇮🇱 i24 News",              "u": "https://www.i24news.tv/en/rss"},
    {"n": "🇮🇱 Ynet English",          "u": "https://news.google.com/rss/search?q=site:ynetnews.com+Iran+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Globes EN",             "u": "https://en.globes.co.il/en/rss-2684.htm"},
    {"n": "🇮🇱 All Israel News",       "u": "https://www.allisrael.com/feed"},
    {"n": "🇮🇱 Israel Defense",        "u": "https://www.israeldefense.co.il/en/rss.xml"},
    {"n": "🇮🇱 IDF Official (GNews)",  "u": "https://news.google.com/rss/search?q=IDF+Israel+Defense+Forces+official+statement&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Maariv EN (GNews)",     "u": "https://news.google.com/rss/search?q=site:maariv.co.il+Iran&hl=en-US&gl=US&ceid=US:en"},
    # ── رسانه‌های عبری (با google translate فید) ──
    {"n": "🇮🇱 N12 חדשות (GNews)",     "u": "https://news.google.com/rss/search?q=site:mako.co.il+Iran+Israel+war&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n": "🇮🇱 Walla News (GNews)",    "u": "https://news.google.com/rss/search?q=site:news.walla.co.il+Iran&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n": "🇮🇱 Kan News (GNews)",      "u": "https://news.google.com/rss/search?q=site:kan.org.il+Iran&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n": "🇮🇱 Channel 12 (GNews)",    "u": "https://news.google.com/rss/search?q=ערוץ+12+איראן+מלחמה&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n": "🇮🇱 Ynet עברית (GNews)",    "u": "https://news.google.com/rss/search?q=site:ynet.co.il+איראן+מלחמה&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n": "🇮🇱 Israel Hayom עברית",    "u": "https://news.google.com/rss/search?q=site:israelhayom.co.il+איראן&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n": "🇮🇱 Haaretz עברית",         "u": "https://news.google.com/rss/search?q=site:haaretz.co.il+איראן+מלחמה&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n": "🇮🇱 The Marker (GNews)",    "u": "https://news.google.com/rss/search?q=site:themarker.com+ביטחון+איראן&hl=iw-IL&gl=IL&ceid=IL:iw"},
    # ── OSINT اسراییل ──
    {"n": "🇮🇱 ISW Israel-Iran",       "u": "https://news.google.com/rss/search?q=site:understandingwar.org+Israel+Iran&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 INSS Israel",           "u": "https://news.google.com/rss/search?q=site:inss.org.il+Iran+war&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Begin-Sadat (BESA)",    "u": "https://besacenter.org/feed/"},
    {"n": "🇮🇱 Alma Research",         "u": "https://www.alma-org.com/feed/"},
    # ── خبرنگاران اسراییلی (GNews) ──
    {"n": "🇮🇱 Barak Ravid (IL)",      "u": "https://news.google.com/rss/search?q=%22Barak+Ravid%22+Iran+Israel+Axios&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Yossi Melman",          "u": "https://news.google.com/rss/search?q=%22Yossi+Melman%22+Iran+Mossad+Israel&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Seth Frantzman",        "u": "https://news.google.com/rss/search?q=%22Seth+Frantzman%22+Iran+Israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Avi Issacharoff",       "u": "https://news.google.com/rss/search?q=%22Avi+Issacharoff%22+Iran+Israel&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Lahav Harkov (JP)",     "u": "https://news.google.com/rss/search?q=%22Lahav+Harkov%22+Iran+Israel&hl=en-US&gl=US&ceid=US:en"},
    # ── جستجوهای هدفمند اسراییل ──
    {"n": "🇮🇱 Netanyahu Iran",        "u": "https://news.google.com/rss/search?q=Netanyahu+Iran+attack+order+war&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇮🇱 IDF Operation Iran",    "u": "https://news.google.com/rss/search?q=IDF+operation+Iran+strike+missile&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇮🇱 Mossad Iran",           "u": "https://news.google.com/rss/search?q=Mossad+Iran+covert+operation+kill&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇮🇱 Iron Dome Gaza",        "u": "https://news.google.com/rss/search?q=Iron+Dome+Arrow+missile+intercept+Iran&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇮🇱 Israel Nuclear Iran",   "u": "https://news.google.com/rss/search?q=Israel+Iran+nuclear+Natanz+bomb&hl=en-US&gl=US&ceid=US:en&num=15"},
    # ── ویژه نظامی-اسراییل ──
    {"n": "🇮🇱 IAF (GNews)",           "u": "https://news.google.com/rss/search?q=Israeli+Air+Force+IAF+strike+Iran&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Shin Bet (GNews)",      "u": "https://news.google.com/rss/search?q=Shin+Bet+Iran+intelligence+arrest&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Israeli Navy",          "u": "https://news.google.com/rss/search?q=Israeli+Navy+Iran+ship+sea&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇮🇱 Hezbollah Israel",      "u": "https://news.google.com/rss/search?q=Hezbollah+attack+Israel+IDF+Lebanon&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇮🇱 Hamas Israel Iran",     "u": "https://news.google.com/rss/search?q=Hamas+Israel+Iran+support+attack&hl=en-US&gl=US&ceid=US:en&num=15"},
]

# ══════════════════════════════════════════════════════════════════════
# 🇺🇸  ۵۰ خبرگزاری و رسانه آمریکا
# ══════════════════════════════════════════════════════════════════════
USA_FEEDS = [
    # ── بزرگ / سیم‌خبری ──
    {"n": "🇺🇸 AP Top News",           "u": "https://feeds.apnews.com/rss/apf-topnews"},
    {"n": "🇺🇸 AP World",              "u": "https://feeds.apnews.com/rss/apf-WorldNews"},
    {"n": "🇺🇸 AP Military",           "u": "https://apnews.com/hub/military-and-defense?format=rss"},
    {"n": "🇺🇸 Reuters World",         "u": "https://feeds.reuters.com/reuters/worldNews"},
    {"n": "🇺🇸 Reuters Top",           "u": "https://feeds.reuters.com/reuters/topNews"},
    {"n": "🇺🇸 Reuters Middle East",   "u": "https://feeds.reuters.com/reuters/MEonlineHeadlines"},
    {"n": "🇺🇸 Bloomberg Politics",    "u": "https://feeds.bloomberg.com/politics/news.rss"},
    {"n": "🇺🇸 WSJ World",             "u": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"},
    {"n": "🇺🇸 NYT (GNews)",           "u": "https://news.google.com/rss/search?q=site:nytimes.com+Iran+Israel+war+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 WaPo (GNews)",          "u": "https://news.google.com/rss/search?q=site:washingtonpost.com+Iran+Israel+military+war&hl=en-US&gl=US&ceid=US:en"},
    # ── تلویزیون / دیجیتال ──
    {"n": "🇺🇸 CNN Middle East",       "u": "http://rss.cnn.com/rss/edition_meast.rss"},
    {"n": "🇺🇸 CNN World",             "u": "http://rss.cnn.com/rss/edition_world.rss"},
    {"n": "🇺🇸 Fox News World",        "u": "https://moxie.foxnews.com/google-publisher/world.xml"},
    {"n": "🇺🇸 NBC News (GNews)",      "u": "https://news.google.com/rss/search?q=site:nbcnews.com+Iran+Israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 ABC News (GNews)",      "u": "https://news.google.com/rss/search?q=site:abcnews.go.com+Iran+Israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 CBS News (GNews)",      "u": "https://news.google.com/rss/search?q=site:cbsnews.com+Iran+military+Israel&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Axios NatSec",          "u": "https://news.google.com/rss/search?q=site:axios.com+Iran+Israel+war+military+national+security&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Politico Defense",      "u": "https://rss.politico.com/defense.xml"},
    {"n": "🇺🇸 The Hill NatSec",       "u": "https://thehill.com/news/feed/"},
    {"n": "🇺🇸 Foreign Policy",        "u": "https://foreignpolicy.com/feed/"},
    # ── رسانه دفاعی / نظامی ──
    {"n": "🇺🇸 Pentagon DoD",          "u": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"n": "🇺🇸 CENTCOM (GNews)",       "u": "https://news.google.com/rss/search?q=CENTCOM+Iran+Iraq+military+operation&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 USNI News",             "u": "https://news.usni.org/feed"},
    {"n": "🇺🇸 Breaking Defense",      "u": "https://breakingdefense.com/feed/"},
    {"n": "🇺🇸 Defense News",          "u": "https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"n": "🇺🇸 Military Times",        "u": "https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    {"n": "🇺🇸 Air Force Mag",         "u": "https://www.airforcemag.com/feed/"},
    {"n": "🇺🇸 National Defense",      "u": "https://www.nationaldefensemagazine.org/rss/articles.xml"},
    {"n": "🇺🇸 The War Zone",          "u": "https://www.twz.com/feed"},
    {"n": "🇺🇸 War on Rocks",          "u": "https://warontherocks.com/feed/"},
    {"n": "🇺🇸 C4ISRNET",              "u": "https://www.c4isrnet.com/arc/outboundfeeds/rss/"},
    # ── ارشد خبرنگاران آمریکایی (GNews) ──
    {"n": "🇺🇸 Natasha Bertrand",      "u": "https://news.google.com/rss/search?q=%22Natasha+Bertrand%22+Iran+Israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Idrees Ali (Reuters)",  "u": "https://news.google.com/rss/search?q=%22Idrees+Ali%22+Pentagon+Iran+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Phil Stewart",          "u": "https://news.google.com/rss/search?q=%22Phil+Stewart%22+Iran+military+Reuters&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Lara Seligman",         "u": "https://news.google.com/rss/search?q=%22Lara+Seligman%22+Iran+defense&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Jack Detsch (FP)",      "u": "https://news.google.com/rss/search?q=%22Jack+Detsch%22+Iran+Israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Dan Lamothe (WaPo)",    "u": "https://news.google.com/rss/search?q=%22Dan+Lamothe%22+Iran+US+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Eric Schmitt (NYT)",    "u": "https://news.google.com/rss/search?q=%22Eric+Schmitt%22+Iran+US+military&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🇺🇸 Farnaz Fassihi (NYT)",  "u": "https://news.google.com/rss/search?q=%22Farnaz+Fassihi%22+Iran+nuclear+war&hl=en-US&gl=US&ceid=US:en"},
    # ── جستجوهای هدفمند آمریکا ──
    {"n": "🇺🇸 US Strike Iran",        "u": "https://news.google.com/rss/search?q=United+States+strike+bomb+Iran+military&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇺🇸 US Navy Iran Gulf",     "u": "https://news.google.com/rss/search?q=US+Navy+aircraft+carrier+Iran+Persian+Gulf&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇺🇸 Trump Iran Policy",     "u": "https://news.google.com/rss/search?q=Trump+Iran+attack+bomb+military+order&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇺🇸 US Sanctions Iran",     "u": "https://news.google.com/rss/search?q=US+sanctions+Iran+maximum+pressure&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🇺🇸 Pentagon Iran Brief",   "u": "https://news.google.com/rss/search?q=Pentagon+briefing+Iran+attack+defense&hl=en-US&gl=US&ceid=US:en&num=15"},
    # ── OSINT / تحلیل ──
    {"n": "🔍 ISW Middle East",        "u": "https://news.google.com/rss/search?q=site:understandingwar.org+Iran+Israel&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🔍 FDD (Long War Jnl)",     "u": "https://www.longwarjournal.org/feed"},
    {"n": "🔍 OSINTdefender",          "u": "https://osintdefender.com/feed/"},
    {"n": "🔍 Bellingcat",             "u": "https://www.bellingcat.com/feed/"},
    {"n": "🔍 RAND Security",          "u": "https://news.google.com/rss/search?q=site:rand.org+Iran+Israel+military+security&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🔍 CSIS Iran",              "u": "https://news.google.com/rss/search?q=site:csis.org+Iran+Israel+war&hl=en-US&gl=US&ceid=US:en"},
]

# ══════════════════════════════════════════════════════════════════════
# 🏛️  اطلاعیه‌های سفارتخانه و هشدارهای سفر
#    (سفارتخانه‌های کشورهای مختلف درباره ایران / جنگ)
# ══════════════════════════════════════════════════════════════════════
EMBASSY_FEEDS = [
    # ── آمریکا (سفارت مجازی) ──
    {"n": "🏛️ US Virtual Embassy Iran",  "u": "https://ir.usembassy.gov/feed/"},
    {"n": "🏛️ US State Dept Alerts",     "u": "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html.rss"},
    {"n": "🏛️ US State-Iran GNews",      "u": "https://news.google.com/rss/search?q=site:ir.usembassy.gov+alert+security&hl=en-US&gl=US&ceid=US:en"},
    # ── انگلیس ──
    {"n": "🏛️ UK FCDO Iran Travel",      "u": "https://www.gov.uk/foreign-travel-advice/iran.atom"},
    {"n": "🏛️ UK FCDO Travel Alerts",    "u": "https://www.gov.uk/foreign-travel-advice/iran/alerts.atom"},
    # ── اروپا ──
    {"n": "🏛️ EU EEAS Iran",             "u": "https://news.google.com/rss/search?q=EU+European+Iran+security+alert+warning+2026&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🏛️ Germany Iran Warning",     "u": "https://news.google.com/rss/search?q=Germany+Auswärtiges+Amt+Iran+Reisewarnung+travel+warning&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🏛️ France Iran Alert",        "u": "https://news.google.com/rss/search?q=France+Iran+security+alert+embassy+2026&hl=en-US&gl=US&ceid=US:en"},
    # ── سایر ──
    {"n": "🏛️ Canada Iran Advisory",     "u": "https://news.google.com/rss/search?q=Canada+Iran+travel+advisory+warning+2026&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🏛️ Australia DFAT Iran",      "u": "https://news.google.com/rss/search?q=Australia+DFAT+Iran+travel+warning+2026&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🏛️ Switzerland Iran (Prot.)", "u": "https://news.google.com/rss/search?q=Switzerland+Embassy+Tehran+Iran+alert+US+interests&hl=en-US&gl=US&ceid=US:en"},
    # ── خبر از سفارتخانه‌ها ──
    {"n": "🏛️ Embassy Evacuations",      "u": "https://news.google.com/rss/search?q=embassy+evacuation+Iran+Tehran+warning+2026&hl=en-US&gl=US&ceid=US:en&num=10"},
    {"n": "🏛️ Airspace Iran Closure",    "u": "https://news.google.com/rss/search?q=Iran+airspace+closure+flight+ban+warning&hl=en-US&gl=US&ceid=US:en&num=10"},
]

# ══════════════════════════════════════════════════════════════════════
# 🌐  خبرگزاری‌های بین‌المللی عمومی
# ══════════════════════════════════════════════════════════════════════
INTL_FEEDS = [
    {"n": "🌐 BBC Middle East",    "u": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"n": "🌐 Al Jazeera",         "u": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"n": "🌐 Middle East Eye",    "u": "https://www.middleeasteye.net/rss"},
    {"n": "🌐 The Intercept",      "u": "https://theintercept.com/feed/?rss=1"},
    {"n": "🌐 Al-Monitor Iran",    "u": "https://news.google.com/rss/search?q=site:al-monitor.com+Iran+Israel+war&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🌐 OSINT Conflict",     "u": "https://news.google.com/rss/search?q=OSINT+Iran+Israel+attack+strike+2026&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "🌐 GeoConfirmed",       "u": "https://news.google.com/rss/search?q=GeoConfirmed+Iran+Israel+confirmed&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🌐 War Monitor",        "u": "https://news.google.com/rss/search?q=WarMonitor+Iran+Israel+attack+missile&hl=en-US&gl=US&ceid=US:en"},
    {"n": "🌐 IntelCrab",          "u": "https://news.google.com/rss/search?q=IntelCrab+Iran+Israel+military+intelligence&hl=en-US&gl=US&ceid=US:en"},
    {"n": "⚠️ DEFCON Alert",       "u": "https://news.google.com/rss/search?q=DEFCON+nuclear+Iran+Israel+alert+escalation&hl=en-US&gl=US&ceid=US:en"},
    {"n": "⚠️ IAEA Iran Nuclear",  "u": "https://news.google.com/rss/search?q=IAEA+Iran+nuclear+uranium+bomb+threat&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n": "⚠️ Red Sea Houthi",     "u": "https://news.google.com/rss/search?q=Houthi+Iran+Red+Sea+attack+ship+US&hl=en-US&gl=US&ceid=US:en&num=15"},
]

# ══════════════════════════════════════════════════════════════════════
# 🐦  Twitter — از طریق Nitter با User-Agent دقیق
#    (تحقیق: nitter.poast.org با UA مشخص RSS برمی‌گردونه)
# ══════════════════════════════════════════════════════════════════════
TWITTER_HANDLES = [
    # ── ایران — رسمی / خبرنگار ──
    ("🇮🇷 IRNA EN",          "IRNA_English"),
    ("🇮🇷 IranIntl EN",      "IranIntl_En"),
    ("🇮🇷 Press TV",         "PressTV"),
    ("🇮🇷 Farnaz Fassihi",   "farnazfassihi"),
    ("🇮🇷 Negar Mortazavi",  "NegarMortazavi"),
    ("🇮🇷 Ali Hashem",       "alihashem_tv"),
    ("🇮🇷 Arash Karami",     "thekarami"),
    # ── آمریکا — سیاستمدار ──
    ("🇺🇸 CENTCOM",          "CENTCOM"),
    ("🇺🇸 DoD",              "DeptofDefense"),
    ("🇺🇸 Marco Rubio",      "marcorubio"),
    ("🇺🇸 Jake Sullivan",    "JakeSullivan46"),
    # ── آمریکا — خبرنگار ──
    ("🇺🇸 Natasha Bertrand", "NatashaBertrand"),
    ("🇺🇸 Barak Ravid",      "BarakRavid"),
    ("🇺🇸 Idrees Ali",       "idreesali114"),
    ("🇺🇸 Lara Seligman",    "laraseligman"),
    ("🇺🇸 Jack Detsch",      "JackDetsch"),
    ("🇺🇸 Eric Schmitt",     "EricSchmittNYT"),
    ("🇺🇸 Dan Lamothe",      "DanLamothe"),
    # ── اسراییل — رسمی ──
    ("🇮🇱 IDF",              "IDF"),
    ("🇮🇱 Israeli PM",       "IsraeliPM"),
    # ── اسراییل — خبرنگار ──
    ("🇮🇱 Yossi Melman",     "yossi_melman"),
    ("🇮🇱 Seth Frantzman",   "sfrantzman"),
    ("🇮🇱 Avi Issacharoff",  "AviIssacharoff"),
    # ── OSINT ──
    ("🔍 OSINTdefender",     "OSINTdefender"),
    ("🔍 IntelCrab",         "IntelCrab"),
    ("🔍 WarMonitor",        "WarMonitor3"),
    ("🔍 GeoConfirmed",      "GeoConfirmed"),
    ("🔍 AuroraIntel",       "AuroraIntel"),
    ("⚠️ DEFCONLevel",       "DEFCONLevel"),
]

# instanceهای Nitter به ترتیب اولویت (از status.d420.de)
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://nitter.tiekoetter.com",
    "https://xcancel.com",
    "https://nuku.trabun.org",
    "https://nitter.catsarch.com",
    "https://lightbrd.com",
    "https://nitter.space",
]

# User-Agent که در تحقیق ثابت شده با برخی instanceها کار می‌کند
NITTER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
}

ALL_RSS_FEEDS = IRAN_FEEDS + ISRAEL_FEEDS + USA_FEEDS + EMBASSY_FEEDS + INTL_FEEDS

# ══════════════════════════════════════════════════════════════════════
# 🎯  فیلتر — فقط جنگ ایران / آمریکا / اسراییل
# ══════════════════════════════════════════════════════════════════════
IRAN_KEYWORDS = [
    "iran","irgc","khamenei","tehran","iranian","revolutionary guard",
    "pasadaran","quds force","sepah","پاسداران","سپاه","ایران","خامنه‌ای",
    "hezbollah","hamas","houthi","ansarallah","حزب‌الله","حماس","حوثی",
    "pezeshkian","araghchi","zarif","قالیباف","آراقچی",
]
OPPONENT_KEYWORDS = [
    "israel","idf","mossad","netanyahu","tel aviv","israeli","اسراییل","نتانیاهو",
    "united states","us forces","pentagon","centcom","american","آمریکا","واشنگتن",
    "trump","rubio","waltz","us military","us navy","us air force",
    "white house","state department","کاخ سفید",
]
ACTION_KEYWORDS = [
    "attack","strike","airstrike","bomb","missile","rocket","drone",
    "war","conflict","military","kill","assassin","explosion","blast",
    "threat","escalat","retaliat","nuclear","weapon","sanction",
    "intercept","shot down","destroy","invade","retaliat",
    "حمله","موشک","بمب","پهپاد","انفجار","جنگ","عملیات","تهدید",
    "کشته","ضربه","هسته‌ای","تحریم","تلافی","سرنگون",
]
# خبرهایی که مستقیماً با اطلاعیه سفارتخانه‌اند (همیشه ارسال)
EMBASSY_OVERRIDE = [
    "travel advisory","security alert","leave iran","evacuate","do not travel",
    "هشدار سفارت","اطلاعیه امنیتی","ترک ایران",
    "airspace clos","flight suspend","flight ban",
]
# موضوعاتی که حذف می‌شوند
HARD_EXCLUDE = [
    "sport","football","soccer","olympic","basketball","tennis","wrestling",
    "weather","earthquake","flood","drought","volcano",
    "covid","corona","vaccine","pharmacy",
    "music","concert","cinema","film","actor","actress",
    "fashion","beauty","cooking","recipe",
    "stock market alone","gdp alone","economy alone",
    "کشتی","فوتبال","ورزش","موسیقی","سینما","هنر","واکسن","آب‌وهوا","زلزله",
]

def is_war_relevant(entry: dict, is_embassy: bool = False, is_twitter: bool = False) -> bool:
    text = " ".join([
        str(entry.get("title", "")),
        str(entry.get("summary", "")),
        str(entry.get("description", "")),
    ]).lower()

    # اطلاعیه سفارتخانه — همیشه مهم
    if is_embassy and any(kw in text for kw in EMBASSY_OVERRIDE):
        return True

    # حذف موضوعات بی‌ربط
    if any(ex in text for ex in HARD_EXCLUDE):
        return False

    has_iran     = any(k in text for k in IRAN_KEYWORDS)
    has_opponent = any(k in text for k in OPPONENT_KEYWORDS)
    has_action   = any(a in text for a in ACTION_KEYWORDS)

    if is_twitter:
        # توییت: کافیه یه طرف + action باشه
        return (has_iran or has_opponent) and has_action

    # RSS: باید هر دو طرف درگیری + action باشد
    return has_iran and has_opponent and has_action

def is_fresh(entry: dict) -> bool:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t: return False
        return datetime(*t[:6], tzinfo=timezone.utc) >= get_cutoff()
    except:
        return False

# ══════════════════════════════════════════════════════════════════════
# دریافت فیدها
# ══════════════════════════════════════════════════════════════════════
COMMON_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:121.0) Gecko/20100101 Firefox/121.0 MilNewsBot/12.0"}

async def fetch_rss(client: httpx.AsyncClient, feed: dict) -> list[tuple]:
    try:
        r = await client.get(feed["u"], timeout=httpx.Timeout(12.0), headers=COMMON_UA)
        if r.status_code == 200:
            entries = feedparser.parse(r.text).entries or []
            is_emb = feed in EMBASSY_FEEDS
            return [(e, feed["n"], False, is_emb) for e in entries]
    except:
        pass
    return []

async def fetch_twitter(client: httpx.AsyncClient, label: str, handle: str) -> list[tuple]:
    """Nitter RSS — چند instance با fallback"""
    instances = NITTER_INSTANCES.copy()
    random.shuffle(instances[1:])  # اولی همیشه nitter.poast.org
    for inst in instances[:5]:
        url = f"{inst}/{handle}/rss"
        try:
            r = await client.get(url, timeout=httpx.Timeout(9.0), headers=NITTER_HEADERS)
            if r.status_code == 200 and len(r.text) > 300:
                entries = feedparser.parse(r.text).entries
                if entries and entries[0].get("title"):
                    return [(e, f"𝕏 {label}", True, False) for e in entries]
        except:
            continue
    return []

async def fetch_all(client: httpx.AsyncClient) -> list:
    rss_tasks = [fetch_rss(client, f) for f in ALL_RSS_FEEDS]
    tw_tasks  = [fetch_twitter(client, lbl, hdl) for lbl, hdl in TWITTER_HANDLES]

    all_results = await asyncio.gather(*rss_tasks, *tw_tasks, return_exceptions=True)

    out = []
    tw_ok = 0
    for i, res in enumerate(all_results):
        if not isinstance(res, list): continue
        out.extend(res)
        if i >= len(ALL_RSS_FEEDS) and res:
            tw_ok += 1

    log.info(f"  𝕏 Twitter: {tw_ok}/{len(TWITTER_HANDLES)} موفق")
    return out

# ══════════════════════════════════════════════════════════════════════
# Gemini — ۷ مدل با quota مستقل
# ══════════════════════════════════════════════════════════════════════
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_POOL = [
    {"id": "gemini-2.5-flash-lite",                 "rpd": 1000, "tier": 1},
    {"id": "gemini-2.5-flash-lite-preview-09-2025", "rpd": 1000, "tier": 1},
    {"id": "gemini-2.5-flash",                      "rpd":  250, "tier": 2},
    {"id": "gemini-2.5-flash-preview-09-2025",      "rpd":  250, "tier": 2},
    {"id": "gemini-3-flash-preview",                "rpd":  100, "tier": 3},
    {"id": "gemini-2.5-pro",                        "rpd":  100, "tier": 3},
    {"id": "gemini-3-pro-preview",                  "rpd":   50, "tier": 3},
]

def load_gstate():
    try:
        if Path(GEMINI_STATE_FILE).exists():
            s = json.load(open(GEMINI_STATE_FILE))
            if s.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                return s
    except: pass
    return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "usage": {}, "fails": {}}

def save_gstate(s):
    json.dump(s, open(GEMINI_STATE_FILE, "w"))

def pick_models(s):
    r = []
    for tier in [1, 2, 3]:
        for m in GEMINI_POOL:
            if m["tier"] == tier:
                if s["usage"].get(m["id"], 0) < m["rpd"] and s["fails"].get(m["id"], 0) < 3:
                    r.append(m)
    return r or GEMINI_POOL

TRANSLATE_PROMPT = """تو یه خبرنگار حرفه‌ای هستی که اخبار جنگ رو به فارسی ساده و روان خلاصه می‌کنی.

دستورات سخت:
۱. فارسی ساده و عامیانه — مثل اینکه به دوستت می‌گی
۲. فقط یک جمله (حداکثر ۲ جمله) — خلاصه کامل خبر
۳. اسامی مهم رو حفظ کن: نتانیاهو، خامنه‌ای، سپاه، IDF، سنتکام...
۴. 🔴 = خبر جنگی/حمله/کشته  ⚠️ = تهدید/موضع‌گیری  🏛️ = اطلاعیه سفارتخانه
۵. اگه خبر اطلاعیه سفارتخانه‌ست یا هشدار تخلیه، با 🏛️ شروع کن
۶. هیچ توضیح اضافه نده

مثال‌های خوب:
- "🔴 اسرائیل دیشب با ۱۵ موشک به رآکتور اراک حمله کرد، ۸ نفر کشته شدن"
- "⚠️ خامنه‌ای گفت اگه آمریکا وارد جنگ بشه، پایگاه‌هاشون در خلیج فارس هدف قرار می‌گیرن"
- "🔴 سنتکام تأیید کرد نیروهای آمریکایی در بغداد با پهپاد ایرانی مورد حمله قرار گرفتن"
- "🏛️ سفارت آمریکا (مجازی): همه شهروندان آمریکایی ایران رو فوری ترک کنن"

فرمت خروجی:
###ITEM_0###
[خلاصه فارسی]
###ITEM_1###
[خلاصه فارسی]

===خبرها===
{items}"""

async def translate_batch(client: httpx.AsyncClient, articles: list) -> list:
    if not GEMINI_API_KEY or not articles:
        return articles

    items_txt = ""
    for i, (t, s) in enumerate(articles):
        items_txt += f"###ITEM_{i}###\nTITLE: {t[:280]}\nBODY: {s[:350]}\n"

    prompt = TRANSLATE_PROMPT.format(items=items_txt)
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192}}

    state = load_gstate()
    models = pick_models(state)

    for m in models:
        mid  = m["id"]
        used = state["usage"].get(mid, 0)
        url  = f"{GEMINI_BASE}/{mid}:generateContent?key={GEMINI_API_KEY}"
        short = mid.split("-")[1] if "-" in mid else mid
        log.info(f"🌐 Gemini [{short}...] quota={used}/{m['rpd']}")

        for _ in range(2):
            try:
                r = await client.post(url, json=payload, timeout=httpx.Timeout(90.0))
                if r.status_code == 200:
                    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    result = _parse(raw, articles)
                    ok = sum(1 for i, x in enumerate(result) if x != articles[i])
                    log.info(f"✅ {ok}/{len(articles)} ترجمه شد")
                    state["usage"][mid] = used + 1
                    state["fails"][mid] = 0
                    save_gstate(state)
                    return result
                elif r.status_code == 429:
                    w = int(r.headers.get("Retry-After", "30"))
                    log.warning(f"⏳ 429 — {min(w,15)}s → مدل بعدی")
                    state["fails"][mid] = state["fails"].get(mid, 0) + 1
                    await asyncio.sleep(min(w, 15))
                    break
                else:
                    break
            except asyncio.TimeoutError:
                log.warning("⏳ timeout → مدل بعدی"); break
            except Exception as e:
                log.debug(f"Gemini: {e}"); break

    save_gstate(state)
    log.warning("⚠️ همه مدل‌ها شکست — متن انگلیسی")
    return articles

def _parse(raw: str, fallback: list) -> list:
    results = list(fallback)
    pat = re.compile(r'###ITEM_(\d+)###\s*\n(.+?)(?=###ITEM_|\Z)', re.DOTALL)
    for m in pat.finditer(raw):
        idx  = int(m.group(1))
        text = m.group(2).strip().replace("**","").replace("*","")
        if 0 <= idx < len(results) and text:
            results[idx] = (nfa(text), "")
    return results

# ══════════════════════════════════════════════════════════════════════
# ابزارها
# ══════════════════════════════════════════════════════════════════════
def clean_html(t: str) -> str:
    return BeautifulSoup(str(t or ""), "html.parser").get_text(" ", strip=True) if t else ""

def make_id(entry: dict) -> str:
    k = entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(k.encode()).hexdigest()

def make_title_id(title: str) -> str:
    t = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', title.lower())
    return "t:" + hashlib.md5(t[:180].encode()).hexdigest()

def format_dt(entry: dict) -> str:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).astimezone(TEHRAN_TZ).strftime("🕐 %H:%M  |  %d %b")
    except: pass
    return ""

def esc(t: str) -> str:
    return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def trim(t: str, n: int) -> str:
    t = re.sub(r'\s+', ' ', t).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"

def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        try:
            return set(json.load(open(SEEN_FILE)))
        except: pass
    return set()

def save_seen(seen: set):
    json.dump(list(seen)[-20000:], open(SEEN_FILE, "w"))

# ══════════════════════════════════════════════════════════════════════
# تلگرام
# ══════════════════════════════════════════════════════════════════════
TGAPI = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_send(client: httpx.AsyncClient, text: str) -> bool:
    for _ in range(4):
        try:
            r = await client.post(f"{TGAPI}/sendMessage", json={
                "chat_id": CHANNEL_ID, "text": text[:MAX_MSG_LEN],
                "parse_mode": "HTML", "disable_web_page_preview": True,
            }, timeout=httpx.Timeout(15.0))
            d = r.json()
            if d.get("ok"): return True
            if d.get("error_code") == 429:
                await asyncio.sleep(d.get("parameters",{}).get("retry_after",20))
            elif d.get("error_code") in (400,403):
                log.error(f"TG fatal: {d.get('description')}"); return False
            else:
                await asyncio.sleep(5)
        except Exception as e:
            log.warning(f"TG: {e}"); await asyncio.sleep(8)
    return False

# ══════════════════════════════════════════════════════════════════════
# حلقه اصلی
# ══════════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID نیست!"); return

    seen   = load_seen()
    cutoff = get_cutoff()
    n_rss  = len(ALL_RSS_FEEDS)
    n_tw   = len(TWITTER_HANDLES)
    log.info(f"🚀 {n_rss} RSS/GNews  +  {n_tw} Twitter")
    log.info(f"   🇮🇷{len(IRAN_FEEDS)} 🇮🇱{len(ISRAEL_FEEDS)} 🇺🇸{len(USA_FEEDS)} 🏛️{len(EMBASSY_FEEDS)} 🌐{len(INTL_FEEDS)}")
    log.info(f"📅 Cutoff: {cutoff.astimezone(TEHRAN_TZ).strftime('%H:%M تهران')} به بعد | حافظه: {len(seen)}")

    async with httpx.AsyncClient(follow_redirects=True) as client:

        log.info("⏬ دریافت همزمان...")
        raw = await fetch_all(client)
        log.info(f"📥 {len(raw)} آیتم خام")

        collected  = []
        title_seen = set()
        old_cnt = irrel_cnt = dup_cnt = 0

        for entry, src_name, is_tw, is_emb in raw:
            eid = make_id(entry)
            if eid in seen: continue
            if not is_fresh(entry):
                seen.add(eid); old_cnt += 1; continue
            if not is_war_relevant(entry, is_embassy=is_emb, is_twitter=is_tw):
                seen.add(eid); irrel_cnt += 1; continue
            t = clean_html(entry.get("title", ""))
            tid = make_title_id(t)
            if tid in title_seen:
                seen.add(eid); dup_cnt += 1; continue
            title_seen.add(tid)
            collected.append((eid, entry, src_name, is_tw, is_emb))

        log.info(f"📊 {old_cnt} قدیمی | {irrel_cnt} نامرتبط | {dup_cnt} تکراری | ✅ {len(collected)} جنگی")

        # قدیمی‌ترین اول، محدود به MAX
        collected = list(reversed(collected))
        if len(collected) > MAX_NEW_PER_RUN:
            log.warning(f"⚠️ {len(collected)} → {MAX_NEW_PER_RUN}")
            collected = collected[-MAX_NEW_PER_RUN:]

        if not collected:
            log.info("💤 هیچ خبر جنگی جدیدی نیست")
            save_seen(seen); return

        # ترجمه دسته‌ای
        arts_in = []
        for eid, entry, src, is_tw, is_emb in collected:
            t = trim(clean_html(entry.get("title","")), 280)
            s = trim(clean_html(entry.get("summary") or entry.get("description") or ""), 350)
            arts_in.append((t, s))

        log.info(f"🌐 ترجمه {len(arts_in)} خبر...")
        translations = await translate_batch(client, arts_in)

        # ارسال
        sent = 0
        for i, (eid, entry, src_name, is_tw, is_emb) in enumerate(collected):
            fa_text, _ = translations[i]
            en_title   = arts_in[i][0]
            link       = entry.get("link", "")
            dt         = format_dt(entry)

            # تشخیص نوع پیام
            if fa_text and fa_text != en_title:
                display = fa_text
            else:
                display = en_title  # fallback

            lines = [f"<b>{esc(display)}</b>", ""]
            lines += [f"─────────────"]
            lines.append(f"{'🏛️' if is_emb else '𝕏' if is_tw else '📡'} <b>{esc(src_name)}</b>")
            if dt:   lines.append(dt)
            if link: lines.append(f'🔗 <a href="{link}">منبع</a>')

            if await tg_send(client, "\n".join(lines)):
                seen.add(eid); sent += 1
                log.info(f"  ✅ {display[:60]}")
            else:
                log.error("  ❌ ارسال ناموفق")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"🏁 {sent}/{len(collected)} ارسال شد")

if __name__ == "__main__":
    asyncio.run(main())
