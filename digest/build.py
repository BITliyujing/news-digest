# -*- coding: utf-8 -*-
"""页面组装：单文件 HTML。
功能：模块标签切换（多行）、信源筛选/开关面板、重要度/时间排序切换、回到顶部、
      原文新页打开、按日期归档。暖色护眼配色，全内联零外链。
"""
import html as H
import json
from datetime import datetime
from pathlib import Path

_CSS = """
:root{
  --bg:#f7f3ec;--bg2:#efe7d9;--card:#fffdfa;--ink:#33302b;--ink2:#7a736a;
  --line:#e9e1d5;--acc:#a8562f;--acc-soft:#f6e9df;--acc2:#5c7a52;
  --chip:#f1eadd;--warn:#b4471f;--warn-soft:#fbe9df;
  --shadow:0 1px 2px rgba(80,60,35,.05),0 6px 18px rgba(80,60,35,.055);
  --shadow-h:0 2px 5px rgba(80,60,35,.08),0 12px 28px rgba(80,60,35,.09)
}
*{box-sizing:border-box}
html,body{max-width:100%;overflow-x:hidden}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
/* 顶部暖色装饰条 */
.topbar{height:4px;background:linear-gradient(90deg,var(--acc) 0%,#d08a5a 48%,var(--acc2) 100%)}
header{padding:16px 16px 8px;max-width:900px;margin:0 auto;display:flex;align-items:flex-start;gap:10px}
header .tt{flex:1;min-width:0}
h1{font-size:20px;margin:0 0 3px;font-weight:700;letter-spacing:.3px}
.sub{color:var(--ink2);font-size:12.5px}
.btn{border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:16px;
 padding:6px 13px;font-size:13px;cursor:pointer;white-space:nowrap;min-height:34px}
.btn:hover{border-color:var(--acc);color:var(--acc)}
/* 模块导航：多行 wrap，不用横向拖动 */
nav{position:sticky;top:0;z-index:9;background:rgba(247,243,236,.96);backdrop-filter:blur(8px);
 border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:7px;padding:10px 14px;max-width:900px;margin:0 auto}
nav button{flex:0 1 auto;border:1px solid var(--line);background:var(--card);color:var(--ink);
 border-radius:18px;padding:7px 14px;font-size:13px;cursor:pointer;min-height:36px;line-height:1.4;
 box-shadow:0 1px 1px rgba(80,60,35,.03)}
nav button:hover{border-color:var(--acc)}
nav button.on{background:var(--acc);color:#fff;border-color:var(--acc);box-shadow:0 3px 10px rgba(168,86,47,.25)}
nav button small{opacity:.72;margin-left:5px;font-size:11px}
.bar{max-width:900px;margin:9px auto 0;padding:0 14px;display:flex;justify-content:space-between;
 align-items:center;gap:10px;flex-wrap:wrap}
.bar .hint{color:var(--ink2);font-size:12px}
.sortgrp{display:flex;gap:6px;align-items:center}
.sortbtn{border:1px solid var(--line);background:var(--card);color:var(--ink2);border-radius:16px;
 padding:5px 12px;font-size:12.5px;cursor:pointer;min-height:32px}
.sortbtn.on{background:var(--acc-soft);color:var(--acc);border-color:var(--acc);font-weight:600}
main{max-width:900px;margin:0 auto;padding:10px 14px 70px}
section{display:none}
section.on{display:block}
.cat{margin:18px 4px 9px;font-size:12.5px;color:var(--ink2);display:flex;justify-content:space-between;
 border-left:3px solid var(--acc);padding-left:9px}
.cat a{color:var(--acc);text-decoration:none;font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
 margin-bottom:11px;box-shadow:var(--shadow);transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease}
.card:hover{transform:translateY(-2px);box-shadow:var(--shadow-h);border-color:#dcc9b6}
.card.hi{border-left:4px solid var(--warn);background:linear-gradient(90deg,#fdf3ec,var(--card) 60px)}
.card h3{margin:0 0 5px;font-size:16px;font-weight:650;line-height:1.55}
.card h3 a{color:var(--ink);text-decoration:none;overflow-wrap:anywhere;word-break:break-word}
.card h3 a:hover{color:var(--acc)}
.meta{color:var(--ink2);font-size:12px;margin-bottom:7px}
.meta .src{color:var(--acc2);font-weight:600;cursor:pointer;border-bottom:1px dashed transparent}
.meta .src:hover{border-bottom-color:var(--acc2)}
.sum{font-size:14px;color:var(--ink);white-space:pre-wrap;margin:0;line-height:1.85;
 overflow-wrap:anywhere;word-break:break-word}
.badge{display:inline-block;font-size:10.5px;border:1px solid var(--line);color:var(--ink2);
 border-radius:8px;padding:0 6px;margin-left:6px;vertical-align:1px}
.badge.warn{color:var(--warn);border-color:var(--warn);background:var(--warn-soft)}
.imp{display:inline-block;font-size:10.5px;border:1px solid var(--line);color:var(--ink2);
 border-radius:8px;padding:0 7px;margin-left:6px;vertical-align:1px}
.imp.high{color:var(--warn);border-color:var(--warn);background:var(--warn-soft)}
.imp.mid{color:var(--acc);border-color:var(--acc);background:var(--acc-soft)}
footer{max-width:900px;margin:0 auto;padding:18px 14px 40px;color:var(--ink2);font-size:12px;line-height:1.75;
 border-top:1px solid var(--line)}
footer a{color:var(--acc)}
.empty{padding:40px 10px;text-align:center;color:var(--ink2);font-size:14px}
/* 回到顶部 */
#toTop{position:fixed;right:20px;bottom:calc(24px + env(safe-area-inset-bottom));width:46px;height:46px;
 border-radius:50%;border:1px solid var(--line);background:var(--card);color:var(--acc);cursor:pointer;
 display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow-h);
 opacity:0;visibility:hidden;transform:translateY(10px);transition:opacity .2s,transform .2s,visibility .2s;z-index:30}
#toTop.on{opacity:1;visibility:visible;transform:none}
#toTop:hover{background:var(--acc);color:#fff}
#toTop svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
/* 信源面板 */
#mask{position:fixed;inset:0;background:rgba(60,45,30,.38);display:none;z-index:40}
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
.prow .only{color:var(--acc);font-size:11.5px;cursor:pointer;background:none;border:none;min-height:auto;padding:2px 4px}
.prow.off .nm{color:var(--ink2);text-decoration:line-through}
.tools{display:flex;gap:8px;margin:8px 0}
.addbox{border-top:1px solid var(--line);margin-top:16px;padding-top:12px}
.addbox label{display:block;font-size:12.5px;color:var(--ink2);margin:6px 0 2px}
.addbox input,.addbox select,.addbox textarea{width:100%;padding:8px;border:1px solid var(--line);
 border-radius:8px;background:var(--bg);color:var(--ink);font-size:16px;font-family:inherit}
.addbox textarea{height:110px;font-family:ui-monospace,Consolas,monospace;font-size:12px}
.hint{font-size:12px;color:var(--ink2);line-height:1.6;margin-top:6px}
#filterTip{display:none;max-width:900px;margin:8px auto 0;padding:6px 14px;font-size:12.5px;color:var(--warn)}
#filterTip.on{display:flex;justify-content:space-between;gap:8px}
@media(max-width:600px){
 header{padding:14px 12px 6px}
 h1{font-size:18px}
 .sub{font-size:12px}
 nav{padding:9px 10px;gap:6px}
 nav button{padding:7px 12px;font-size:12.5px}
 main{padding:8px 10px 70px}
 .card{padding:12px 13px}
 .card h3{font-size:15px}
 .sum{font-size:13.5px}
 .bar{padding:0 10px}
}
"""

_JS = r"""
var LS_OFF='digest.srcOff', LS_ONLY='digest.only', LS_SORT='digest.sort';
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
/* 排序：imp=重要度优先，new=最新优先。只重排 DOM，不与 go/apply 互相调用 */
function sortCards(mode){
  document.querySelectorAll('section').forEach(function(sec){
    var cards=[].slice.call(sec.querySelectorAll('.card'));
    cards.sort(function(a,b){
      var ta=parseInt(a.dataset.ts)||0, tb=parseInt(b.dataset.ts)||0;
      if(mode==='new') return tb-ta;
      var d=(parseInt(b.dataset.imp)||3)-(parseInt(a.dataset.imp)||3);
      return d?d:(tb-ta);
    });
    cards.forEach(function(c){sec.appendChild(c)});
  });
}
function setSort(mode){
  var cur=mode||localStorage.getItem(LS_SORT)||'imp';
  try{localStorage.setItem(LS_SORT,cur)}catch(e){}
  document.querySelectorAll('.sortbtn').forEach(function(b){b.classList.toggle('on',b.dataset.s===cur)});
  sortCards(cur);
}
/* 回到顶部按钮显隐 */
function onScroll(){
  var y=window.scrollY||document.documentElement.scrollTop||0;
  var b=document.getElementById('toTop');
  if(b) b.classList.toggle('on',y>360);
}
function scrollTop(){window.scrollTo({top:0,behavior:'smooth'});}

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
window.addEventListener('scroll',onScroll,{passive:true});
(function(){
  var m=(location.hash||'#m1').slice(1);
  if(location.hash){history.replaceState(null,'',location.pathname+location.search);}
  go(document.getElementById(m)?m:'m1');
  setSort();
  apply();
  onScroll();
  setTimeout(function(){window.scrollTo(0,0);onScroll();},120);
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
<div class="topbar"></div>
<header>
  <div class="tt">
    <h1>行业资讯简报</h1>
    <div class="sub">{date} · {time} 自动生成 · {win} · 共{total}条 · {src_n}个信源</div>
  </div>
  <button class="btn" onclick="openPanel()">信源设置</button>
</header>
<nav>{nav}</nav>
<div class="bar">
  <span class="hint">默认按重要度从高到低排列</span>
  <span class="sortgrp">
    <button class="sortbtn" data-s="imp" onclick="setSort('imp')">重要度优先</button>
    <button class="sortbtn" data-s="new" onclick="setSort('new')">最新优先</button>
  </span>
</div>
<div id="filterTip">只看信源：<b id="onlyName"></b><a href="javascript:clearOnly()" style="color:var(--acc)">恢复全部</a></div>
<main>{sections}</main>
<footer>
  摘要由大模型自动生成，仅基于各信源公开内容归纳；每条附原文链接，点击新窗口打开，版权归原作者及原发布方所有。<br>
  生成流程：抓取 → 去重 → 排序 → 摘要 → 静态页面。历史归档见 <a href="archive/">archive/</a>。<br>
  “信源设置”里的开关只影响本机浏览显示；新增信源请把生成的配置发给维护者加入 sources.json 后重新生成。
</footer>
<button id="toTop" aria-label="回到顶部" onclick="scrollTop()">
  <svg viewBox="0 0 24 24"><path d="M12 19V6M6 12l6-6 6 6"/></svg>
</button>
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
    imp = it.get("importance")
    try:
        imp = int(imp) if imp is not None else None
    except (TypeError, ValueError):
        imp = None
    cat = (it.get("category") or "").strip()
    imp_badge = ""
    # 默认 3 分（dry 运行 / 旧缓存 / 摘要降级）不显示，避免满屏无意义的"重要度3"
    if cat or (imp and imp >= 4):
        label = (cat + " · " if cat else "") + f"重要度{imp}"
        cls = "imp high" if imp and imp >= 4 else "imp mid"
        imp_badge = f'<span class="{cls}">{_esc(label)}</span>'
    imp_v = imp if imp is not None else 3
    hi = " hi" if imp and imp >= 4 else ""
    # 排序用：published 是 datetime；无日期用 0（排最后）
    pubdt = it.get("published")
    if pubdt is not None:
        try:
            ts = int(pubdt.timestamp())
        except Exception:
            ts = 0
    else:
        ts = 0
    return (f'<div class="card{hi}" data-src="{_esc(it["source_id"])}" data-mod="{_esc(it["module"])}" '
            f'data-imp="{imp_v}" data-ts="{ts}">'
            f'<h3><a href="{_esc(it["url"])}" target="_blank" rel="noopener noreferrer">{_esc(it["title"])}</a>{badge}</h3>'
            f'<div class="meta"><span class="src" onclick="onlySrc(\'{_esc(it["source_id"])}\')">{_esc(it["source_name"])}</span>'
            f' · {pub}{imp_badge}</div>'
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


def _imp_key(it):
    """卡片排序：重要度降序 → 时间降序。与 run_daily 的 final_score 排序兼容
    （final_score 本就以重要度为主，这里再按重要度显式归组，保证页面观感一致）。"""
    try:
        imp = int(it.get("importance")) if it.get("importance") is not None else 3
    except (TypeError, ValueError):
        imp = 3
    pub = it.get("published")
    try:
        ts = pub.timestamp() if pub is not None else 0
    except Exception:
        ts = 0
    return (-imp, -ts)


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
        cards = sorted(cards, key=_imp_key)  # 重要度优先排序
        body = "\n".join(_card(it) for it in cards) or \
            '<div class="empty">该模块今日暂无收录（信源可能未更新或抓取失败，见运行日志）</div>'
        sections.append(f'<section id="{m}"><div class="cat"><span>{module_defs[m]["name"]}</span>'
                        f'<span class="num" data-m="{m}">{len(cards)} 条</span></div>\n{body}</section>')
    modopts = "".join(f'<option value="{m}">{module_defs[m]["name"]}</option>' for m in mods)
    only_active = [s for s in sources if s.get("active")]
    page = _TMPL.format(date=date, time=now.strftime("%H:%M"),
                        win=("近24小时" if int(settings.get("window_days", 1)) == 1
                             else f"近{settings.get('window_days')}天"), total=len(items),
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
          "p": it.get("published_str", ""), "x": it.get("summary", ""),
          "i": it.get("importance", 3), "c": it.get("category", "")} for it in items],
        ensure_ascii=False), encoding="utf-8")
    log(f"  页面已生成: {out}/index.html（{len(items)}条，归档 archive/{date}.html）")
    return str(out / "index.html")
