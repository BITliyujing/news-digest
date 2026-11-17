# -*- coding: utf-8 -*-
"""主入口：抓取 → 处理 → 正文抓取 → 摘要 → 组装页面 → 日志/健康记录。

用法：
  python run_daily.py            # 完整运行（若已配置GLM Key则自动摘要）
  python run_daily.py --dry      # 干跑：不调GLM，用导语/占位摘要，验证链路
  python run_daily.py --only m1 m3   # 只跑指定模块
  python run_daily.py --max-items 60 # 控制摘要条数上限（试运行省事）
"""
import argparse, json, os, re, sys, traceback
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
if not (BASE / "digest" / "__init__.py").exists():
    (BASE / "digest" / "__init__.py").write_text("", encoding="utf-8")

from digest import fetchers, pipeline, summarize, build, http  # noqa: E402


def log(msg, logf=None):
    line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    if logf:
        logf.write(line + "\n")


# 已知 CMS 正文容器 id/class：命中后只在容器内取正文，避免误抓页脚/侧栏。
# 中财绿金院用 v_news_content；很多高校/机构站用 vsb_content / TRS_Editor。
_BODY_CONTAINER_RE = re.compile(
    r'<(?:div|article|section)\b[^>]*?(?:id|class)\s*=\s*["\'][^"\']*'
    r'(?:v_news_content|vsb_content|vsb_content_\d+|TRS_Editor|article[-_]?content|'
    r'entry[-_]?content|post[-_]?content|news[-_]?content|content[-_]?area|'
    r'text[-_]?area|detail[-_]?content|article)[^"\']*["\'][^>]*>(.*)',
    re.S | re.I)
# 段落级噪声：联系方式/版权行等（原先只在 nav_hits 里数，个别站点单条就够成噪声）
_LINE_NOISE_RE = re.compile(
    r"(关于我们|联系方式|通讯地址|友情链接|网站声明|版权声明|举报|广告服务|用户协议|"
    r"All Rights Reserved|责任编辑[：:]|编辑[：:]|来源[：:]|点击收起全文|返回顶部|"
    r"扫一扫|分享到微信|地址[：:].{0,40}(号|路|街)|电话[（(]?传真|邮箱[：:]|E-?mail)", re.I)
_NAV_WORDS = ("关于我们", "网站声明", "联系方式", "用户反馈", "网站地图", "举报",
              "版权声明", "广告服务", "返回央视网首页", "返回首页", "精彩图集",
              "最新推荐", "望海热线")


def _clean_paras(html_fragment):
    """从 HTML 片段里抽 <p> 段落文本，过滤导航/版权噪声。"""
    paras = re.findall(r"<p[^>]*>(.*?)</p>", html_fragment, re.S | re.I)
    out = []
    for p in paras:
        t = re.sub(r"<[^>]+>", " ", p)
        t = re.sub(r"&[a-z#0-9]{2,8};", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 12 or _LINE_NOISE_RE.search(t):
            continue
        out.append(t)
    return " ".join(out)


def _decode_cctv(contentdate):
    """央视正文藏在 <script> 的 var contentdate='...' 里（含 \\uXXXX 转义与视频占位标记）。"""
    txt = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), contentdate)
    txt = re.sub(r"\[!--.*?--\]", " ", txt)          # 去视频/广告占位
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"&[a-z#0-9]{2,8};", " ", txt)
    txt = re.sub(r"\b[0-9a-f]{32},\d+,\d+,[\d:]+,\w+\b", " ", txt)  # 残留的视频ID串
    return re.sub(r"\s+", " ", txt).strip()


def fetch_article_text(it, settings):
    """抓原文正文前N字。优先已知正文容器 > <p> 段落 > <article> 兜底；反爬/纯导航返回空串。"""
    import re
    try:
        status, raw = http.fetch(it["url"], settings, referer=it["url"],
                                 read_bytes=300000, sleep=0.3)
        html = http.decode_html(raw)
        head = html[:6000]
        if re.search(r"(var arg1\s*=|__jsl_clearance|renderData|请开启JavaScript|"
                     r"Access Denied|captcha|cf-browser-verification|"
                     r"<title>\s*(403|404|Just a moment|安全验证)\s*</title>)", head, re.I):
            return ""
        cap = settings.get("article_text_chars", 1200)
        # 0) 央视：正文是 JS 渲染，但原始 HTML 里内嵌 var contentdate，直接解码最干净
        mc = re.search(r"var\s+contentdate\s*=\s*['\"](.*?)['\"]\s*;", html, re.S)
        if mc:
            t = _decode_cctv(mc.group(1))
            if len(t) >= 60:
                return t[:cap]
        # 注意：不能剥 <form>——中财等高校 CMS 用 <form> 包裹整篇正文，剥了会把正文一起删掉。
        # 只剥确定的非正文标签；<p> 抽取天然避开导航，容器匹配进一步收窄范围。
        html = re.sub(r"<(script|style|noscript|nav|footer|header|aside)[^>]*>.*?</\1>", " ",
                      html, flags=re.S | re.I)
        # 1) 已知正文容器：容器内取 <p>，取不到再去标签取整段
        text = ""
        m = _BODY_CONTAINER_RE.search(html)
        if m:
            text = _clean_paras(m.group(1))
            if len(text) < 200:
                body = re.sub(r"<[^>]+>", " ", m.group(1))
                body = re.sub(r"&[a-z#0-9]{2,8};", " ", body)
                fallback = re.sub(r"\s+", " ", body).strip()
                if len(fallback) > len(text):
                    text = fallback
        # 2) 容器没拿到/太短：全页 <p> 段落拼接
        if len(text) < 200:
            more = _clean_paras(html)
            if len(more) > len(text):
                text = more
        # 3) 仍不足：<article> 兜底
        if len(text) < 200:
            ma = re.search(r"<article[^>]*>(.*?)</article>", html, re.S | re.I)
            if ma:
                body = re.sub(r"<[^>]+>", " ", ma.group(1))
                fallback = re.sub(r"\s+", " ", body).strip()
                if len(fallback) > len(text):
                    text = fallback
        # 导航残留识别：出现多个站点导航词 → 判为抽错，弃用
        nav_hits = sum(1 for w in _NAV_WORDS if w in text)
        if nav_hits >= 2:
            return ""
        if re.search(r'(var |function\s*\(|\{"|\\u[0-9a-f]{4})', text[:300]):
            return ""
        return text[:cap]
    except Exception:
        return ""


def load_discovered(base):
    p = base / "data" / "discovered.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_discovered(base, disc):
    p = base / "data" / "discovered.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(disc, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--max-items", type=int, default=None)
    ap.add_argument("--no-fetch-article", action="store_true")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))
    sources_cfg = json.loads((BASE / "sources.json").read_text(encoding="utf-8"))
    module_defs = sources_cfg["modules"]
    all_sources = sources_cfg["sources"]

    today = datetime.now().strftime("%Y-%m-%d")
    log_dir = BASE / settings["log_dir"]
    log_dir.mkdir(exist_ok=True)
    logf = open(log_dir / f"run_{today}.log", "a", encoding="utf-8")
    log(f"=== 行业资讯简报运行开始 {'(dry)' if args.dry else ''} ===", logf)

    active = [s for s in all_sources if s.get("active")]
    # 云端运行时（GitHub Actions 等），出口在境外，需代理的英文源可直接抓
    if os.environ.get("CLOUD_RUN") == "1":
        active += [s for s in all_sources if s.get("requires_proxy") and s not in active]
    if args.only:
        active = [s for s in active if any(m in args.only for m in s["modules"])]

    # 注入上次自动发现到的 feed，省去每天重复探测
    discovered = load_discovered(BASE)
    for s in active:
        if s.get("channel", {}).get("type") == "auto" and s["id"] in discovered:
            s["channel"]["_feed"] = discovered[s["id"]]

    log(f"启用信源 {len(active)} 个（未启用/待代理 {len(all_sources)-len([s for s in all_sources if s.get('active')])} 个）", logf)

    # 1) 抓取（并发）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    raw_items = []
    health = {}
    hp = BASE / "logs" / "health.json"
    if hp.exists():
        try:
            health = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            health = {}
    workers = int(settings.get("source_concurrency", 6))
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetchers.fetch_source, s, settings): s for s in active}
        for f in as_completed(futs):
            s = futs[f]
            try:
                results[s["id"]] = f.result()
            except Exception as e:
                results[s["id"]] = ([], f"{type(e).__name__}: {e}")
    for s in active:
        items, err = results.get(s["id"], ([], "no result"))
        err_str = str(err) if err else ""
        rec = health.get(s["id"], {})
        if err:
            rec.update({"last_ok": rec.get("last_ok", ""),
                        "fail_streak": rec.get("fail_streak", 0) + 1,
                        "last_count": len(items), "last_error": err_str[:150],
                        "checked": today})
            log(f"  [失败] {s['name']}: {err_str[:90]}", logf)
        else:
            rec.update({"last_ok": today, "fail_streak": 0,
                        "last_count": len(items), "last_error": "",
                        "checked": today})
            log(f"  [抓取] {s['name']}: {len(items)}条", logf)
        health[s["id"]] = rec
        if items:
            raw_items.append((s, items))
        # 记录自动发现到的 feed，明天直接用
        fd = s.get("channel", {}).get("_feed")
        if fd and discovered.get(s["id"]) != fd:
            discovered[s["id"]] = fd
    save_discovered(BASE, discovered)
    hp.write_text(json.dumps(health, ensure_ascii=False, indent=1), encoding="utf-8")

    # 2) 处理（路由/窗口/去重/排序/配额）
    sources_by_id = {s["id"]: s for s in all_sources}
    items = pipeline.process_items(raw_items, sources_by_id, module_defs, settings,
                                   str(BASE / settings["data_dir"]))
    log(f"处理后候选条目 {len(items)} 条", logf)
    if args.max_items:
        items = items[:args.max_items]

    # 3) 抓原文正文（并发；接口已给出足够导语的跳过，省时间也省噪声）
    if not args.no_fetch_article:
        from concurrent.futures import ThreadPoolExecutor
        ok = {"n": 0, "skip": 0}
        def _work(it):
            lead = (it.get("lead") or "").strip()
            src = sources_by_id.get(it["source_id"], {})
            # 官方接口已给出规范导语的（财联社/华尔街见闻/澎湃/Crossref），直接用，不再抓页面
            api_src = src.get("channel", {}).get("type") == "api"
            if api_src and len(lead) >= 60:
                it["summary_text"] = lead
                ok["skip"] += 1
                return
            if len(lead) >= settings.get("lead_enough_chars", 180):
                it["summary_text"] = lead
                ok["skip"] += 1
                return
            it["summary_text"] = fetch_article_text(it, settings) or lead
            ok["n"] += bool(it["summary_text"])
        with ThreadPoolExecutor(max_workers=int(settings.get("article_concurrency", 6))) as ex:
            list(ex.map(_work, items))
        log(f"  正文抓取完成：{ok['n']} 条抓取成功，{ok['skip']} 条直接用接口导语，"
            f"共 {len(items)} 条", logf)
    else:
        for it in items:
            it["summary_text"] = it.get("lead", "")

    # 3.5) 只有标题、正文一个字都没取到的条目（反爬/付费墙/纯导航页）不进简报：
    #      没有正文就写不出靠谱摘要，留着只会占版面。
    keep, dropped = [], 0
    for it in items:
        txt = (it.get("summary_text") or it.get("lead") or "").strip()
        if len(txt) >= 15:
            keep.append(it)
        else:
            dropped += 1
    if dropped:
        kept_ids = {id(x) for x in keep}
        drop_names = "、".join(sorted({it["source_name"] for it in items if id(it) not in kept_ids}))[:120]
        log(f"  剔除 {dropped} 条仅有标题无正文的条目（{drop_names}）", logf)
    items = keep

    # 4) 摘要
    summarize.summarize_items(items, settings, str(BASE), log=log, dry=args.dry)

    # 4.5) 模型看过正文后给的重要度决定谁排前面；关键词分只负责谁进摘要队列。
    #      只重排、不增删，所以模块的配额不受影响。
    items = pipeline.rerank_by_llm(items, settings)
    hi = sum(1 for it in items if it.get("importance", 3) >= 4)
    log(f"  重要度重排完成：{hi}/{len(items)} 条评为高重要度（≥4）")

    # 5) 组装页面 + 数据落盘
    out_dir = BASE / settings["out_dir"]
    page = build.build_page(items, module_defs, settings, str(out_dir), log=log, sources=all_sources)
    data_dir = BASE / settings["data_dir"]
    data_dir.mkdir(exist_ok=True)
    (data_dir / f"processed_{today}.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # 健康摘要
    bad = [f"{sid}({rec.get('fail_streak',0)}连败)" for sid, rec in health.items()
           if rec.get("fail_streak", 0) >= 2]
    log(f"疑似不健康信源: {', '.join(bad) if bad else '无'}", logf)
    log("=== 运行结束 ===", logf)
    logf.close()
    print(f"\nDONE. 页面: {page}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
