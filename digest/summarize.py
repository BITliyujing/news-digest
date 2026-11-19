# -*- coding: utf-8 -*-
"""摘要层：多供应商自动切换（智谱GLM免费 / 魔搭ModelScope免费 / DeepSeek付费 / 硅基流动）。

摘要之外还让模型顺手给每条打「重要度 1-5 + 类别」，写回 item 供 pipeline 重排使用；
元数据在解析时剥离，不会出现在页面摘要和缓存正文里。

两种调用方式：
  1) 批量（默认）：把 llm.batch_size 条资讯合并成一次请求，按 <<<序号>>> 分节输出，再拆回各条。
     好处是请求数降到 1/N，能绕开免费档"每分钟约5次"的硬限流——这是之前失败率高的根因。
  2) 单条（兜底）：批量结果里缺哪几条，再用单条模式补；依旧缺就退回导语截取。

全部走 OpenAI 兼容的 /chat/completions 协议，配置在 settings.json 的 llm.providers。
"""
import json, os, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import http

_CTX = http._CTX
_SYS_PROMPT = (
    "你是一名资深行业资讯编辑，为中文读者（科研人员与投资人）撰写每日简报。"
    "只依据给定材料归纳，不编造、不添加材料外的事实；英文术语、机构名、人名保留英文原文。"
    "无论材料是中文还是英文，摘要正文一律用简体中文书写——英文材料要翻译归纳，"
    "严禁整段照抄英文原句（实测中英文源会被原样抄成英文，中文读者读不了）。"
    "你还负责为每条资讯评估重要度并归类，判断要有区分度，不要一律打高分。"
)

# 模型附在摘要末尾的元数据，例如：重要度:4|类别:政策
_META_LINE = re.compile(
    r"(?:重要度|重要性|importance)\s*[:：为]?\s*([1-5])(?:分|/5)?"
    r"(?:(?:\s+|\s*[,，;；|｜、]\s*)(?:类别|分类|category)\s*[:：为]?\s*([^\s|｜,，;；、/]+))?",
    re.I,
)
_META_CAT = re.compile(
    r"(?:类别|分类|category)\s*[:：为]?\s*([^\s|｜,，;；、/]+)", re.I
)


def _extract_meta(body):
    """从摘要尾部剥离模型附带的元数据，返回 (纯摘要, 重要度 or None, 类别 or None)。

    模型偶尔不换行、把元数据和正文写在同一行，所以匹配到以后只切掉尾部片段：
    若这一行前面还有超过 30 字的正文就保留，避免把摘要正文误删。
    """
    lines = (body or "").rstrip().split("\n")
    imp = cat = None
    for idx in range(len(lines) - 1, max(-1, len(lines) - 4), -1):
        m = _META_LINE.search(lines[idx])
        if not m:
            continue
        imp = int(m.group(1))
        cat = m.group(2) or None
        prefix = lines[idx][:m.start()].strip()
        if len(prefix) > 30:
            lines[idx] = prefix
        else:
            lines = lines[:idx]
        break
    if imp is not None and not cat and lines:
        m2 = _META_CAT.search(lines[-1])
        if m2:
            cat = m2.group(1)
            if len(lines[-1][:m2.start()].strip()) <= 30:
                lines = lines[:-1]
    return "\n".join(lines).strip(), imp, cat

# 分节标记：优先只认"行首"的 <<<1>>>、【1】、[1]、#1，避免正文里的引用数字被误判
_SEC_LINE = re.compile(r"^[ \t]*(?:<<<\s*(\d{1,3})\s*>>>|【\s*(\d{1,3})\s*】|\[\s*(\d{1,3})\s*\]|#\s*(\d{1,3})(?![0-9]))",
                       re.M)
# 退一步：允许和正文同一行
_SEC_ANY = re.compile(r"(?:<<<\s*(\d{1,3})\s*>>>|【\s*(\d{1,3})\s*】)")
# 模型把"序号"当字面量抄下来的情况（<<<序号>>> / 【序号】），无法得知原编号，
# 只能按出现顺序依次映射回 1..n；否则整批会因为找不到分节标记而作废。
_SEC_LITERAL = re.compile(r"<<<\s*序\s*号\s*>>>|【\s*序\s*号\s*】")


def _load_key(path):
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _post(url, payload, key, timeout=90):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "news-digest/1.2",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def build_providers(settings):
    """返回可用供应商列表：只保留已配置 Key 的。"""
    llm = settings.get("llm") or {}
    out = []
    for p in llm.get("providers", []):
        key = os.environ.get(p.get("key_env", "").strip(), "") if p.get("key_env") else ""
        if not key:
            key = _load_key(p.get("key_file", ""))
        if key:
            out.append({**p, "_key": key})
    return out


# ---------------------------------------------------------------- 单条模式
def _ask(title, source_name, text, settings, prov, model):
    text = (text or "").strip()[: settings.get("article_text_chars", 1200) + 400]
    if not text:
        text = title
    user = (f"信源：{source_name}\n标题：{title}\n材料：{text}\n\n"
            f"请用简体中文写一段约{settings.get('summary_chars', 300)}字的中文简报摘要（280～320字，材料单薄时可略短，不低于180字）："
            "先给核心事实（谁、做了什么、关键数字），再给一句意义/影响；"
            "材料是英文也务必翻译成中文来写，只保留术语/机构名/人名的英文原文，不要照抄英文句子；"
            "严禁编造材料外的信息；不要标题、不要项目符号、不要客套话。\n\n"
            "最后另起一行，只写一行元数据：重要度:数字|类别:政策/融资/技术/市场/动态/观点/人事/其他（八选一）。\n"
            "重要度标准：5=重大政策/突破性技术/巨额融资/市场剧震；4=重要政策/大额融资/重要成果；"
            "3=常规行业动态或论文；2=边缘信息；1=花絮。元数据不要写进摘要正文，不要解释。")
    resp = _post(prov["base_url"], {
        "model": model,
        "messages": [{"role": "system", "content": _SYS_PROMPT},
                     {"role": "user", "content": user}],
        "temperature": prov.get("temperature", 0.3),
        "max_tokens": prov.get("max_tokens", 600),
    }, prov["_key"], timeout=prov.get("timeout", 90))
    return (resp["choices"][0]["message"].get("content") or "").strip()


# ---------------------------------------------------------------- 批量模式
def _ask_batch(batch, settings, prov, model):
    """把 N 条材料塞进一次请求，要求模型按 <<<序号>>> 分节输出 N 段摘要。"""
    chars = int(settings.get("summary_chars", 300))
    cap = int(settings.get("article_text_chars", 1200))
    blocks = []
    for i, it in enumerate(batch, 1):
        text = (it.get("summary_text") or it.get("lead") or "").strip()[:cap] or it["title"]
        blocks.append(f"<<<{i}>>>\n信源：{it.get('source_name', '')}\n标题：{it['title']}\n材料：{text}")
    n = len(batch)
    user = (
        f"下面是 {n} 条来自不同信源的资讯，每条以 <<<1>>> 这样的分隔标记起头——"
        f"尖括号内是阿拉伯数字，不是“序号”两个字。"
        f"请为每一条各写一段约{chars}字的中文简报摘要（{chars-20}～{chars+20}字；材料确实单薄时可略短，但不低于180字），严格按原序号输出：\n"
        f"1) 每段第一行只写该条的序号标记（第 1 条写 <<<1>>>、第 2 条写 <<<2>>>，依次类推），"
        f"从下一行开始写该条的摘要正文，不要把标记或“序号”二字写进正文；段与段之间空一行；\n"
        f"2) 必须输出全部 {n} 段，序号连续完整，不合并、不跳过、不改变顺序、不额外加总述或结语；\n"
        "3) 每条只能使用标注在该序号下的材料，严禁把其他条目的信息混进来，严禁编造材料外事实；\n"
        "4) 每段先给核心事实（谁、做了什么、关键数字），再给一句意义/影响；\n"
        "5) 不要标题、不要项目符号、不要客套话；\n"
        "6) 每段摘要正文之后另起一行，只写一行元数据：重要度:数字|类别:政策/融资/技术/市场/动态/观点/人事/其他（八选一）。\n"
        "   重要度标准：5=重大政策/突破性技术/巨额融资/市场剧震；4=重要政策/大额融资/重要成果；"
        "3=常规行业动态或论文；2=边缘信息；1=花絮。元数据不写入摘要正文，不要解释。\n\n"
        + "\n\n".join(blocks)
    )
    # 输出预算：中文约 1.75 token/字，模型还会写超，按每条约 900 token 预留，
    # 否则 finish_reason=length，只会输出前一两段就被截断（这是批量失败的根因）。
    max_tokens = min(int(prov.get("batch_max_tokens", 8000)), 300 + 900 * n)
    resp = _post(prov["base_url"], {
        "model": model,
        "messages": [{"role": "system", "content": _SYS_PROMPT},
                     {"role": "user", "content": user}],
        "temperature": prov.get("temperature", 0.3),
        "max_tokens": max_tokens,
    }, prov["_key"], timeout=prov.get("batch_timeout", 240))
    return (resp["choices"][0]["message"].get("content") or "").strip()


def _parse_batch(content, n):
    """把批量输出切回 {序号: {summary, importance, category}}。

    元数据在切段时就剥离，保证写进页面 data.json 和缓存的都是纯摘要；
    剥离后正文不足 40 字的段落直接丢弃，交给补齐环节。
    """
    content = content or ""
    # 容错：整篇都把标记写成字面“<<<序号>>>”时，按出现顺序重编号再解析
    if _SEC_LITERAL.search(content) and not re.search(r"<<<\s*\d{1,3}\s*>>>", content):
        seq = iter(range(1, n + 1))
        content = _SEC_LITERAL.sub(lambda _m: "<<<%d>>>" % next(seq, n), content)
    best = {}
    for pat in (_SEC_LINE, _SEC_ANY):
        hits = []
        for m in pat.finditer(content):
            num = next((int(g) for g in m.groups() if g), 0)
            if num:
                hits.append((num, m.start(), m.end()))
        if len(hits) < 2:
            continue
        got = {}
        for k, (num, start, m_end) in enumerate(hits):
            if not (1 <= num <= n) or num in got:
                continue
            end = hits[k + 1][1] if k + 1 < len(hits) else len(content)
            body = _clean_summary(content[m_end:end])
            if not (40 <= len(body) <= 1200):
                continue
            text, imp, cat = _extract_meta(body)
            if len(text) < 40:
                continue
            got[num] = {"summary": text, "importance": imp, "category": cat}
        if len(got) > len(best):
            best = got
        if len(best) >= n:
            break
    return best


def _clean_summary(s):
    s = (s or "").strip()
    s = re.sub(r"^(?:摘要|正文|摘要正文|简报)\s*[:：]\s*", "", s)
    s = s.replace("**", "").replace("__", "")
    s = re.sub(r"^[-—•·]\s*", "", s)
    # 模型偶尔把分节标记抄成摘要开头，甚至抄成字面“<<<序号>>>”。
    # 这里统一剥掉（含序号已转成数字、或仍是“序号”二字两种情况）。
    for pat in (r"^<<<[^>\n]{0,10}>>>\s*", r"^【[^】\n]{0,10}】\s*",
                r"^\[\s*\d{1,3}\s*\]\s*", r"^#\s*\d{1,3}\s+"):
        s = re.sub(pat, "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


# ---------------------------------------------------------------- 通道调度
def _iter_attempts(providers, state):
    """按"上次成功的供应商/模型优先"的顺序给出候选通道。"""
    with state["lock"]:
        pinned = state.get("pinned")
        pinned_model = state.get("model")
    order = ([pinned] + [p for p in providers if p is not pinned]) if pinned else list(providers)
    for prov in order:
        models = list(prov.get("models") or [])
        if prov is pinned and pinned_model in models:
            models = [pinned_model] + [m for m in models if m != pinned_model]
        for model in models:
            yield prov, model


def _call(kind, payload, settings, providers, state):
    """带容错的调用。kind='one' 传单条 item，kind='batch' 传 item 列表。
    返回 (正文, 通道标记, 错误描述)。"""
    last_err = ""
    for prov, model in _iter_attempts(providers, state):
        for attempt in range(3):
            try:
                if kind == "batch":
                    content = _ask_batch(payload, settings, prov, model)
                else:
                    content = _ask(payload["title"], payload["source_name"],
                                   payload.get("summary_text") or payload.get("lead") or "",
                                   settings, prov, model)
                if content:
                    with state["lock"]:
                        state["pinned"] = prov
                        state["model"] = model
                    return content, f"{prov['name']}:{model}", ""
                last_err = f"{prov['name']}/{model} empty-content"
                break  # 推理模型思考耗尽 token：换模型
            except Exception as e:
                body = ""
                if hasattr(e, "read"):
                    try:
                        body = e.read().decode("utf-8", "ignore")[:200]
                    except Exception:
                        pass
                last_err = f"{prov['name']}/{model} {type(e).__name__}: {body or str(e)[:100]}"
                if re.search(r"model.*(not exist|not found|no permission)", body, re.I):
                    break  # 换模型
                if re.search(r"(401|403|Unauthorized|invalid.*key)", body, re.I):
                    break  # 换供应商
                if re.search(r"(429|Too Many|rate.?limit|1302|1305)", body + str(e), re.I):
                    # 免费档被限流：整体冷却一段时间，避免并发线程继续猛撞
                    cool = float((settings.get("llm") or {}).get("cooldown_seconds", 45))
                    with state["lock"]:
                        state["pause_until"] = max(state.get("pause_until", 0.0), time.time() + cool)
                    time.sleep(cool * (attempt + 1))
                    continue
                time.sleep(1 + attempt)
    return None, "", last_err


def fallback_summary(item):
    """模型不可用时的降级：优先用抓到的正文，其次用接口导语。
    门槛放到 15 字，是因为财联社这类快讯本身就是二三十字的一句话，够直接当摘要读。"""
    for k in ("summary_text", "lead"):
        v = (item.get(k) or "").strip()
        if len(v) >= 15:
            return v[:300]
    return ""


def summarize_items(items, settings, base_dir, log=print, dry=False):
    """给每条 item 补 summary / summary_mode。

    - 批量：llm.batch_size 条/次请求（默认 5），请求数降到 1/5，避开免费档限流
    - 补齐：批量里漏掉的条目再用单条模式补，最多 llm.repair_max 条
    - 限速：llm.min_interval_seconds 控制全局请求间隔（免费档实测约5次/分钟）
    - 缓存：data/summary_cache.json 按 URL 跨日复用，窗口内重复出现的旧条目不再请求；
      重要度与类别也一并缓存，重复条目沿用上次的评分。
    """
    providers = [] if dry else build_providers(settings)
    if not providers:
        for it in items:
            it["summary"] = fallback_summary(it) or "（摘要待启用：配置任一模型 API Key 后自动生成）"
            it["summary_mode"] = "lead" if it.get("lead") else "placeholder"
            it["importance"] = 3
            it["category"] = ""
        log("  摘要：未检测到可用模型 Key，已用正文截取占位")
        return items

    import threading
    llm_cfg = settings.get("llm", {})
    interval = float(llm_cfg.get("min_interval_seconds", 12))
    batch_size = max(1, int(llm_cfg.get("batch_size", 5)))
    repair_max = int(llm_cfg.get("repair_max", 24))
    cache_path = Path(base_dir) / "data" / "summary_cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    today = time.strftime("%Y-%m-%d")
    state = {"lock": threading.Lock(), "pinned": None, "model": "", "ok": 0,
             "fail": 0, "last_error": "", "cached": 0,
             "batches": 0, "batch_fail": 0,
             "gate": threading.Lock(), "next_slot": 0.0}
    # 时钟预算：免费档被限流时冷却会不断叠加，没有预算就可能跑上几个小时。
    # 到点后剩余条目直接降级为正文截取，保证定时任务在可预期的时间内结束。
    deadline = time.time() + float(llm_cfg.get("max_minutes", 25)) * 60
    state["skipped_timeout"] = 0

    def out_of_time():
        return time.time() > deadline

    def take_slot():
        """全局限速：相邻两次真实请求至少间隔 interval 秒；被限流时整体冷却。"""
        with state["gate"]:
            now = time.time()
            slot = max(state["next_slot"], now, state.get("pause_until", 0.0))
            state["next_slot"] = slot + interval
            wait = slot - now
        if wait > 0:
            time.sleep(wait)

    def put(it, sm, mode, imp=None, cat=None):
        # 没有重要度分时用 3（中等），保证 dry / 缓存 / 摘要降级都能参与重排
        it["summary"] = sm
        it["summary_mode"] = mode
        it["importance"] = imp or 3
        it["category"] = cat or ""
        url = it.get("url") or ""
        if url:
            cache[url] = {"summary": sm, "mode": mode, "date": today,
                          "imp": it["importance"], "cat": it["category"]}

    # 缓存自愈：正文抓取逻辑修复前生成的旧摘要可能混进页脚/导航噪声
    # （如"地址：…电话…""责任编辑：…""点击收起全文"）。这类摘要即使命中缓存也
    # 不能复用，否则修复代码后旧噪声摘要还会续命 30 天。命中即作废，强制重生成。
    _CACHE_NOISE_RE = re.compile(
        r"(责任编辑[：:]|点击收起全文|返回央视网首页|扫一扫|分享到微信|"
        r"友情链接|通讯地址|地址[：:].{0,40}(号|路|街).{0,40}电话|"
        r"邮箱[：:]\s*\S+@|电话[（(]?传真|"
        # 模型把分节标记抄进摘要（<<<序号>>> / 【序号】），旧缓存要作废
        r"<<<|【\s*序\s*号\s*】)", re.I)

    # 1) 命中缓存的先落袋，剩下的是本次真正要生成的
    todo = []
    for it in items:
        url = it.get("url") or ""
        hit = cache.get(url) if url else None
        if hit and hit.get("summary") and not _CACHE_NOISE_RE.search(hit["summary"]):
            it["summary"] = hit["summary"]
            it["summary_mode"] = "cache"
            # 旧缓存没有 imp/cat，按中等分处理；新缓存会带回上次模型给的分数
            it["importance"] = hit.get("imp", 3)
            it["category"] = hit.get("cat", "")
            state["cached"] += 1
        elif len((it.get("summary_text") or it.get("lead") or "").strip()) < 40:
            it["summary"] = fallback_summary(it) or "（本条材料过短，未能生成摘要）"
            it["summary_mode"] = "lead" if it.get("lead") else "failed"
            it["importance"] = 3
            it["category"] = ""
            state["fail"] += 1
        else:
            todo.append(it)

    log(f"  摘要：共 {len(items)} 条，缓存命中 {state['cached']}，待生成 {len(todo)}"
        f"（每批 {batch_size} 条，预计 {-(-len(todo) // batch_size)} 次请求）")

    # 2) 分批并发请求
    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    missing = []
    dump_dir = Path(base_dir) / "logs" / "batch_debug" if llm_cfg.get("debug_batch_dump") else None
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)

    def work(batch):
        if out_of_time():
            with state["lock"]:
                state["skipped_timeout"] += len(batch)
            return
        take_slot()
        content, tag, err = _call("batch", batch, settings, providers, state)
        with state["lock"]:
            state["batches"] += 1
        if not content:
            with state["lock"]:
                state["batch_fail"] += 1
                state["last_error"] = err
            missing.extend(batch)
            return
        parts = _parse_batch(content, len(batch))
        if dump_dir and len(parts) < len(batch):
            try:
                tag_name = re.sub(r"[^0-9A-Za-z]+", "-", time.strftime("%H%M%S")) + f"-{len(batch)}-{len(parts)}"
                (dump_dir / f"{tag_name}.txt").write_text(
                    f"=== 解析到 {len(parts)}/{len(batch)} 段 ===\n标题：\n"
                    + "\n".join(f"  {i}. {it['title'][:70]}" for i, it in enumerate(batch, 1))
                    + f"\n\n=== 原始输出（{len(content)}字）===\n{content}",
                    encoding="utf-8")
            except Exception:
                pass
        for i, it in enumerate(batch, 1):
            p = parts.get(i)
            if p:
                put(it, p["summary"], tag, p["importance"], p["category"])
                with state["lock"]:
                    state["ok"] += 1
            else:
                missing.append(it)

    workers = max(1, min(int(llm_cfg.get("concurrency", 2)), len(batches) or 1))
    if batches:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(work, batches))
        log(f"  批量完成：{len(batches)} 次请求，成功 {state['ok']} 条，"
            f"批次失败 {state['batch_fail']}，待补齐 {len(missing)} 条")

    # 3) 补齐：先按 3 条一批重试（截断/漏段多是批太长），剩下的再单条补
    still = []
    if missing and not out_of_time():
        chunks = [missing[i:i + 3] for i in range(0, len(missing), 3)]

        def repair_batch(chunk):
            if out_of_time():
                still.extend(chunk)
                return
            take_slot()
            content, tag, _err = _call("batch", chunk, settings, providers, state)
            parts = _parse_batch(content, len(chunk)) if content else {}
            for i, it in enumerate(chunk, 1):
                p = parts.get(i)
                if p:
                    put(it, p["summary"], tag, p["importance"], p["category"])
                    with state["lock"]:
                        state["ok"] += 1
                else:
                    still.append(it)

        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(repair_batch, chunks))
        log(f"  补齐批次：{len(chunks)} 次请求，仍缺 {len(still)} 条")

    if still and repair_max > 0 and not out_of_time():
        queue = still[:repair_max]

        def repair(it):
            if out_of_time():
                still_skipped.append(it)
                return
            take_slot()
            sm, mode, _err = _call("one", it, settings, providers, state)
            if sm:
                sm, imp, cat = _extract_meta(_clean_summary(sm))
                put(it, sm, mode, imp, cat)
                with state["lock"]:
                    state["ok"] += 1
            else:
                with state["lock"]:
                    state["fail"] += 1

        still_skipped = []
        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(repair, queue))
        state["skipped_timeout"] += len(still_skipped)
        log(f"  单条补齐完成：{sum(1 for it in queue if it.get('summary_mode') not in ('lead', 'failed'))}"
            f"/{len(queue)} 条")

    # 4) 仍无摘要的条目退回导语截取
    for it in items:
        if not it.get("summary"):
            it["summary"] = fallback_summary(it) or "（本条摘要生成失败，可点原文查看）"
            it["summary_mode"] = "lead" if it.get("lead") else "failed"
        it.setdefault("importance", 3)
        it.setdefault("category", "")

    # 4.5) 语言兜底：英文材料偶尔被整段照抄成英文摘要（Gemini 批量请求下会这样），
    #      中文简报里不应出现。中文占比过低的条目用单条模式重生成一次；
    #      重生成仍不合格就保留原样，不反复消耗配额。
    def _cjk_ratio(s):
        s = s or ""
        return sum(1 for c in s if "\u4e00" <= c <= "\u9fff") / max(1, len(s))

    off_lang = [it for it in items
                if it.get("summary_mode") not in ("lead", "failed")
                and _cjk_ratio(it.get("summary")) < 0.20]
    if off_lang and not out_of_time():
        log(f"  语言兜底：{len(off_lang)} 条摘要非中文，改为单条重生成")
        fixed = {"n": 0}

        def _relang(it):
            if out_of_time():
                return
            take_slot()
            sm, mode, _err = _call("one", it, settings, providers, state)
            if not sm:
                return
            sm, imp, cat = _extract_meta(_clean_summary(sm))
            if _cjk_ratio(sm) >= 0.20:
                put(it, sm, mode, imp, cat)
                with state["lock"]:
                    fixed["n"] += 1

        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(_relang, off_lang[:15]))
        log(f"  语言兜底完成：{fixed['n']}/{len(off_lang[:15])} 条已改为中文")

    # 缓存落盘（只保留最近 30 天）
    if cache:
        cut = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * 86400))
        cache = {k: v for k, v in cache.items() if v.get("date", "") >= cut}
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    if state.get("skipped_timeout"):
        log(f"  时钟预算用尽：{state['skipped_timeout']} 条改用正文截取（下次运行会补上）")
    used = state.get("pinned")
    log(f"  摘要完成：成功 {state['ok']}，失败 {state['fail']}，缓存命中 {state['cached']}，"
        f"请求 {state['batches'] + min(len(missing), repair_max)} 次，"
        f"通道 {used['name'] + '/' + state['model'] if used else '无'}")
    if state["fail"] and state["last_error"]:
        log(f"  最近错误：{state['last_error'][:160]}")
    return items
