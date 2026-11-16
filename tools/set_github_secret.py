# -*- coding: utf-8 -*-
"""把本地令牌写入 GitHub Actions Secrets（用于云端多模型备胎）。

凭据来源：
  - GitHub 操作令牌：Windows Git 凭据管理器（需有 Secrets 写权限）
  - 待写入的令牌：本地文件（必须已被 .gitignore 忽略）

用法：
  python tools/set_github_secret.py MODELSCOPE_API_KEY digest/ms_api_key.txt

注意：脚本不会打印任何令牌内容。
"""
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from nacl.public import PublicKey, SealedBox

REPO = "https://api.github.com/repos/BITliyujing/news-digest"
UA = {"User-Agent": "news-digest-secret-setter",
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"}


def git_token():
    r = subprocess.run(
        ["bash", "-c",
         'printf "protocol=https\\nhost=github.com\\n\\n" | git credential fill 2>/dev/null'
         ' | grep "^password=" | cut -d= -f2'],
        capture_output=True, text=True)
    tok = r.stdout.strip()
    if not tok:
        sys.exit("拿不到 GitHub 操作令牌")
    return tok


def api(tok, path, data=None, method=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(REPO + path, data=body, method=method,
                                 headers={**UA, "Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"message": e.read().decode("utf-8", "ignore")[:300]}
    except Exception as e:
        return 0, {"message": str(e)[:300]}


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    name, key_file = sys.argv[1], sys.argv[2]
    p = Path(key_file)
    if not p.exists():
        sys.exit(f"令牌文件不存在：{key_file}")
    value = p.read_text(encoding="utf-8").strip()
    if not value:
        sys.exit("令牌文件为空")
    # 安全检查：拒绝把未被 git 忽略的令牌文件推到云端密钥以外的任何地方
    ignored = subprocess.run(["git", "check-ignore", "-q", key_file],
                             capture_output=True).returncode == 0
    if not ignored:
        sys.exit(f"拒绝处理：{key_file} 未被 .gitignore 忽略")

    tok = git_token()
    st, pub = api(tok, "/actions/secrets/public-key")
    if st != 200:
        sys.exit(f"读取公钥失败：HTTP {st} {pub}")
    sealed = SealedBox(PublicKey(base64.b64decode(pub["key"]))).encrypt(value.encode())
    st, res = api(tok, f"/actions/secrets/{name}",
                  {"encrypted_value": base64.b64encode(sealed).decode(),
                   "key_id": pub["key_id"]}, method="PUT")
    if st not in (201, 204):
        sys.exit(f"写入密钥失败：HTTP {st} {res}")
    print(f"云端密钥 {name} 已写入（来源：{key_file}，长度 {len(value)}）")

    st, meta = api(tok, "/actions/secrets")
    names = [x["name"] for x in meta.get("secrets", [])] if st == 200 else []
    print("云端现有密钥：" + ", ".join(names))


if __name__ == "__main__":
    main()
