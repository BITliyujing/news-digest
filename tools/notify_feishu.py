# -*- coding: utf-8 -*-
"""把当日简报的高重要度条目推送到飞书群机器人。

用法：
  python tools/notify_feishu.py                    # 推送当日（读 output/data.json）
  python tools/notify_feishu.py --date 2026-11-16  # 指定日期的归档
  python tools/notify_feishu.py --dry              # 只打印消息内容，不发送

配置：环境变量 FEISHU_WEBHOOK_URL（GitHub Actions 中来自 secrets）。
起飞书群：群设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook 地址。
若机器人设置了关键词或签名校验，本脚本也支持 FEISHU_WEBHOOK_KEYWORD /
FEISHU_WEBHOOK_SECRET 环境变量。

设计原则：推送失败只记日志、返回非 0，但绝不让主流程（简报生成）失败；
脚本本身可重复运行（同一天多次推送是可接受的，便于手动补发）。
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PAGE_URL = "https://bitliyujing.github.io/news-digest/"
CAT_LABEL = {"政策": "政策", "融资": "融资", "技术": "技术", "市场": "市场",
             "动态": "动态", "观点": "观点", "人事": "人事", "其他": ""}
MOD_NAME = {"m1": "新能源技术", "m2": "新能源金融", "m3": "能源材料学术",
            "m4": "国内时政", "m5": "国际地缘", "m6": "高等教育", "m7": "综合财经"}


def load_items(date_arg):
    """读取当日数据，优先本地 output/data.json，其次从线上 Pages 拉取。

    只认带 i/c 重要度字段的线上数据；data/processed_*.json 是重排前的
    中间产物（无重要度），不可用作推送源。deploy job 里没有本地产物，
    故需支持从 PAGE_URL 在线拉取。
    """
    p = BASE / "output" / "data.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data:
            return data, p
    except Exception:
        pass
    try:
        req = urllib.request.Request(PAGE_URL + "data.json", headers={"User-Agent": "news-digest-notify"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        if data:
            return data, PAGE_URL + "data.json"
    except Exception as e:
        print("线上数据拉取失败:", type(e).__name__, str(e)[:150])
    return [], None


def build_message(items, date_str):
    """返回飞书 post 富文本消息体。"""
    high = [it for it in items if (it.get("i") or 3) >= 4]
    high.sort(key=lambda x: (x.get("i") or 3, x.get("f") or x.get("s") or 0), reverse=True)
    top = high[:5]

    lines = [[{"tag": "text", "text": f"共 {len(items)} 条 · 高重要度 {len(high)} 条"}]]
    if top:
        lines.append([{"tag": "text", "text": "今日要闻："}])
        for idx, it in enumerate(top, 1):
            title = (it.get("t") or it.get("title") or "").strip()
            if len(title) > 52:
                title = title[:50] + "…"
            cat = CAT_LABEL.get(it.get("c") or it.get("category") or "", "")
            mod = MOD_NAME.get(it.get("m") or it.get("module") or "", "")
            tag = " · ".join(x for x in (cat, mod) if x)
            prefix = f"{idx}. "
            lines.append([{"tag": "text", "text": prefix + title + (f"  [{tag}]" if tag else "")}])
    else:
        lines.append([{"tag": "text", "text": "今日无高重要度条目，可点开完整版浏览。"}])
    lines.append([])
    lines.append([{"tag": "text", "text": "打开完整版："},
                  {"tag": "a", "text": PAGE_URL, "href": PAGE_URL}])

    return {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {
            "title": f"📰 行业简报 · {date_str}",
            "content": lines,
        }}}
    }


def sign_if_needed(payload, secret, keyword):
    if keyword:
        payload["content"]["post"]["zh_cn"]["title"] = keyword + " " + payload["content"]["post"]["zh_cn"]["title"]
    if secret:
        ts = str(int(time.time()))
        # 飞书自定义机器人的签名算法（官方示例）：把 timestamp+"\n"+密钥 整体当作
        # HMAC 的 key，对空字符串签名后 Base64。注意与常见"密钥作 key、消息作 body"相反。
        string_to_sign = f"{ts}\n{secret}"
        h = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        payload["timestamp"] = ts
        payload["sign"] = base64.b64encode(h).decode("utf-8")
    return payload


def send(url, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="指定日期 YYYY-MM-DD")
    ap.add_argument("--dry", action="store_true", help="只打印不发送")
    args = ap.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    items, src = load_items(args.date)
    if not items:
        print("未找到当日数据，跳过推送")
        return 2
    payload = build_message(items, date_str)
    print(f"数据源: {src} | 条目 {len(items)}")
    if args.dry:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not url:
        print("未配置 FEISHU_WEBHOOK_URL，跳过推送")
        return 2
    payload = sign_if_needed(payload, os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip(),
                             os.environ.get("FEISHU_WEBHOOK_KEYWORD", "").strip())
    try:
        status, body = send(url, payload)
        print("推送响应:", status, body[:300])
        if "StatusCode" in body and '"StatusCode":0' not in body.replace(" ", ""):
            print("飞书返回非成功状态码")
            return 1
        return 0
    except urllib.error.HTTPError as e:
        print("HTTP 错误:", e.code, e.read().decode("utf-8", "ignore")[:300])
        return 1
    except Exception as e:
        print("推送失败:", type(e).__name__, str(e)[:200])
        return 1


if __name__ == "__main__":
    sys.exit(main())
