import os, json, hashlib, asyncio, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser, httpx, pytz
from deep_translator import GoogleTranslator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("MilBot")

# ════════════════════════════════════════════════════════════════
# تنظیمات اصلی
# ════════════════════════════════════════════════════════════════
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID  = os.environ.get("CHANNEL_ID", "")
SEEN_FILE   = "seen.json"
MAX_NEW_PER_RUN = 60          
SEND_DELAY  = 3               
MAX_MSG_LEN = 4000
TEHRAN_TZ   = pytz.timezone("Asia/Tehran")

# ════════════════════════════════════════════════════════════════
# ۱. فیدهای اصلی (تایید شده و سالم)
# ════════════════════════════════════════════════════════════════
RSS_FEEDS = [
    # خبرگزاری‌های بین‌المللی
    {"name": "🌐 Axios NatSec",       "url": "https://api.axios.com/feed/national-security"},
    {"name": "🌐 Reuters Defense",    "url": "https://feeds.reuters.com/reuters/worldNews"},
    {"name": "🌐 CNN Middle East",    "url": "http://rss.cnn.com/rss/edition_meast.rss"},
    {"name": "🌐 Fox News World",     "url": "https://moxie.foxnews.com/google-publisher/world.xml"},
    {"name": "🌐 Al Jazeera",         "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "🌐 AP Defense",         "url": "https://apnews.com/hub/military-and-defense?format=rss"},
    {"name": "🌐 Politico Defense",   "url": "https://rss.politico.com/defense.xml"},
    
    # رسانه‌های تخصصی نظامی آمریکا
    {"name": "🇺🇸 Pentagon News",     "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"name": "🇺🇸 CENTCOM",           "url": "https://www.centcom.mil/RSS/"},
    {"name": "🇺🇸 Breaking Defense",  "url": "https://breakingdefense.com/feed/"},
    {"name": "🇺🇸 Defense News",      "url": "https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 The War Zone",      "url": "https://www.thedrive.com/feeds/the-war-zone"},
    {"name": "🇺🇸 Military.com",      "url": "https://www.military.com/RSS/News/Defense.rss"},
    {"name": "🇺🇸 Stars & Stripes",   "url": "https://www.stripes.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "🇺🇸 C4ISRNet",          "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Defense One",       "url": "https://www.defenseone.com/rss/all/"},
    
    # رسانه‌های اسراییل
    {"name": "🇮🇱 IDF Official",      "url": "https://www.idf.il/en/mini-sites/idf-spokesperson-english/feed/"},
    {"name": "🇮🇱 Jerusalem Post",    "url": "https://www.jpost.com/rss/rssfeedsmilitary.aspx"},
    {"name": "🇮🇱 Times of Israel",   "url": "https://www.timesofisrael.com/feed/"},
    {"name": "🇮🇱 Haaretz",          "url": "https://www.haaretz.com/cmlink/1.4455099"},
    {"name": "🇮🇱 Ynetnews",          "url": "https://www.ynetnews.com/category/3082/feed"},
    {"name": "🇮🇱 i24 News",          "url": "https://www.i24news.tv/en/rss"},
    
    # رسانه‌های ایران و خاورمیانه
    {"name": "🇮🇷 Iran International","url": "https://www.iranintl.com/en/rss"},
    {"name": "🇮🇷 Radio Farda",       "url": "https://www.radiofarda.com/api/zmqpqopvp"},
    {"name": "🌐 Middle East Eye",    "url": "https://www.middleeasteye.net/rss"},
    {"name": "🌐 Al Monitor",         "url": "https://www.al-monitor.com/rss.xml"},
    
    # اندیشکده‌ها و اطلاعاتی
    {"name": "🔍 ISW (War Study)",   "url": "https://www.understandingwar.org/rss.xml"},
    {"name": "🔍 Bellingcat",        "url": "https://www.bellingcat.com/feed/"},
    {"name": "🔍 CSIS",              "url": "https://www.csis.org/rss"},
    {"name": "🔍 Long War Journal",  "url": "https://www.longwarjournal.org/feed"},
]

# ════════════════════════════════════════════════════════════════
# ۲. جستجوگر پیشرفته گوگل نیوز (پوشش هزاران سایت خبری)
# ════════════════════════════════════════════════════════════════
GOOGLE_NEWS_QUERIES = [
    # تنش ایران و اسرائیل
    ("⚔️ Iran Israel Attack",       "Iran Israel military attack strike revenge"),
    ("⚔️ IDF Strike Iran",          "IDF airstrike Iran IRGC base facilities"),
    ("⚔️ Mossad Operation",         "Mossad covert operation assassination Iran"),
    ("⚔️ Iran Drone Attack",        "Iran drone Shahed ballistic missile attack Israel"),
    
    # آمریکا و خاورمیانه
    ("⚔️ US Forces Attacked",       "US forces attacked base Iraq Syria CENTCOM"),
    ("⚔️ Pentagon Iran",            "Pentagon warning Iran military action"),
    ("⚔️ US Navy Middle East",      "US Navy carrier strike group 5th Fleet Red Sea Gulf"),
    
    # گروه‌های نیابتی
    ("⚔️ Hezbollah Conflict",       "Hezbollah IDF border strike Lebanon rockets"),
    ("⚔️ Houthis Red Sea",          "Houthis Red Sea attack ship US Navy strike"),
    ("⚔️ IRGC Quds Force",          "IRGC Quds Force Syria Iraq weapons smuggling"),
    
    # برنامه هسته‌ای و تسلیحاتی
    ("☢️ Iran Nuclear",             "Iran nuclear enrichment Natanz Fordow IAEA centrifuge"),
    ("🚀 Hypersonic Missile",       "Iran hypersonic ballistic missile test aerospace"),
    ("🛡️ Iron Dome/Arrow",         "Israel Iron Dome Arrow David Sling interception"),
    
    # جستجوهای متمرکز در خبرگزاری‌های خاص (ایندکس لحظه‌ای)
    ("📰 NYT Iran Military",        "site:nytimes.com Iran Israel military"),
    ("📰 WSJ NatSec",               "site:wsj.com Iran US military defense"),
]

def google_news_url(query: str) -> str:
    q = query.replace(" ", "+")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en&num=15"

GOOGLE_FEEDS = [{"name": name, "url": google_news_url(q), "is_google": True} for name, q in GOOGLE_NEWS_QUERIES]

# ════════════════════════════════════════════════════════════════
# ۳. توییتر / شبکه X (سریع‌ترین منبع خبرها)
# ════════════════════════════════════════════════════════════════
TWITTER_ACCOUNTS = [
    # خبرنگاران ارشد
    ("📰 Barak Ravid (Axios)",      "BarakRavid"),
    ("📰 Natasha Bertrand (CNN)",   "NatashaBertrand"),
    ("📰 Idrees Ali (Reuters)",     "idreesali114"),
    ("📰 Farnaz Fassihi (NYT)",     "farnazfassihi"),
    ("📰 Emanuel Fabian (TOI)",     "manniefabian"),
    ("📰 Trey Yingst (Fox)",        "TreyYingst"),
    ("📰 Joe Truzman (FDD)",        "JoeTruzman"),
    
    # اطلاعات باز (OSINT) و مانیتورینگ جنگ
    ("🔍 OSINT Defender",    "OSINTdefender"),
    ("🔍 Intel Crab",        "IntelCrab"),
    ("🔍 Aurora Intel",      "AuroraIntel"),
    ("🔍 Clash Report",      "clashreport"),
    ("🔍 Faytuks News",      "Faytuks"),
    ("🔍 Global: Military",  "Global_Mil_Info"),
    ("🔍 War Monitor",       "WarMonitor3"),
    
    # مقامات رسمی
    ("🇮🇱 IDF Official",    "IDF"),
    ("🇺🇸 CENTCOM",         "CENTCOM"),
    ("🇺🇸 US Dept Defense", "DeptofDefense"),
]

NITTER_MIRRORS = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.1d4.us",
]

def get_nitter_feeds() -> list[dict]:
    feeds = []
    for name, handle in TWITTER_ACCOUNTS:
        for mirror in NITTER_MIRRORS:
            feeds.append({"name": f"𝕏 {name}", "url": f"{mirror}/{handle}/rss", "nitter_handle": handle})
            break 
    return feeds

NITTER_FEEDS = get_nitter_feeds()
ALL_FEEDS = RSS_FEEDS + GOOGLE_FEEDS + NITTER_FEEDS

# ════════════════════════════════════════════════════════════════
# توابع پردازش (فیلترهای زمانی قطعی و مرتبط بودن)
# ════════════════════════════════════════════════════════════════
def is_fresh_news(entry: dict) -> bool:
    """ فقط خبرهای 21 فوریه 2026 به بعد و حداکثر مربوط به 24 ساعت گذشته """
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t: return True 
        
        dt = datetime(*t[:6], tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        
        # ۱. فیلتر قطعی: هیچ خبری قبل از 21 فوریه 2026 تایید نشود
        cutoff = datetime(2026, 2, 21, tzinfo=timezone.utc)
        if dt < cutoff:
            return False
            
        # ۲. خبر نباید برای بیشتر از 24 ساعت پیش باشد
        if (now - dt) > timedelta(hours=24):
            return False
            
        return True
    except:
        return True

def is_relevant(entry: dict, is_twitter: bool = False) -> bool:
    text = " ".join([
        str(entry.get("title", "")),
        str(entry.get("summary", "")),
        str(entry.get("description", "")),
    ]).lower()
    
    # کلمات کلیدی برای حذف خبرهای نامربوط سیاسی داخلی یا اقتصادی
    if is_twitter:
        if any(kw in text for kw in ["iran", "israel", "us ", "strike", "war", "gaza", "lebanon", "irgc", "idf", "military", "attack", "missile", "hezbollah", "houthi"]):
            return True
        return False
        
    KEYWORDS = ["iran", "irgc", "tehran", "khamenei", "israel", "idf", "mossad", "tel aviv", "netanyahu",
                "us forces", "centcom", "pentagon", "american base", "strike", "airstrike", "drone", "missile", "war", "حمله", "نظامی", "سپاه"]
    return any(kw in text for kw in KEYWORDS)

# ════════════════════════════════════════════════════════════════
# دانلود همزمان فیدها (Asynchronous Fetching) - سرعت بسیار بالا
# ════════════════════════════════════════════════════════════════
async def fetch_single_feed(client: httpx.AsyncClient, cfg: dict) -> list:
    url = cfg["url"]
    try:
        response = await client.get(url, timeout=15.0, headers={"User-Agent": "Mozilla/5.0 MilNewsBot/5.0"})
        if response.status_code == 200:
            parsed = feedparser.parse(response.text)
            return parsed.entries
    except Exception as e:
        # لاگ کردن ارورها نادیده گرفته میشود تا صفحه شلوغ نشود
        pass
    return []

async def fetch_all_feeds_concurrently(client: httpx.AsyncClient, feeds: list) -> list:
    tasks = [fetch_single_feed(client, cfg) for cfg in feeds]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    entries_with_cfg = []
    for i, entries in enumerate(results):
        if isinstance(entries, list):
            for entry in entries:
                entries_with_cfg.append((entry, feeds[i]))
    return entries_with_cfg

# ════════════════════════════════════════════════════════════════
# موتور ترجمه هوشمند
# ════════════════════════════════════════════════════════════════
def translate_to_fa(text: str) -> str:
    if not text or len(text.strip()) < 3:
        return ""
    try:
        # در صورت طولانی بودن متن، برای جلوگیری از ارور مترجم کوتاه میشود
        text = text[:4000]
        return GoogleTranslator(source='auto', target='fa').translate(text)
    except Exception:
        return text 

def clean_html(text: str) -> str:
    if not text: return ""
    return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

def truncate(text: str, n: int = 300) -> str:
    if len(text) <= n: return text
    return text[:n].rsplit(" ", 1)[0] + "…"

def make_id(entry: dict) -> str:
    key = entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(key.encode("utf-8")).hexdigest()

def format_dt(entry: dict) -> str:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            dt = datetime(*t[:6], tzinfo=timezone.utc).astimezone(TEHRAN_TZ)
            return dt.strftime("🕐 %H:%M  |  📅 %Y/%m/%d")
    except:
        pass
    return ""

def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def build_message(entry: dict, source: str, is_twitter: bool = False) -> str:
    en_title   = clean_html(entry.get("title", "No Title")).strip()
    en_summary = clean_html(entry.get("summary") or entry.get("description") or "")
    link       = entry.get("link", "")
    dt         = format_dt(entry)

    fa_title = escape_html(translate_to_fa(en_title))
    fa_summary_short = escape_html(translate_to_fa(truncate(en_summary, 350)))
    en_title_escaped = escape_html(en_title)

    icon = "𝕏" if is_twitter else "📡"

    lines = [f"🔴 <b>{fa_title}</b>", ""]
    
    if fa_summary_short and fa_summary_short.lower() not in fa_title.lower():
        lines += [f"🔹 <i>{fa_summary_short}</i>", ""]
        
    lines += [
        "──────────────",
        f"🇺🇸 <b>متن اصلی:</b>",
        f"<blockquote expandable>{en_title_escaped}</blockquote>"
    ]

    if dt: lines.append(dt)
    lines.append(f"{icon} <b>{source}</b>")
    if link: lines.append(f'🔗 <a href="{link}">لینک خبر اصلی</a>')

    return "\n".join(lines)

def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f: return set(json.load(f))
        except: pass
    return set()

def save_seen(seen: set):
    recent = list(seen)[-15000:] # افزایش حافظه به ۱۵ هزار خبر بخاطر منابع زیاد
    with open(SEEN_FILE, "w") as f: json.dump(recent, f)

# ════════════════════════════════════════════════════════════════
# ارسال به تلگرام
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
            }, timeout=25)
            data = r.json()
            if data.get("ok"): return True
            if data.get("error_code") == 429:
                wait = data.get("parameters", {}).get("retry_after", 30)
                await asyncio.sleep(wait)
            else:
                return False
        except Exception:
            await asyncio.sleep(8)
    return False

# ════════════════════════════════════════════════════════════════
# حلقه اصلی اجرای ربات
# ════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ توکن بات یا آیدی کانال تنظیم نشده است!")
        return

    seen = load_seen()
    
    log.info(f"🔄 در حال دریافت همزمان اطلاعات از {len(ALL_FEEDS)} منبع خبری...")
    
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # مرحله ۱: دانلود همزمان تمام خبرها در چند ثانیه
        raw_entries = await fetch_all_feeds_concurrently(client, ALL_FEEDS)
        
        collected: list[tuple] = [] 

        # مرحله ۲: پردازش و فیلتر کردن
        for entry, cfg in raw_entries:
            is_tw = bool(cfg.get("nitter_handle"))
            eid = make_id(entry)
            
            if eid in seen:
                continue
            
            # فیلتر تاریخ: فقط ۲۱ فوریه ۲۰۲۶ به بعد
            if not is_fresh_news(entry):
                seen.add(eid)
                continue
            
            # فیلتر کلمات کلیدی
            if not is_relevant(entry, is_twitter=is_tw):
                seen.add(eid)
                continue
                
            collected.append((eid, entry, cfg, is_tw))

        # مرتب‌سازی خبرها از قدیمی‌ترین به جدیدترین
        collected = collected[::-1]

        if len(collected) > MAX_NEW_PER_RUN:
            collected = collected[-MAX_NEW_PER_RUN:]

        # مرحله ۳: ترجمه و ارسال
        sent = 0
        for eid, entry, cfg, is_tw in collected:
            msg = build_message(entry, cfg["name"], is_tw)
            if await tg_send(client, msg):
                seen.add(eid)
                sent += 1
                log.info(f"  ✅ [{cfg['name']}] ارسال شد.")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"✔️ پایان | {sent} خبر جدید (امروز به بعد) از ده‌ها منبع ارسال شد.")

if __name__ == "__main__":
    asyncio.run(main())
