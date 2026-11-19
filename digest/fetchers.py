# -*- coding: utf-8 -*-
"""信源抓取层：rss / atom / sitemap(news) / scrape(锚点) / api / rsshub 六种通道适配。
统一产出 item：{title, url, published(datetime|None), lead, source_id, source_name, module}
"""
import json, re, time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape as _unescape
from urllib.parse import quote, urlparse

from . import http

CN_TZ = timezone(timedelta(hours=8))


# ---------- 通用 ----------

def _strip_tags(s):
    if not s:
        return ""
    # 先整段删掉 <style>/<script> 的内容再剥标签。
    # 有些站点（BNEF 的 bbg-cta 组件）把 <style> 嵌在 <a> 内部，只剥标签会把
    # CSS 文本留在标题里，表现为标题尾部挂一串 "#cta_1234.bbg-cta .bbg-cta-link"。
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    # HTML 实体要还原成字符（&#039; → '），直接删会留下 "don t" 这种断词
    s = _unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# 标题里的 CSS 选择器/规则残留：#cta_1234、.bbg-cta-link.link-holder、{...}、!important
_CSS_RESIDUE_RE = re.compile(r"(?:\s#[A-Za-z][\w-]*_\d+|\s\.[a-z][\w-]*(?:\.[\w-]+)+|\s*\{[^{}]{0,200}\}\s*|!important)")
_TITLE_TAIL_JUNK_RE = re.compile(r"\s*(?:#[\w-]+|[.#][\w-]+\s*[.#][\w-]+).*$")


def _clean_title(t):
    """清洗标题：去 CSS 残留、去尾部选择器串、压缩空白。

    BNEF 这类站点的锚点内文会夹带 <style>，清洗后只剩正题；
    对正常标题是无害的（不含上述特征时原样返回）。
    """
    t = _strip_tags(t)
    if not t:
        return ""
    if _CSS_RESIDUE_RE.search(t):
        t = _TITLE_TAIL_JUNK_RE.sub("", t)
        t = _CSS_RESIDUE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—|·>»«\"'")
    return t


def _parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(CN_TZ)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(CN_TZ)
    except Exception:
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=CN_TZ)
        except ValueError:
            return None
    return None


def _mk_item(title, url, published, lead, src, date_from_title=False):
    """构造统一 item。date_from_title=True 时，若 published 为空则尝试从标题末尾解析
    YYYY-MM-DD 并剥离（某些高校/机构列表页只在标题尾部带日期，URL 里没有日期，
    不解析会导致时间窗过滤失效、旧文混入）。"""
    title = _clean_title(title)
    if published is None and date_from_title:
        m = re.search(r"\s*(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})\s*日?\s*$", title)
        if m:
            try:
                published = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=CN_TZ)
                title = title[:m.start()].strip()
            except ValueError:
                pass
    return {"title": title[:180], "url": url, "published": published,
            "lead": _strip_tags(lead or "")[:400], "source_id": src["id"],
            "source_name": src["name"], "lang": src.get("lang", "zh")}


# ---------- RSS / Atom ----------

# 这些命名空间里也常有 <title>/<description>，但装的是“图片说明/版权”，
# 不是文章标题。遍历时必须跳过，否则图片 caption 会把真标题覆盖掉。
_NOISE_NS = ("media", "image", "thumbnail", "itunes", "georss", "wfw", "slash")


def _ns_of(tag):
    return tag.split("}")[0].lstrip("{").lower() if tag.startswith("{") else ""


def _parse_rss_or_atom(raw, src):
    """解析 RSS/Atom。

    取字段只认 item/entry 的**直接子元素**，并且跳过 media:/image: 等命名空间。
    原来的写法用 el.iter() + 按 local name 匹配，导致 <media:title>（图片说明）
    在文档顺序后面把真正的 <title> 覆盖掉——Fortune 的标题因此变成
    "Photo: Jensen Huang" / "Many hundred dollar bills are seen in this photo."
    这类图注。description 同理会被 <media:description> 顶替。
    """
    text = raw.decode("utf-8", "ignore")
    root = ET.fromstring(re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", text))
    items = []

    def txt(node):
        return (node.text or "").strip()

    def noisy(node):
        return any(n in _ns_of(node.tag) for n in _NOISE_NS)

    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = link = date = lead = None
        # 1) 严格模式：只看直接子元素
        for ch in list(el):
            if not isinstance(ch.tag, str) or noisy(ch):
                continue
            name = ch.tag.split("}")[-1]
            if name == "title" and title is None:
                title = txt(ch)
            elif name == "link":
                if ch.get("href"):
                    link = link or ch.get("href")
                elif txt(ch).startswith("http"):
                    link = link or txt(ch)
            elif name in ("pubDate", "published", "updated", "date") and date is None:
                date = _parse_date(txt(ch))
            elif name in ("description", "summary", "content", "encoded") and not lead:
                lead = txt(ch)
        # 2) 兜底：个别 feed 把标题/链接套了一层容器，再深遍历一次（仍跳过噪声命名空间）
        if not title or not link:
            for ch in el.iter():
                if not isinstance(ch.tag, str) or noisy(ch):
                    continue
                name = ch.tag.split("}")[-1]
                if name == "title" and not title:
                    title = txt(ch)
                elif name == "link" and not link:
                    if ch.get("href"):
                        link = ch.get("href")
                    elif txt(ch).startswith("http"):
                        link = txt(ch)
        if title and link:
            items.append(_mk_item(title, link, date, lead, src))
    return items


def fetch_rss(src, ch, settings):
    status, raw = http.fetch(ch["url"], settings)
    return _parse_rss_or_atom(raw, src)


# ---------- Sitemap（news sitemap，如 Hydrogen Insight / IEA）----------

def _sitemap_news_urls(url, settings):
    """返回 [(loc, lastmod, news_title|None), ...]，支持 index -> 子 sitemap。"""
    status, raw = http.fetch(url, settings)
    text = raw.decode("utf-8", "ignore")
    root = ET.fromstring(re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", text))
    NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    NNS = "{http://www.google.com/schemas/sitemap-news/0.9}"
    locs = [(el.text.strip(), None) for el in root.iter(NS + "loc")]
    if not locs:
        return []
    subs = [l for l, _ in locs if l.lower().endswith(".xml")]
    if subs:
        picked = [l for l in subs if "news" in l.lower()][:3] or subs[:2]
        out = []
        for u in picked:
            try:
                out.extend(_sitemap_news_urls(u, settings))
            except Exception:
                continue
        return out
    entries = []
    for url_el in root.iter(NS + "url"):
        # 只取 <url> 的直接子节点，避免把 <image:loc>（图片地址）当成文章链接
        loc_el = url_el.find(NS + "loc")
        if loc_el is None or not (loc_el.text or "").strip():
            continue
        loc = loc_el.text.strip()
        if re.search(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|mp4)(\?|$)", loc, re.I):
            continue
        lm_el = url_el.find(NS + "lastmod")
        lastmod = _parse_date(lm_el.text or "") if lm_el is not None else None
        title_el = url_el.find(".//" + NNS + "title")
        if title_el is None:
            title_el = url_el.find(".//" + NNS + "news/" + NNS + "title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        entries.append((loc, lastmod, title or None))
    return entries


def fetch_sitemap(src, ch, settings):
    entries = _sitemap_news_urls(ch["url"], settings)
    items = []
    now = datetime.now(CN_TZ)
    for loc, lastmod, title in entries:
        if not title:
            slug = loc.rstrip("/").split("/")[-1].replace("-", " ").strip()
            if 12 <= len(slug) <= 120:
                title = slug[:110]
        if not title:
            continue
        if lastmod and (now - lastmod).days > 10:
            continue
        items.append(_mk_item(title, loc, lastmod, "", src))
    return items[:40]


# ---------- Scrape（锚点提取）----------

_ANCHOR_RE = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def _date_from_url(url, base_hint=""):
    m = re.search(r"/(\d{4})[-/]?(\d{2})[-/]?(\d{2})/", url)
    if not m:
        m = re.search(r"/(\d{6})/", url)
        if m:
            y, mo = m.group(1)[:4], m.group(1)[4:]
            d = None
            m2 = re.search(r"(\d{8})", url)
            if m2:
                y, mo, d = m2.group(1)[:4], m2.group(1)[4:6], m2.group(1)[6:8]
            try:
                return datetime(int(y), int(mo), int(d or 15), tzinfo=CN_TZ)
            except Exception:
                return None
        return None
    y, mo, d = m.group(1), m.group(2), m.group(3)
    try:
        return datetime(int(y), int(mo), int(d), tzinfo=CN_TZ)
    except Exception:
        return None


def fetch_scrape(src, ch, settings):
    urls = [ch.get("list_url")]
    if ch.get("fallback_list_url"):
        urls.append(ch["fallback_list_url"])
    pat = re.compile(ch["url_regex"])
    min_len = ch.get("title_min", 10)
    read_bytes = ch.get("read_bytes", 300000)
    cmap = ch.get("url_channel_map") or {}
    items, seen = [], set()
    last_err = None
    for list_url in urls:
        try:
            status, raw = http.fetch(list_url, settings, referer=list_url,
                                      read_bytes=read_bytes)
        except Exception as e:
            last_err = e
            continue
        html = http.decode_html(raw)
        for href, inner in _ANCHOR_RE.findall(html):
            u = http.absolutize(href, ch.get("base") or list_url)
            if not pat.search(u):
                continue
            if u in seen:
                continue
            title = _strip_tags(inner)
            if len(title) < min_len or title.startswith("http"):
                continue
            seen.add(u)
            hint = next((m for pat2, m in cmap.items() if pat2 in u), None)
            items.append(_mk_item(title, u, _date_from_url(u), "", src))
            if hint:
                items[-1]["_channel"] = hint
        if items:
            break
    if not items and last_err:
        raise last_err
    return items[:40]


# ---------- RSSHub ----------

def fetch_rsshub(src, ch, settings):
    route = ch.get("route", "")
    if "{wechat_id}" in route:
        wid = src.get("wechat_id")
        if not wid:
            return []  # 公众号尚未配置微信号：静默跳过（健康日志记 inactive）
        route = route.replace("{wechat_id}", wid)
    # 公众号等专用源可用 channel.base 覆盖默认 RSSHub 实例；
    # 也可在 settings.wechat_mirror 统一指定公众号转 RSS 服务地址。
    base = (ch.get("base") or
            (settings.get("wechat_mirror") if "{wechat_id}" in ch.get("route", "") else None) or
            settings.get("mirror", "")).rstrip("/")
    url = base + quote(route, safe="/@:.")
    status, raw = http.fetch(url, settings, timeout=settings.get("rsshub_timeout", 45))
    return _parse_rss_or_atom(raw, src)


# ---------- API 适配 ----------

def fetch_api(src, ch, settings):
    adapter = ch.get("adapter")
    url = ch.get("url") or ""
    if adapter == "cls_roll":
        import hashlib, time as _t
        params = {"app": "CailianpressWeb", "os": "web", "sv": "8.4.6",
                  "rn": str(ch.get("rows", 30)), "last_time": str(int(_t.time()))}
        qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sign = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
        url = f"https://www.cls.cn/v1/roll/get_roll_list?{qs}&sign={sign}"
    elif adapter == "crossref":
        rows = ch.get("rows", 20)
        base = "https://api.crossref.org/"
        if ch.get("issn"):
            url = (base + f"journals/{ch['issn']}/works?rows={rows}&sort=created&order=desc"
                   "&select=title,DOI,created,URL,abstract,container-title")
        else:
            url = (base + f"prefixes/{ch.get('prefix','10.26434')}/works?rows={rows}"
                   "&sort=created&order=desc&select=title,DOI,created,URL,abstract,container-title")
    status, raw = http.fetch(url, settings, accept="application/json",
                             referer="https://www.cls.cn/" if adapter == "cls_roll" else None)
    data = json.loads(raw.decode("utf-8", "ignore"))
    if adapter == "wallstcn_articles":
        out = []
        for it in (data.get("data") or {}).get("items") or []:
            url = it.get("uri") or ""
            rid = it.get("id")
            if not url and rid:
                url = f"https://wallstcn.com/articles/{rid}"
            if not url or not it.get("title"):
                continue
            ts = it.get("display_time")
            dt = None
            if isinstance(ts, (int, float)) and ts > 0:
                dt = datetime.fromtimestamp(ts, tz=CN_TZ)
            out.append(_mk_item(it["title"], url, dt,
                               it.get("content_short") or "", src))
        return out
    if adapter == "wallstcn_lives":
        out = []
        for it in (data.get("data") or {}).get("items") or []:
            content = _strip_tags(it.get("content") or it.get("title") or "")
            if len(content) < 20:
                continue
            rid = it.get("id")
            out.append(_mk_item(content[:80], f"https://wallstcn.com/lives/{rid}",
                               _parse_date(str(it.get("display_time") or "")), content, src))
        return out[:60]
    if adapter == "thepaper_sidebar":
        return _thepaper(src, data)
    if adapter == "cls_roll":
        out = []
        for it in (data.get("data") or {}).get("roll_data") or []:
            title = _strip_tags(it.get("title") or "") or _strip_tags(it.get("brief") or "")
            if not title:
                continue
            rid = it.get("id")
            t = it.get("ctime")
            dt = datetime.fromtimestamp(t, tz=CN_TZ) if isinstance(t, (int, float)) and t else None
            lead = _strip_tags(it.get("brief") or "")
            out.append(_mk_item(title, f"https://www.cls.cn/detail/{rid}" if rid else
                               "https://www.cls.cn/telegraph", dt, lead, src))
        return out
    if adapter == "crossref":
        out = []
        for it in (data.get("message") or {}).get("items") or []:
            title = (it.get("title") or [""])[0]
            if not title:
                continue
            doi = it.get("DOI") or ""
            link = f"https://doi.org/{doi}" if doi else (it.get("URL") or "")
            dt = None
            for k in ("published", "created", "issued"):
                parts = ((it.get(k) or {}).get("date-parts") or [[None]])[0]
                if parts and parts[0]:
                    try:
                        y = parts[0]
                        mo = parts[1] if len(parts) > 1 else 1
                        d = parts[2] if len(parts) > 2 else 1
                        dt = datetime(int(y), int(mo), int(d), tzinfo=CN_TZ)
                        break
                    except Exception:
                        continue
            abstract = _strip_tags(re.sub(r"<[^>]+>", " ", it.get("abstract") or ""))
            journal = (it.get("container-title") or [""])[0]
            lead = (f"{journal}. " if journal else "") + abstract
            out.append(_mk_item(title, link, dt, lead[:400], src))
        return out
    raise ValueError(f"未知api适配器: {adapter}")


def _thepaper(src, data):
    from urllib.parse import urljoin
    out = []
    def walk(o, path="r"):
        if isinstance(o, dict):
            name = o.get("name") or o.get("contentTitle") or o.get("title")
            url = o.get("link") or o.get("contentUrl") or o.get("url")
            if not url and o.get("contId"):
                url = f"https://www.thepaper.cn/newsDetail_forward_{o['contId']}"
            if isinstance(url, str) and url and name and len(str(name)) > 8:
                if url.startswith("/"):
                    url = urljoin("https://www.thepaper.cn/", url)
                if url.startswith("http"):
                    ch = "财经" if "financial" in path.lower() else ""
                    out.append((str(name), url, ch))
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list) and o:
            for v in o[:20]:
                walk(v, f"{path}[]")
    walk(data)
    items = []
    for name, url, channel in out[:50]:
        it = _mk_item(name, url, None, "", src)
        it["_channel"] = channel
        items.append(it)
    return items


# ---------- 自动发现（给批量信源用：找 RSS → 退回通用列表解析）----------

_FEED_HINTS = ("/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml",
               "/index.xml", "/rss/index.xml", "/feeds/all.atom.xml", "/feed/rss",
               "/?feed=rss2", "/rssfeed.xml")

_BAD_URL_RE = re.compile(
    r"(/tag/|/tags?/|/category/|/categories/|/author/|/search|/login|/register|"
    r"/about|/contact|/privacy|/terms|/subscribe|/newsletter|/advertis|/cookie|"
    r"/javascript:|mailto:|#|\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|css|js)$)", re.I)
_BAD_TITLE = set("""首页 登录 注册 关于我们 联系我们 广告服务 版权声明 隐私政策 用户协议 更多 查看更多
下一页 上一页 返回 网站地图 招聘 订阅 搜索 全部 热点 推荐 English 中文""".split())
_JUNK_TITLE_RE = re.compile(
    r"(下载|客户端|APP|app下载|学社|登录|注册|忘记密码|微博|微信公号|公众号|视频|直播|图集|"
    r"专题|广告|合作|投稿|招聘|商城|课程|培训|会议报名|付费|会员|订阅|RSS|网站声明|举报)", re.I)


def discover_feed(home, settings):
    """从首页 HTML 里找 RSS/Atom 声明，找不到再试常见路径。返回可用 feed URL 或 None。"""
    candidates = []
    try:
        st, raw = http.fetch(home, settings, referer=home, read_bytes=300000)
        html = http.decode_html(raw)
        for tag in re.findall(r"<link[^>]*>", html, re.I):
            if re.search(r"application/(rss|atom)\+xml", tag, re.I):
                m = re.search(r"href=[\"']([^\"']+)[\"']", tag)
                if m:
                    candidates.append(http.absolutize(m.group(1), home))
        m = re.search(r"href=[\"']([^\"']*(?:rss|feed)[^\"']*)[\"'][^>]*>[^<]*(?:RSS|订阅|Feed)", html, re.I)
        if m:
            candidates.append(http.absolutize(m.group(1), home))
    except Exception:
        pass

    base = home.rstrip("/")
    for h in _FEED_HINTS[:5]:
        candidates.append(base + h)

    seen = set()
    for u in candidates:
        if u in seen or not u.startswith("http"):
            continue
        seen.add(u)
        try:
            st, raw = http.fetch(u, settings, timeout=8, read_bytes=60000, sleep=0.2)
        except Exception:
            continue
        head = raw[:400].decode("utf-8", "ignore").lstrip()
        if not (head.startswith("<?xml") or "<rss" in head[:200] or "<feed" in head[:200]):
            continue
        try:
            probe = _parse_rss_or_atom(raw, {"id": "_probe", "name": "_probe"})
        except Exception:
            continue
        if probe:
            return u
    return None


def fetch_generic_list(src, ch, settings):
    """通用列表页解析：不依赖站点专属正则，靠链接特征+打分猜文章。"""
    list_url = ch.get("list_url") or ch.get("home")
    st, raw = http.fetch(list_url, settings, referer=list_url,
                         read_bytes=ch.get("read_bytes", 400000))
    html = http.decode_html(raw)
    html = re.sub(r"<(nav|footer|header)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    goods, seen = [], set()
    for href, inner in _ANCHOR_RE.findall(html):
        u = http.absolutize(href, list_url)
        if not u.startswith("http") or u in seen:
            continue
        if _BAD_URL_RE.search(u) or _BAD_URL_RE.search(href):
            continue
        if len(u.rstrip("/").split("/")) <= 3 and not re.search(r"\d{4}", u):
            continue  # 太浅的路径（栏目首页）跳过
        title = _strip_tags(inner)
        if not title or title in _BAD_TITLE or _JUNK_TITLE_RE.search(title):
            continue
        cjk = sum(1 for c in title if "\u4e00" <= c <= "\u9fff")
        min_len = 10 if cjk >= 4 else 28
        if len(title) < min_len or len(title) > 110:
            continue
        seen.add(u)
        # 打分：URL 带日期 > 路径较深 > 标题长度合理 > 有中文标点
        score = 0
        if re.search(r"(19|20)\d{2}[-/]?\d{1,2}[-/]?\d{1,2}", u):
            score += 3
        depth = len(u.rstrip("/").split("/"))
        score += min(depth - 3, 3)
        if 14 <= len(title) <= 70:
            score += 1
        if re.search(r"[，。：、？！]", title):
            score += 1
        goods.append((score, len(goods), title, u))
    if not goods:
        raise RuntimeError("通用解析到0条")
    goods.sort(key=lambda x: (-x[0], x[1]))
    items = []
    for score, pos, title, u in goods[:35]:
        # 通用列表页的日期常在标题尾（而非 URL），如高校/机构站；开启 date_from_title 兜底
        items.append(_mk_item(title, u, _date_from_url(u), "", src, date_from_title=True))
    return items


def fetch_auto(src, ch, settings):
    """自动通道：优先已发现/缓存的 feed，其次现场发现，最后通用列表解析。"""
    cached = ch.get("_feed")
    if cached:
        try:
            st, raw = http.fetch(cached, settings, read_bytes=300000)
            got = _parse_rss_or_atom(raw, src)
            if got:
                return got
        except Exception:
            pass
    if ch.get("try_feed", True):
        feed = discover_feed(ch.get("home") or ch.get("list_url"), settings)
        if feed:
            st, raw = http.fetch(feed, settings, read_bytes=300000)
            got = _parse_rss_or_atom(raw, src)
            if got:
                ch["_feed"] = feed
                return got
    return fetch_generic_list(src, ch, settings)


# ---------- 总入口 ----------

def fetch_source(src, settings):
    """返回 (items, error_or_None)。items 可能为空列表。"""
    ch = src["channel"]
    t = ch["type"]
    try:
        if t == "rss":
            return fetch_rss(src, ch, settings), None
        if t == "sitemap":
            return fetch_sitemap(src, ch, settings), None
        if t == "scrape":
            items = fetch_scrape(src, ch, settings)
            if not items:
                return [], RuntimeError("页面解析到0条")
            return items, None
        if t == "rsshub":
            return fetch_rsshub(src, ch, settings), None
        if t == "api":
            return fetch_api(src, ch, settings), None
        if t == "auto":
            return fetch_auto(src, ch, settings), None
        if t == "manual":
            return [], None
        return [], RuntimeError(f"未知通道类型 {t}")
    except Exception as e:
        return [], f"{type(e).__name__}: {str(e)[:120]}"
