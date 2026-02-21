"""
╔══════════════════════════════════════════════════════════════════════════╗
║          🛡️ Military Intel Bot — AI LLM Translation Edition              ║
║     Iran · Israel · USA  |  RSSHub + Google News + Twitter/X            ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os, json, hashlib, asyncio, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser, httpx, pytz
import google.generativeai as genai

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("MilBot")

# ════════════════════════════════════════════════════════════════
# تنظیمات اصلی
# ════════════════════════════════════════════════════════════════
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SEEN_FILE   = "seen.json"
MAX_NEW_PER_RUN = 30          
SEND_DELAY  = 5  # تاخیر ۵ ثانیه برای رعایت محدودیت رایگان هوش مصنوعی (15 RPM)
TEHRAN_TZ   = pytz.timezone("Asia/Tehran")

# کانفیگ هوش مصنوعی گوگل
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # استفاده از مدل سریع و قدرتمند فلش
    generation_config = {"temperature": 0.2, "top_p": 0.95} 
    ai_model = genai.GenerativeModel('gemini-1.5-flash', generation_config=generation_config)
else:
    ai_model = None
    log.error("⚠️ GEMINI_API_KEY تنظیم نشده است. ترجمه انجام نخواهد شد.")

# ════════════════════════════════════════════════════════════════
# ۱. منابع معتبر بر اساس پروژه‌های متن‌باز گیت‌هاب
# ════════════════════════════════════════════════════════════════
RSS_FEEDS = [
    {"name": "🌐 Axios NatSec",       "url": "https://api.axios.com/feed/national-security"},
    {"name": "🌐 Reuters Defense",    "url": "https://feeds.reuters.com/reuters/worldNews"},
    {"name": "🌐 CNN Middle East",    "url": "http://rss.cnn.com/rss/edition_meast.rss"},
    {"name": "🌐 Fox News World",     "url": "https://moxie.foxnews.com/google-publisher/world.xml"},
    {"name": "🌐 Al Jazeera",         "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "🇺🇸 Breaking Defense",  "url": "https://breakingdefense.com/feed/"},
    {"name": "🇺🇸 Defense News",      "url": "https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"name": "🇮🇱 IDF Official",      "url": "https://www.idf.il/en/mini-sites/idf-spokesperson-english/feed/"},
    {"name": "🇮🇱 Times of Israel",   "url": "https://www.timesofisrael.com/feed/"},
    {"name": "🇮🇱 Haaretz",          "url": "https://www.haaretz.com/cmlink/1.4455099"},
    {"name": "🇮🇷 Iran International","url": "https://www.iranintl.com/en/rss"},
    {"name": "🔍 ISW (War Study)",   "url": "https://www.understandingwar.org/rss.xml"},
]

# جستجوی گوگل نیوز
GOOGLE_NEWS_QUERIES = [
    ("⚔️ Iran Israel Attack",       "Iran Israel military attack strike revenge"),
    ("⚔️ IDF Strike Iran",          "IDF airstrike Iran IRGC base facilities"),
    ("⚔️ US Forces Attacked",       "US forces attacked base Iraq Syria CENTCOM"),
    ("⚔️ Hezbollah Conflict",       "Hezbollah IDF border strike Lebanon rockets"),
]

def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en&num=15"

GOOGLE_FEEDS = [{"name": name, "url": google_news_url(q), "is_google": True} for name, q in GOOGLE_NEWS_QUERIES]

# ════════════════════════════════════════════════════════════════
# ۲. توییتر از طریق RSSHub (قدرتمندترین پلتفرم گیت‌هاب) و Nitter
# ════════════════════════════════════════════════════════════════
TWITTER_ACCOUNTS = [
    ("📰 Barak Ravid",      "BarakRavid"),
    ("📰 Natasha Bertrand", "NatashaBertrand"),
    ("📰 Idrees Ali",       "idreesali114"),
    ("📰 Farnaz Fassihi",   "farnazfassihi"),
    ("🔍 OSINT Defender",   "OSINTdefender"),
    ("🔍 Intel Crab",       "IntelCrab"),
    ("🔍 War Monitor",      "WarMonitor3"),
    ("🇮🇱 IDF Official",   "IDF"),
    ("🇺🇸 CENTCOM",        "CENTCOM"),
]

# ترکیب RSSHub (پروژه برتر گیت‌هاب) و Nitter برای اینکه هیچ توییتی مسدود نشود
TWITTER_MIRRORS = [
    "https://rsshub.app/twitter/user",     # RSSHub اصلی
    "https://nitter.poast.org",            # Nitter جایگزین
    "https://nitter.privacydev.net",       # Nitter جایگزین ۲
]

def get_twitter_feeds() -> list[dict]:
    feeds = []
    for name, handle in TWITTER_ACCOUNTS:
        for mirror in TWITTER_MIRRORS:
            url = f"{mirror}/{handle}" if "rsshub" in mirror else f"{mirror}/{handle}/rss"
            feeds.append({"name": f"𝕏 {name}", "url": url, "nitter_handle": handle})
            break # اولی رو برمیداره، در صورت خرابی بعدا تو تابع fetch هندل میشه
    return feeds

ALL_FEEDS = RSS_FEEDS + GOOGLE_FEEDS + get_twitter_feeds()

# ════════════════════════════════════════════════════════════════
# ۳. فیلترهای زمانی و محتوایی
# ════════════════════════════════════════════════════════════════
def is_fresh_news(entry: dict) -> bool:
    """ فقط خبرهای 21 فوریه 2026 به بعد و حداکثر مربوط به 24 ساعت گذشته """
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t: return True 
        
        dt = datetime(*t[:6], tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        
        # ۱. فیلتر قطعی تاریخ درخواستی کاربر: 21 Feb 2026
        cutoff = datetime(2026, 2, 21, tzinfo=timezone.utc)
        if dt < cutoff:
            return False
            
        # ۲. فیلتر ۲۴ ساعت: خبرهای بیشتر از ۲۴ ساعت گذشته رد میشن
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
    
    if is_twitter:
        if any(kw in text for kw in ["iran", "israel", "us ", "strike", "war", "gaza", "lebanon", "irgc", "idf", "military", "attack", "missile"]):
            return True
        return False
        
    KEYWORDS = ["iran", "irgc", "tehran", "khamenei", "israel", "idf", "mossad", "tel aviv", "netanyahu",
                "us forces", "centcom", "pentagon", "american base", "strike", "airstrike", "drone", "missile"]
    return any(kw in text for kw in KEYWORDS)

# ════════════════════════════════════════════════════════════════
# ۴. مترجم هوش مصنوعی (Google Gemini) - لحن خبری
# ════════════════════════════════════════════════════════════════
async def ai_translate(text: str) -> str:
    if not text or len(text.strip()) < 5 or not ai_model:
        return text
    
    prompt = f"""
شما یک مترجم ارشد خبرگزاری‌های نظامی و ژئوپلیتیک هستید.
متن زیر را به زبان فارسی روان، دقیق و با لحن کاملاً خبری ترجمه کنید.
بدون هیچ کلمه اضافه، بدون سلام و احوالپرسی، و بدون استفاده از فرمت‌های کدی (مثل ```). فقط متن ترجمه شده را برگردان.

متن:
{text}
    """
    try:
        response = await asyncio.to_thread(ai_model.generate_content, prompt)
        translated = response.text.strip().replace("```", "").strip()
        return translated if translated else text
    except Exception as e:
        log.error(f"خطای هوش مصنوعی: {e}")
        return text

def clean_html(text: str) -> str:
    if not text: return ""
    return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

def make_id(entry: dict) -> str:
    # استفاده از لینک برای MD5 عشان عدم ارسال خبر تکراری
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

# ════════════════════════════════════════════════════════════════
# دانلود همزمان اطلاعات
# ════════════════════════════════════════════════════════════════
async def fetch_single_feed(client: httpx.AsyncClient, cfg: dict) -> list:
    url = cfg["url"]
    try:
        response = await client.get(url, timeout=15.0, headers={"User-Agent": "Mozilla/5.0 MilNewsBot/6.0"})
        if response.status_code == 200:
            return feedparser.parse(response.text).entries
    except: pass
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

def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f: return set(json.load(f))
        except: pass
    return set()

def save_seen(seen: set):
    recent = list(seen)[-15000:]
    with open(SEEN_FILE, "w") as f: json.dump(recent, f)

# ════════════════════════════════════════════════════════════════
# ارسال به تلگرام
# ════════════════════════════════════════════════════════════════
TGAPI = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_send(client: httpx.AsyncClient, text: str) -> bool:
    for _ in range(3):
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
                await asyncio.sleep(data.get("parameters", {}).get("retry_after", 30))
            else:
                return False
        except Exception:
            await asyncio.sleep(5)
    return False

# ════════════════════════════════════════════════════════════════
# حلقه اصلی اجرای ربات
# ════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ توکن بات یا آیدی کانال تنظیم نشده است!")
        return

    seen = load_seen()
    log.info(f"🔄 شروع دریافت همزمان اطلاعات از منابع...")
    
    async with httpx.AsyncClient(follow_redirects=True) as client:
        raw_entries = await fetch_all_feeds_concurrently(client, ALL_FEEDS)
        collected = []

        for entry, cfg in raw_entries:
            is_tw = bool(cfg.get("nitter_handle"))
            eid = make_id(entry)
            
            if eid in seen: continue
            if not is_fresh_news(entry):
                seen.add(eid)
                continue
            if not is_relevant(entry, is_twitter=is_tw):
                seen.add(eid)
                continue
                
            collected.append((eid, entry, cfg, is_tw))

        collected = collected[::-1] # قدیمی‌ترین به جدیدترین
        if len(collected) > MAX_NEW_PER_RUN:
            collected = collected[-MAX_NEW_PER_RUN:]

        sent = 0
        for eid, entry, cfg, is_tw in collected:
            # آماده سازی متن اصلی
            en_title = clean_html(entry.get("title", "بدون عنوان")).strip()
            en_summary = clean_html(entry.get("summary") or entry.get("description") or "")
            link = entry.get("link", "")
            dt = format_dt(entry)
            icon = "𝕏" if is_tw else "📡"

            # ترجمه با هوش مصنوعی گوگل
            fa_title = escape_html(await ai_translate(en_title))
            
            summary_short = en_summary[:400].rsplit(" ", 1)[0] + "…" if len(en_summary) > 400 else en_summary
            fa_summary = escape_html(await ai_translate(summary_short))
            
            en_title_escaped = escape_html(en_title)

            # ساختار پیام
            lines = [f"🔴 <b>{fa_title}</b>", ""]
            if fa_summary and fa_summary.lower() not in fa_title.lower():
                lines += [f"🔹 <i>{fa_summary}</i>", ""]
                
            lines += [
                "──────────────",
                f"🇺🇸 <b>متن اصلی:</b>",
                f"<blockquote expandable>{en_title_escaped}</blockquote>"
            ]
            if dt: lines.append(dt)
            lines.append(f"{icon} <b>{cfg['name']}</b>")
            if link: lines.append(f'🔗 <a href="{link}">لینک خبر اصلی</a>')

            msg = "\n".join(lines)
            
            if await tg_send(client, msg):
                seen.add(eid)
                sent += 1
                log.info(f"  ✅ [{cfg['name']}] با موفقیت ترجمه و ارسال شد.")
            
            # تاخیر برای رعایت محدودیت سرعت تلگرام و API هوش مصنوعی گوگل
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"✔️ پایان | {sent} خبر جدید (امروز به بعد) با هوش مصنوعی ترجمه و ارسال شد.")

if __name__ == "__main__":
    asyncio.run(main())
