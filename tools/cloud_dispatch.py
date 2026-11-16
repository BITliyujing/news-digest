# -*- coding: utf-8 -*-
"""触发云端简报运行并验证结果。

凭据从 Windows Git 凭据管理器读取（与 push_via_api.py 同源），不写入任何文件。

用法：
  python tools/cloud_dispatch.py                 # 触发一次 + 等待完成 + 打印关键日志
  python tools/cloud_dispatch.py --no-watch      # 只触发，不等待
  python tools/cloud_dispatch.py --run-id 123    # 跟踪已有运行
"""
import argparse
import io
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

API = "https://api.github.com/repos/BITliyujing/news-digest"
WORKFLOW = "daily-digest.yml"
UA = {"User-Agent": "news-digest-cloud-check",
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"}


def get_token():
    r = subprocess.run(
        ["bash", "-c",
         'printf "protocol=https\\nhost=github.com\\n\\n" | git credential fill 2>/dev/null'
         ' | grep "^password=" | cut -d= -f2'],
        capture_output=True, text=True)
    tok = r.stdout.strip()
    if not tok:
        sys.exit("拿不到 GitHub 凭据：请先成功 git push 一次")
    return tok


def api(tok, path, data=None, method=None, timeout=40):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(API + path, data=body, method=method,
                                 headers={**UA, "Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"message": e.read().decode("utf-8", "ignore")[:200]}
    except Exception as e:
        return 0, {"message": str(e)[:200]}


def dispatch(tok):
    status, res = api(tok, f"/actions/workflows/{WORKFLOW}/dispatches",
                      {"ref": "main"}, method="POST")
    if status != 204:
        sys.exit(f"触发失败：HTTP {status} {res}")
    print(f"已触发云端运行（workflow: {WORKFLOW}, ref: main）", flush=True)


def latest_dispatch_run(tok):
    status, res = api(tok, "/actions/runs?per_page=10")
    if status != 200:
        sys.exit(f"查询运行失败：HTTP {status} {res}")
    for run in res.get("workflow_runs", []):
        if run.get("event") == "workflow_dispatch":
            return run
    return None


def watch(tok, run_id, max_minutes=45):
    deadline = time.time() + max_minutes * 60
    last = ""
    while time.time() < deadline:
        status, run = api(tok, f"/actions/runs/{run_id}")
        if status != 200:
            print(f"  查询失败 HTTP {status}，稍后重试", flush=True)
            time.sleep(30)
            continue
        state = f"{run.get('status')}/{run.get('conclusion') or ''}"
        if state != last:
            print(f"  运行状态：{state}", flush=True)
            last = state
        if run.get("status") == "completed":
            conclusion = run.get("conclusion")
            print(f"运行结束：{conclusion}", flush=True)
            print(f"页面：{run.get('html_url')}", flush=True)
            show_steps(tok, run_id)
            show_log(tok, run_id)
            return conclusion == "success"
        time.sleep(30)
    print("等待超时，请到 GitHub Actions 页面查看", flush=True)
    return False


def show_steps(tok, run_id):
    status, data = api(tok, f"/actions/runs/{run_id}/jobs")
    if status != 200:
        return
    for job in data.get("jobs", []):
        print(f"  Job {job.get('name')}: {job.get('conclusion')}", flush=True)
        for step in job.get("steps", []):
            if step.get("conclusion") not in (None, "skipped"):
                print(f"    - {step.get('name')}: {step.get('conclusion')}", flush=True)


def show_log(tok, run_id):
    """拉取运行日志，打印关键行。失败时静默跳过，不影响主流程。"""
    try:
        req = urllib.request.Request(
            API + f"/actions/runs/{run_id}/logs",
            headers={**UA, "Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        z = zipfile.ZipFile(io.BytesIO(raw))
        lines = []
        for name in z.namelist():
            if name.endswith(".txt"):
                lines.extend(z.read(name).decode("utf-8", "ignore").splitlines())
        keys = ("启用信源", "处理后候选", "正文抓取完成", "摘要：", "批量完成",
                "摘要完成", "重要度重排完成", "页面已生成", "疑似不健康信源", "DONE")
        hits = [ln for ln in lines if any(k in ln for k in keys)]
        print("  ---- 运行日志关键行 ----", flush=True)
        for ln in hits[-25:]:
            print("  " + ln[:180], flush=True)
    except Exception as e:
        print(f"  （日志获取跳过：{str(e)[:100]}）", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-watch", action="store_true")
    ap.add_argument("--run-id", type=int)
    args = ap.parse_args()

    tok = get_token()
    rid = args.run_id
    if rid is None:
        dispatch(tok)
        time.sleep(8)
        run = latest_dispatch_run(tok)
        if not run:
            sys.exit("没找到刚触发的运行，请稍后用 --run-id 跟踪")
        rid = run["id"]
        print(f"运行编号：{rid}", flush=True)
    if not args.no_watch:
        sys.exit(0 if watch(tok, rid) else 1)
