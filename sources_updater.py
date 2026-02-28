#!/usr/bin/env python3
"""
sources_updater.py — هفته‌ای یک بار در GitHub Actions اجرا می‌شود
فقط فایل‌های کوچک دانلود می‌کند (کمتر از ۵ مگابایت)
خروجی: data/extra_sources.json  ← bot.py این را هر بار startup می‌خواند
"""

import asyncio, json, re, io, sys
from pathlib import Path
from datetime import datetime, timezone

try:
    import httpx
    import pandas as pd
except ImportError:
    print("نصب: pip install httpx pandas")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════
# تنظیمات
# ══════════════════════════════════════════════════════════════════════════

# فقط رسانه‌هایی که خاورمیانه/جنگ پوشش می‌دهند
RELEVANT_KEYWORDS = [
    "middle east", "iran", "israel", "arab", "gulf", "nuclear",
    "military", "defense", "security", "foreign", "world",
    "international", "geopolit", "war", "conflict", "sanctions",
    "irgc", "idf", "nato", "terrorism", "intelligence",
]

SPAM_KEYWORDS = [
    "crypto", "bitcoin", "forex", "casino", "adult", "dating",
    "movie", "music", "funny", "meme", "game", "sport", "food",
    "fashion", "travel", "shopping", "nft", "invest",
]

# رسانه‌های بین‌المللی مطمئن که خاورمیانه پوشش می‌دهند
TRUSTED_DOMAINS = {
    "apnews.com", "reuters.com", "bbc.com", "aljazeera.com",
    "nbcnews.com", "cnn.com", "foreignpolicy.com", "axios.com",
    "politico.com", "vox.com", "npr.org", "pbs.org",
    "defensenews.com", "stripes.com", "militarytimes.com",
    "nationalinterest.org", "brookings.edu", "cfr.org",
    "mei.edu", "stimson.org", "rand.org", "wilsoncenter.org",
    "atlanticcouncil.org", "middleeasteye.net", "haaretz.com",
    "jpost.com", "timesofisrael.com", "ynetnews.com",
    "arabnews.com", "alaraby.co.uk",
}

# ══════════════════════════════════════════════════════════════════════════
# منابع برای دانلود (همه کوچک هستند — زیر ۵ مگابایت)
# ══════════════════════════════════════════════════════════════════════════

SOURCES = {

    # ── ercexpo/us-news-domains  (~1.5 MB) ───────────────────────────────
    "ercexpo_domains": {
        "url": "https://raw.githubusercontent.com/ercexpo/us-news-domains/main/dataset/us-news-domains-v2.0.0.csv",
        "type": "csv",
        "desc": "دامنه‌های خبری آمریکا",
    },
    "ercexpo_twitter": {
        "url": "https://raw.githubusercontent.com/ercexpo/us-news-domains/main/dataset/us-news-twitter-v1.0.0.csv",
        "type": "csv",
        "desc": "Twitter handles رسانه‌های خبری",
    },

    # ── TGDataset — فقط channel_list (کوچک) ─────────────────────────────
    # ❌ TGDataset اصلی ۴۶۰ گیگابایت است — آن را دانلود نمی‌کنیم
    # ✅ فقط فایل metadata کوچک آن را می‌گیریم
    "tgdataset_list": {
        "url": "https://raw.githubusercontent.com/SystemsLab-Sapienza/TGDataset/main/data/channel_list.json",
        "type": "json",
        "desc": "لیست کانال‌های تلگرام (metadata فقط)",
    },

    # ── verified Twitter accounts (~200 KB) ──────────────────────────────
    "verified_twitter": {
        "url": "https://raw.githubusercontent.com/thansen0/verified_twitters/main/verified_users.csv",
        "type": "csv",
        "desc": "اکانت‌های verified توییتر",
    },
}

# ══════════════════════════════════════════════════════════════════════════
# دانلود — با timeout و حداکثر ۵ مگابایت
# ══════════════════════════════════════════════════════════════════════════

MAX_FILE_SIZE = 5 * 1024 * 1024   # ۵ مگابایت سقف

async def safe_get(client: httpx.AsyncClient, url: str, desc: str) -> str | None:
    """دانلود امن — اگر فایل بزرگ‌تر از ۵MB بود، رد می‌کند"""
    print(f"  📥 {desc} ...", end=" ", flush=True)
    try:
        # اول فقط header بگیر تا حجم را بدانیم
        head = await client.head(url, timeout=10)
        size = int(head.headers.get("content-length", 0))
        if size > MAX_FILE_SIZE:
            print(f"❌ حجم {size//1024//1024}MB — رد شد (سقف ۵MB)")
            return None

        # دانلود اصل فایل
        r = await client.get(url, timeout=30)
        if r.status_code != 200:
            print(f"❌ HTTP {r.status_code}")
            return None

        if len(r.content) > MAX_FILE_SIZE:
            print(f"❌ حجم {len(r.content)//1024}KB — رد شد")
            return None

        print(f"✅ {len(r.content)//1024}KB")
        return r.text

    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════
# پردازش ercexpo_domains → RSS feeds جدید
# ══════════════════════════════════════════════════════════════════════════

def process_ercexpo_domains(csv_text: str) -> list[dict]:
    """از CSV دامنه‌ها → RSS feeds مرتبط با خاورمیانه"""
    feeds = []
    try:
        df = pd.read_csv(io.StringIO(csv_text))
        cols = {c.lower(): c for c in df.columns}
        print(f"    ستون‌ها: {list(df.columns[:8])}")

        # پیدا کردن ستون‌های مهم
        domain_col = next((cols[k] for k in cols if "domain" in k or "url" in k), None)
        name_col   = next((cols[k] for k in cols if "name" in k or "outlet" in k or "title" in k), None)
        scope_col  = next((cols[k] for k in cols if "scope" in k or "type" in k or "level" in k or "national" in k), None)

        if not domain_col:
            print("    ⚠️  ستون دامنه نیافتم")
            return []

        for _, row in df.iterrows():
            domain = str(row.get(domain_col, "")).strip().lower()
            domain = re.sub(r'^https?://', '', domain).strip("/")
            if not domain or domain == "nan": continue

            name   = str(row.get(name_col, domain) if name_col else domain).strip()
            scope  = str(row.get(scope_col, "") if scope_col else "").lower()

            # فیلتر ۱: فقط national/international (نه purely local)
            if scope and "local" in scope and "national" not in scope:
                continue

            combined = (domain + " " + name).lower()

            # فیلتر ۲: مرتبط با موضوع ما
            is_trusted = any(td in domain for td in TRUSTED_DOMAINS)
            is_relevant = any(kw in combined for kw in RELEVANT_KEYWORDS)

            if not (is_trusted or is_relevant):
                continue

            # ساخت URL فید — الگوهای رایج
            rss_url = f"https://{domain}/feed/"
            feeds.append({
                "n": f"📰 {name}",
                "u": rss_url,
                "domain": domain,
                "source": "ercexpo",
            })

        print(f"    → {len(feeds)} فید مرتبط")
    except Exception as e:
        print(f"    ❌ خطا: {e}")

    return feeds


# ══════════════════════════════════════════════════════════════════════════
# پردازش ercexpo_twitter → Twitter handles جدید
# ══════════════════════════════════════════════════════════════════════════

def process_ercexpo_twitter(csv_text: str) -> list[dict]:
    """از CSV توییتر → handle‌های مرتبط"""
    handles = []
    try:
        df = pd.read_csv(io.StringIO(csv_text))
        cols = {c.lower(): c for c in df.columns}
        print(f"    ستون‌ها: {list(df.columns[:8])}")

        handle_col = next((cols[k] for k in cols
                           if "handle" in k or "screen" in k or "twitter" in k or "username" in k), None)
        name_col   = next((cols[k] for k in cols
                           if "name" in k or "outlet" in k), None)

        if not handle_col:
            print("    ⚠️  ستون handle نیافتم")
            return []

        for _, row in df.iterrows():
            handle = str(row.get(handle_col, "")).strip().lstrip("@")
            if not handle or handle == "nan": continue

            name = str(row.get(name_col, "") if name_col else "").strip()
            combined = (handle + " " + name).lower()

            if any(kw in combined for kw in RELEVANT_KEYWORDS):
                handles.append({
                    "label":  f"📰 {name}" if name and name != "nan" else f"📰 @{handle}",
                    "handle": handle,
                    "source": "ercexpo",
                })

        print(f"    → {len(handles)} handle مرتبط")
    except Exception as e:
        print(f"    ❌ خطا: {e}")

    return handles


# ══════════════════════════════════════════════════════════════════════════
# پردازش verified_twitter → handle‌های خبری تأییدشده
# ══════════════════════════════════════════════════════════════════════════

def process_verified_twitter(csv_text: str) -> list[dict]:
    """از لیست verified — فقط رسانه‌های خبری مرتبط"""
    handles = []
    try:
        df = pd.read_csv(io.StringIO(csv_text))
        cols = {c.lower(): c for c in df.columns}
        print(f"    ستون‌ها: {list(df.columns[:8])}")

        handle_col = next((cols[k] for k in cols
                           if "screen" in k or "handle" in k or "name" in k or "username" in k), None)
        desc_col   = next((cols[k] for k in cols
                           if "desc" in k or "bio" in k or "category" in k), None)

        if not handle_col:
            print("    ⚠️  ستون handle نیافتم")
            return []

        for _, row in df.iterrows():
            handle = str(row.get(handle_col, "")).strip().lstrip("@")
            if not handle or handle == "nan": continue

            desc = str(row.get(desc_col, "") if desc_col else "").lower()

            # فقط رسانه/خبرنگار/تحلیلگر مرتبط
            is_relevant = any(kw in (handle + " " + desc).lower() for kw in RELEVANT_KEYWORDS)
            is_spam     = any(kw in (handle + " " + desc).lower() for kw in SPAM_KEYWORDS)

            if is_relevant and not is_spam:
                handles.append({
                    "label":  f"✅ @{handle}",
                    "handle": handle,
                    "source": "verified_tw",
                })

        print(f"    → {len(handles)} handle خبری/تحلیلی")
    except Exception as e:
        print(f"    ❌ خطا: {e}")

    return handles[:30]   # سقف ۳۰ تا از این منبع


# ══════════════════════════════════════════════════════════════════════════
# پردازش TGDataset channel_list → کانال‌های تلگرامی مرتبط
# ══════════════════════════════════════════════════════════════════════════

def process_tgdataset(json_text: str) -> list[dict]:
    """از channel_list.json → کانال‌های مرتبط با ایران/جنگ"""
    channels = []
    try:
        data = json.loads(json_text)

        # ساختارهای مختلف ممکن
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (data.get("channels") or data.get("data") or
                     data.get("items") or list(data.values()))
            if items and isinstance(items[0], list):
                items = items[0]
        else:
            items = []

        print(f"    {len(items)} کانال در لیست")

        for item in items:
            if isinstance(item, str):
                username = item.strip().lstrip("@")
                title = desc = ""
            elif isinstance(item, dict):
                username = (item.get("username") or item.get("handle") or
                            item.get("id") or item.get("name") or "").strip().lstrip("@")
                title    = (item.get("title") or item.get("name") or "").strip()
                desc     = (item.get("description") or item.get("about") or "").strip()
            else:
                continue

            if not username or len(username) < 3: continue

            combined = (username + " " + title + " " + desc).lower()

            # حذف اسپم
            if any(kw in combined for kw in SPAM_KEYWORDS): continue

            # امتیاز مرتبط بودن
            score = sum(1 for kw in RELEVANT_KEYWORDS if kw in combined)
            if score >= 2:
                channels.append({
                    "label":  f"🔴 {title}" if title else f"🔴 @{username}",
                    "handle": username,
                    "score":  score,
                    "source": "tgdataset",
                })

        channels.sort(key=lambda x: -x["score"])
        print(f"    → {len(channels)} کانال مرتبط (score≥2)")
        return channels[:60]   # سقف ۶۰ کانال برتر

    except Exception as e:
        print(f"    ❌ خطا: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════
# حذف موارد تکراری با bot.py
# ══════════════════════════════════════════════════════════════════════════

def load_existing() -> tuple[set, set, set]:
    """آنچه در bot.py هست را می‌خواند تا تکراری اضافه نکنیم"""
    existing_rss = set()
    existing_tw  = set()
    existing_tg  = set()

    for fname in ["bot.py", "warbot.py", "main.py"]:
        if not Path(fname).exists(): continue
        text = Path(fname).read_text(encoding="utf-8")
        for m in re.finditer(r'"u"\s*:\s*"([^"]+)"', text):
            existing_rss.add(m.group(1).split("?")[0].rstrip("/").lower())
        for m in re.finditer(r'\(\s*"[^"]*"\s*,\s*"([A-Za-z0-9_]{3,50})"\s*\)', text):
            h = m.group(1).lower()
            existing_tw.add(h)
            existing_tg.add(h)
        break

    print(f"  موجود: {len(existing_rss)} RSS  {len(existing_tw)} Twitter  {len(existing_tg)} TG")
    return existing_rss, existing_tw, existing_tg


# ══════════════════════════════════════════════════════════════════════════
# ذخیره نتیجه
# ══════════════════════════════════════════════════════════════════════════

def save(rss: list, tw: list, tg: list):
    Path("data").mkdir(exist_ok=True)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "rss": len(rss),
            "twitter": len(tw),
            "telegram": len(tg),
        },
        "rss_feeds": rss,
        "twitter":   tw,
        "telegram":  tg,
    }
    Path("data/extra_sources.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n✅ data/extra_sources.json ذخیره شد")
    print(f"   RSS: {len(rss)}  Twitter: {len(tw)}  Telegram: {len(tg)}")


# ══════════════════════════════════════════════════════════════════════════
# اجرای اصلی
# ══════════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print("  sources_updater — کشف منابع جدید (فقط فایل‌های کوچک)")
    print("=" * 60)

    existing_rss, existing_tw, existing_tg = load_existing()

    all_rss = []
    all_tw  = []
    all_tg  = []

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": "WarBot-sources/1.0 (+github.com)"},
        timeout=30,
    ) as client:

        for key, meta in SOURCES.items():
            print(f"\n── {key} — {meta['desc']}")
            text = await safe_get(client, meta["url"], meta["desc"])
            if not text:
                continue

            if key == "ercexpo_domains":
                all_rss.extend(process_ercexpo_domains(text))

            elif key == "ercexpo_twitter":
                all_tw.extend(process_ercexpo_twitter(text))

            elif key == "verified_twitter":
                all_tw.extend(process_verified_twitter(text))

            elif key == "tgdataset_list":
                all_tg.extend(process_tgdataset(text))

    # ── حذف تکراری با bot.py ─────────────────────────────────────────────
    print("\n── فیلتر موارد تکراری")
    new_rss = []
    seen_rss = set(existing_rss)
    for f in all_rss:
        url_clean = f["u"].split("?")[0].rstrip("/").lower()
        if url_clean not in seen_rss:
            new_rss.append(f)
            seen_rss.add(url_clean)

    new_tw = []
    seen_tw = set(existing_tw)
    for t in all_tw:
        h = t["handle"].lower()
        if h not in seen_tw:
            new_tw.append(t)
            seen_tw.add(h)

    new_tg = []
    seen_tg = set(existing_tg)
    for t in all_tg:
        h = t["handle"].lower()
        if h not in seen_tg:
            new_tg.append(t)
            seen_tg.add(h)

    print(f"  جدید: {len(new_rss)} RSS  {len(new_tw)} Twitter  {len(new_tg)} Telegram")

    save(new_rss, new_tw, new_tg)


if __name__ == "__main__":
    asyncio.run(main())
