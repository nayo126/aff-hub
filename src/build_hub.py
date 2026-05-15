"""aff-hub のindex.html / daily / feed.json をビルド。

入力:
  ~/Desktop/pin-money/data/products/{date}.json
  ~/MONETIZATION_IDS.json
出力:
  public/index.html
  public/daily/{date}.html
  public/feed.json
  public/assets/style.css
"""
from __future__ import annotations

import html
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.utils import (DATA, JST, PUBLIC, jst_today, load_config,
                       load_monetization_ids, setup_logger)

log = setup_logger("build_hub")

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-font-smoothing: antialiased; }
html, body { background: #0d0d0f; color: #f5f5f7; font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Helvetica Neue", sans-serif; }
.wrap { max-width: 520px; margin: 0 auto; padding: 32px 20px 80px; }
.profile { text-align: center; padding: 16px 0 28px; }
.profile .avatar { width: 84px; height: 84px; border-radius: 50%; margin: 0 auto 14px; background: linear-gradient(135deg, #ff7a00, #ff3d77); display: flex; align-items: center; justify-content: center; font-size: 32px; }
.profile h1 { font-size: 22px; font-weight: 700; }
.profile .handle { color: #999; font-size: 14px; margin-top: 4px; }
.profile .tagline { color: #ccc; font-size: 13px; margin-top: 10px; line-height: 1.6; }
.section { margin: 28px 0 10px; font-size: 13px; color: #8a8a8e; letter-spacing: 0.1em; text-transform: uppercase; }
.row { display: flex; flex-direction: column; gap: 10px; }
.btn { display: block; padding: 14px 18px; background: #18181b; border: 1px solid #2a2a2f; border-radius: 14px; color: #f5f5f7; text-decoration: none; font-weight: 600; transition: transform .12s, border-color .12s; }
.btn:hover { transform: translateY(-1px); border-color: #4a4a52; }
.btn .ico { display: inline-block; margin-right: 10px; }
.card { background: #15151a; border: 1px solid #2a2a2f; border-radius: 14px; padding: 14px; display: flex; gap: 12px; align-items: center; color: inherit; text-decoration: none; transition: transform .12s; }
.card:hover { transform: translateY(-1px); }
.card img { width: 64px; height: 64px; border-radius: 10px; object-fit: cover; background: #2a2a2f; flex-shrink: 0; }
.card .meta { flex: 1; min-width: 0; }
.card .ttl { font-size: 14px; font-weight: 600; color: #f5f5f7; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card .price { color: #ff7a00; font-size: 13px; font-weight: 700; margin-top: 4px; }
.foot { text-align: center; margin-top: 40px; color: #5a5a62; font-size: 11px; line-height: 1.7; }
.foot a { color: #5a5a62; }
.card.camp { background: linear-gradient(135deg, #1f1410, #2a1f15); border-color: #ff7a00; flex-direction: column; align-items: stretch; gap: 4px; }
.card.camp .ttl { color: #ffcfa3; }
.card.camp .campsum { color: #c9c4be; font-size: 12px; line-height: 1.5; margin-top: 4px; }
.card.camp .campend { color: #ff7a00; font-size: 11px; margin-top: 4px; font-weight: 600; }
"""


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def load_latest_products(cfg: dict) -> list[dict]:
    pdir = Path(cfg["data_sources"]["rakuten_products_dir"])
    if not pdir.exists():
        log.warning(f"no rakuten products dir: {pdir}")
        return []
    files = sorted(pdir.glob("*.json"))
    if not files:
        return []
    latest = json.loads(files[-1].read_text(encoding="utf-8"))
    out: list[dict] = []
    for slug, g in latest.get("genres", {}).items():
        for it in g.get("items", []):
            it["_genre"] = slug
            it["_genre_name"] = g.get("name", slug)
            out.append(it)
    # レビュー件数で並べ替え（人気優先）
    out.sort(key=lambda x: x.get("review_count", 0), reverse=True)
    return out


def load_campaigns() -> list[dict]:
    """rakuten-radar が書いた campaigns.json を読む。"""
    p = PUBLIC / "campaigns.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("campaigns") or []
    except Exception as e:
        log.warning(f"failed to load campaigns.json: {e}")
        return []


def render_campaign_row(c: dict) -> str:
    name = html.escape(c.get("name") or "")
    summary = html.escape(_truncate(c.get("summary") or "", 80))
    url = html.escape(c.get("url") or "#")
    end = html.escape(c.get("end_jst") or "")
    return f'''<a class="card camp" href="{url}" target="_blank" rel="nofollow sponsored noopener">
  <div class="meta">
    <div class="ttl">🔥 {name}</div>
    <div class="campsum">{summary}</div>
    <div class="campend">〜 {end}</div>
  </div>
</a>'''


def render_card(it: dict) -> str:
    img = (it.get("images") or [""])[0]
    aff = it.get("affiliate_url") or it.get("url") or "#"
    title = html.escape(_truncate(it.get("name", ""), 70))
    price = it.get("price", 0)
    price_str = f"¥{int(price):,}" if price else ""
    return f'''<a class="card" href="{html.escape(aff)}" target="_blank" rel="nofollow sponsored noopener">
  <img src="{html.escape(img)}" loading="lazy" alt="">
  <div class="meta">
    <div class="ttl">{title}</div>
    <div class="price">{price_str}</div>
  </div>
</a>'''


def render_social_btn(s: dict) -> str:
    url = s.get("url") or ""
    if not url:
        return ""
    name = html.escape(s.get("name", ""))
    icon = s.get("icon", "")
    return f'<a class="btn" href="{html.escape(url)}" target="_blank" rel="noopener"><span class="ico">{icon}</span>{name}</a>'


def render_jsonld_products(products: list[dict], base_url: str) -> str:
    items = []
    for i, it in enumerate(products[:20], start=1):
        img = (it.get("images") or [""])[0]
        aff = it.get("affiliate_url") or it.get("url") or ""
        price = it.get("price", 0)
        rc = it.get("review_count", 0)
        ra = it.get("review_average", 0)
        product = {
            "@type": "ListItem",
            "position": i,
            "item": {
                "@type": "Product",
                "name": (it.get("name") or "")[:120],
                "image": img,
                "url": aff,
                "offers": {
                    "@type": "Offer",
                    "price": str(int(price)) if price else "0",
                    "priceCurrency": "JPY",
                    "availability": "https://schema.org/InStock",
                    "url": aff,
                },
            },
        }
        if rc and ra:
            product["item"]["aggregateRating"] = {
                "@type": "AggregateRating",
                "ratingValue": str(ra),
                "reviewCount": str(rc),
            }
        items.append(product)
    payload = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": items,
    }
    return json.dumps(payload, ensure_ascii=False)


def render_page(cfg: dict, products: list[dict], *, daily_date: str | None = None) -> str:
    p = cfg["profile"]
    site = cfg["site"]
    base_url = site.get("base_url", "")
    featured = products[: int(cfg.get("featured_count", 10))]
    cards = "\n".join(render_card(it) for it in featured)
    socials = "\n".join(filter(None, [render_social_btn(s) for s in cfg.get("social", [])]))
    campaigns = load_campaigns()
    camp_rows = "\n".join(render_campaign_row(c) for c in campaigns[:5]) if campaigns else ""
    camp_section = (
        f'\n  <div class="section">▼ 開催中のキャンペーン</div>\n  <div class="row">{camp_rows}</div>\n'
        if camp_rows else ""
    )
    today = daily_date or jst_today()
    daily_link = f'<a class="btn" href="/aff-hub/daily/{today}.html">📅 今日の推し全商品（{today}）</a>'
    title = html.escape(site.get("title", "aff-hub"))
    desc = html.escape(p.get("tagline", ""))
    canonical = f"{base_url}/" if not daily_date else f"{base_url}/daily/{daily_date}.html"
    og_image = (featured[0].get("images") or [""])[0] if featured else ""
    jsonld = render_jsonld_products(products, base_url)
    return f'''<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer-when-downgrade">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="keywords" content="楽天,アフィリエイト,おすすめ,セール,ランキング,お買い物マラソン,SUPER SALE">
<meta name="author" content="{html.escape(p.get('name',''))}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{html.escape(og_image)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{html.escape(og_image)}">
<link rel="stylesheet" href="/aff-hub/assets/style.css">
<script type="application/ld+json">{jsonld}</script>
</head><body>
<div class="wrap">
  <div class="profile">
    <div class="avatar">🐷→💰</div>
    <h1>{html.escape(p.get('name',''))}</h1>
    <div class="handle">{html.escape(p.get('handle',''))}</div>
    <div class="tagline">{html.escape(p.get('tagline',''))}</div>
  </div>

  <div class="section">▼ SNS</div>
  <div class="row">{socials}</div>
{camp_section}
  <div class="section">▼ 今日の推し</div>
  <div class="row">{daily_link}{cards}</div>

  <div class="foot">
    リンクは楽天市場アフィリエイトを含みます。<br>
    Last updated {html.escape(today)} JST · <a href="https://github.com/{html.escape(site.get('github_user',''))}/{html.escape(site.get('repo',''))}">source</a>
  </div>
</div>
</body></html>'''


def render_sitemap(cfg: dict) -> str:
    base = cfg["site"].get("base_url", "").rstrip("/")
    today = jst_today()
    daily_dir = PUBLIC / "daily"
    urls = [
        f"{base}/",
    ]
    if daily_dir.exists():
        for f in sorted(daily_dir.glob("*.html")):
            urls.append(f"{base}/daily/{f.name}")
    items = "\n".join(
        f"  <url><loc>{u}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>"
        for u in urls
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{items}
</urlset>'''


def render_robots(cfg: dict) -> str:
    base = cfg["site"].get("base_url", "").rstrip("/")
    return f"""User-agent: *
Allow: /

Sitemap: {base}/sitemap.xml
"""


def render_feed(cfg: dict, products: list[dict]) -> str:
    payload = {
        "updated_at": datetime.now(JST).isoformat(),
        "items": [
            {
                "title": it.get("name", ""),
                "url": it.get("affiliate_url") or it.get("url"),
                "image": (it.get("images") or [None])[0],
                "price": it.get("price", 0),
                "review_count": it.get("review_count", 0),
                "genre": it.get("_genre", ""),
            }
            for it in products[:30]
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


THREADS_QUEUE_URL = "https://threads-api-app.onrender.com/api/claude-posts/bulk"


def push_to_threads_queue(cfg: dict, products: list[dict]) -> None:
    """その日の daily ページ URL とトップ3を Threads キューに投入。"""
    if not products:
        return
    state_file = DATA / "threads_pushed.json"
    today = jst_today()
    pushed: dict = {}
    if state_file.exists():
        try:
            pushed = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pushed = {}
    if pushed.get(today):
        log.info(f"already pushed to threads queue for {today}")
        return

    base = cfg["site"].get("base_url", "").rstrip("/")
    daily_url = f"{base}/daily/{today}.html"
    top = products[:3]
    lines = [f"楽天で今売れてる物 ({today})", ""]
    for i, p in enumerate(top, 1):
        name = (p.get("name") or "")[:30]
        price = p.get("price", 0)
        lines.append(f"{i}位 {name}")
        if price:
            lines.append(f"   ¥{int(price):,}")
    lines.append("")
    lines.append(f"全商品→ {daily_url}")
    text = "\n".join(lines)
    # Threads 200字制限
    if len(text) > 480:
        text = text[:475] + "…"

    payload = {
        "items": [{
            "texts": [text],
            "label": f"aff-hub_daily_{today}",
            "type": "楽天アフィ",
            "format": "ランキング型",
        }]
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        THREADS_QUEUE_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = r.read().decode("utf-8", errors="replace")
            log.info(f"threads queue rc={r.status}  body={resp[:120]}")
        pushed[today] = True
        state_file.write_text(json.dumps(pushed, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception as e:
        log.warning(f"threads queue push failed (will retry next build): {e}")


def main() -> int:
    cfg = load_config()
    products = load_latest_products(cfg)
    if not products:
        log.error("no products to render. Run pin-money first.")
        return 1
    log.info(f"loaded {len(products)} products")

    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "assets").mkdir(parents=True, exist_ok=True)
    (PUBLIC / "daily").mkdir(parents=True, exist_ok=True)

    (PUBLIC / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    today = jst_today()
    (PUBLIC / "index.html").write_text(render_page(cfg, products), encoding="utf-8")
    (PUBLIC / "daily" / f"{today}.html").write_text(
        render_page(cfg, products, daily_date=today), encoding="utf-8")
    (PUBLIC / "feed.json").write_text(render_feed(cfg, products), encoding="utf-8")
    (PUBLIC / "sitemap.xml").write_text(render_sitemap(cfg), encoding="utf-8")
    (PUBLIC / "robots.txt").write_text(render_robots(cfg), encoding="utf-8")
    # 404.html for GitHub Pages (redirect to index)
    (PUBLIC / "404.html").write_text(
        '<!DOCTYPE html><meta http-equiv="refresh" content="0;url=/aff-hub/">'
        '<title>Redirecting...</title><a href="/aff-hub/">Go home</a>',
        encoding="utf-8")
    log.info(f"wrote public/ (today={today})")
    push_to_threads_queue(cfg, products)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
