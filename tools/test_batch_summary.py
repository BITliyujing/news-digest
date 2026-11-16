# -*- coding: utf-8 -*-
"""摘要链路冒烟测试：取最近一次 processed_*.json 的若干条，跑批量摘要并打印结果。
用法：python tools/test_batch_summary.py [条数，默认10]
"""
import json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from digest import summarize  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
settings = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))
files = sorted((BASE / "data").glob("processed_*.json"))
if not files:
    print("没有 processed_*.json，请先跑一次 run_daily.py")
    sys.exit(1)
items = json.loads(files[-1].read_text(encoding="utf-8"))
# 挑有正文的、不同模块的若干条
pick = [it for it in items if len((it.get("summary_text") or "").strip()) >= 200][:n]
for it in pick:
    it.pop("summary", None)
    it.pop("summary_mode", None)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print(f"取自 {files[-1].name}，共 {len(pick)} 条待摘要\n")
summarize.summarize_items(pick, settings, str(BASE), log=lambda m: print(m, flush=True))
print("\n=== 结果 ===")
for i, it in enumerate(pick, 1):
    sm = it.get("summary", "")
    print(f"\n[{i}] {it.get('summary_mode')} | {len(sm)}字 | {it['title'][:60]}")
    print(sm)
