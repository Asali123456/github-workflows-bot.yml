"""
╔══════════════════════════════════════════════════════════════════════════╗
║          🛡️ Military Intel Bot — Anti-Freeze & Gemini 2.5 Edition        ║
║     Iran · Israel · USA  |  REST API + Hard Timeouts + RSSHub           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os, json, hashlib, asyncio, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import feedparser, httpx, pytz

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

SEEN_FILE       = "seen.json"
MAX_NEW_PER_RUN = 25          
SEND_DELAY      = 6  # تاخیر ۶ ثانیه برای جلوگیری از مسدود شدن توسط لیمیت گوگل (۱۰ درخواست در دقیقه)
TEHRAN_TZ       = pytz.timezone("Asia/Tehran")

# متغیر سراسری برای جلوگیری از هنگ کردن در صورت لیمیت شدن API گوگل
AI_LIMIT_REACHED = False

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

GOOGLE_NEWS_QUERIES = [
    ("⚔️ Iran Israel Attack",       "Iran Israel military attack strike revenge"),
    ("⚔️ IDF Strike Iran",          "IDF airstrike Iran IRGC base facilities"),
    ("⚔️ US Forces Attacked",       "US forces attacked base Iraq Syria CENTCOM"),
    ("⚔️ Hezbollah Conflict",       "Hezbollah IDF border strike Lebanon rockets"),
]

def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en&num=10"

GOOGLE_FEEDS = [{"name": name, "url": google_news_url(q), "is_google": True} for name, q in GOOGLE_NEWS_QUERIES]

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

TWITTER_MIRRORS = [
    "https://rsshub.app/twitter/user",     
    "https://nitter.poast.org",            
    "https://nitter.privacydev.net",       
]

def get_twitter_feeds() -> list[dict]:
    feeds = []
    for name, handle in TWITTER_ACCOUNTS:
        for mirror in TWITTER_MIRRORS:
            url = f"{mirror}/{handle}" if "rsshub" in mirror else f"{mirror}/{handle}/rss"
            feeds.append({"name": f"𝕏 {name}", "url": url, "nitter_handle": handle})
            break 
    return feeds

ALL_FEEDS = RSS_FEEDS + GOOGLE_FEEDS + get_twitter_feeds()

# ════════════════════════════════════════════════════════════════
# ۲. فیلترهای زمانی و محتوایی
# ════════════════════════════════════════════════════════════════
def is_fresh_news(entry: dict) -> bool:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t: return True 
        
        dt = datetime(*t[:6], tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        
        # فیلتر سخت‌گیرانه ۲۱ فوریه ۲۰۲۶
        cutoff = datetime(2026, 2, 21, tzinfo=timezone.utc)
        if dt < cutoff:
            return False
            
        # فیلتر ۲۴ ساعت: خبر بیشتر از ۲۴ ساعت گذشته ارسال نمی‌شود
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
# ۳. دانلود امن و ضد هنگ اطلاعات (Absolute Timeouts)
# ════════════════════════════════════════════════════════════════
async def fetch_single_feed(client: httpx.AsyncClient, cfg: dict) -> list:
    url = cfg["url"]
    try:
        # تایم‌اوت سخت ۶ ثانیه. اگر سایتی جواب نداد بلافاصله قطع می‌شود تا برنامه هنگ نکند
        response = await client.get(url, timeout=httpx.Timeout(6.0), headers={"User-Agent": "Mozilla/5.0 MilNewsBot/8.0"})
        if response.status_code == 200:
            return feedparser.parse(response.text).entries
    except:
        pass 
    return []

async def fetch_all_feeds_concurrently(client: httpx.AsyncClient, feeds: list) -> list:
    tasks = [fetch_single_feed(client, cfg) for cfg in feeds]
    # کل پروسه دانلود حداکثر اجازه دارد ۱۵ ثانیه طول بکشد
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=15.0)
    except asyncio.TimeoutError:
        log.error("⚠️ Timeout کل در دریافت خبرها رخ داد.")
        return []
        
    entries_with_cfg = []
    for i, entries in enumerate(results):
        if isinstance(entries, list):
            for entry in entries:
                entries_with_cfg.append((entry, feeds[i]))
    return entries_with_cfg

# ════════════════════════════════════════════════════════════════
# ۴. مترجم هوش مصنوعی مستقیم با مدل پایدار Gemini 2.5 Flash
# ════════════════════════════════════════════════════════════════
async def ai_translate_combined(client: httpx.AsyncClient, title: str, summary: str) -> tuple:
    global AI_LIMIT_REACHED
    # اگر قبلاً لیمیت شده باشیم، وقت را تلف نمی‌کند و سریع متن انگلیسی را برمی‌گرداند
    if not GEMINI_API_KEY or len(title) < 3 or AI_LIMIT_REACHED:
        return title, summary

    prompt = f"""شما یک مترجم ارشد نظامی هستید.
عنوان و خلاصه خبر زیر را به فارسی روان و با لحن کاملاً خبری ترجمه کنید و دقیقاً با فرمت زیر برگردانید (بدون کلمه اضافه):
[عنوان فارسی]
---
[خلاصه فارسی]

Title: {title}
Summary: {summary}"""

    # ارتقا یافته به نسخه قدرتمند و پایدار 2.5 فلش
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    }

    try:
        response = await client.post(url, json=payload, timeout=httpx.Timeout(8.0))
        if response.status_code == 200:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            parts = text.split("---")
            if len(parts) >= 2:
                return parts[0].strip(), parts[1].strip()
            return text.strip(), summary
            
        elif response.status_code in (429, 403, 400):
            log.warning(f"⚠️ خطای API یا لیمیت گوگل (کد {response.status_code}). ترجمه برای بقیه خبرها در این دور متوقف شد تا ربات هنگ نکند.")
            AI_LIMIT_REACHED = True
            
    except Exception as e:
        log.error(f"خطای ارتباط با هوش مصنوعی: {e}")
        
    return title, summary 

def clean_html(text: str) -> str:
    if not text: return ""
    return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

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

# ════════════════════════════════════════════════════════════════
# حافظه خبرها
# ════════════════════════════════════════════════════════════════
def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f: return set(json.load(f))
        except: pass
    return set()

def save_seen(seen: set):
    recent = list(seen)[-10000:]
    with open(SEEN_FILE, "w") as f: json.dump(recent, f)

# ════════════════════════════════════════════════════════════════
# ارسال به تلگرام
# ════════════════════════════════════════════════════════════════
TGAPI = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_send(client: httpx.AsyncClient, text: str) -> bool:
    for _ in range(2):
        try:
            r = await client.post(f"{TGAPI}/sendMessage", json={
                "chat_id": CHANNEL_ID,
                "text": text[:MAX_MSG_LEN],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=httpx.Timeout(8.0))
            
            data = r.json()
            if data.get("ok"): return True
            if data.get("error_code") == 429:
                await asyncio.sleep(data.get("parameters", {}).get("retry_after", 5))
            else:
                return False
        except Exception:
            await asyncio.sleep(2)
    return False

# ════════════════════════════════════════════════════════════════
# حلقه اصلی اجرای ربات
# ════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ توکن بات یا آیدی کانال تنظیم نشده است!")
        return

    seen = load_seen()
    log.info(f"🔄 ۱. در حال دریافت همزمان خبرها از خبرگزاری‌ها...")
    
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # مرحله ۱: دریافت خبرها
        raw_entries = await fetch_all_feeds_concurrently(client, ALL_FEEDS)
        log.info(f"✅ ۲. دریافت پایان یافت. فیلتر کردن خبرهای نامعتبر و قدیمی...")
        
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

        collected = collected[::-1] 
        if len(collected) > MAX_NEW_PER_RUN:
            collected = collected[-MAX_NEW_PER_RUN:]

        log.info(f"🔍 ۳. تعداد {len(collected)} خبر جدید برای ترجمه و ارسال یافت شد.")

        # مرحله ۲: ترجمه و ارسال
        sent = 0
        for eid, entry, cfg, is_tw in collected:
            en_title = clean_html(entry.get("title", "بدون عنوان")).strip()
            raw_summary = clean_html(entry.get("summary") or entry.get("description") or "")
            en_summary_short = raw_summary[:400].rsplit(" ", 1)[0] + "…" if len(raw_summary) > 400 else raw_summary
            link = entry.get("link", "")
            dt = format_dt(entry)
            icon = "𝕏" if is_tw else "📡"

            log.info(f"⏳ در حال پردازش خبر: {en_title[:40]}...")
            fa_title, fa_summary = await ai_translate_combined(client, en_title, en_summary_short)
            
            fa_title = escape_html(fa_title.replace("**", ""))
            fa_summary = escape_html(fa_summary.replace("**", ""))
            en_title_escaped = escape_html(en_title)

            # چک کردن اینکه آیا ترجمه موفق بوده یا به دلیل لیمیت گوگل لغو شده است
            if fa_title == en_title_escaped or fa_title == en_title:
                # ── فرمت در صورت عدم ترجمه ──
                lines = [f"🔴 <b>{en_title_escaped}</b>", ""]
                if en_summary_short:
                    lines += [f"🔹 <i>{escape_html(en_summary_short)}</i>", ""]
            else:
                # ── فرمت در صورت ترجمه موفق ──
                lines = [f"🔴 <b>{fa_title}</b>", ""]
                if fa_summary and fa_summary.lower() not in fa_title.lower() and len(fa_summary) > 10:
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
                log.info(f"  ✅ ارسال شد.")
            
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"✔️ پایان پردازش | {sent} خبر جدید با موفقیت ارسال شد.")

if __name__ == "__main__":
    asyncio.run(main())
