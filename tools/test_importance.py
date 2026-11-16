# -*- coding: utf-8 -*-
"""重要度标签回归测试：离线解析单测 + 可选的 --live 真实模型调用。

用法：
  python tools/test_importance.py          # 离线，不消耗 token
  python tools/test_importance.py --live   # 再调一次真实模型，验证 prompt 输出能被解析

以后改摘要 prompt 或解析正则后，重跑本脚本即可确认没有回归。
"""
import json
import sys
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from digest import pipeline, summarize  # noqa: E402


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        raise AssertionError(label)


def test_parse_batch():
    print("[1] 批量摘要解析 + 元数据剥离")
    fake = """<<<1>>>
中共中央印发《中国共产党地方委员会工作条例》，条例对地方党委的职责、议事程序和监督机制作出系统规定，要求各地各部门结合实际抓好贯彻落实，相关解读文章同步发布。
重要度:5|类别:政策

<<<2>>>
Trigonal Prismatic Coordination Field-Induced Chirality in a Dual-Atom Catalyst. 该研究通过调控配位场实现了选择性的显著提升，为下一代电催化剂设计提供了新的思路与实验证据。
重要度：3 类别：技术

<<<3>>>
某公司今日宣布完成数亿元A轮融资，由某知名机构领投，资金将主要用于氢能电解槽产线扩建与研发团队扩充，公司称新产品已进入中试阶段重要度:4|类别:融资
"""
    parts = summarize._parse_batch(fake, 3)
    check(len(parts) == 3, f"解析出 3 段（实际 {len(parts)}）")
    check(parts[1]["importance"] == 5 and parts[1]["category"] == "政策", "第1条元数据=5/政策")
    check(parts[2]["importance"] == 3 and parts[2]["category"] == "技术", "第2条元数据=3/技术")
    check(parts[3]["importance"] == 4 and parts[3]["category"] == "融资", "第3条同行元数据解析")
    for n in (1, 2, 3):
        check("重要度" not in parts[n]["summary"] and "类别" not in parts[n]["summary"],
              f"第{n}条摘要正文未混入元数据")
    check("产线扩建" in parts[3]["summary"], "同行元数据未误删正文")

    print("[2] 元数据格式兼容")
    body = "某公司发布新一代储能产品，容量与循环寿命均有提升，并公布了首批项目落地情况。" * 2
    cases = [
        (body + "\n重要度:2|类别:动态", 2, "动态"),
        (body + "\n重要性：4，类别:政策", 4, "政策"),
        (body + "\nImportance: 3 | Category: Market", 3, "Market"),
        (body, None, None),
    ]
    for text, imp, cat in cases:
        got_text, got_imp, got_cat = summarize._extract_meta(text)
        check(got_imp == imp and got_cat == cat and len(got_text) >= 40,
              f"格式解析 {text.splitlines()[-1][:20]!r}")


def test_keywords():
    print("[3] 英文关键词与词边界")
    cfg = json.loads((BASE / "sources.json").read_text(encoding="utf-8"))
    md = cfg["modules"]
    cases = [
        ("Federal Reserve signals rate decision", "m7"),
        ("University faculty tenure review", "m6"),
        ("Russia and Ukraine talks continue", "m5"),
        ("State Council issued new policy", "m4"),
        ("Green finance investment in clean energy", "m2"),
    ]
    for title, mid in cases:
        n = pipeline.keyword_score(title, "", md[mid])
        check(n > 0, f"{mid} 命中英文标题：{title[:34]}（命中 {n}）")
    check(not pipeline._kw_hit("rate", "corporate accurate"), "rate 不再误命中 corporate/accurate")
    check(pipeline._kw_hit("rate", "interest rate"), "rate 仍能命中独立词")
    check(pipeline._kw_hit("her", "her paper"), "her 作为独立词仍能命中")
    check(not pipeline._kw_hit("her", "other gathering"), "her 不再误命中 other/gathering 的子串")


def test_rerank():
    print("[4] 重要度重排")
    items = [
        {"title": "论文", "module": "m3", "score": 8.6, "importance": 3},
        {"title": "政策", "module": "m4", "score": 8.3, "importance": 5},
        {"title": "无分", "module": "m1", "score": 5.0},
    ]
    out = pipeline.rerank_by_llm(items, {"rerank_keyword_weight": 0.3,
                                         "rerank_importance_weight": 2.0})
    check(out[0]["title"] == "政策", "重要度5的政策排到第一（关键词分更低）")
    check(out[2]["title"] == "无分" and out[2]["final_score"] == 7.5,
          "缺失重要度按 3 分处理，不报错")


def test_live():
    print("[5] 真实模型调用（1 次请求，消耗少量 token）")
    settings = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))
    provs = summarize.build_providers(settings)
    if not provs:
        print("  跳过：未配置任何模型 Key")
        return
    batch = [
        {"title": "中共中央印发《中国共产党地方委员会工作条例》",
         "source_name": "中国政府网",
         "summary_text": "条例对地方党委的职责、议事程序和监督机制作出系统规定，要求各地各部门结合实际抓好贯彻落实。新华社受权发布全文，多个部委同步表态将完善配套措施。" * 2},
        {"title": "Dual-atom catalyst boosts hydrogen evolution",
         "source_name": "ACS Catalysis",
         "summary_text": "Researchers report a heteronuclear dual single-atom catalyst with enhanced hydrogen evolution activity. The study combines operando spectroscopy and DFT calculations to identify the active site." * 2},
    ]
    state = {"lock": threading.Lock(), "pinned": None, "model": ""}
    content, tag, err = summarize._call("batch", batch, settings, provs, state)
    if not content:
        print("  调用失败：" + str(err)[:200])
        raise AssertionError("模型调用失败")
    parts = summarize._parse_batch(content, 2)
    print(f"  通道 {tag}，解析 {len(parts)}/2 段")
    for n, p in parts.items():
        print(f"  <<<{n}>>> 重要度={p['importance']} 类别={p['category']} 摘要={p['summary'][:40]}...")
        check(1 <= (p["importance"] or 0) <= 5, f"第{n}条重要度在 1-5 之间")
        check(bool(p["category"]), f"第{n}条有类别")
        check("重要度" not in p["summary"], f"第{n}条摘要已剥离元数据")
    check(len(parts) == 2, "两条都成功解析")


if __name__ == "__main__":
    test_parse_batch()
    test_keywords()
    test_rerank()
    if "--live" in sys.argv:
        test_live()
    print("\n全部离线检查通过。")
