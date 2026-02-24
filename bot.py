import os, json, hashlib, asyncio, logging, re, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser, httpx, pytz, io

try:
    from PIL import Image, ImageDraw, ImageFont
    import arabic_reshaper
    from bidi.algorithm import get_display
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
# تنظیمات پایه و متغیرهای محیطی
# ──────────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SEEN_FILE         = "seen.json"
TITLE_HASH_FILE   = "title_hashes.json"
GEMINI_STATE_FILE = "gemini_state.json"
FLIGHT_ALERT_FILE = "flight_alerts.json"
NITTER_CACHE_FILE = "nitter_cache.json"
STORY_FILE        = "stories.json"
RUN_STATE_FILE    = "run_state.json"

MAX_NEW_PER_RUN   = 30
MAX_MSG_LEN       = 4096
SEND_DELAY        = 2
CUTOFF_HOURS      = 4
TG_CUTOFF_HOURS   = 1
JACCARD_THRESHOLD = 0.38

_VIOLENCE_CODES  = {"MSL","AIR","ATK","KIA","DEF","EXP"}
_POLITICAL_CODES = {"THR","DIP","SAN","NUC","SPY","STM"}
TEHRAN_TZ         = pytz.timezone("Asia/Tehran")

def get_cutoff(h=None):
    return datetime.now(timezone.utc) - timedelta(hours=h or CUTOFF_HOURS)

# ──────────────────────────────────────────────────────────────────────────
# تابع ذخیره‌سازی ایمن (Atomic Write) برای جلوگیری از خرابی JSON در GitHub Actions
# ──────────────────────────────────────────────────────────────────────────
def save_json_safe(data, filename):
    try:
        fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(filename) or ".")
        with open(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(temp_path, filename)
    except Exception as e:
        log.error(f"Error saving {filename}: {e}")

# ──────────────────────────────────────────────────────────────────────────
# منابع خبری (RSS)
# ──────────────────────────────────────────────────────────────────────────
IRAN_FEEDS = [
    {"n":"🇮🇷 IRNA English",       "u":"https://en.irna.ir/rss"},
    {"n":"🇮🇷 Mehr News EN",        "u":"https://en.mehrnews.com/rss"},
    {"n":"🇮🇷 Tasnim News EN",      "u":"https://www.tasnimnews.com/en/rss"},
    {"n":"🇮🇷 Press TV",            "u":"https://www.presstv.ir/rss"},
    {"n":"🇮🇷 ISNA English",        "u":"https://en.isna.ir/rss"},
    {"n":"🇮🇷 Tehran Times",        "u":"https://www.tehrantimes.com/rss"},
    {"n":"🇮🇷 Iran International",  "u":"https://www.iranintl.com/en/rss"},
    {"n":"🇮🇷 Radio Farda",         "u":"https://www.radiofarda.com/api/zoyqvpemr"},
    {"n":"🇮🇷 خبرگزاری تسنیم",      "u":"https://www.tasnimnews.com/fa/rss/feed/0/8/0"},
    {"n":"🇮🇷 خبرگزاری مهر",         "u":"https://www.mehrnews.com/rss"},
    {"n":"🇮🇷 خبرگزاری ایرنا",       "u":"https://www.irna.ir/rss"},
    {"n":"🇮🇷 خبرگزاری فارس",        "u":"https://www.farsnews.ir/rss/fa"},
    {"n":"🇮🇷 خبرگزاری دانشجو",      "u":"https://snn.ir/rss"},
    {"n":"🇮🇷 سپاه نیوز",             "u":"https://www.sepahnews.com/rss"},
    {"n":"🇮🇷 صدای ارتش",            "u":"https://arteshara.ir/fa/rss"},
    {"n":"🇮🇷 GNews جنگ ایران FA",   "u":"https://news.google.com/rss/search?q=ایران+اسراییل+جنگ+حمله&hl=fa&gl=IR&ceid=IR:fa&num=15"},
    {"n":"🇮🇷 GNews سپاه موشک FA",   "u":"https://news.google.com/rss/search?q=سپاه+موشک+حمله+اسراییل&hl=fa&gl=IR&ceid=IR:fa&num=15"},
]

ISRAEL_FEEDS = [
    {"n":"🇮🇱 Jerusalem Post",       "u":"https://www.jpost.com/rss/rssfeedsheadlines.aspx"},
    {"n":"🇮🇱 J-Post Military",      "u":"https://www.jpost.com/Rss/RssFeedsIsraelNews.aspx"},
    {"n":"🇮🇱 Times of Israel",      "u":"https://www.timesofisrael.com/feed/"},
    {"n":"🇮🇱 Israel Defense",       "u":"https://www.israeldefense.co.il/en/rss.xml"},
    {"n":"🇮🇱 Alma Research",        "u":"https://www.alma-org.com/feed/"},
    {"n":"🇮🇱 Haaretz GNews",        "u":"https://news.google.com/rss/search?q=site:haaretz.com+Iran+military+war&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇮🇱 Ynet GNews",           "u":"https://news.google.com/rss/search?q=site:ynetnews.com+Iran+military&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🇮🇱 N12 GNews",            "u":"https://news.google.com/rss/search?q=site:mako.co.il+Iran+Israel+war&hl=iw-IL&gl=IL&ceid=IL:iw"},
    {"n":"🇮🇱 Netanyahu Iran GNews", "u":"https://news.google.com/rss/search?q=Netanyahu+Iran+attack+order+war&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 IDF Iran GNews",       "u":"https://news.google.com/rss/search?q=IDF+operation+Iran+strike+missile&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 Iron Dome GNews",      "u":"https://news.google.com/rss/search?q=Iron+Dome+Arrow+missile+intercept+Iran&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇮🇱 IAF Strike Iran",      "u":"https://news.google.com/rss/search?q=Israeli+Air+Force+IAF+strike+Iran&hl=en-US&gl=US&ceid=US:en"},
]

USA_FEEDS = [
    {"n":"🇺🇸 AP Top News",          "u":"https://feeds.apnews.com/rss/apf-topnews"},
    {"n":"🇺🇸 Reuters World",        "u":"https://feeds.reuters.com/reuters/worldNews"},
    {"n":"🇺🇸 CNN Middle East",      "u":"http://rss.cnn.com/rss/edition_meast.rss"},
    {"n":"🇺🇸 Fox News World",       "u":"https://moxie.foxnews.com/google-publisher/world.xml"},
    {"n":"🇺🇸 Politico Defense",     "u":"https://rss.politico.com/defense.xml"},
    {"n":"🇺🇸 Pentagon DoD",         "u":"https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"n":"🇺🇸 The War Zone",         "u":"https://www.twz.com/feed"},
    {"n":"🇺🇸 US Strike Iran GNews", "u":"https://news.google.com/rss/search?q=United+States+strike+bomb+Iran+military&hl=en-US&gl=US&ceid=US:en&num=15"},
    {"n":"🇺🇸 CENTCOM GNews",        "u":"https://news.google.com/rss/search?q=CENTCOM+Iran+Iraq+military+operation&hl=en-US&gl=US&ceid=US:en"},
    {"n":"🔍 OSINTdefender",         "u":"https://osintdefender.com/feed/"},
]

EMBASSY_FEEDS = [
    {"n":"🏛️ US Virtual Embassy",   "u":"https://ir.usembassy.gov/feed/"},
    {"n":"🏛️ US State Travel",      "u":"https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html.rss"},
    {"n":"🏛️ UK FCDO Alerts",       "u":"https://www.gov.uk/foreign-travel-advice/iran/alerts.atom"},
    {"n":"🏛️ Embassy Evacuations",  "u":"https://news.google.com/rss/search?q=embassy+evacuation+Iran+Tehran+warning&hl=en-US&gl=US&ceid=US:en&num=10"},
]

INTL_FEEDS = [
    {"n":"🌐 BBC Middle East",  "u":"https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"n":"🌐 Al Jazeera",       "u":"https://www.aljazeera.com/xml/rss/all.xml"},
    {"n":"⚠️ DEFCON Iran",      "u":"https://news.google.com/rss/search?q=DEFCON+nuclear+Iran+Israel+escalation&hl=en-US&gl=US&ceid=US:en"},
]

ALL_RSS_FEEDS = IRAN_FEEDS + ISRAEL_FEEDS + USA_FEEDS + EMBASSY_FEEDS + INTL_FEEDS
EMBASSY_SET = set(id(f) for f in EMBASSY_FEEDS)

# ──────────────────────────────────────────────────────────────────────────
# کانال‌های تلگرام و اکانت‌های توییتر
# ──────────────────────────────────────────────────────────────────────────
TELEGRAM_CHANNELS = [
    ("🔴 Middle East Spectator", "Middle_East_Spectator"),
    ("🔴 Intel Slava Z",         "intelslava"),
    ("🔍 OSINTtechnical",        "Osinttechnical"),
    ("🇮🇷 تسنیم فارسی",         "tasnimnewsfa"),
    ("🇮🇷 مهر فارسی",            "mehrnews_fa"),
    ("🇮🇱 Kann News",            "kann_news"),
    ("🇸🇦 Al Arabiya Breaking",  "AlArabiya_Brk"),
    ("🇾🇲 Masirah TV",           "AlMasirahNet"),
    ("🌐 Reuters Breaking",      "ReutersBreaking"),
]

TWITTER_HANDLES = [
    ("🇮🇷 IRNA EN",               "IRNA_English"),
    ("🇮🇷 Farnaz Fassihi",        "farnazfassihi"),
    ("🇺🇸 CENTCOM",               "CENTCOM"),
    ("🇺🇸 DoD",                   "DeptofDefense"),
    ("🇮🇱 IDF",                   "IDF"),
    ("🇮🇱 Israeli PM",            "IsraeliPM"),
    ("🔍 OSINTdefender",          "OSINTdefender"),
    ("🔍 WarMonitor",             "WarMonitor3"),
    ("🔍 Clash Report",           "clashreport"),
    ("⚠️ DEFCONLevel",            "DEFCONLevel"),
]

TG_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
TG_HEADERS = {"User-Agent": TG_UA, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.5"}

# ──────────────────────────────────────────────────────────────────────────
# مدیریت Nitter
# ──────────────────────────────────────────────────────────────────────────
NITTER_FALLBACK = [
    "https://xcancel.com",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.catsarch.com",
]

NITTER_CACHE_TTL  = 3600
NITTER_HDR = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
}

_nitter_pool: list[str] = []
_NITTER_SEMA: asyncio.Semaphore | None = None
_NITTER_INST_LAST: dict[str, float] = {}

async def _nitter_get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    global _NITTER_SEMA
    inst = "/".join(url.split("/")[:3])
    sema = _NITTER_SEMA if _NITTER_SEMA is not None else asyncio.Semaphore(4)
    async with sema:
        loop = asyncio.get_event_loop()
        now  = loop.time()
        last = _NITTER_INST_LAST.get(inst, 0)
        gap  = now - last
        if gap < 0.8:
            await asyncio.sleep(0.8 - gap)
        _NITTER_INST_LAST[inst] = loop.time()

        try:
            # زمان تایم‌اوت به 7.0 کاهش یافت تا از هنگ کردن Action جلوگیری شود
            return await client.get(url, headers=NITTER_HDR, timeout=httpx.Timeout(7.0))
        except Exception as e:
            log.debug(f"𝕏 _nitter_get: {type(e).__name__} — {url[:50]}")
            return None

def _load_nitter_disk():
    try:
        if Path(NITTER_CACHE_FILE).exists():
            d = json.load(open(NITTER_CACHE_FILE))
            return d.get("instances", []), d.get("ts", 0.0)
    except: pass
    return [], 0.0

def _save_nitter_disk(instances: list[str]):
    save_json_safe({"instances": instances, "ts": datetime.now(timezone.utc).timestamp()}, NITTER_CACHE_FILE)

async def build_nitter_pool(client: httpx.AsyncClient) -> list[str]:
    global _nitter_pool
    if _nitter_pool: return _nitter_pool

    cached, ts = _load_nitter_disk()
    age = datetime.now(timezone.utc).timestamp() - ts
    if cached and age < NITTER_CACHE_TTL:
        log.info(f"🔌 Nitter: {len(cached)} inst از cache (age={int(age//60)}m)")
        _nitter_pool = cached
        return cached

    candidates: list[tuple[str, float]] = []
    try:
        r = await client.get("https://status.d420.de/api/v1/instances", headers={"User-Agent": "WarBot/14"}, timeout=httpx.Timeout(8.0))
        if r.status_code == 200:
            for inst in r.json():
                url  = inst.get("url", "").rstrip("/")
                pts  = float(inst.get("points", 0))
                up   = inst.get("healthy", inst.get("up", False))
                if url.startswith("https://") and (up or pts > 30):
                    candidates.append((url, pts))
            candidates.sort(key=lambda x: x[1], reverse=True)
    except Exception as e:
        log.warning(f"🔌 status.d420.de: {e} — fallback")

    result_urls = [u for u, _ in candidates[:10]]
    known = set(result_urls)
    for fb in NITTER_FALLBACK:
        if fb not in known:
            result_urls.append(fb)

    if not result_urls:
        result_urls = NITTER_FALLBACK.copy()

    _save_nitter_disk(result_urls)
    _nitter_pool = result_urls
    return result_urls

# ──────────────────────────────────────────────────────────────────────────
# ADS-B پروازهای نظامی
# ──────────────────────────────────────────────────────────────────────────
ADSB_API = "https://api.adsb.one/v2"
ADSB_REGIONS = [
    ("ایران",         32.4, 53.7, 250),
    ("خلیج‌فارس",    26.5, 52.0, 250),
    ("اسراییل/لبنان",32.1, 35.2, 200),
    ("عراق",          33.3, 44.4, 250),
]
MIL_CALLSIGN_PREFIXES = {"RCH":"C-17 (حمل نظامی)","LAGR":"RQ-4 Global Hawk","ROCKY":"B-52","VADER":"F-22",
                         "GRIM":"B-1B","RACER":"B-2 Spirit","STEEL":"KC-46","OASIS":"E-3 AWACS","IRON":"F-16","ASLAN":"F-35"}
SPECIAL_AC_TYPES = {"B52":"بمب‌افکن B-52","B1":"بمب‌افکن B-1","B2":"بمب‌افکن B-2 مخفی","F35":"جنگنده F-35","F22":"جنگنده F-22",
                    "KC135":"سوخت‌رسان KC-135","KC46":"سوخت‌رسان KC-46","E3":"AWACS","RQ4":"پهپاد Global Hawk"}

def load_flight_alerts() -> dict:
    try:
        if Path(FLIGHT_ALERT_FILE).exists():
            with open(FLIGHT_ALERT_FILE, encoding='utf-8') as f:
                d = json.load(f)
            cutoff = datetime.now(timezone.utc).timestamp() - 3600
            return {k:v for k,v in d.items() if v.get("t",0) > cutoff}
    except: pass
    return {}

async def fetch_military_flights(client: httpx.AsyncClient) -> list[dict]:
    known  = load_flight_alerts()
    alerts = []
    hdrs   = {"User-Agent":"WarBot/14"}

    for region, lat, lon, radius in ADSB_REGIONS:
        url = f"{ADSB_API}/point/{lat}/{lon}/{radius}"
        try:
            r = await client.get(url, headers=hdrs, timeout=httpx.Timeout(10.0))
            if r.status_code != 200: continue
            for ac in r.json().get("ac", []):
                db_flags = ac.get("dbFlags", 0)
                is_mil   = bool(db_flags & 1)
                typ      = (ac.get("t") or "").upper()
                call     = (ac.get("flight") or "").strip().upper()
                icao     = ac.get("hex","")
                if not icao: continue

                if not (is_mil or any(s in typ for s in SPECIAL_AC_TYPES) or any(call.startswith(p) for p in MIL_CALLSIGN_PREFIXES)):
                    continue

                uid = f"{icao}_{int(datetime.now(timezone.utc).timestamp()//1800)}"
                if uid in known: continue

                alt = ac.get("alt_baro","?")
                spd = int(ac.get("gs",0))
                type_desc = SPECIAL_AC_TYPES.get(typ, MIL_CALLSIGN_PREFIXES.get(call[:4],"هواپیمای نظامی"))
                emrg_txt  = " 🚨 اورژانس!" if ac.get("emergency","none") not in ("none","") else ""

                msg = (f"✈️ <b>تحرک نظامی — {region}</b>{emrg_txt}\n"
                       f"▸ نوع: <b>{type_desc}</b>\n"
                       f"▸ کال‌ساین: {call or 'نامعلوم'}\n"
                       f"▸ ارتفاع: {alt if isinstance(alt,str) else f'{int(alt):,} ft'}  |  سرعت: {spd} kt\n"
                       f"🔗 <a href='https://globe.adsbexchange.com/?icao={icao}'>ADS-B Exchange</a>")
                known[uid] = {"t": datetime.now(timezone.utc).timestamp()}
                alerts.append(msg)
                if len(alerts) >= 4: break
        except Exception as e: log.debug(f"ADS-B {region}: {e}")

    save_json_safe(known, FLIGHT_ALERT_FILE)
    return alerts

# ──────────────────────────────────────────────────────────────────────────
# کارت تصویری اخبار (با پشتیبانی کامل از RTL و Vazirmatn)
# ──────────────────────────────────────────────────────────────────────────
ACCENT_MAP = {
    "🇮🇷":(0,100,170),"🇮🇱":(0,90,200),"🇺🇸":(178,34,52),
    "🏛️":(100,70,180),"✈️":(10,130,110),"🔴":(210,40,40),
    "⚠️":(210,150,0), "🌐":(40,110,170),"🔍":(70,90,100),
}
BG_DARK, BG_BAR, FG_WHITE, FG_GREY  = (14,16,22), (22,26,34), (235,237,242), (120,132,148)

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

def make_news_card(headline:str, fa_text:str, src:str, dt_str:str, urgent:bool=False, sentiment_icons:list|None=None) -> io.BytesIO | None:
    if not PIL_OK: return None
    try:
        W, H = 960, 310
        acc = _get_accent(src, urgent)
        img = Image.new("RGB", (W,H), BG_DARK)
        drw = ImageDraw.Draw(img)

        drw.rectangle([(0,0),(W,5)], fill=acc)
        drw.rectangle([(0,5),(W,58)], fill=BG_BAR)
        drw.rectangle([(0,58),(W,61)], fill=acc)

        # بارگذاری فونت وزیرمتن (دانلود شده توسط Action)
        try:
            F_sm = ImageFont.truetype("Vazirmatn.ttf", 15)
            F_H  = ImageFont.truetype("Vazirmatn.ttf", 24)
            F_em = ImageFont.truetype("Vazirmatn.ttf", 22)
        except:
            F_sm = F_H = F_em = ImageFont.load_default()

        # هدر (نام منبع و زمان) - اعمال Bidi
        src_bidi = get_display(arabic_reshaper.reshape(src[:50]))
        drw.text((18,16), src_bidi, font=F_sm, fill=acc)
        drw.text((W-170,16), dt_str[:25], font=F_sm, fill=FG_GREY)

        # متن اصلی فارسی (راست‌چین و متصل)
        y = 75
        body = fa_text if (fa_text and fa_text!=headline and len(fa_text)>5) else headline
        reshaped_text = arabic_reshaper.reshape(body)
        bidi_text = get_display(reshaped_text)

        for line in _wrap_text(bidi_text, 55)[:3]:
            drw.text((W-25, y), line, font=F_H, fill=FG_WHITE, anchor="ra")
            y += 40

        # نوار احساسات (پایین)
        drw.rectangle([(0, H-56),(W, H)], fill=BG_BAR)
        drw.rectangle([(0, H-58),(W, H-56)], fill=acc)
        
        ICON_BG = {"💀":(140,20,20), "🔴":(180,30,30), "💥":(190,80,10), "✈️":(20,90,160), "🚀":(100,20,160), "☢️":(0,130,50)}
        icons = sentiment_icons or ["📰"]
        x_pos = 16
        for ico in icons[:4]:
            bg = ICON_BG.get(ico, (50,65,75))
            drw.rounded_rectangle([(x_pos-2, H-52),(x_pos+38, H-6)], radius=7, fill=bg)
            drw.text((x_pos+2, H-50), ico, font=F_em, fill=(255,255,255))
            x_pos += 50

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
# Dedup و فیلتر اخبار جنگی
# ──────────────────────────────────────────────────────────────────────────
IRAN_KEYWORDS = ["iran","irgc","khamenei","tehran","pasadaran","quds","پاسداران","سپاه","ایران","خامنه‌ای","hezbollah","حزب‌الله","حوثی"]
OPPONENT_KEYWORDS = ["israel","idf","mossad","netanyahu","tel aviv","اسراییل","نتانیاهو","united states","pentagon","centcom","آمریکا"]
ACTION_KEYWORDS = ["attack","strike","airstrike","bomb","missile","rocket","drone","war","kill","assassin","explosion","threat","حمله","موشک","بمب","انفجار","جنگ","تهدید","کشته"]
HARD_EXCLUDE = ["sport","football","olympic","weather","earthquake","flood","covid","music","cinema","کشتی","فوتبال","ورزش","سینما","زلزله"]

def is_war_relevant(text:str, is_embassy=False, is_tg=False, is_tw=False) -> bool:
    txt = text.lower()
    if is_embassy and any(k in txt for k in ["evacuate","leave iran","airspace"]): return True
    if any(k in txt for k in HARD_EXCLUDE): return False
    hi = any(k in txt for k in IRAN_KEYWORDS)
    ho = any(k in txt for k in OPPONENT_KEYWORDS)
    ha = any(k in txt for k in ACTION_KEYWORDS)
    if is_tg or is_tw: return (hi or ho) and ha
    return hi and ho and ha

def is_fresh(entry: dict, cutoff: datetime) -> bool:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t: return datetime(*t[:6], tzinfo=timezone.utc) >= cutoff
        if entry.get("_tg_dt"): return entry.get("_tg_dt") >= cutoff
        return True
    except: return True

WHO_MAP = {"iran":"IR","irgc":"IR","سپاه":"IR","ایران":"IR","hezbollah":"HZ","israel":"IL","idf":"IL","اسراییل":"IL","us":"US","آمریکا":"US"}
ACTION_MAP = {"missile":"MSL","موشک":"MSL","airstrike":"AIR","حمله هوایی":"AIR","strike":"ATK","حمله":"ATK","kill":"KIA","کشته":"KIA"}

def _extract_triple(text: str) -> frozenset:
    full = re.sub(r"[^\w\u0600-\u06FF\s]", " ", text.lower())
    res = {code for p, code in WHO_MAP.items() if p in full} | {code for p, code in ACTION_MAP.items() if p in full}
    return frozenset(res)

def _stemmed_jaccard(a: str, b: str) -> float:
    stop = {"the","in","of","to","and","در","و","از","به","با"}
    s1 = {w for w in re.sub(r"[^\w\u0600-\u06FF\s]", " ", a.lower()).split() if w not in stop and len(w)>2}
    s2 = {w for w in re.sub(r"[^\w\u0600-\u06FF\s]", " ", b.lower()).split() if w not in stop and len(w)>2}
    return len(s1 & s2) / len(s1 | s2) if s1 and s2 else 0.0

def is_duplicate_story(title_a: str, title_b: str) -> bool:
    ta, tb = _extract_triple(title_a), _extract_triple(title_b)
    if len(ta)>=2 and len(tb)>=2 and (ta & tb): return True
    return _stemmed_jaccard(title_a, title_b) >= JACCARD_THRESHOLD

def load_stories() -> list[dict]:
    try:
        if Path(STORY_FILE).exists():
            with open(STORY_FILE, encoding='utf-8') as f:
                data = json.load(f)
            cutoff = datetime.now(timezone.utc).timestamp() - 7200
            return [x for x in data if x.get("t", 0) > cutoff]
    except: pass
    return []

# ──────────────────────────────────────────────────────────────────────────
# دریافت داده از پلتفرم‌ها
# ──────────────────────────────────────────────────────────────────────────
async def fetch_rss(client:httpx.AsyncClient, feed:dict) -> list:
    try:
        r = await client.get(feed["u"], timeout=httpx.Timeout(10.0), headers={"User-Agent":"WarBot/14"})
        if r.status_code==200:
            return [(e, feed["n"], "rss", id(feed) in EMBASSY_SET) for e in feedparser.parse(r.text).entries or []]
    except: pass
    return []

async def fetch_telegram_channel(client:httpx.AsyncClient, label:str, handle:str) -> list:
    try:
        r = await client.get(f"https://t.me/s/{handle}", timeout=httpx.Timeout(10.0), headers=TG_HEADERS)
        if r.status_code not in (200,301,302): return []
        soup = BeautifulSoup(r.text,"html.parser")
        results, cutoff = [], get_cutoff(TG_CUTOFF_HOURS)
        for msg in soup.select(".tgme_widget_message_wrap")[-20:]:
            txt_el = msg.select_one(".tgme_widget_message_text")
            text = txt_el.get_text(" ",strip=True) if txt_el else ""
            if len(text)<15: continue
            time_el = msg.select_one("time")
            entry_dt = None
            if time_el:
                try: entry_dt = datetime.fromisoformat(time_el.get("datetime","").replace("Z","+00:00"))
                except: pass
            if entry_dt and entry_dt < cutoff: continue
            link = msg.select_one("a.tgme_widget_message_date")
            results.append(({"title":text[:200],"summary":text[:600],"link":link.get("href","") if link else f"https://t.me/{handle}","_tg_dt":entry_dt}, label, "tg", False))
        return results
    except: return []

async def fetch_twitter(client: httpx.AsyncClient, label: str, handle: str) -> list:
    pool = _nitter_pool or NITTER_FALLBACK
    if not pool: return []
    start = abs(hash(handle)) % len(pool)
    for inst in (pool * 2)[start: start + min(5, len(pool))]:
        r = await _nitter_get(client, f"{inst}/{handle}/rss")
        if r and r.status_code == 200 and ("xml" in r.headers.get("content-type", "") or "<rss" in r.text[:500]):
            valid = [e for e in feedparser.parse(r.text).entries if len(e.get("title", "").strip()) > 5]
            if valid: return [(e, f"𝕏 {label}", "tw", False) for e in valid]
    return []

async def fetch_all(client: httpx.AsyncClient) -> list:
    await build_nitter_pool(client)
    tasks = [fetch_rss(client, f) for f in ALL_RSS_FEEDS] + \
            [fetch_telegram_channel(client, l, h) for l, h in TELEGRAM_CHANNELS] + \
            [fetch_twitter(client, l, h) for l, h in TWITTER_HANDLES]
    
    res = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for r in res:
        if isinstance(r, list): out.extend(r)
    return out

# ──────────────────────────────────────────────────────────────────────────
# Gemini Translation
# ──────────────────────────────────────────────────────────────────────────
def load_gstate():
    try:
        if Path(GEMINI_STATE_FILE).exists():
            with open(GEMINI_STATE_FILE, encoding='utf-8') as f:
                s = json.load(f)
            if s.get("date")==datetime.now(timezone.utc).strftime("%Y-%m-%d"): return s
    except: pass
    return {"date":datetime.now(timezone.utc).strftime("%Y-%m-%d"),"usage":{},"fails":{}}

async def translate_batch(client:httpx.AsyncClient, articles:list) -> list:
    if not GEMINI_API_KEY or not articles: return articles
    items_txt = "".join(f"###ITEM_{i}###\nTITLE: {t[:280]}\nBODY: {s[:350]}\n" for i,(t,s) in enumerate(articles))
    prompt = "خلاصه یک خطی فارسی، عامیانه و بدون توضیح اضافه:\n" + items_txt
    payload = {"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.1}}
    
    state = load_gstate()
    mid = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{mid}:generateContent?key={GEMINI_API_KEY}"
    
    try:
        r = await client.post(url, json=payload, timeout=httpx.Timeout(60.0))
        if r.status_code==200:
            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            res = list(articles)
            for m in re.finditer(r'###ITEM_(\d+)###\s*\n(.+?)(?=###ITEM_|\Z)',raw,re.DOTALL):
                idx=int(m.group(1)); text=m.group(2).strip().replace("**","")
                if 0<=idx<len(res) and text: res[idx]=(nfa(text),"")
            state["usage"][mid] = state["usage"].get(mid,0) + 1
            save_json_safe(state, GEMINI_STATE_FILE)
            return res
    except: pass
    return articles

# ──────────────────────────────────────────────────────────────────────────
# ابزارها و اجرای اصلی
# ──────────────────────────────────────────────────────────────────────────
def make_id(entry:dict) -> str:
    return hashlib.md5((entry.get("link") or entry.get("title") or "").encode()).hexdigest()

def analyze_sentiment(text: str) -> list[str]:
    txt = text.lower()
    rules = [("💀",["killed","کشته","شهید"]), ("🔴",["attack","حمله"]), ("💥",["explosion","انفجار"]), 
             ("✈️",["airstrike","حمله هوایی"]), ("🚀",["missile","موشک"]), ("⚠️",["threat","تهدید"])]
    found = [icon for icon, kws in rules if any(kw in txt for kw in kws)]
    return found[:3] if found else ["📰"]

async def tg_send(client:httpx.AsyncClient, text:str="", buf=None, caption:str="") -> bool:
    try:
        if buf:
            r=await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id":CHANNEL_ID,"caption":caption[:1024],"parse_mode":"HTML"},
                files={"photo":("card.jpg",buf,"image/jpeg")}, timeout=30.0)
        else:
            r=await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                "chat_id":CHANNEL_ID,"text":text[:4096],"parse_mode":"HTML","disable_web_page_preview":True}, timeout=15.0)
        return r.json().get("ok",False)
    except: return False

def load_seen():
    try: 
        with open(SEEN_FILE, encoding='utf-8') as f: return set(json.load(f))
    except: return set()

def load_last_run():
    try:
        with open(RUN_STATE_FILE, encoding='utf-8') as f:
            return datetime.fromtimestamp(json.load(f).get("last_run",0), tz=timezone.utc)
    except: return datetime.now(timezone.utc) - timedelta(minutes=20)

async def main():
    global _NITTER_SEMA
    _NITTER_SEMA = asyncio.Semaphore(4)

    seen = load_seen()
    stories = load_stories()
    cutoff = max(load_last_run() - timedelta(minutes=3), datetime.now(timezone.utc) - timedelta(minutes=20))

    limits = httpx.Limits(max_connections=60, max_keepalive_connections=20)
    async with httpx.AsyncClient(follow_redirects=True, limits=limits) as client:
        flight_msgs = await fetch_military_flights(client)
        raw = await fetch_all(client)
        
        collected = []
        for entry, src_name, src_type, is_emb in raw:
            eid = make_id(entry)
            if eid in seen or not is_fresh(entry, cutoff): continue
            
            t, s = map(lambda x: BeautifulSoup(str(x or ""),"html.parser").get_text(" ",strip=True), (entry.get("title"), entry.get("summary")))
            if not is_war_relevant(f"{t} {s}", is_emb, src_type=="tg", src_type=="tw"): continue
            if is_duplicate_story(t, stories): continue
            
            collected.append((eid, entry, src_name, src_type, is_emb))
            stories.append({"title": t, "t": datetime.now(timezone.utc).timestamp()})

        for msg in flight_msgs[:3]: await tg_send(client, text=msg); await asyncio.sleep(SEND_DELAY)

        collected = collected[-MAX_NEW_PER_RUN:]
        if collected:
            arts_in = [(BeautifulSoup(str(e.get("title")),"html.parser").get_text()[:280], "") for _,e,_,_,_ in collected]
            translations = await translate_batch(client, arts_in)

            for i, (eid, entry, src_name, stype, is_emb) in enumerate(collected):
                fa, en = translations[i][0], arts_in[i][0]
                display = fa if len(fa)>5 else en
                dt = datetime.now(TEHRAN_TZ).strftime("🕐 %H:%M")
                s_bar = "  ".join(analyze_sentiment(display))
                
                buf = make_news_card(en, fa, src_name, dt, "حمله" in display or "کشته" in display, analyze_sentiment(display))
                cap = f"{s_bar}\n\n<b>{display.replace('<','').replace('>','')}</b>\n\n{'🏛️' if is_emb else '📡'} <b>{src_name}</b>"
                
                if buf: await tg_send(client, buf=buf, caption=cap)
                else: await tg_send(client, text=f"{cap}")
                
                seen.add(eid)
                await asyncio.sleep(SEND_DELAY)

        save_json_safe(list(seen)[-30000:], SEEN_FILE)
        save_json_safe(stories[-4000:], STORY_FILE)
        save_json_safe({"last_run": datetime.now(timezone.utc).timestamp()}, RUN_STATE_FILE)

if __name__=="__main__":
    asyncio.run(main())
