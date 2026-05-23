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


def _aff_hub_rakuten_id() -> str:
    """MONETIZATION_IDS.json の routing に従って aff-hub 用の楽天IDを解決。
    別アカウントID (secondary 等) を aff-hub だけに割り当てられる。"""
    import sys
    sys.path.insert(0, "/Users/tsukaking/.claude/lib")
    try:
        from rakuten_id_router import get_rakuten_id
        return get_rakuten_id("aff-hub") or ""
    except Exception:
        # フォールバック: MIDS を直接読む
        try:
            mids = json.loads((Path.home() / "MONETIZATION_IDS.json").read_text(encoding="utf-8"))
            r = mids.get("rakuten_affiliate") or {}
            return (r.get("ids") or {}).get("main") or r.get("affiliate_id") or ""
        except Exception:
            return ""


def _rewrap_affiliate(raw_item_url: str, aff_id: str) -> str:
    """生の楽天商品URLを aff-hub 用アフィIDでラップ。"""
    import urllib.parse
    if not aff_id or aff_id == "TODO":
        return raw_item_url
    encoded = urllib.parse.quote(raw_item_url, safe="")
    return f"https://hb.afl.rakuten.co.jp/hgc/{aff_id}/?pc={encoded}"


def load_latest_products(cfg: dict) -> list[dict]:
    pdir = Path(cfg["data_sources"]["rakuten_products_dir"])
    if not pdir.exists():
        log.warning(f"no rakuten products dir: {pdir}")
        return []
    files = sorted(pdir.glob("*.json"))
    if not files:
        return []
    latest = json.loads(files[-1].read_text(encoding="utf-8"))
    aff_id = _aff_hub_rakuten_id()
    out: list[dict] = []
    for slug, g in latest.get("genres", {}).items():
        for it in g.get("items", []):
            it["_genre"] = slug
            it["_genre_name"] = g.get("name", slug)
            # pin-money 継承ではなく aff-hub 自身の routing IDで再ラップ
            raw = it.get("url") or ""
            if raw:
                it["affiliate_url"] = _rewrap_affiliate(raw, aff_id)
            out.append(it)
    # レビュー件数で並べ替え（人気優先）
    out.sort(key=lambda x: x.get("review_count", 0), reverse=True)
    return out


def load_campaigns() -> list[dict]:
    """rakuten-radar が書いた campaigns.json を読む。期限切れは除外。"""
    p = PUBLIC / "campaigns.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("campaigns") or []
    except Exception as e:
        log.warning(f"failed to load campaigns.json: {e}")
        return []
    now = datetime.now(JST)
    active = []
    for c in raw:
        end = c.get("end_jst") or ""
        if end:
            try:
                dt = datetime.strptime(end, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
                if dt < now:
                    continue
            except (ValueError, TypeError):
                pass
        active.append(c)
    return active


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


def render_genre_page(cfg: dict, genre_slug: str, genre_name: str,
                      products: list[dict]) -> str:
    """ジャンル別ページ。SEO狙いで個別URLを持たせる。"""
    site = cfg["site"]
    base_url = site.get("base_url", "").rstrip("/")
    cards = "\n".join(render_card(it) for it in products[:30])
    title = html.escape(f"{genre_name} 楽天で本当に売れてる物 {jst_today()}")
    desc = html.escape(f"楽天で今売れている{genre_name}カテゴリの商品を毎日更新。レビュー件数の多い順。")
    canonical = f"{base_url}/genre/{genre_slug}.html"
    og_image = (products[0].get("images") or [""])[0] if products else ""
    jsonld = render_jsonld_products(products, base_url)
    return f'''<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="keywords" content="楽天,{html.escape(genre_name)},おすすめ,人気,ランキング,レビュー">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{html.escape(og_image)}">
<link rel="stylesheet" href="/aff-hub/assets/style.css">
<script type="application/ld+json">{jsonld}</script>
</head><body>
<div class="wrap">
  <div class="profile">
    <div class="avatar">🛍️</div>
    <h1>{html.escape(genre_name)}</h1>
    <div class="tagline">楽天で今売れている{html.escape(genre_name)} · 毎日自動更新</div>
  </div>
  <div class="section">▼ 売れ筋（レビュー多い順）</div>
  <div class="row">{cards}</div>
  <div class="foot">
    <a href="/aff-hub/">← トップに戻る</a><br>
    リンクは楽天市場アフィリエイトを含みます。<br>
    Last updated {jst_today()} JST
  </div>
</div>
</body></html>'''


def render_sitemap(cfg: dict, genre_slugs: list[str]) -> str:
    base = cfg["site"].get("base_url", "").rstrip("/")
    today = jst_today()
    daily_dir = PUBLIC / "daily"
    urls = [
        f"{base}/",
    ]
    if daily_dir.exists():
        for f in sorted(daily_dir.glob("*.html")):
            urls.append(f"{base}/daily/{f.name}")
    for slug in genre_slugs:
        urls.append(f"{base}/genre/{slug}.html")
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


def render_rss(cfg: dict, products: list[dict], campaigns: list[dict]) -> str:
    site = cfg["site"]
    base = site.get("base_url", "").rstrip("/")
    title = html.escape(site.get("title", "aff-hub"))
    desc = html.escape(cfg.get("profile", {}).get("tagline", ""))
    now_rfc = datetime.now(JST).strftime("%a, %d %b %Y %H:%M:%S +0900")
    items_xml = []
    # 商品上位15件
    for p in products[:15]:
        name = html.escape((p.get("name") or "")[:120])
        url = html.escape(p.get("affiliate_url") or p.get("url") or base)
        img = (p.get("images") or [""])[0]
        price = p.get("price", 0)
        guid = html.escape(p.get("code") or url)
        desc_text = html.escape(
            f"楽天で売れてる「{p.get('_genre_name', '')}」: {p.get('name', '')[:80]} ¥{int(price):,}"
            if price else (p.get("name") or "")
        )
        img_tag = f'<enclosure url="{html.escape(img)}" type="image/jpeg"/>' if img else ""
        items_xml.append(f"""<item>
  <title>{name}</title>
  <link>{url}</link>
  <guid isPermaLink="false">{guid}</guid>
  <description>{desc_text}</description>
  <pubDate>{now_rfc}</pubDate>
  {img_tag}
</item>""")
    # キャンペーン
    for c in campaigns[:5]:
        cname = html.escape(c.get("name") or "")
        curl = html.escape(c.get("url") or base)
        csum = html.escape(c.get("summary") or "")
        guid = html.escape(c.get("id") or curl)
        items_xml.append(f"""<item>
  <title>🔥 {cname}</title>
  <link>{curl}</link>
  <guid isPermaLink="false">campaign:{guid}</guid>
  <description>{csum}</description>
  <pubDate>{now_rfc}</pubDate>
</item>""")
    items = "\n".join(items_xml)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
<title>{title}</title>
<link>{base}/</link>
<description>{desc}</description>
<language>ja</language>
<lastBuildDate>{now_rfc}</lastBuildDate>
<atom:link href="{base}/rss.xml" rel="self" type="application/rss+xml"/>
{items}
</channel>
</rss>"""


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

# IndexNow: Bing/Yandex/Seznam等が共通で受け付ける即時インデックスAPI
# https://www.indexnow.org/documentation
# 64桁 hex key (英数字) を docs/{key}.txt に置き、APIにURLリストを POST する
INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"


def _generate_indexnow_key() -> str:
    """初回のみ key を生成、以後は永続。"""
    import secrets
    return secrets.token_hex(32)  # 64桁hex


def write_verification_files(cfg: dict) -> None:
    """各種Webmaster Tools の owner verification ファイルを生成。

    config.json の verification セクションに以下を入れると自動で docs/ に書く:
      "verification": {
        "google_site_verification": "google0123...html の中身 or filename",
        "bing_msvalidate": "<BingsiteAuth>...</BingsiteAuth>",
        "yandex_verification": "yandex_xxx.html の中身"
      }
    本人がSearch Console等で発行したコードを config に貼るだけ。
    """
    v = cfg.get("verification") or {}
    PUBLIC.mkdir(parents=True, exist_ok=True)

    # Google: google{hex}.html という名前のファイルを置く
    g = v.get("google_site_verification") or ""
    if g:
        # filename自動推測 or 完全指定
        if g.endswith(".html"):
            fn = g
            body = f"google-site-verification: {g}"
        else:
            fn = f"google{g}.html"
            body = f"google-site-verification: {fn}"
        (PUBLIC / fn).write_text(body, encoding="utf-8")
        log.info(f"GSC verification file: {fn}")

    # Bing: BingSiteAuth.xml
    b = v.get("bing_msvalidate") or ""
    if b:
        xml = f'<?xml version="1.0"?>\n<users><user>{b}</user></users>'
        (PUBLIC / "BingSiteAuth.xml").write_text(xml, encoding="utf-8")
        log.info("Bing verification file: BingSiteAuth.xml")

    # Yandex: yandex_xxx.html
    y = v.get("yandex_verification") or ""
    if y:
        if y.endswith(".html"):
            fn = y
        else:
            fn = f"yandex_{y[:16]}.html"
        (PUBLIC / fn).write_text(
            f'<html><head><meta name="yandex-verification" content="{y}"/></head></html>',
            encoding="utf-8")
        log.info(f"Yandex verification file: {fn}")


def ensure_indexnow_key(cfg: dict) -> str | None:
    """IndexNow key を取得or生成し、PUBLIC/{key}.txt に書く。"""
    state_dir = DATA
    state_dir.mkdir(parents=True, exist_ok=True)
    key_file = state_dir / "indexnow_key.txt"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
    else:
        key = _generate_indexnow_key()
        key_file.write_text(key, encoding="utf-8")
        log.info(f"generated new IndexNow key: {key[:8]}...")
    # 公開側にも置く（owner検証用）
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / f"{key}.txt").write_text(key, encoding="utf-8")
    return key


def ping_search_engines(cfg: dict, genre_slugs: list[str]) -> None:
    """IndexNow API に新URL一覧を送信。Google sitemap ping もあわせて。"""
    base = cfg["site"].get("base_url", "").rstrip("/")
    host = base.replace("https://", "").replace("http://", "").split("/")[0]
    today = jst_today()

    # 送る URL リスト（メインページ + 今日の daily + 全 genre）
    urls = [f"{base}/", f"{base}/daily/{today}.html"]
    for slug in genre_slugs:
        urls.append(f"{base}/genre/{slug}.html")

    # 重複防止: 1日1回まで
    state_file = DATA / "indexnow_sent.json"
    sent: dict = {}
    if state_file.exists():
        try:
            sent = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            sent = {}
    if sent.get(today):
        log.info(f"indexnow already sent today ({today})")
        return

    key = ensure_indexnow_key(cfg)
    payload = {
        "host": host,
        "key": key,
        "keyLocation": f"{base}/{key}.txt",
        "urlList": urls,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        INDEXNOW_ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            log.info(f"indexnow rc={r.status}  urls={len(urls)}")
    except Exception as e:
        log.warning(f"indexnow ping failed: {e}")

    # Google sitemap ping (公式は2023年に廃止だが、Search Console webhookは別)
    # → Bing経由のIndexNowで十分なのでGoogle pingはskip
    sent[today] = True
    state_file.write_text(json.dumps(sent, ensure_ascii=False, indent=2),
                          encoding="utf-8")


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
    (PUBLIC / "genre").mkdir(parents=True, exist_ok=True)

    (PUBLIC / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    today = jst_today()
    (PUBLIC / "index.html").write_text(render_page(cfg, products), encoding="utf-8")
    (PUBLIC / "daily" / f"{today}.html").write_text(
        render_page(cfg, products, daily_date=today), encoding="utf-8")
    # ジャンル別ページ
    by_genre: dict[str, list[dict]] = {}
    genre_names: dict[str, str] = {}
    for p in products:
        slug = p.get("_genre", "misc")
        genre_names[slug] = p.get("_genre_name", slug)
        by_genre.setdefault(slug, []).append(p)
    for slug, items in by_genre.items():
        (PUBLIC / "genre" / f"{slug}.html").write_text(
            render_genre_page(cfg, slug, genre_names[slug], items),
            encoding="utf-8")
    (PUBLIC / "feed.json").write_text(render_feed(cfg, products), encoding="utf-8")
    (PUBLIC / "sitemap.xml").write_text(render_sitemap(cfg, list(by_genre.keys())), encoding="utf-8")
    (PUBLIC / "robots.txt").write_text(render_robots(cfg), encoding="utf-8")
    (PUBLIC / "rss.xml").write_text(render_rss(cfg, products, load_campaigns()), encoding="utf-8")
    # 404.html for GitHub Pages (redirect to index)
    (PUBLIC / "404.html").write_text(
        '<!DOCTYPE html><meta http-equiv="refresh" content="0;url=/aff-hub/">'
        '<title>Redirecting...</title><a href="/aff-hub/">Go home</a>',
        encoding="utf-8")
    write_verification_files(cfg)
    log.info(f"wrote public/ (today={today})")
    push_to_threads_queue(cfg, products)
    ping_search_engines(cfg, list(by_genre.keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
