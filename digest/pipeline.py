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


def keyword_score(title, lead, module_def):
    hits = 0
    for kw in module_def.get("keywords", []):
        if kw.lower() in (title + " " + (lead or "")).lower():
            hits += 1
    return hits


def process_items(raw_items, sources_by_id, module_defs, settings, state_dir):
    """raw_items: (src, items) 列表。返回按模块分组、排序、截断后的条目列表。"""
    now = datetime.now(_CN_TZ)
    window = timedelta(days=settings.get("window_days", 3))
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
                if (now - pub) > window + timedelta(days=2):
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
