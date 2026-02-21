"""
╔══════════════════════════════════════════════════════════════════════════╗
║          🛡️ Military Intel Bot — GitHub Actions Edition                  ║
║     Iran · Israel · USA  |  RSS + Google News + Twitter/X (Nitter)      ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os, json, hashlib, time, re, logging, asyncio
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import feedparser, httpx, pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("MilBot")

# ════════════════════════════════════════════════════════════════
# تنظیمات — از Environment Variables خوانده می‌شه (GitHub Secrets)
# ════════════════════════════════════════════════════════════════
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID  = os.environ.get("CHANNEL_ID", "")
SEEN_FILE   = "seen.json"
MAX_NEW_PER_RUN = 30          # حداکثر خبر در هر اجرا (جلوگیری از flood)
SEND_DELAY  = 3               # ثانیه بین ارسال‌ها
MAX_MSG_LEN = 4000
TEHRAN_TZ   = pytz.timezone("Asia/Tehran")

# ════════════════════════════════════════════════════════════════
# ─── ۱. فیدهای RSS نظامی ────────────────────────────────────
# ════════════════════════════════════════════════════════════════
RSS_FEEDS = [
    # ── آمریکا رسمی ──
    {"name": "🇺🇸 Pentagon",          "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"name": "🇺🇸 CENTCOM",           "url": "https://www.centcom.mil/RSS/"},
    {"name": "🇺🇸 USNI News",         "url": "https://news.usni.org/feed"},
    {"name": "🇺🇸 Stars & Stripes",   "url": "https://www.stripes.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "🇺🇸 Military Times",    "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Defense News",      "url": "https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Breaking Defense",  "url": "https://breakingdefense.com/feed/"},
    {"name": "🇺🇸 The War Zone",      "url": "https://www.thedrive.com/feeds/the-war-zone"},
    {"name": "🇺🇸 War on Rocks",      "url": "https://warontherocks.com/feed/"},
    {"name": "🇺🇸 C4ISRNET",          "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Janes",             "url": "https://www.janes.com/feeds/news"},
    # ── اسراییل ──
    {"name": "🇮🇱 IDF Official",      "url": "https://www.idf.il/en/mini-sites/idf-spokesperson-english/feed/"},
    {"name": "🇮🇱 Jerusalem Post",    "url": "https://www.jpost.com/rss/rssfeedsmilitary.aspx"},
    {"name": "🇮🇱 Times of Israel",   "url": "https://www.timesofisrael.com/feed/"},
    {"name": "🇮🇱 Haaretz",          "url": "https://www.haaretz.com/cmlink/1.4455099"},
    {"name": "🇮🇱 Israel Hayom",      "url": "https://www.israelhayom.com/feed/"},
    {"name": "🇮🇱 Ynetnews",          "url": "https://www.ynetnews.com/category/3082/feed"},
    {"name": "🇮🇱 i24 News",          "url": "https://www.i24news.tv/en/rss"},
    {"name": "🇮🇱 Arutz Sheva",       "url": "https://www.israelnationalnews.com/Rss.aspx/news"},
    # ── ایران / منطقه ──
    {"name": "🇮🇷 Iran International","url": "https://www.iranintl.com/en/rss"},
    {"name": "🇮🇷 Radio Farda",       "url": "https://www.radiofarda.com/api/zmqpqopvp"},
    {"name": "🌐 Al-Monitor",         "url": "https://www.al-monitor.com/rss.xml"},
    {"name": "🌐 Middle East Eye",    "url": "https://www.middleeasteye.net/rss"},
    {"name": "🌐 Reuters World",      "url": "https://feeds.reuters.com/reuters/worldNews"},
    {"name": "🌐 BBC Middle East",    "url": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"name": "🌐 AP Defense",         "url": "https://apnews.com/hub/military-and-defense?format=rss"},
    {"name": "🌐 Foreign Policy",     "url": "https://foreignpolicy.com/feed/"},
    {"name": "🌐 ISW",                "url": "https://www.understandingwar.org/rss.xml"},
    {"name": "🌐 Long War Journal",   "url": "https://www.longwarjournal.org/feed"},
    {"name": "🌐 Bellingcat",         "url": "https://www.bellingcat.com/feed/"},
    {"name": "🌐 OSINT Defender",     "url": "https://osintdefender.com/feed/"},
    {"name": "🌐 Lawfare",            "url": "https://www.lawfaremedia.org/feed"},
    {"name": "🌐 RAND Security",      "url": "https://www.rand.org/topics/defense-and-security.xml"},
    {"name": "🌐 Axios NatSec",       "url": "https://api.axios.com/feed/national-security"},
]

# ════════════════════════════════════════════════════════════════
# ─── ۲. گوگل نیوز ───────────────────────────────────────────
# ════════════════════════════════════════════════════════════════
GOOGLE_NEWS_QUERIES = [
    ("⚔️ Iran Israel War",          "Iran Israel war attack strike"),
    ("⚔️ Iran USA Military",        "Iran United States military IRGC"),
    ("⚔️ Iran Nuclear",             "Iran nuclear deal bomb missile"),
    ("⚔️ IDF Operation",            "IDF military operation Gaza Lebanon"),
    ("⚔️ Iran Sanctions",           "Iran sanctions SWIFT oil embargo"),
    ("⚔️ Middle East Conflict",     "Middle East military conflict attack"),
    ("⚔️ Hezbollah IRGC",           "Hezbollah IRGC proxy militia Lebanon"),
    ("⚔️ Strait of Hormuz",         "Strait Hormuz oil tanker navy ship"),
    ("⚔️ Iran Drone Missile",       "Iran drone missile ballistic hypersonic"),
    ("⚔️ Israel Airstrike",         "Israel airstrike bomb Syria Iraq Iran"),
    ("⚔️ US Navy 5th Fleet",        "US Navy 5th fleet carrier Bahrain Gulf"),
    ("⚔️ F-35 Iron Dome",           "F-35 Iron Dome Arrow Patriot Israel"),
    ("⚔️ Mossad CIA Operation",     "Mossad CIA intelligence operation covert"),
    ("⚔️ Khamenei Netanyahou",      "Khamenei Netanyahou war threat"),
    ("⚔️ CENTCOM Operations",       "CENTCOM US forces Middle East operations"),
]

def google_news_url(query: str) -> str:
    q = query.replace(" ", "+")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en&num=20"

GOOGLE_FEEDS = [
    {"name": name, "url": google_news_url(q), "is_google": True}
    for name, q in GOOGLE_NEWS_QUERIES
]

# ════════════════════════════════════════════════════════════════
# ─── ۳. توییتر/X بدون اکانت — از طریق Nitter RSS ───────────
# ════════════════════════════════════════════════════════════════
# خبرنگاران و تحلیلگران مهم نظامی
TWITTER_ACCOUNTS = [
    # OSINT & Intel
    ("🔍 OSINT Defender",    "OSINTdefender"),
    ("🔍 Intel Crab",        "IntelCrab"),
    ("🔍 War Monitor",       "WarMonitor3"),
    ("🔍 Conflicts.media",   "Conflicts"),
    ("🔍 Aurora Intel",      "AuroraIntel"),
    ("🔍 Jake Hanrahan",     "Jake_Hanrahan"),
    ("🔍 Calibre Obscura",   "CalibreObscura"),
    # اسراییل/نظامی
    ("🇮🇱 IDF Official",    "IDF"),
    ("🇮🇱 Barak Ravid",     "BarakRavid"),    # Axios Israel
    ("🇮🇱 Ben Caspit",      "BenCaspit"),     # تحلیلگر اسراییل
    ("🇮🇱 Yossi Melman",    "yossi_melman"),  # مسائل اطلاعاتی
    ("🇮🇱 Avi Issacharoff", "AviIssacharoff"),
    ("🇮🇱 Israel Shield",   "Israel_Shield"),
    # ایران
    ("🇮🇷 Iran Intl Eng",   "IranIntl_En"),
    ("🇮🇷 Farnaz Fassihi",  "farnazfassihi"),  # NYT Iran
    ("🇮🇷 Sina Matagi",     "SinaMatagi"),
    # آمریکا / نظامی
    ("🇺🇸 CENTCOM",         "CENTCOM"),
    ("🇺🇸 Lara Seligman",   "laraseligman"),   # Politico Defense
    ("🇺🇸 Phil Stewart",    "phil_stewart_"),  # Reuters Defense
    ("🇺🇸 Jack Detsch",     "JackDetsch"),     # Foreign Policy
    ("🇺🇸 Dan Lamothe",     "DanLamothe"),     # Washington Post
    ("🇺🇸 Thomas Gibbons",  "TGibboN_OHL"),    # Sandboxx
    # منطقه‌ای
    ("🌐 Ragip Soylu",      "ragipsoylu"),     # Al-Monitor Turkey/ME
    ("🌐 Joyce Karam",      "Joyce_Karam"),    # Al-Monitor US-ME
    ("🌐 Lindsey Snell",    "LindseySnell"),
    ("🌐 Seth Frantzman",   "sfrantzman"),     # Jerusalem Post defense
    # DEFCON/Alert
    ("⚠️ DEFCON Level",     "DEFCONLevel"),
    ("⚠️ Nuclear Posture",  "ArmsControlWonk"),
]

# میرور‌های Nitter (چند میرور برای failover)
NITTER_MIRRORS = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

def get_nitter_feeds() -> list[dict]:
    feeds = []
    for name, handle in TWITTER_ACCOUNTS:
        # سعی می‌کنه از میرورهای مختلف
        for mirror in NITTER_MIRRORS:
            feeds.append({
                "name": f"𝕏 {name}",
                "url": f"{mirror}/{handle}/rss",
                "nitter_handle": handle,
                "nitter_primary": mirror == NITTER_MIRRORS[0],
            })
            break  # فقط اولی رو اضافه کن — اگه fail شد بقیه try میشه
    return feeds

NITTER_FEEDS = get_nitter_feeds()

ALL_FEEDS = RSS_FEEDS + GOOGLE_FEEDS + NITTER_FEEDS

# ════════════════════════════════════════════════════════════════
# کلیدواژه‌های فیلتر هوشمند
# ════════════════════════════════════════════════════════════════
KEYWORDS = [
    # فارسی
    "سپاه", "موشک", "جنگ", "حمله", "اسراییل", "آمریکا", "ایران", "هسته‌ای",
    "پهپاد", "نظامی", "بمب", "انفجار", "عملیات", "خلیج‌فارس",
    # انگلیسی — ایران/اسراییل/آمریکا
    "iran", "irgc", "khamenei", "tehran", "revolutionary guard", "nuclear",
    "israel", "idf", "mossad", "tel aviv", "netanyahu", "gaza", "west bank",
    "hezbollah", "hamas", "houthi", "ansarallah",
    "pentagon", "centcom", "us forces", "american military",
    # عملیات
    "strike", "airstrike", "missile", "ballistic", "drone", "uav",
    "attack", "bomb", "explosion", "assassination", "operation",
    "warship", "carrier", "navy", "air force", "troops", "soldiers",
    # منطقه
    "persian gulf", "strait of hormuz", "red sea", "middle east",
    "syria", "iraq", "lebanon", "yemen", "bahrain",
    # سلاح/فناوری
    "iron dome", "arrow", "patriot", "f-35", "f-15", "hypersonic",
    "uranium", "enrichment", "centrifuge", "fordo", "natanz",
    # اطلاعات
    "intelligence", "cia", "mossad", "covert", "espionage", "spy",
    "sanctions", "embargo",
]

def is_relevant(entry: dict, is_twitter: bool = False) -> bool:
    """توییتر همیشه مرتبطه — بقیه فیلتر میشن"""
    if is_twitter:
        return True
    text = " ".join([
        str(entry.get("title", "")),
        str(entry.get("summary", "")),
        str(entry.get("description", "")),
    ]).lower()
    return any(kw in text for kw in KEYWORDS)

# ════════════════════════════════════════════════════════════════
# ابزارهای کمکی
# ════════════════════════════════════════════════════════════════
def clean_html(text: str) -> str:
    if not text:
        return ""
    return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

def truncate(text: str, n: int = 350) -> str:
    if len(text) <= n:
        return text
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
    title   = escape_html(clean_html(entry.get("title", "بدون عنوان")).strip())
    summary = clean_html(entry.get("summary") or entry.get("description") or "")
    link    = entry.get("link", "")
    dt      = format_dt(entry)

    icon = "𝕏" if is_twitter else "📡"
    summary_short = escape_html(truncate(summary, 300))

    lines = [f"<b>{title}</b>", ""]
    if summary_short and summary_short.lower() != title.lower():
        lines += [f"<i>{summary_short}</i>", ""]
    if dt:
        lines.append(dt)
    lines.append(f"{icon} <b>{source}</b>")
    if link:
        lines.append(f'🔗 <a href="{link}">ادامه مطلب</a>')

    return "\n".join(lines)

# ════════════════════════════════════════════════════════════════
# حافظه دیده‌شده‌ها
# ════════════════════════════════════════════════════════════════
def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f:
                return set(json.load(f))
        except:
            pass
    return set()

def save_seen(seen: set):
    recent = list(seen)[-8000:]
    with open(SEEN_FILE, "w") as f:
        json.dump(recent, f)

# ════════════════════════════════════════════════════════════════
# فیلد فیدها
# ════════════════════════════════════════════════════════════════
def fetch_feed(cfg: dict) -> list:
    handle = cfg.get("nitter_handle")
    mirrors = NITTER_MIRRORS if handle else [None]

    for i, mirror in enumerate(mirrors):
        url = f"{mirror}/{handle}/rss" if handle else cfg["url"]
        try:
            parsed = feedparser.parse(url, request_headers={
                "User-Agent": "Mozilla/5.0 MilNewsBot/3.0 (+https://github.com)"
            })
            if parsed.entries:
                return parsed.entries
            if handle and i < len(mirrors) - 1:
                log.debug(f"Nitter {mirror} خالی — میرور بعدی")
                continue
        except Exception as e:
            log.debug(f"Feed error {url[:60]}: {e}")
            if handle and i < len(mirrors) - 1:
                continue
    return []

# ════════════════════════════════════════════════════════════════
# تلگرام
# ════════════════════════════════════════════════════════════════
TGAPI = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def tg_send(client: httpx.AsyncClient, text: str) -> bool:
    for attempt in range(4):
        try:
            r = await client.post(f"{TGAPI}/sendMessage", json={
                "chat_id": CHANNEL_ID,
                "text": text[:MAX_MSG_LEN],
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }, timeout=25)
            data = r.json()
            if data.get("ok"):
                return True
            if data.get("error_code") == 429:
                wait = data.get("parameters", {}).get("retry_after", 35)
                log.warning(f"⏳ Rate limit — {wait}s")
                await asyncio.sleep(wait)
            elif data.get("error_code") in (400, 403):
                log.error(f"TG error {data}")
                return False
            else:
                await asyncio.sleep(5)
        except Exception as e:
            log.warning(f"TG attempt {attempt+1}: {e}")
            await asyncio.sleep(8)
    return False

async def send_startup(client: httpx.AsyncClient):
    now = datetime.now(TEHRAN_TZ).strftime("%Y/%m/%d  %H:%M")
    text = (
        "🛡️ <b>Military Intel Bot — آنلاین</b>\n\n"
        f"⏰ {now}\n"
        f"📡 <b>{len(RSS_FEEDS)}</b> منبع RSS نظامی\n"
        f"📰 <b>{len(GOOGLE_FEEDS)}</b> جستجوی Google News\n"
        f"𝕏 <b>{len(TWITTER_ACCOUNTS)}</b> خبرنگار و تحلیلگر Twitter\n\n"
        "🇺🇸 Pentagon · CENTCOM · USNI · Defense News\n"
        "🇮🇱 IDF · Jerusalem Post · Haaretz · i24\n"
        "🇮🇷 Iran International · Radio Farda\n"
        "🌐 ISW · Bellingcat · OSINT Defender · Reuters\n"
        "𝕏 OSINTdefender · IntelCrab · WarMonitor · IDF · CENTCOM\n\n"
        "#شروع #military_bot"
    )
    await tg_send(client, text)

# ════════════════════════════════════════════════════════════════
# حلقه اصلی
# ════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID تنظیم نشده!")
        return

    is_first_run = not Path(SEEN_FILE).exists()
    seen = load_seen()
    log.info(f"🚀 شروع | {len(seen)} آیتم در حافظه | اولین اجرا: {is_first_run}")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        if is_first_run:
            await send_startup(client)

        collected: list[tuple] = []  # (entry, cfg)

        for cfg in ALL_FEEDS:
            is_tw = bool(cfg.get("nitter_handle"))
            entries = fetch_feed(cfg)
            src_count = 0
            for entry in entries:
                eid = make_id(entry)
                if eid in seen:
                    continue
                if not is_relevant(entry, is_twitter=is_tw):
                    seen.add(eid)
                    continue
                collected.append((eid, entry, cfg, is_tw))
                src_count += 1
            if src_count:
                log.info(f"  📥 {cfg['name']}: {src_count} جدید")

        # محدود کردن به MAX_NEW_PER_RUN
        if len(collected) > MAX_NEW_PER_RUN:
            log.warning(f"⚠️ {len(collected)} خبر — محدود به {MAX_NEW_PER_RUN}")
            collected = collected[-MAX_NEW_PER_RUN:]

        sent = 0
        for eid, entry, cfg, is_tw in collected:
            msg = build_message(entry, cfg["name"], is_tw)
            ok = await tg_send(client, msg)
            if ok:
                seen.add(eid)
                sent += 1
                log.info(f"  ✅ [{cfg['name']}] {entry.get('title','')[:55]}")
            else:
                log.error(f"  ❌ ارسال ناموفق")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"✔️ پایان | {sent}/{len(collected)} ارسال شد")

if __name__ == "__main__":
    asyncio.run(main())
