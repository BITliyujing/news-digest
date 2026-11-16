# -*- coding: utf-8 -*-
"""HTTP 工具：带超时/UA/编码自适应/重试的抓取。全部标准库，无第三方依赖。"""
import gzip, ssl, time, urllib.request, urllib.error, urllib.parse

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_last_ts = 0.0


def _polite(sleep):
    global _last_ts
    if sleep and _last_ts:
        dt = sleep - (time.time() - _last_ts)
        if dt > 0:
            time.sleep(dt)
    _last_ts = time.time()


def fetch(url, settings, referer=None, timeout=None, accept="*/*",
          read_bytes=400000, sleep=None, extra_headers=None):
    """GET 一个 URL，返回 (status, bytes)。
    尝试顺序：直连(标准UA) → 直连(curl UA) → 系统代理；404 不重试。"""
    _polite(sleep if sleep is not None else settings.get("politeness_sleep", 0.6))
    if any(ord(c) > 127 for c in url):
        url = urllib.parse.quote(url, safe=":/?&=%+@,;,$-_.!~*'()")
    tmo = timeout or settings.get("http_timeout", 25)

    def _headers(ua):
        h = {"User-Agent": ua, "Accept": accept,
             "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
             "Accept-Encoding": "gzip, deflate"}
        if referer:
            h["Referer"] = referer
        if extra_headers:
            h.update(extra_headers)
        return h

    def _opener(proxy_map):
        hd = [urllib.request.ProxyHandler(proxy_map), urllib.request.HTTPSHandler(context=_CTX)]
        return urllib.request.build_opener(*hd)

    if settings.get("proxy"):
        attempts = [(_opener({"http": settings["proxy"], "https": settings["proxy"]}), _headers(_UA)),
                    (_opener({"http": settings["proxy"], "https": settings["proxy"]}), _headers("curl/8.4.0"))]
    else:
        attempts = [(_opener({}), _headers(_UA)), (_opener({}), _headers("curl/8.4.0"))]
        sysproxies = urllib.request.getproxies()
        if sysproxies:
            attempts.append((_opener(sysproxies), _headers(_UA)))

    last_exc = None
    if settings.get("http_fast"):
        attempts = attempts[:1]
    for i, (opener, headers) in enumerate(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=tmo) as r:
                raw = r.read(read_bytes)
            if raw[:2] == b"\x1f\x8b":
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
            return r.status, raw
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code == 404:
                raise
            time.sleep(1)
        except Exception as e:
            last_exc = e
            time.sleep(1)
    # 全部常规通道失败后，尝试本机常见代理端口（Clash/V2Ray 等默认端口）
    if (last_exc is not None and settings.get("auto_proxy", True)
            and not settings.get("proxy") and not settings.get("http_fast")):
        for port in settings.get("auto_proxy_ports", [7890, 7897, 10809, 1080]):
            px = f"http://127.0.0.1:{port}"
            try:
                req = urllib.request.Request(url, headers=_headers(_UA))
                with _opener({"http": px, "https": px}).open(req, timeout=min(tmo, 12)) as r:
                    raw = r.read(read_bytes)
                if raw[:2] == b"\x1f\x8b":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        pass
                return r.status, raw
            except Exception:
                continue
    raise last_exc


def decode_html(raw):
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def absolutize(href, base):
    href = href.strip()
    if href.startswith("./"):
        href = href[2:]
    return urllib.parse.urljoin(base, href)
