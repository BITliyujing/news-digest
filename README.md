# 行业资讯简报工具（方案A：定时生成静态页 → 随时随地打开）

每天定时抓取 7 个门类的核心信源，去重排序后生成约 300 字中文摘要，输出一个手机自适应单页 HTML。
打开即看，可按模块切换、按信源筛选；每条附原文链接。

---

## 一、目录结构

```
资讯工具/
├─ run_daily.py            主程序（抓取→处理→摘要→生成页面）
├─ sources.json            信源清单与通道配置（可手工增删）
├─ settings.json           参数（时间窗、条数、模型、并发等）
├─ digest/                 核心模块
│  ├─ http.py              抓取层（直连/curl UA/系统代理/本机代理端口自动回退）
│  ├─ fetchers.py          通道适配：rss / sitemap / scrape / api / rsshub / auto
│  ├─ pipeline.py          模块路由、时间窗、去重、关键词排序、配额
│  ├─ summarize.py         摘要层（多模型供应商自动切换）
│  └─ build.py             页面生成（模块标签、信源面板、归档）
├─ tools/
│  ├─ probe_sources.py     批量探测信源可用性
│  ├─ build_sources.py     把探测结果并入 sources.json
│  └─ test_importance.py   重要度标签回归测试（--live 可真实调用一次）
├─ cloud/                  云端运行（电脑关机也能出简报）
├─ output/                 index.html + archive/ 按日归档 + data.json
├─ data/                   当日结构化数据、去重记忆、发现的RSS
└─ logs/                   运行日志、信源健康记录
```

---

## 二、本地怎么跑

```bash
cd "D:/Personal&Family/量化投资相关/学习资料/行业资讯更新/资讯工具"
"D:/Program Files/Python314/python.exe" run_daily.py                 # 完整运行（有Key就自动摘要）
"D:/Program Files/Python314/python.exe" run_daily.py --dry           # 不调模型，验证链路
"D:/Program Files/Python314/python.exe" run_daily.py --only m1 m3    # 只跑指定模块
```

零第三方依赖，只用 Python 标准库。

---

## 三、摘要模型（token 从这里走）

配置在 `settings.json` 的 `llm.providers`，按顺序尝试，前一个不可用自动换下一个。
Key 放文件（`digest/*.txt`）或环境变量均可。

| 供应商 | 现状 | 获取方式 |
|---|---|---|
| **智谱 GLM**（glm-4.7-flash / glm-4.5-flash） | **目前仍免费**，无 token 总量上限 | open.bigmodel.cn 手机号注册 → 创建 API Key → 存 `digest/glm_api_key.txt` |
| 魔搭 ModelScope | 免费层按「魔粒」计费（每日约 250 粒，主流模型约 2 粒/次，约 125 次/天）；**需绑定阿里云账号并完成实名认证**；含 GLM-4.7-Flash / Qwen3.8-Flash-Next | modelscope.cn → 访问令牌（ms-…）→ `digest/ms_api_key.txt` |
| DeepSeek | 付费备胎，约 ¥1-4/天 | platform.deepseek.com → `digest/deepseek_api_key.txt` |
| 硅基流动 | 部分小模型免费 | siliconflow.cn → `digest/siliconflow_api_key.txt` |

说明：
- 抓取、去重、排序、页面生成都在本地完成，**不消耗 token**；token 只花在“写 300 字摘要”。
- **批量摘要**（默认 `llm.batch_size=5`）：5 条资讯合并进一次请求，模型按 `<<<序号>>>` 分节输出，再拆回各条。请求数降到 1/5，是绕开免费档“每分钟约 5 次”限流的关键；拆不出来的个别条目再用单条模式补（`llm.repair_max`，默认最多 24 条）。
- 摘要按 URL 缓存 30 天（`data/summary_cache.json`），窗口内重复出现的旧条目不重复请求。
- 全部 Key 都没有时页面仍会生成，摘要降级为正文前 300 字截取，并标注“摘要未生成”。
- 批并发默认 2（`llm.concurrency`），全局限速 `llm.min_interval_seconds=12`（免费档实测约 5 次/分钟），并发开太大只会换来 429。

### 重要度排序（两段式）

- **粗筛（本地、不花 token）**：关键词命中数 × 信源权重 × 时效，决定哪些条目有资格进摘要队列；`sources.json` 里为 7 个模块都配了中英文关键词，英文按词边界匹配（避免 `rate` 命中 `corporate`）。
- **精排（模型、几乎不增加 token）**：批量摘要时顺带让模型给每条打「重要度 1-5 + 类别（政策/融资/技术/市场/动态/观点/人事/其他）」，模型看过正文后判断，决定页面上的先后顺序。这一步能把“中央政策”排到“常规论文”前面——关键词分做不到。
- 权重可在 `settings.json` 的 `rerank_keyword_weight`（默认 0.3）与 `rerank_importance_weight`（默认 2.0）调整。元数据在解析时剥离，不会出现在摘要正文里，但会随摘要一起缓存复用。
- 未评分条目（dry 运行 / 旧缓存 / 摘要降级）默认 3 分，页面不显示徽章，不会报错。
- 改过 prompt 或解析规则后跑 `python tools/test_importance.py` 回归；加 `--live` 会真实调用一次模型确认输出可解析。

---

## 四、页面功能

- **7 个模块标签**：顶部横滑切换，URL 锚点记住上次位置。
- **重要度徽章**：卡片上显示模型判定的类别与重要度（高分标橙色）。
- **信源设置面板**（右上角按钮）：
  - 按模块列出全部信源，勾选/取消即在本机隐藏该信源条目（手机、电脑各记各的）；
  - “只看”按钮：只看单条信源，页面上方出现恢复入口；点卡片里的信源名等价；
  - “添加信源”：填名称/网址/模块 → 生成 JSON 配置，复制发给维护者即可加入每日抓取。
- **归档**：`output/archive/YYYY-MM-DD.html` 保留每日快照。

---

## 五、云端运行（电脑关机也能更新 + 手机随时看）

详细操作见 `cloud/SETUP-STEPS.md`（6 步，约 20 分钟）。要点：
- GitHub Actions 每天北京时间 07:00 跑一次，产物发布到 GitHub Pages，得到一个可分享网址；
- **本地 Key 文件不会自动同步到云端**（`.gitignore` 已忽略，避免令牌泄露）。要把新令牌同步到云端密钥，运行 `python tools/set_github_secret.py MODELSCOPE_API_KEY digest/ms_api_key.txt`（换其他供应商时替换密钥名和文件名即可）；云端密钥列表可在 GitHub 仓库 Settings → Secrets and variables → Actions 查看；
- 手机浏览器打开 → 添加到主屏幕，等于一个 App 图标；
- 云端出口在境外，路透、经济学人、外交事务等原本被拦的英文源可直接抓（`CLOUD_RUN=1` 自动启用）。

---

## 六、信源维护

- **季度体检**：`python tools/probe_sources.py` 全量探测失效源；`python tools/build_sources.py` 把新发现的可抓站点并入 `sources.json`。
- **健康日志**：`logs/health.json` 记录每个源最近成功日、连续失败次数、错误原因。
- **通道优先级**：官方 RSS > 官方 API（财联社/华尔街见闻/澎湃/Crossref）> 页面解析 > RSSHub 镜像。
- **公众号**：无 RSS，需 RSSHub 实例并填 `wechat_id`（`sources.json` 已预留 7 个，`active:false`）。
  - 微信号查法：公众号文章页 → 右上角 → 更多资料 → 微信号。
  - 公共镜像对公众号支持不稳，建议自建（Docker 一条命令）或二期用付费代抓。

---

## 七、常见问题

| 现象 | 原因与处理 |
|---|---|
| 某源 0 条 | 看 `logs/health.json` 的 `last_error`；403/429 多为反爬限流，换通道或等次日 |
| 摘要全是正文截取 | 未检测到任何模型 Key，按第三节配一个 |
| 英文源抓不到 | 本机网络被拦；配代理（`settings.json` 的 `proxy`），或直接走云端运行 |
| 页面条目少 | 调大 `per_source_daily_cap` / `items_per_module_cap`；确认 `window_days`=1（当前为近 1 天） |
| 想加某个网站 | 页面“信源设置→添加信源”生成配置，或直接改 `sources.json` 加 `{"type":"auto","home":"网址"}` |
