"""在 GitHub Actions 云端探测指定主机是否可达（仅做 TCP/HTTP 探测，不打印令牌）。

用法：把本文件内容临时作为 workflow 的一个 step 运行，或本地 python tools/cloud_probe_host.py
环境变量 PROBE_URL 默认 https://maas.bit.edu.cn/v1/models
"""
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

url = os.environ.get("PROBE_URL", "https://maas.bit.edu.cn/v1/models")
host = urlparse(url).hostname or ""
print("探测地址:", url)
print("主机名:", host)
try:
    print("DNS 解析:", ", ".join(sorted({a[4][0] for a in socket.getaddrinfo(host, 443)})))
except Exception as e:
    print("DNS 解析失败:", type(e).__name__, str(e)[:200])
try:
    req = urllib.request.Request(url, headers={"User-Agent": "connectivity-probe"})
    with urllib.request.urlopen(req, timeout=20) as r:
        print("HTTP:", r.status)
except urllib.error.HTTPError as e:
    print("HTTP:", e.code, "(能连通，仅认证失败——这正是我们期待的结果)")
except Exception as e:
    print("连接失败:", type(e).__name__, str(e)[:200])
