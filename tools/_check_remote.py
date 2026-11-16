# -*- coding: utf-8 -*-
"""从 GitHub API 读取远端 main 的最新数据文件，统计云端运行结果。"""
import json, subprocess, urllib.request, base64, base64, collections


def get_token():
    r = subprocess.run(["bash", "-c",
        'printf "protocol=https\\nhost=github.com\\n\\n" | git credential fill 2>/dev/null'
        ' | grep "^password=" | cut -d= -f2'],
        capture_output=True, text=True)
    return r.stdout.strip()


def api(path, retries=5):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request("https://api.github.com" + path,
                headers={"Authorization": f"Bearer {TOKEN}",
                         "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            import time; time.sleep(3)
    raise last


TOKEN = get_token()
if not TOKEN:
    sys.exit("no token")

# 最新提交
commits = api("/repos/BITliyujing/news-digest/commits?per_page=3")
print("最近提交:", [c["commit"]["message"][:40] for c in commits])

# 读云端文件内容
def content(path):
    d = api(f"/repos/BITliyujing/news-digest/contents/{path}?ref=main")
    return json.loads(base64.b64decode(d["content"]).decode("utf-8"))

items = content("data/processed_2026-11-16.json")
modes = collections.Counter(i.get("summary_mode", "") for i in items)
print("条目:", len(items), "| 摘要模式:", dict(modes))
ai = [i for i in items if i.get("summary_mode", "").startswith("glm")]
if ai:
    print("\nAI摘要样例:")
    for i in ai[:2]:
        print(f"  [{i['source_name']}] {i['title'][:36]}")
        print("   ", (i.get("summary") or "")[:120])

