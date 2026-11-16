# -*- coding: utf-8 -*-
"""处理层：模块路由 → 时间窗过滤 → 去重 → 关键词加权排序 → 摘要。"""
import difflib, json, re
from datetime import datetime, timedelta
from pathlib import Path

from . import fetchers

_CN_TZ = fetchers.CN_TZ


def _norm_title(t):
    t = re.sub(r"[\s　：:，,。.！!？?·—\-—_()（）\[\]【】\"'“”‘’|/\\]+", "", (t or "").lower())
    return t


def route_module(item, src, module_defs):
    """多模块信源按频道/URL提示路由，否则按模块关键词命中率路由；默认第一个模块。"""
    hint = item.get("_channel")
    if hint:
        if str(hint) in module_defs and str(hint) in src["modules"]:
            return str(hint)
        if any(k in str(hint) for k in ("国际", "外交")) and "m5" in src["modules"]:
            return "m5"
        if any(k in str(hint) for k in ("财经", "金融")) and "m7" in src["modules"]:
            return "m7"
    mods = src["modules"]
    if len(mods) > 1:
        title = item["title"] + " " + (item.get("lead") or "")
        best, best_score = mods[0], 0
        for m in mods:
            hits = sum(1 for kw in module_defs[m].get("keywords", [])
                       if kw.lower() in title.lower())
            if hits > best_score:
                best, best_score = m, hits
        return best
    return mods[0]


_KW_PATTERNS = {}


def _kw_hit(kw, text):
    """英文关键词按词边界匹配，中文仍按子串匹配。

    为什么：原来一律用子串匹配，'rate' 会命中 corporate / accurate，
    'her' 会命中英文代词 her，英文源的相关性分因此虚高。
    """
    kw = kw.strip().lower()
    if not kw:
        return False
    if kw.isascii():
        pat = _KW_PATTERNS.get(kw)
        if pat is None:
            pat = re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])")
            _KW_PATTERNS[kw] = pat
        return bool(pat.search(text))
    return kw in text


def keyword_score(title, lead, module_def):
    text = (title + " " + (lead or "")).lower()
    return sum(1 for kw in module_def.get("keywords", []) if _kw_hit(kw, text))


def process_items(raw_items, sources_by_id, module_defs, settings, state_dir):
    """raw_items: (src, items) 列表。返回按模块分组、排序、截断后的条目列表。"""
    now = datetime.now(_CN_TZ)
    window = timedelta(days=settings.get("window_days", 1))
    # 有些站点只给日期不给时分（抓到的都是 00:00），按 1 天窗口会在早上7点把它判成"31小时前"而漏掉，
    # 所以对这类条目单独放宽一个 grace 时段，保证前一天下午/晚上的稿子不漏。
    grace_date_only = timedelta(hours=settings.get("date_only_grace_hours", 20))
    grace_exact = timedelta(hours=2)  # 有时分的时间戳只做轻微容差（时区/校时抖动）
    cap_src = settings.get("per_source_daily_cap", 6)
    cap_mod = settings.get("items_per_module_cap", 40)
    thr = settings.get("dedupe_threshold", 0.72)

    seen_path = Path(state_dir) / "seen.json"
    seen = {}
    if seen_path.exists():
        try:
            seen = json.loads(seen_path.read_text(encoding="utf-8"))
        except Exception:
            seen = {}

    # 1) 模块路由 + 窗口过滤 + 关键词相关性过滤（自动通道需命中模块关键词）
    candidates = []
    for src, items in raw_items:
        count = 0
        strict = (src.get("channel", {}).get("type") == "auto"
                  and src.get("strict_keywords", True))
        for it in items:
            if count >= cap_src:
                break
            pub = it.get("published")
            if pub is not None:
                date_only = (pub.hour == 0 and pub.minute == 0)
                limit = window + (grace_date_only if date_only else grace_exact)
                if (now - pub) > limit:
                    continue  # 过旧直接丢
            elif it["url"] in seen:
                age_days = (now - datetime.fromisoformat(seen[it["url"]])).days
                if age_days >= window.days:
                    continue  # 无日期且首次见到已超过窗口：旧闻
            mod = route_module(it, src, module_defs)
            if strict and keyword_score(it["title"], it.get("lead", ""), module_defs[mod]) == 0:
                continue  # 首页噪声（导航/广告/无关内容）
            it = dict(it)
            it["module"] = mod
            it["published_str"] = pub.strftime("%m-%d %H:%M") if pub else ""
            candidates.append(it)
            count += 1

    # 2) 全局去重（标题相似度），优先保留权重高的信源
    deduped, kept_titles = [], []
    candidates.sort(key=lambda x: -(sources_by_id[x["source_id"]].get("weight", 1.0)))
    for it in candidates:
        nt = _norm_title(it["title"])
        if len(nt) < 4:
            continue
        dup = False
        for kt in kept_titles:
            if difflib.SequenceMatcher(None, nt, kt).ratio() >= thr:
                dup = True
                break
        if not dup:
            deduped.append(it)
            kept_titles.append(nt)

    # 3) 打分排序
    scored = []
    for it in deduped:
        src = sources_by_id[it["source_id"]]
        md = module_defs[it["module"]]
        w = src.get("weight", 1.0)
        kw = keyword_score(it["title"], it.get("lead", ""), md)
        pub = it.get("published")
        rec = 0.0
        if pub:
            hrs = (now - pub).total_seconds() / 3600
            rec = 2.0 if hrs < 24 else (1.0 if hrs < 48 else 0.2)
        elif it["url"] not in seen:
            rec = 1.0  # 无日期但首次见：当新条目
        score = w * 2 + kw * 1.5 + rec + (0.5 if it.get("lead") else 0)
        scored.append((score, it))
    scored.sort(key=lambda x: -x[0])

    # 4) 模块配额
    out, per_mod = [], {}
    for score, it in scored:
        m = it["module"]
        if per_mod.get(m, 0) >= cap_mod:
            continue
        per_mod[m] = per_mod.get(m, 0) + 1
        it["score"] = round(score, 2)
        out.append(it)

    # 5) 更新 seen
    for it in out:
        seen[it["url"]] = now.isoformat()
    # 只保留近14天
    seen = {u: d for u, d in seen.items()
            if (now - datetime.fromisoformat(d)).days <= 14}
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    return out


def rerank_by_llm(items, settings):
    """摘要完成后，用模型给的重要度分做最终排序。

    为什么分两段排序：关键词分只负责"谁值得花 token 进摘要队列"，
    模型看过正文后给的重要度才负责"谁该排在前面"。前者是粗筛，
    后者能区分"中央政策"和"一篇常规论文"——关键词分做不到这一点。

    模块配额在 process_items 里已切好，这里只重排、不增删条目。
    没有重要度分的条目（dry 运行 / 旧缓存 / 摘要降级）取默认 3 分，
    保证任何模式都不会因缺字段而崩。
    """
    kw_w = float(settings.get("rerank_keyword_weight", 0.3))
    imp_w = float(settings.get("rerank_importance_weight", 2.0))
    for it in items:
        imp = it.get("importance") or 3
        try:
            kw = float(it.get("score", 0))
        except (TypeError, ValueError):
            kw = 0.0
        it["final_score"] = round(kw * kw_w + float(imp) * imp_w, 2)
    items.sort(key=lambda x: -x.get("final_score", 0))
    return items
