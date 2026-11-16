# -*- coding: utf-8 -*-
"""API 推送通道：当 git push 走不通（代理隧道 502 / 连接重置）时的备用方案。
原理：api.github.com 在国内通常比 github.com 主站稳定得多，
通过 Git Data API（blob → tree → commit → ref）把本地 HEAD 与 origin/main 的差异推上去。

用法：
  python tools/push_via_api.py                 # 推送本地领先 origin/main 的全部提交内容
  python tools/push_via_api.py -m "消息" -- path1 path2   # 只推指定文件（工作区内容）

注意：走 API 推送后本地 origin/main 引用不会自动更新（fetch 也要网络），
脚本会用 git update-ref 手动对齐，等网络恢复后 fetch 验证即可。
"""
import argparse, base64, json, subprocess, sys, urllib.request, os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPO_API = "https://api.github.com/repos/BITliyujing/news-digest"
UA = {"User-Agent": "news-digest-push", "Accept": "application/vnd.github+json",
      "Content-Type": "application/json"}


def get_token():
    r = subprocess.run(["bash", "-c",
        'printf "protocol=https\\nhost=github.com\\n\\n" | git credential fill 2>/dev/null'
        ' | grep "^password=" | cut -d= -f2'],
        capture_output=True, text=True)
    tok = r.stdout.strip()
    if not tok:
        sys.exit("拿不到 GitHub 凭据：请先成功 git push 一次让 Windows 凭据管理器存下令牌")
    return tok


def api(tok, path, data=None, method=None, retries=4):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(REPO_API + path,
                data=json.dumps(data).encode() if data else None, method=method,
                headers={**UA, "Authorization": f"Bearer {tok}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode()
                return r.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as e:
            return e.code, {}
        except Exception as e:
            last = e
    sys.exit(f"API 不通（重试{retries}次）: {last}")


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          cwd=str(BASE)).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", default=None)
    ap.add_argument("--paths", nargs="*", default=[])
    args = ap.parse_args()
    tok = get_token()

    # 远端 main 当前 sha
    st, ref = api(tok, "/git/ref/heads/main")
    remote_sha = ref["object"]["sha"]

    if args.paths:
        # 指定文件模式：直接以工作区内容创建新提交
        files = args.paths
        message = args.message or "update files via API"
    else:
        # 差异模式：找本地 HEAD 领先远端的提交，取其差异文件与提交信息
        local_sha = sh("git rev-parse HEAD")
        if local_sha == remote_sha:
            print("无领先提交，无需推送")
            return
        files = sh(f"git diff --name-only {remote_sha}..HEAD").split("\n")
        files = [f for f in files if f.strip()]
        message = args.message or sh(
            f'git log --format=%B -n1 {local_sha}').split("\n")[0] or "via API"

    # 基础 tree
    st, commit = api(tok, f"/git/commits/{remote_sha}")
    base_tree = commit["tree"]["sha"]

    # 建 blobs + tree
    tree = []
    for f in files:
        p = BASE / f
        if not p.exists():
            print(f"跳过不存在文件: {f}")
            continue
        blob = base64.b64encode(p.read_bytes()).decode()
        st, b = api(tok, "/git/blobs", {"content": blob, "encoding": "base64"})
        tree.append({"path": f, "mode": "100644", "type": "blob", "sha": b["sha"]})
    if not tree:
        sys.exit("没有可推送的文件")
    st, t = api(tok, "/git/trees", {"base_tree": base_tree, "tree": tree})

    # 建提交并移动引用
    st, c = api(tok, "/git/commits",
                {"message": message, "tree": t["sha"], "parents": [remote_sha]})
    st, _ = api(tok, "/git/refs/heads/main",
                {"sha": c["sha"], "force": False}, method="PATCH")
    if st != 200:
        sys.exit(f"ref 更新失败 HTTP {st}（远端可能有新提交，先 git pull）")
    print(f"API 推送成功: {c['sha'][:9]} {message[:60]}")
    # 对齐本地 remote-tracking 引用
    sh(f"git update-ref refs/remotes/origin/main {c['sha']}")
    print("本地 origin/main 引用已对齐（网络恢复后可 git fetch 校验）")


if __name__ == "__main__":
    main()
