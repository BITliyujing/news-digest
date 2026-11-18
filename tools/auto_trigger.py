# -*- coding: utf-8 -*-
"""可靠定时触发：绕开 GitHub Actions schedule 的平台故障。

背景：GitHub Actions 的 schedule 事件自 2026-11 中旬起在公开仓库上出现
平台级投递故障（GitHub Community discussion #213232），表现为
workflow_dispatch 正常、schedule 一次都不触发，重新提交 cron、禁用/启用
workflow 均无效，官方未给出修复时间。本脚本通过 REST API 直接触发
workflow_dispatch，该通道经实测稳定可用。

幂等性：同一天多次运行只会真正触发一次（检查当天是否已有成功运行）。

用法：
  python tools/auto_trigger.py                # 智能触发 + 等待完成
  python tools/auto_trigger.py --no-wait      # 只触发，不等待（推荐给定时器）
  python tools/auto_trigger.py --check-only   # 只检查今天是否已跑过
  python tools/auto_trigger.py --force        # 无视检查结果，强制触发
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

WORKFLOW = "daily-digest.yml"
REPO_API = "https://api.github.com/repos/BITliyujing/news-digest"
UA = {
    "User-Agent": "news-digest-auto-trigger",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(BASE, "logs", "auto_trigger.log")
BJ = timezone(timedelta(hours=8))


def log(msg):
    line = "[%s] %s" % (datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_token():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    payload = "protocol=https\nhost=github.com\n\n"
    # 方式 1：直接调用 git（Windows 计划任务/各平台通用，不依赖 bash 是否在 PATH）
    try:
        r = subprocess.run(["git", "credential", "fill"], input=payload,
                           capture_output=True, text=True, timeout=20)
        for line in (r.stdout or "").splitlines():
            if line.startswith("password="):
                t = line.split("=", 1)[1].strip()
                if t:
                    return t
    except Exception:
        pass
    # 方式 2：bash 兜底（Git Bash 环境）
    try:
        r = subprocess.run(
            ["bash", "-c",
             'printf "protocol=https\\nhost=github.com\\n\\n" | git credential fill 2>/dev/null'
             ' | grep "^password=" | cut -d= -f2'],
            capture_output=True, text=True, timeout=20)
        tok = r.stdout.strip()
        if tok:
            return tok
    except Exception:
        pass
    sys.exit("拿不到 GitHub 凭据：请确认 git 已登录，或设置环境变量 GITHUB_TOKEN")


def api(tok, path, data=None, method=None, timeout=40):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        REPO_API + path, data=body, method=method,
        headers={**UA, "Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"message": e.read().decode("utf-8", "ignore")[:300]}
    except Exception as e:
        return 0, {"message": str(e)[:300]}


def beijing_today():
    return datetime.now(BJ).date()


def parse_created(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def today_active(tok):
    """返回北京时间当天最近一次“成功或进行中”的运行（dict），没有则 None。

    把 in_progress/queued 也算作“已触发”，这样多个定时器（本机计划任务 +
    WorkBuddy 定时）错开几分钟先后触发时，后一个不会重复启动同一次简报。
    """
    status, res = api(tok, "/actions/workflows/%s/runs?per_page=20" % WORKFLOW)
    if status != 200:
        log("查询运行记录失败 HTTP %s: %s" % (status, res.get("message")))
        return None
    today = beijing_today()
    for run in res.get("workflow_runs", []):
        done = run.get("status") == "completed" and run.get("conclusion") == "success"
        pending = run.get("status") in ("in_progress", "queued", "waiting")
        if not (done or pending):
            continue
        try:
            d = parse_created(run["created_at"]).astimezone(BJ).date()
        except Exception:
            continue
        if d == today:
            return run
    return None


def dispatch(tok):
    status, res = api(tok, "/actions/workflows/%s/dispatches" % WORKFLOW,
                      {"ref": "main"}, method="POST")
    if status != 204:
        log("触发失败 HTTP %s: %s" % (status, res.get("message")))
        return False
    log("已触发云端简报（workflow_dispatch）")
    return True


def find_new_run(tok):
    status, res = api(tok, "/actions/runs?per_page=8")
    if status == 200:
        for r in res.get("workflow_runs", []):
            if r.get("event") == "workflow_dispatch":
                return r
    return None


def wait_done(tok, rid, minutes=40):
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        status, run = api(tok, "/actions/runs/%s" % rid)
        if status == 200 and run.get("status") == "completed":
            conclusion = run.get("conclusion")
            log("运行结束：%s  %s" % (conclusion, run.get("html_url")))
            return conclusion == "success"
        time.sleep(30)
    log("等待超时，请到 Actions 页面查看")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-wait", action="store_true", help="只触发不等待")
    ap.add_argument("--check-only", action="store_true", help="只检查不触发")
    ap.add_argument("--force", action="store_true", help="强制触发")
    args = ap.parse_args()

    tok = get_token()
    run = today_active(tok)
    if run and not args.force:
        log("今天已有运行 #%s（状态 %s/%s，%s），跳过触发"
            % (run["id"], run.get("status"), run.get("conclusion"), run["created_at"]))
        return 0
    if args.check_only:
        log("今天尚无运行（仅检查，未触发）")
        return 0
    if not dispatch(tok):
        return 1
    if args.no_wait:
        return 0
    time.sleep(8)
    new_run = find_new_run(tok)
    if not new_run:
        log("未找到刚触发的运行编号，请到 Actions 页面查看")
        return 0
    log("运行编号 #%s" % new_run["id"])
    return 0 if wait_done(tok, new_run["id"]) else 1


if __name__ == "__main__":
    sys.exit(main())
