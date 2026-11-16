# -*- coding: utf-8 -*-
"""把探测结果合并进 sources.json：只加可用且未被现有信源覆盖的站点。
用法：python tools/build_sources.py [--per-module 22] [--dry]
"""
import argparse, json, re, sys
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JUNK = re.compile(r"(下载|客户端|APP|登录|注册|会员|课程|学社|商城|广告|招聘)")
# 门户/聚合站：不能当成垂直信源（首页内容与门类无关）
PORTAL_HOSTS = {
    "sina.com.cn", "sina.cn", "sohu.com", "163.com", "qq.com", "baidu.com",
    "toutiao.com", "zhihu.com", "weibo.com", "ifeng.com", "thepaper.cn",
    "36kr.com", "cctv.com", "people.com.cn", "xinhuanet.com", "chinanews.com.cn",
    "jiemian.com", "yicai.com", "cls.cn", "stcn.com", "cs.com.cn", "eol.cn",
    "gov.cn", "huanqiu.com", "cnfin.com", "in-en.com", "bjx.com.cn",
    # 探测时匹配错的站点（名称与站点不符/明显非该媒体）
    "haimen.gov.cn", "aiww.com", "hark.news", "graphene.tv", "10100.com",
    "eol.cn", "zhuanzhiai.com",
}
_MULTI_SUFFIX = ("com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "co.uk",
                 "com.au", "co.jp", "com.hk", "com.tw")


def host_of(url):
    try:
        h = urlparse(url).hostname or ""
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def reg_domain(host):
    """归并到可注册域名：news.bjx.com.cn → bjx.com.cn"""
    parts = host.split(".")
    for suf in _MULTI_SUFFIX:
        if host.endswith("." + suf) or host == suf:
            n = len(suf.split(".")) + 1
            return ".".join(parts[-n:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def slug_of(host):
    s = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
    return s[:22] or "src"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-module", type=int, default=22)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    cfg = json.loads((BASE / "sources.json").read_text(encoding="utf-8"))
    srcs = cfg["sources"]
    probe = json.loads((BASE / "data" / "probe_result.json").read_text(encoding="utf-8"))

    used_hosts = set()
    used_ids = {s["id"] for s in srcs}
    used_names = {s["name"] for s in srcs}
    for s in srcs:
        ch = s.get("channel", {})
        for k in ("url", "home", "list_url"):
            if ch.get(k):
                h = host_of(ch[k])
                if h:
                    used_hosts.add(reg_domain(h))

    per_mod = {}
    for s in srcs:
        for m in s.get("modules", []):
            per_mod[m] = per_mod.get(m, 0) + 1

    added = []
    for r in sorted(probe, key=lambda x: (x.get("module") or "", x.get("name") or "")):
        if not r.get("ok") or not r.get("module"):
            continue
        h = host_of(r["url"])
        if not h:
            continue
        rd = reg_domain(h)
        if rd in PORTAL_HOSTS or rd in used_hosts:
            continue
        if re.search(r"(公众号|公号|微信)", r["name"] or ""):
            continue
        if not r.get("count") or r["count"] < 3:
            continue
        samples = r.get("samples") or []
        if samples and any(JUNK.search(x) for x in samples):
            continue
        if per_mod.get(r["module"], 0) >= 34:
            continue
        sid = slug_of(h)
        base_id, n = sid, 2
        while sid in used_ids:
            sid = f"{base_id}-{n}"
            n += 1
        name = re.split(r"[（(]", r["name"])[0].strip()[:24]
        if name in used_names:
            name = f"{name}·{h.split('.')[0]}"
        ch = ({"type": "rss", "url": r["feed"]} if r.get("kind") == "rss"
              else {"type": "auto", "home": r["url"]})
        item = {"id": sid, "name": name, "modules": [r["module"]],
                "lang": "zh" if "中文" in (r.get("lang") or "") else "en",
                "weight": 0.9 if r.get("kind") == "rss" else 0.75,
                "active": True, "strict_keywords": True, "channel": ch}
        srcs.append(item)
        used_hosts.add(h)
        used_ids.add(sid)
        used_names.add(name)
        per_mod[r["module"]] = per_mod.get(r["module"], 0) + 1
        added.append(item)

    print(f"新增 {len(added)} 个信源；模块分布：{per_mod}")
    for a in added:
        print(f"  [{a['modules'][0]}] {a['name'][:22]:<24} {a['channel']['type']:<5} {a['channel'].get('url') or a['channel'].get('home')}")

    if not args.dry and added:
        (BASE / "sources.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已写入 sources.json，共 {len(srcs)} 个信源")
    elif args.dry:
        print("\n(dry-run，未写入)")


if __name__ == "__main__":
    main()
