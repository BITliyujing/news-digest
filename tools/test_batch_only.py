# -*- coding: utf-8 -*-
"""只测摘要批量通道（不重新抓取）：从最近一次 processed_*.json 取若干条，重跑批量摘要。
会打印每批解析出的段数，并把解析不完整的批次原始输出存到 logs/batch_debug/。
用法：python tools/test_batch_only.py [条数=10] [每批=5]
"""
import json, shutil, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from digest import summarize  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
bs = int(sys.argv[2]) if len(sys.argv) > 2 else 5

settings = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))
settings["llm"]["batch_size"] = bs
settings["llm"]["debug_batch_dump"] = True
settings["llm"]["repair_max"] = 0          # 先只看批量本身的成功率
tmp = BASE / "data" / "tmp_test"
if tmp.exists():
    shutil.rmtree(tmp)
tmp.mkdir(parents=True, exist_ok=True)

files = sorted((BASE / "data").glob("processed_*.json"))
items = json.loads(files[-1].read_text(encoding="utf-8"))
pick = [it for it in items if len((it.get("summary_text") or "").strip()) >= 200][:n]
for it in pick:
    it.pop("summary", None)
    it.pop("summary_mode", None)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print(f"取自 {files[-1].name}：{len(pick)} 条，每批 {bs} 条\n")
summarize.summarize_items(pick, settings, str(tmp), log=lambda m: print(m, flush=True))

ok = [it for it in pick if it.get("summary_mode", "").startswith(("glm", "deepseek", "model", "silicon"))]
print(f"\n=== 批量直出 {len(ok)}/{len(pick)} 条 ===")
for it in pick:
    print(f"- {it.get('summary_mode'):>22} | {len(it.get('summary','')):>3}字 | {it['title'][:52]}")
