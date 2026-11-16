# -*- coding: utf-8 -*-
"""摘要层：多供应商自动切换（智谱GLM免费 / 魔搭ModelScope免费 / DeepSeek付费 / 硅基流动）。
全部走 OpenAI 兼容的 /chat/completions 协议，配置在 settings.json 的 llm.providers。
无可用 Key 或全部失败时，降级为正文前 300 字截取。"""
import json, os, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import http

_CTX = http._CTX
_SYS_PROMPT = (
    "你是一名资深行业资讯编辑，为中文读者（科研人员与投资人）撰写每日简报。"
    "只依据给定材料归纳，不编造、不添加材料外的事实；英文术语、机构名、人名保留英文原文。"
)


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
        "User-Agent": "news-digest/1.1",
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


def _ask(title, source_name, text, settings, prov, model):
    text = (text or "").strip()[: settings.get("article_text_chars", 1200) + 400]
    if not text:
        text = title
    user = (f"信源：{source_name}\n标题：{title}\n材料：{text}\n\n"
            f"请写一段约{settings.get('summary_chars', 300)}字的中文简报摘要："
            "先给核心事实（谁、做了什么、关键数字），再给一句意义/影响；"
            "严禁编造材料外的信息；不要标题、不要项目符号、不要客套话。")
    resp = _post(prov["base_url"], {
        "model": model,
        "messages": [{"role": "system", "content": _SYS_PROMPT},
                     {"role": "user", "content": user}],
        "temperature": prov.get("temperature", 0.3),
        "max_tokens": prov.get("max_tokens", 600),
    }, prov["_key"], timeout=prov.get("timeout", 90))
    return resp["choices"][0]["message"]["content"].strip()


def summarize_one(item, settings, providers, state):
    """单条摘要。state 里记住本次运行已验证可用的 provider+model。"""
    text = item.get("summary_text") or item.get("lead") or ""
    if len(text) < 40:
        return None, "text-too-short"
    lock = state["lock"]
    with lock:
        pinned = state.get("pinned")
    order = ([pinned] + [p for p in providers if p is not pinned]) if pinned else list(providers)
    last_err = ""
    for prov in order:
        models = prov.get("models") or []
        for model in models:
            for attempt in range(2):
                try:
                    sm = _ask(item["title"], item["source_name"], text, settings, prov, model)
                    if sm:
                        with lock:
                            state["pinned"] = prov
                            state["model"] = model
                            state["ok"] += 1
                        return sm, f"{prov['name']}:{model}"
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
                    time.sleep(1 + attempt)
    with lock:
        state["fail"] += 1
        state["last_error"] = last_err
    return None, last_err


def fallback_summary(item):
    for k in ("summary_text", "lead"):
        v = (item.get(k) or "").strip()
        if len(v) >= 60:
            return v[:300]
    return ""


def summarize_items(items, settings, base_dir, log=print, dry=False):
    """给每条 item 补 summary / summary_mode。多线程并发（glm 免费档约30并发）。"""
    providers = [] if dry else build_providers(settings)
    if not providers:
        for it in items:
            it["summary"] = fallback_summary(it) or "（摘要待启用：配置任一模型 API Key 后自动生成）"
            it["summary_mode"] = "lead" if it.get("lead") else "placeholder"
        log("  摘要：未检测到可用模型 Key，已用正文截取占位")
        return items

    import threading
    state = {"lock": threading.Lock(), "pinned": None, "model": "", "ok": 0,
             "fail": 0, "last_error": ""}
    workers = int(settings.get("llm", {}).get("concurrency", 6))
    total = len(items)
    done = {"n": 0}

    def work(it):
        sm, mode = summarize_one(it, settings, providers, state)
        if sm:
            it["summary"] = sm
            it["summary_mode"] = mode
        else:
            it["summary"] = fallback_summary(it) or "（本条摘要生成失败）"
            it["summary_mode"] = "lead" if it.get("lead") else "failed"
        with state["lock"]:
            done["n"] += 1
            if done["n"] % 20 == 0:
                log(f"  摘要进度 {done['n']}/{total}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, items))

    used = state.get("pinned")
    log(f"  摘要完成：成功 {state['ok']}，失败 {state['fail']}，"
        f"通道 {used['name'] + '/' + state['model'] if used else '无'}")
    if state["fail"] and state["last_error"]:
        log(f"  最近错误：{state['last_error'][:160]}")
    return items
