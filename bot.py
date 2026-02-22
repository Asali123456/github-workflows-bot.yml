"""
╔══════════════════════════════════════════════════════════════════════════╗
║        🛡️ Military Intel Bot v10 — ALL BUGS FIXED                        ║
║                                                                          ║
║  ✅ Fix1: Twitter/RSSHub مرده → Google News journalist search            ║
║  ✅ Fix2: Gemini 429 → dual-model fallback + exponential backoff         ║
║  ✅ Fix3: URLهای مرده حذف/جایگزین شدند                                   ║
║  ✅ Fix4: Cutoff 2h → 6h (96% خبرها قدیمی فیلتر می‌شدند)               ║
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

SEEN_FILE       = "seen.json"
MAX_NEW_PER_RUN = 20
MAX_MSG_LEN     = 4096
SEND_DELAY      = 2
TEHRAN_TZ       = pytz.timezone("Asia/Tehran")

# ✅ Fix4: پنجره ۶ ساعت — قبلاً ۲ ساعت بود و 96% خبرها رد می‌شد
CUTOFF_HOURS = 6

def get_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=CUTOFF_HOURS)

# ════════════════════════════════════════════════════════════════
# ─── ۱. فیدهای RSS — فقط URLهای کار‌کرده (از لاگ تأیید شده)
# ════════════════════════════════════════════════════════════════
RSS_FEEDS = [
    # ══ خبرگزاری‌های بزرگ ══
    {"name": "🌐 Reuters World",      "url": "https://feeds.reuters.com/reuters/worldNews"},
    {"name": "🌐 Reuters Top",        "url": "https://feeds.reuters.com/reuters/topNews"},
    {"name": "🌐 AP Top",             "url": "https://feeds.apnews.com/rss/apf-topnews"},
    {"name": "🌐 AP World",           "url": "https://feeds.apnews.com/rss/apf-WorldNews"},
    {"name": "🌐 AP Military",        "url": "https://apnews.com/hub/military-and-defense?format=rss"},
    {"name": "🌐 Bloomberg Politics", "url": "https://feeds.bloomberg.com/politics/news.rss"},
    {"name": "🌐 WSJ World",          "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"},
    # ✅ NYT → از Google News (RSS 404 است)
    {"name": "🌐 NYT (GNews)",        "url": "https://news.google.com/rss/search?q=site:nytimes.com+iran+israel+military&hl=en-US&gl=US&ceid=US:en"},
    # ✅ CNN — کار می‌کند
    {"name": "🌐 CNN Middle East",    "url": "http://rss.cnn.com/rss/edition_meast.rss"},
    {"name": "🌐 CNN World",          "url": "http://rss.cnn.com/rss/edition_world.rss"},
    # ✅ BBC — با https کار می‌کند
    {"name": "🌐 BBC Middle East",    "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"name": "🌐 BBC World",          "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "🌐 Al Jazeera",         "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "🌐 Fox News World",     "url": "https://moxie.foxnews.com/google-publisher/world.xml"},
    {"name": "🌐 Politico NatSec",   "url": "https://rss.politico.com/defense.xml"},
    {"name": "🌐 Politico Politics", "url": "https://rss.politico.com/politics-news.xml"},
    # ✅ The Hill — با redirect کار می‌کند
    {"name": "🌐 The Hill",           "url": "https://thehill.com/news/feed/"},
    {"name": "🌐 Foreign Policy",     "url": "https://foreignpolicy.com/feed/"},
    {"name": "🌐 Foreign Affairs",    "url": "https://www.foreignaffairs.com/rss.xml"},
    {"name": "🌐 The Intercept",      "url": "https://theintercept.com/feed/?rss=1"},
    {"name": "🌐 Middle East Eye",    "url": "https://www.middleeasteye.net/rss"},

    # ══ اکسیوس — از Google News ══
    {"name": "📰 Axios (GNews)",      "url": "https://news.google.com/rss/search?q=site:axios.com+iran+israel+military+national+security&hl=en-US&gl=US&ceid=US:en"},

    # ══ آمریکا نظامی — فقط URLهای کار‌کرده ══
    {"name": "🇺🇸 Pentagon",          "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"},
    {"name": "🇺🇸 CENTCOM (GNews)",   "url": "https://news.google.com/rss/search?q=CENTCOM+military+operation+Iran+Iraq&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🇺🇸 USNI News",         "url": "https://news.usni.org/feed"},
    {"name": "🇺🇸 Breaking Defense",  "url": "https://breakingdefense.com/feed/"},
    {"name": "🇺🇸 Defense News",      "url": "https://www.defensenews.com/arc/outboundfeeds/rss/"},
    {"name": "🇺🇸 Military Times",    "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/"},
    # ✅ Stars & Stripes → GNews (feed 404)
    {"name": "🇺🇸 Stars & Stripes",   "url": "https://news.google.com/rss/search?q=site:stripes.com+iran+israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🇺🇸 C4ISRNET",          "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/"},
    # ✅ The War Zone — URL صحیح (twz.com که کار می‌کند)
    {"name": "🇺🇸 The War Zone",      "url": "https://www.twz.com/feed"},
    {"name": "🇺🇸 War on Rocks",      "url": "https://warontherocks.com/feed/"},
    {"name": "🇺🇸 Task & Purpose",    "url": "https://taskandpurpose.com/feed/"},

    # ══ اسراییل ══
    {"name": "🇮🇱 IDF (GNews)",       "url": "https://news.google.com/rss/search?q=IDF+Israel+Defense+Forces+operation+strike&hl=en-US&gl=US&ceid=US:en"},
    # ✅ JP All headlines (Military 404 است)
    {"name": "🇮🇱 Jerusalem Post",    "url": "https://www.jpost.com/rss/rssfeedsheadlines.aspx"},
    {"name": "🇮🇱 Times of Israel",   "url": "https://www.timesofisrael.com/feed/"},
    {"name": "🇮🇱 Haaretz (GNews)",   "url": "https://news.google.com/rss/search?q=site:haaretz.com+iran+israel+war+military&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🇮🇱 Israel Hayom",      "url": "https://www.israelhayom.com/feed/"},
    # ✅ Ynetnews → GNews (feed 404)
    {"name": "🇮🇱 Ynetnews (GNews)",  "url": "https://news.google.com/rss/search?q=site:ynetnews.com+iran+israel+military&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🇮🇱 i24 News",          "url": "https://www.i24news.tv/en/rss"},
    # ✅ Arutz Sheva — کار می‌کند
    {"name": "🇮🇱 Arutz Sheva",       "url": "https://www.israelnationalnews.com/rss.aspx"},

    # ══ ایران ══
    {"name": "🇮🇷 Iran International","url": "https://www.iranintl.com/en/rss"},
    # ✅ Radio Farda — URL جدید RFE/RL
    {"name": "🇮🇷 Radio Farda",       "url": "https://www.radiofarda.com/api/zoyqvpemr"},

    # ══ تحلیلی / OSINT ══
    {"name": "🔍 ISW (GNews)",        "url": "https://news.google.com/rss/search?q=site:understandingwar.org+iran+israel&hl=en-US&gl=US&ceid=US:en"},
    {"name": "🔍 Long War Journal",   "url": "https://www.longwarjournal.org/feed"},
    {"name": "🔍 Bellingcat",         "url": "https://www.bellingcat.com/feed/"},
    {"name": "🔍 OSINT Defender",     "url": "https://osintdefender.com/feed/"},
    # ✅ RAND → GNews (XML 404)
    {"name": "🔍 RAND (GNews)",       "url": "https://news.google.com/rss/search?q=site:rand.org+iran+israel+military+nuclear&hl=en-US&gl=US&ceid=US:en"},
    # ✅ Lawfare → GNews (403)
    {"name": "🔍 Lawfare (GNews)",    "url": "https://news.google.com/rss/search?q=site:lawfaremedia.org+iran+israel&hl=en-US&gl=US&ceid=US:en"},
]

# ════════════════════════════════════════════════════════════════
# ─── ۲. Google News — جستجوهای موضوعی
# ════════════════════════════════════════════════════════════════
TOPIC_QUERIES = [
    ("⚔️ Iran Israel War",      "Iran Israel war attack strike"),
    ("⚔️ Iran Airstrike",       "Iran airstrike bomb explosion"),
    ("⚔️ US Iran Military",     "United States Iran military IRGC"),
    ("⚔️ IDF Operation",        "IDF military operation strike Gaza"),
    ("⚔️ Iran Nuclear",         "Iran nuclear IAEA uranium enrichment"),
    ("⚔️ Iran Missile Drone",   "Iran ballistic missile drone attack"),
    ("⚔️ Hezbollah IDF",        "Hezbollah IDF Lebanon border strike"),
    ("⚔️ Strait Hormuz",        "Strait Hormuz tanker navy seized"),
    ("⚔️ IRGC Attack",          "IRGC Revolutionary Guard attack base"),
    ("⚔️ Israel Airstrike",     "Israel airstrike Syria Iraq Iran"),
    ("⚔️ Mossad Operation",     "Mossad CIA covert operation"),
    ("⚔️ US Navy Gulf",         "US carrier strike group Persian Gulf"),
    ("⚔️ Iran Sanctions",       "Iran sanctions oil SWIFT 2026"),
    ("⚔️ Red Sea Houthis",      "Red Sea Houthi attack ship missile"),
    ("⚔️ Gaza Deal",            "Gaza ceasefire Hamas IDF deal"),
    ("⚔️ Iran Proxy",           "Iran proxy militia Iraq Syria US base"),
    ("⚔️ Nuclear Escalation",   "nuclear military escalation Middle East"),
    ("⚔️ Trump Iran Israel",    "Trump Iran Israel military policy"),
    ("⚔️ Khamenei Netanyahu",   "Khamenei Netanyahu threat war"),
    ("⚔️ Iron Dome",            "Iron Dome Patriot Arrow missile intercept"),
]

def gnews(q):
    return f"https://news.google.com/rss/search?q={q.replace(' ','+')}&hl=en-US&gl=US&ceid=US:en&num=15"

TOPIC_FEEDS = [{"name": n, "url": gnews(q)} for n, q in TOPIC_QUERIES]

# ════════════════════════════════════════════════════════════════
# ─── ✅ Fix1: Twitter → Google News journalist search
# ════════════════════════════════════════════════════════════════
# RSSHub کاملاً بلاک شده (rsshub.app → google.com/404)
# راه‌حل: Google News جستجوی نام خبرنگار + موضوع = همان خبرها را برمی‌گرداند
JOURNALIST_QUERIES = [
    # OSINT
    ("🔍 OSINTdefender",       "OSINTdefender iran israel military"),
    ("🔍 Intel Crab",          "IntelCrab military attack strike"),
    ("🔍 War Monitor",         "WarMonitor conflict strike attack"),
    ("🔍 Aurora Intel",        "AuroraIntel military intelligence"),
    ("🔍 GeoConfirmed",        "GeoConfirmed military conflict"),
    # Axios
    ("📰 Barak Ravid",         "Barak Ravid Iran Israel Axios"),
    ("📰 Alex Ward",           "Alex Ward national security Axios"),
    # Reuters
    ("📰 Idrees Ali",          "Idrees Ali Pentagon Reuters"),
    ("📰 Phil Stewart",        "Phil Stewart military Reuters"),
    # NYT
    ("📰 Farnaz Fassihi",      "Farnaz Fassihi Iran NYT"),
    ("📰 Eric Schmitt",        "Eric Schmitt military national security NYT"),
    # WaPo
    ("📰 Dan Lamothe",         "Dan Lamothe military Washington Post"),
    # Politico / FP
    ("📰 Lara Seligman",       "Lara Seligman defense Politico"),
    ("📰 Jack Detsch",         "Jack Detsch Pentagon Foreign Policy"),
    # اسراییل
    ("🇮🇱 Yossi Melman",       "Yossi Melman Mossad Israel intelligence"),
    ("🇮🇱 Seth Frantzman",     "Seth Frantzman Israel defense"),
    # منطقه‌ای
    ("🌐 Joyce Karam",         "Joyce Karam Middle East national security"),
    ("🌐 Ragip Soylu",         "Ragip Soylu Middle East Turkey"),
    # هشدار
    ("⚠️ DEFCON",              "DEFCON nuclear alert military escalation"),
    ("⚠️ Arms Control",        "arms control nuclear Iran missile"),
]

JOURNALIST_FEEDS = [
    {"name": f"𝕏 {n}", "url": gnews(q), "is_journalist": True}
    for n, q in JOURNALIST_QUERIES
]

ALL_FEEDS = RSS_FEEDS + TOPIC_FEEDS + JOURNALIST_FEEDS

# ════════════════════════════════════════════════════════════════
# فیلترها
# ════════════════════════════════════════════════════════════════
KEYWORDS = [
    "سپاه","موشک","جنگ","حمله","اسراییل","آمریکا","ایران","هسته‌ای","پهپاد","نظامی",
    "iran","irgc","khamenei","tehran","revolutionary guard","nuclear",
    "israel","idf","mossad","netanyahu","hamas","hezbollah","houthi",
    "pentagon","centcom","us forces","us military","us base",
    "strike","airstrike","missile","ballistic","drone",
    "attack","bomb","explosion","assassination","operation",
    "warship","carrier","navy","air force",
    "persian gulf","strait of hormuz","red sea","middle east",
    "iron dome","arrow","patriot","hypersonic",
    "uranium","enrichment","natanz","fordo","iaea",
    "intelligence","cia","covert","sanction",
    "gaza","west bank","lebanon","syria","iraq","yemen",
    "trump","war","conflict","escalat","deploy",
]

def is_fresh(entry: dict) -> bool:
    cutoff = get_cutoff()
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if not t: return False
        dt = datetime(*t[:6], tzinfo=timezone.utc)
        return dt >= cutoff
    except:
        return False

def is_relevant(entry: dict, is_journalist: bool = False) -> bool:
    text = " ".join([
        str(entry.get("title", "")),
        str(entry.get("summary", "")),
        str(entry.get("description", "")),
    ]).lower()
    if is_journalist:
        kw = ["iran","israel","idf","irgc","strike","war","attack","missile",
              "drone","military","nuclear","hezbollah","hamas","houthi",
              "centcom","pentagon","gaza","lebanon","tehran","sanction"]
        return any(k in text for k in kw)
    return any(k in text for k in KEYWORDS)

# ════════════════════════════════════════════════════════════════
# دریافت فیدها
# ════════════════════════════════════════════════════════════════
async def fetch_one(client: httpx.AsyncClient, cfg: dict) -> list:
    try:
        r = await client.get(
            cfg["url"],
            timeout=httpx.Timeout(12.0),
            headers={"User-Agent": "Mozilla/5.0 MilNewsBot/10.0"}
        )
        if r.status_code == 200:
            entries = feedparser.parse(r.text).entries
            return entries or []
    except:
        pass
    return []

async def fetch_all(client: httpx.AsyncClient) -> list:
    tasks = [fetch_one(client, cfg) for cfg in ALL_FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for i, res in enumerate(results):
        if isinstance(res, list):
            cfg = ALL_FEEDS[i]
            is_j = bool(cfg.get("is_journalist"))
            for entry in res:
                out.append((entry, cfg, is_j))
    return out

# ════════════════════════════════════════════════════════════════
# ✅ Fix2: Gemini — dual-model + exponential backoff
# ════════════════════════════════════════════════════════════════
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# مدل اصلی و fallback با quota جداگانه
GEMINI_MODELS = [
    "gemini-2.0-flash",       # اصلی: 15 RPM رایگان
    "gemini-1.5-flash",       # fallback: quota جداگانه
    "gemini-1.5-flash-8b",    # آخرین fallback: سبک‌تر
]

async def translate_batch(
    client: httpx.AsyncClient,
    articles: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    if not GEMINI_API_KEY or not articles:
        return articles

    items_text = ""
    for i, (title, summary) in enumerate(articles):
        items_text += f"###ITEM_{i}###\nTITLE: {title[:300]}\nBODY: {summary[:450]}\n"

    prompt = f"""ترجمه {len(articles)} خبر نظامی به فارسی روان و خبری.
قوانین: فقط ترجمه، بدون توضیح. اسامی خاص دقیق. لحن رسمی خبرگزاری.

فرمت خروجی دقیقاً:
###ITEM_0###
عنوان: [ترجمه]
متن: [ترجمه]
###ITEM_1###
عنوان: [ترجمه]
متن: [ترجمه]
...

===خبرها===
{items_text}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.05, "maxOutputTokens": 8192}
    }

    # امتحان هر مدل به ترتیب
    for model in GEMINI_MODELS:
        url = f"{GEMINI_BASE}/{model}:generateContent?key={GEMINI_API_KEY}"
        wait = 35  # شروع با ۳۵ ثانیه

        for attempt in range(3):
            try:
                log.info(f"🌐 Gemini [{model}] — attempt {attempt+1}")
                r = await client.post(url, json=payload, timeout=httpx.Timeout(90.0))

                if r.status_code == 200:
                    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    result = _parse_batch(raw, articles)
                    ok = sum(1 for i, x in enumerate(result) if x != articles[i])
                    log.info(f"✅ Gemini [{model}]: {ok}/{len(articles)} ترجمه شد")
                    return result

                elif r.status_code == 429:
                    retry_h = r.headers.get("Retry-After", "")
                    wait_s  = int(retry_h) if retry_h.isdigit() else wait
                    log.warning(f"⏳ Gemini [{model}] 429 — {wait_s}s صبر (attempt {attempt+1})")
                    await asyncio.sleep(wait_s)
                    wait = min(wait * 2, 120)  # exponential backoff تا ۲ دقیقه

                elif r.status_code == 503:
                    log.warning(f"⏳ Gemini [{model}] 503 — 20s")
                    await asyncio.sleep(20)

                else:
                    log.warning(f"Gemini [{model}] {r.status_code}")
                    break  # این مدل کار نمی‌کند، بعدی

            except asyncio.TimeoutError:
                log.warning(f"⏳ Gemini [{model}] timeout")
                await asyncio.sleep(10)
            except Exception as e:
                log.debug(f"Gemini [{model}]: {e}")
                break

        log.warning(f"⚠️ Gemini [{model}] شکست — مدل بعدی")

    # اگه همه مدل‌ها شکست خوردن، متن اصلی انگلیسی
    log.warning("⚠️ همه مدل‌های Gemini شکست — خبر به انگلیسی ارسال می‌شود")
    return articles


def _parse_batch(raw: str, fallback: list[tuple[str, str]]) -> list[tuple[str, str]]:
    results = list(fallback)
    pattern = re.compile(
        r'###ITEM_(\d+)###\s*\n'
        r'(?:عنوان|title)\s*:\s*(.+?)\s*\n'
        r'(?:متن|body|text)\s*:\s*(.+?)(?=###ITEM_|\Z)',
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
def clean_html(text: str) -> str:
    if not text: return ""
    return BeautifulSoup(str(text), "html.parser").get_text(" ", strip=True)

def make_id(entry: dict) -> str:
    key = entry.get("link") or entry.get("id") or entry.get("title") or ""
    return hashlib.md5(key.encode("utf-8")).hexdigest()

def make_title_id(title: str) -> str:
    t = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', title.lower())
    return "t:" + hashlib.md5(t[:200].encode()).hexdigest()

def format_dt(entry: dict) -> str:
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).astimezone(TEHRAN_TZ).strftime("🕐 %H:%M  |  📅 %Y/%m/%d")
    except: pass
    return ""

def esc(t: str) -> str:
    return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def trim(t: str, n: int) -> str:
    t = re.sub(r'\s+', ' ', t).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"

# ════════════════════════════════════════════════════════════════
# حافظه
# ════════════════════════════════════════════════════════════════
def load_seen() -> set:
    if Path(SEEN_FILE).exists():
        try:
            with open(SEEN_FILE) as f: return set(json.load(f))
        except: pass
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-15000:], f)

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
                "disable_web_page_preview": True,
            }, timeout=httpx.Timeout(15.0))
            data = r.json()
            if data.get("ok"): return True
            if data.get("error_code") == 429:
                wait = data.get("parameters", {}).get("retry_after", 20)
                await asyncio.sleep(wait)
            elif data.get("error_code") in (400, 403):
                log.error(f"TG fatal: {data.get('description')}")
                return False
            else:
                await asyncio.sleep(5)
        except Exception as e:
            log.warning(f"TG #{attempt+1}: {e}")
            await asyncio.sleep(8)
    return False

# ════════════════════════════════════════════════════════════════
# حلقه اصلی
# ════════════════════════════════════════════════════════════════
async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        log.error("❌ BOT_TOKEN یا CHANNEL_ID تنظیم نشده!"); return

    seen   = load_seen()
    cutoff = get_cutoff()
    log.info(f"🚀 {len(ALL_FEEDS)} منبع ({len(RSS_FEEDS)} RSS + {len(TOPIC_FEEDS)} موضوع + {len(JOURNALIST_FEEDS)} خبرنگار)")
    log.info(f"📅 Cutoff: {CUTOFF_HOURS} ساعت اخیر ({cutoff.astimezone(TEHRAN_TZ).strftime('%H:%M تهران')} به بعد)")
    log.info(f"💾 حافظه: {len(seen)} خبر قبلی")

    async with httpx.AsyncClient(follow_redirects=True) as client:

        # مرحله ۱: دریافت
        log.info("⏬ دریافت همزمان...")
        raw = await fetch_all(client)
        log.info(f"📥 {len(raw)} آیتم خام")

        # مرحله ۲: فیلتر
        collected  = []
        title_seen = set()
        old_cnt = irrel_cnt = dup_cnt = 0

        for entry, cfg, is_j in raw:
            eid = make_id(entry)
            if eid in seen: continue

            if not is_fresh(entry):
                seen.add(eid); old_cnt += 1; continue

            if not is_relevant(entry, is_journalist=is_j):
                seen.add(eid); irrel_cnt += 1; continue

            raw_title = clean_html(entry.get("title", ""))
            tid = make_title_id(raw_title)
            if tid in title_seen:
                seen.add(eid); dup_cnt += 1; continue

            title_seen.add(tid)
            collected.append((eid, entry, cfg, is_j))

        log.info(f"📊 فیلتر: {old_cnt} قدیمی | {irrel_cnt} نامرتبط | {dup_cnt} تکراری | ✅ {len(collected)} جدید")

        collected = list(reversed(collected))
        if len(collected) > MAX_NEW_PER_RUN:
            log.warning(f"⚠️ {len(collected)} → محدود به {MAX_NEW_PER_RUN}")
            collected = collected[-MAX_NEW_PER_RUN:]

        if not collected:
            log.info("💤 هیچ خبر جدیدی نیست")
            save_seen(seen)
            return

        # مرحله ۳: ترجمه دسته‌ای
        articles_in = []
        for eid, entry, cfg, is_j in collected:
            en_t = trim(clean_html(entry.get("title", "")), 300)
            en_s = trim(clean_html(entry.get("summary") or entry.get("description") or ""), 450)
            articles_in.append((en_t, en_s))

        log.info(f"🌐 ترجمه دسته‌ای {len(articles_in)} خبر...")
        translations = await translate_batch(client, articles_in)

        # مرحله ۴: ارسال
        sent = 0
        for i, (eid, entry, cfg, is_j) in enumerate(collected):
            en_title         = articles_in[i][0]
            fa_title, fa_sum = translations[i]
            link = entry.get("link", "")
            dt   = format_dt(entry)
            icon = "𝕏" if is_j else "📡"

            lines = [f"🔴 <b>{esc(fa_title)}</b>", ""]
            if fa_sum and len(fa_sum) > 10 and fa_sum.lower() not in fa_title.lower():
                lines += [esc(fa_sum), ""]
            lines += ["─────────────", f"📌 <i>{esc(en_title)}</i>"]
            if dt:   lines.append(dt)
            lines.append(f"{icon} <b>{cfg['name']}</b>")
            if link: lines.append(f'🔗 <a href="{link}">منبع</a>')

            if await tg_send(client, "\n".join(lines)):
                seen.add(eid); sent += 1
                log.info(f"  ✅ {fa_title[:50]}")
            else:
                log.error("  ❌ ارسال ناموفق")
            await asyncio.sleep(SEND_DELAY)

        save_seen(seen)
        log.info(f"🏁 پایان | {sent}/{len(collected)} خبر ارسال شد")

if __name__ == "__main__":
    asyncio.run(main())
