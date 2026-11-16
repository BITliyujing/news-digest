# -*- coding: utf-8 -*-
"""批量探测信源可用性：对每个候选站点尝试 自动发现RSS → 通用列表解析。
产出 data/probe_result.json：{name, url, module, ok, kind, feed, count, samples[], err}
用法：python tools/probe_sources.py [--limit N] [--workers 8]
"""
import argparse, json, socket, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
socket.setdefaulttimeout(12)   # 兜底：DNS/连接卡死时不无限等待

from digest import fetchers, http  # noqa: E402


def probe_one(row, settings):
    url = row["url"]
    src = {"id": "probe", "name": row["name"][:30], "lang": "zh" if "中文" in row["lang"] else "en"}
    home = url
    # 若给的是具体文章页，退到域名根
    if url.count("/") > 3:
        parts = url.split("/")
        home = "/".join(parts[:3]) + "/"
    ch = {"home": home}
    out = {"name": row["name"], "url": home, "module": row["module"],
           "cat": row["cat"], "lang": row["lang"], "ok": False, "kind": "", "feed": "",
           "count": 0, "samples": [], "err": ""}
    # 1) 发现的 feed
    try:
        feed = fetchers.discover_feed(home, settings)
    except Exception:
        feed = None
    if feed:
        try:
            st, raw = http.fetch(feed, settings, read_bytes=300000)
            items = fetchers._parse_rss_or_atom(raw, src)
            if items:
                out.update(ok=True, kind="rss", feed=feed, count=len(items),
                           samples=[i["title"][:70] for i in items[:3]])
                return out
        except Exception as e:
            out["err"] = f"feed:{type(e).__name__}"
    # 2) 通用列表
    try:
        items = fetchers.fetch_generic_list(src, ch, settings)
        out.update(ok=True, kind="list", count=len(items),
                   samples=[i["title"][:70] for i in items[:3]])
        return out
    except Exception as e:
        out["err"] = (out["err"] + " " + f"list:{type(e).__name__}:{str(e)[:50]}").strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="data/probe_result.json")
    ap.add_argument("--merge", action="store_true", help="与已有结果合并，不覆盖")
    args = ap.parse_args()

    settings = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))
    settings["politeness_sleep"] = 0.1
    settings["http_timeout"] = 10
    settings["http_fast"] = True

    rows = json.loads((BASE / "data" / "research_sources_raw.json").read_text(encoding="utf-8"))
    rows = [r for r in rows if r.get("url")]
    rows = rows[args.offset:]
    if args.limit:
        rows = rows[: args.limit]

    done, results = 0, []

    def _flush():
        out = BASE / args.out
        out.parent.mkdir(exist_ok=True)
        prev = []
        if args.merge and out.exists():
            try:
                prev = [r for r in json.loads(out.read_text(encoding="utf-8"))
                        if r.get("name") not in {x.get("name") for x in results}]
            except Exception:
                prev = []
        out.write_text(json.dumps(prev + results, ensure_ascii=False, indent=1), encoding="utf-8")

    pool = ThreadPoolExecutor(max_workers=args.workers)
    futs = {pool.submit(probe_one, r, settings): r for r in rows}
    try:
        for f in as_completed(futs, timeout=600 if rows else None):
            try:
                r = f.result(timeout=5)
            except Exception as e:
                r = {"ok": False, "err": f"{type(e).__name__}:{str(e)[:50]}", "name": futs[f]["name"]}
            results.append(r)
            done += 1
            if r.get("ok"):
                print(f"[{done}/{len(rows)}] OK  {r['name'][:26]:<28} {r['kind']:<4} {r['count']:>3}条  例:{r['samples'][0][:40] if r['samples'] else ''}", flush=True)
            else:
                print(f"[{done}/{len(rows)}] --  {r['name'][:26]:<28} {r['err'][:50]}", flush=True)
            if done % 5 == 0:
                _flush()
    except TimeoutError:
        print("\n（部分站点超时，已保存已完成的结果）", flush=True)
    pool.shutdown(wait=False, cancel_futures=True)
    _flush()
    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n完成：{ok}/{len(results)} 个站点可抓取")


if __name__ == "__main__":
    main()
