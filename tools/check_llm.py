# -*- coding: utf-8 -*-
"""检测摘要模型是否可用：读取 settings.json 的 llm.providers，逐个试一条。
用法：python tools/check_llm.py
"""
import json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from digest import summarize  # noqa: E402


def main():
    settings = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))
    providers = summarize.build_providers(settings)
    if not providers:
        print("未检测到任何 Key。可选：")
        for p in settings["llm"]["providers"]:
            print(f"  - {p['name']:<11} 放到 {p['key_file']} 或设环境变量 {p.get('key_env')}")
        return
    text = ("国家能源局发布《关于加快新型储能规模化应用的通知》，提出到2027年新型储能装机达到"
            "1.8亿千瓦以上，重点支持长时储能、构网型储能技术，并完善容量电价机制。"
            "业内预计将带动约3000亿元投资，锂电、液流电池、压缩空气储能等路线均受益。")
    for p in providers:
        for model in p["models"]:
            try:
                sm = summarize._ask("新型储能装机目标提至1.8亿千瓦", "测试源", text,
                                    settings, p, model)
                print(f"[OK] {p['name']}/{model} → {len(sm)}字：{sm[:60]}...")
                break
            except Exception as e:
                body = ""
                if hasattr(e, "read"):
                    try:
                        body = e.read().decode("utf-8", "ignore")[:150]
                    except Exception:
                        pass
                print(f"[FAIL] {p['name']}/{model} → {type(e).__name__} {body or str(e)[:80]}")


if __name__ == "__main__":
    main()
