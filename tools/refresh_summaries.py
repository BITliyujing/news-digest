# -*- coding: utf-8 -*-
"""重跑摘要并重建页面（不重新抓取）：把降级为导语/失败的条目重新批量摘要，然后重新生成 index.html。
用法：python tools/refresh_summaries.py [--all]
  --all 表示全部条目重跑；默认只补降级的（summary_mode 为 lead/failed/placeholder）。
"""
import json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from digest import summarize, build  # noqa: E402

redo_all = "--all" in sys.argv
settings = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))
scfg = json.loads((BASE / "sources.json").read_text(encoding="utf-8"))
files = sorted((Path(BASE / settings["data_dir"])).glob("processed_*.json"))
if not files:
    print("没有 processed_*.json")
    sys.exit(1)
src_file = files[-1]
items = json.loads(src_file.read_text(encoding="utf-8"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 与 run_daily 一致：只有标题、正文为空的条目直接剔除
before = len(items)
items = [it for it in items if len((it.get("summary_text") or it.get("lead") or "").strip()) >= 15]
if len(items) < before:
    print(f"剔除 {before - len(items)} 条仅有标题无正文的条目")

if redo_all:
    for it in items:
        it.pop("summary", None)
        it.pop("summary_mode", None)
else:
    for it in items:
        if it.get("summary_mode") in ("lead", "failed", "placeholder"):
            it.pop("summary", None)
            it.pop("summary_mode", None)

print(f"{src_file.name}：共 {len(items)} 条，其中 {sum(1 for it in items if not it.get('summary'))} 条待重做")
summarize.summarize_items(items, settings, str(BASE), log=lambda m: print(m, flush=True))

page = build.build_page(items, scfg["modules"], settings, str(BASE / settings["out_dir"]),
                       log=lambda m: print(m, flush=True), sources=scfg["sources"])
src_file.write_text(json.dumps(items, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
bad = sum(1 for it in items if it.get("summary_mode") in ("lead", "failed", "placeholder"))
print(f"\n重做完成：仍降级 {bad}/{len(items)} 条。页面：{page}")
