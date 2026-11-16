# -*- coding: utf-8 -*-
"""页面组装：单文件 HTML。
功能：7模块标签切换、信源筛选/开关面板、新增信源配置生成、原文新页打开、按日期归档。
"""
import html as H
import json
from datetime import datetime
from pathlib import Path

_CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#1c2733;--ink2:#5b6b7c;--line:#e3e8ee;
--acc:#185fa5;--acc2:#0f6e56;--chip:#eef2f7;--warn:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#11151a;--card:#1a2027;--ink:#d8e0e8;
--ink2:#93a1ad;--line:#2a323b;--acc:#7fb1e0;--acc2:#5dcaa5;--chip:#232b33;--warn:#e0a458}}
*{box-sizing:border-box}
html,body{max-width:100%;overflow-x:hidden}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",Roboto,sans-serif}
header{padding:14px 16px 6px;max-width:860px;margin:0 auto;display:flex;align-items:flex-start;gap:10px}
header .tt{flex:1;min-width:0}
h1{font-size:19px;margin:0 0 4px}
.sub{color:var(--ink2);font-size:12.5px}
.btn{border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:16px;
padding:5px 12px;font-size:13px;cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--acc)}
nav{position:sticky;top:0;z-index:9;background:var(--bg);border-bottom:1px solid var(--line);
display:flex;gap:6px;overflow-x:auto;padding:8px 10px;max-width:860px;margin:0 auto}
nav button{flex:0 0 auto;border:1px solid var(--line);background:var(--chip);color:var(--ink);
border-radius:18px;padding:5px 13px;font-size:13px;cursor:pointer}
nav button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
nav button small{opacity:.6;margin-left:2px}
main{max-width:860px;margin:0 auto;padding:12px 12px 60px}
section{display:none}
section.on{display:block}
.cat{margin:14px 4px 6px;font-size:12.5px;color:var(--ink2);display:flex;justify-content:space-between}
.cat a{color:var(--acc);text-decoration:none;font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.card h3{margin:0 0 4px;font-size:16px;font-weight:600;line-height:1.5}
.card h3 a{color:var(--ink);text-decoration:none;overflow-wrap:anywhere;word-break:break-word}
.card h3 a:hover{color:var(--acc)}
.meta{color:var(--ink2);font-size:12px;margin-bottom:6px}
.meta .src{color:var(--acc2);font-weight:600;cursor:pointer;border-bottom:1px dashed transparent}
.meta .src:hover{border-bottom-color:var(--acc2)}
.sum{font-size:14px;color:var(--ink);white-space:pre-wrap;margin:0;
overflow-wrap:anywhere;word-break:break-word}
.badge{display:inline-block;font-size:10.5px;border:1px solid var(--line);color:var(--ink2);
border-radius:8px;padding:0 6px;margin-left:6px;vertical-align:1px}
.badge.warn{color:var(--warn);border-color:var(--warn)}
footer{max-width:860px;margin:0 auto;padding:18px 12px 40px;color:var(--ink2);font-size:12px;line-height:1.7}
footer a{color:var(--acc)}
.empty{padding:40px 10px;text-align:center;color:var(--ink2);font-size:14px}
/* 信源面板 */
#mask{position:fixed;inset:0;background:rgba(0,0,0,.35);display:none;z-index:40}
#mask.on{display:block}
#panel{position:fixed;top:0;right:0;height:100%;width:min(430px,94vw);background:var(--card);
border-left:1px solid var(--line);z-index:41;transform:translateX(102%);transition:transform .22s;
display:flex;flex-direction:column}
#panel.on{transform:none}
#panel header{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line);max-width:none}
#panel header b{font-size:15px;flex:1}
#panel .body{overflow-y:auto;padding:10px 14px 30px;flex:1}
.pgroup{margin:12px 0 4px;font-size:12.5px;color:var(--ink2);font-weight:600}
.prow{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px dashed var(--line);font-size:13.5px}
.prow input{accent-color:var(--acc);width:15px;height:15px}
.prow .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prow .ct{color:var(--ink2);font-size:11.5px}
.prow .only{color:var(--acc);font-size:11.5px;cursor:pointer;background:none;border:none}
.prow.off .nm{color:var(--ink2);text-decoration:line-through}
.tools{display:flex;gap:8px;margin:8px 0}
.addbox{border-top:1px solid var(--line);margin-top:16px;padding-top:12px}
.addbox label{display:block;font-size:12.5px;color:var(--ink2);margin:6px 0 2px}
.addbox input,.addbox select,.addbox textarea{width:100%;padding:6px 8px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--ink);font-size:13px;font-family:inherit}
.addbox textarea{height:110px;font-family:ui-monospace,Consolas,monospace;font-size:12px}
.hint{font-size:12px;color:var(--ink2);line-height:1.6;margin-top:6px}
#filterTip{display:none;max-width:860px;margin:8px auto 0;padding:6px 12px;font-size:12.5px;color:var(--warn)}
#filterTip.on{display:flex;justify-content:space-between;gap:8px}
"""

_JS = r"""
var LS_OFF='digest.srcOff', LS_ONLY='digest.only';
function getOff(){try{return new Set(JSON.parse(localStorage.getItem(LS_OFF)||'[]'))}catch(e){return new Set()}}
function saveOff(s){localStorage.setItem(LS_OFF,JSON.stringify([...s]))}
var off=getOff(), only=localStorage.getItem(LS_ONLY)||'';

function go(m){
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.m===m));
  document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id===m));
  history.replaceState(null,'','#'+m);
  window.scrollTo({top:0});
}
function apply(){
  off=getOff(); if(off.size===0) localStorage.removeItem(LS_OFF);
  only=localStorage.getItem(LS_ONLY)||'';
  var shown={};
  document.querySelectorAll('.card').forEach(function(c){
    var s=c.dataset.src, m=c.dataset.mod;
    var vis = !off.has(s) && (!only || s===only);
    c.style.display = vis?'':'none';
    if(vis) shown[m]=(shown[m]||0)+1;
  });
  document.querySelectorAll('nav button').forEach(function(b){
    var n=shown[b.dataset.m]||0, sm=b.querySelector('small');
    if(sm) sm.textContent=n;
  });
  document.querySelectorAll('section .cat .num').forEach(function(e){
    e.textContent=(shown[e.dataset.m]||0)+' 条';
  });
  document.querySelectorAll('.prow').forEach(function(r){
    var s=r.dataset.src; r.classList.toggle('off', off.has(s));
    var cb=r.querySelector('input'); if(cb) cb.checked=!off.has(s);
  });
  var tip=document.getElementById('filterTip');
  if(only){tip.classList.add('on');document.getElementById('onlyName').textContent=only;}else{tip.classList.remove('on');}
}
function toggleSrc(id,on){var s=getOff(); if(on)s.delete(id); else s.add(id); saveOff(s); apply();}
function onlySrc(id){
  if(localStorage.getItem(LS_ONLY)===id) localStorage.removeItem(LS_ONLY);
  else localStorage.setItem(LS_ONLY,id);
  apply(); closePanel();
}
function clearOnly(){localStorage.removeItem(LS_ONLY);apply();}
function allSrc(ids,on){var s=getOff(); ids.forEach(function(i){on?s.delete(i):s.add(i)}); saveOff(s); apply();}
function openPanel(){document.getElementById('mask').classList.add('on');document.getElementById('panel').classList.add('on');}
function closePanel(){document.getElementById('mask').classList.remove('on');document.getElementById('panel').classList.remove('on');}
function copyText(el){
  var t=document.getElementById(el); t.select(); t.setSelectionRange(0,99999);
  try{navigator.clipboard.writeText(t.value);}catch(e){document.execCommand('copy');}
  var b=document.getElementById('copyTip'); b.textContent='已复制';
  setTimeout(function(){b.textContent='';},1500);
}
function buildSnippet(){
  var nm=document.getElementById('fName').value.trim();
  var url=document.getElementById('fUrl').value.trim();
  var md=document.getElementById('fMod').value;
  if(!url){document.getElementById('fOut').value='请先填网址';return;}
  var id='c-'+url.replace(/^https?:\/\//,'').split('/')[0].replace(/[^a-z0-9]/gi,'-').slice(0,18).toLowerCase();
  var o={id:id,name:nm||id,modules:[md],lang:/[\u4e00-\u9fff]/.test(nm)?'zh':'en',weight:0.8,active:true,
         channel:{type:'auto',home:url}};
  document.getElementById('fOut').value=JSON.stringify(o);
}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closePanel();});
(function(){
  var m=(location.hash||'#m1').slice(1);
  if(location.hash){history.replaceState(null,'',location.pathname+location.search);}
  go(document.getElementById(m)?m:'m1');
  setTimeout(function(){window.scrollTo(0,0);},120);
  apply();
})();
"""

_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>行业资讯简报 · {date}</title>
<style>{css}</style>
</head>
<body>
<header>
  <div class="tt">
    <h1>行业资讯简报</h1>
    <div class="sub">{date} · {time} 自动生成 · 近{win}天 · 共{total}条 · {src_n}个信源</div>
  </div>
  <button class="btn" onclick="openPanel()">信源设置</button>
</header>
<nav>{nav}</nav>
<div id="filterTip">只看信源：<b id="onlyName"></b><a href="javascript:clearOnly()" style="color:var(--acc)">恢复全部</a></div>
<main>{sections}</main>
<footer>
  摘要由大模型自动生成，仅基于各信源公开内容归纳；每条附原文链接，点击新窗口打开，版权归原作者及原发布方所有。<br>
  生成流程：抓取 → 去重 → 排序 → 摘要 → 静态页面。历史归档见 <a href="archive/">archive/</a>。<br>
  “信源设置”里的开关只影响本机浏览显示；新增信源请把生成的配置发给维护者加入 sources.json 后重新生成。
</footer>
<div id="mask" onclick="closePanel()"></div>
<aside id="panel">
  <header><b>信源设置</b><span id="copyTip" style="font-size:12px;color:var(--acc2)"></span>
    <button class="btn" onclick="closePanel()">关闭</button></header>
  <div class="body">
    <div class="hint">勾选=在页面上显示该信源的条目。手机与电脑各自记住自己的选择。</div>
    {panel}
    <div class="addbox">
      <div class="pgroup">添加信源（生成配置）</div>
      <label>名称</label><input id="fName" placeholder="例如：势银能链">
      <label>网址（首页或新闻列表页）</label><input id="fUrl" placeholder="https://...">
      <label>所属模块</label>
      <select id="fMod">{modopts}</select>
      <div class="tools"><button class="btn" onclick="buildSnippet()">生成配置</button>
        <button class="btn" onclick="copyText('fOut')">复制</button></div>
      <textarea id="fOut" readonly placeholder="点上面“生成配置”后，把这段发给维护者即可加入每日抓取"></textarea>
      <div class="hint">抓取规则是“自动发现 RSS → 退回通用列表解析”，多数站点填首页就能用；若是公众号或登录墙内容，需要另配通道。</div>
    </div>
  </div>
</aside>
<script>{js}</script>
</body>
</html>
"""


def _esc(s):
    return H.escape(s or "", quote=True)


def _card(it):
    mode = it.get("summary_mode") or ""
    badge = ""
    if mode in ("placeholder", "failed"):
        badge = '<span class="badge warn">摘要未生成</span>'
    pub = it.get("published_str") or "近日"
    return (f'<div class="card" data-src="{_esc(it["source_id"])}" data-mod="{_esc(it["module"])}">'
            f'<h3><a href="{_esc(it["url"])}" target="_blank" rel="noopener noreferrer">{_esc(it["title"])}</a>{badge}</h3>'
            f'<div class="meta"><span class="src" onclick="onlySrc(\'{_esc(it["source_id"])}\')">{_esc(it["source_name"])}</span>'
            f' · {pub}</div>'
            f'<p class="sum">{_esc(it.get("summary") or "")}</p></div>')


def _panel(module_defs, sources, counts):
    """信源面板：按模块分组列出全部信源（含未启用的），带勾选与“只看”。"""
    out = []
    for m in sorted(module_defs):
        ss = [s for s in sources if m in s.get("modules", [])]
        if not ss:
            continue
        ids = ",".join(f"'{s['id']}'" for s in ss)
        out.append(f'<div class="pgroup" style="display:flex;justify-content:space-between">'
                   f'<span>{_esc(module_defs[m]["name"])}</span>'
                   f'<span><a href="javascript:allSrc([{ids}],true)" style="color:var(--acc);font-size:11.5px">全开</a> '
                   f'<a href="javascript:allSrc([{ids}],false)" style="color:var(--ink2);font-size:11.5px">全关</a></span></div>')
        for s in ss:
            n = counts.get(s["id"], 0)
            tag = "" if s.get("active") else ' <span class="ct">(未启用)</span>'
            out.append(
                f'<div class="prow" data-src="{_esc(s["id"])}">'
                f'<input type="checkbox" onchange="toggleSrc(\'{_esc(s["id"])}\',this.checked)">'
                f'<span class="nm" title="{_esc(s["name"])}">{_esc(s["name"])}{tag}</span>'
                f'<span class="ct">{n}条</span>'
                f'<button class="only" onclick="onlySrc(\'{_esc(s["id"])}\')">只看</button></div>')
    return "\n".join(out)


def build_page(items, module_defs, settings, out_dir, log=print, sources=None):
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    mods = sorted(module_defs.keys())
    counts = {m: 0 for m in mods}
    src_counts = {}
    for it in items:
        counts[it["module"]] = counts.get(it["module"], 0) + 1
        src_counts[it["source_id"]] = src_counts.get(it["source_id"], 0) + 1
    sources = sources or []
    nav = "".join(
        f'<button data-m="{m}" onclick="go(\'{m}\')">{module_defs[m]["name"]}<small>{counts.get(m,0)}</small></button>'
        for m in mods)
    sections = []
    for m in mods:
        cards = [it for it in items if it["module"] == m]
        body = "\n".join(_card(it) for it in cards) or \
            '<div class="empty">该模块今日暂无收录（信源可能未更新或抓取失败，见运行日志）</div>'
        sections.append(f'<section id="{m}"><div class="cat"><span>{module_defs[m]["name"]}</span>'
                        f'<span class="num" data-m="{m}">{len(cards)} 条</span></div>\n{body}</section>')
    modopts = "".join(f'<option value="{m}">{module_defs[m]["name"]}</option>' for m in mods)
    only_active = [s for s in sources if s.get("active")]
    page = _TMPL.format(date=date, time=now.strftime("%H:%M"),
                        win=settings.get("window_days", 3), total=len(items),
                        src_n=len(only_active), css=_CSS, js=_JS, nav=nav,
                        sections="\n".join(sections),
                        panel=_panel(module_defs, sources, src_counts), modopts=modopts)
    out = Path(out_dir)
    (out / "archive").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "archive" / f"{date}.html").write_text(page, encoding="utf-8")
    # 前端可直接读取的数据快照（给二期云端版/检索用）
    (out / "data.json").write_text(json.dumps(
        [{"t": it["title"], "u": it["url"], "s": it["source_name"], "m": it["module"],
          "p": it.get("published_str", ""), "x": it.get("summary", "")} for it in items],
        ensure_ascii=False), encoding="utf-8")
    log(f"  页面已生成: {out}/index.html（{len(items)}条，归档 archive/{date}.html）")
    return str(out / "index.html")
