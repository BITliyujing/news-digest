# 云端部署操作清单（GitHub Actions + Pages）

本目录已经是初始化好的 git 仓库（本地已提交一次）。你只需做完下面 6 步，之后每天北京时间 07:00 自动更新，电脑关机也不影响。

---

## 第 1 步：注册两个免费模型 Key（各 2 分钟）

**智谱 GLM（主用）**
1. 打开 https://open.bigmodel.cn/ → 手机号注册/登录
2. 右上角「API Keys」→ 新建 → 复制
3. 本地存成：`digest/glm_api_key.txt`（一行纯文本，无空格引号）

**魔搭 ModelScope（备胎）**
1. 打开 https://modelscope.cn/ → 登录
2. 右上角头像 → 「访问令牌」→ 新建令牌 → 复制
3. 本地存成：`digest/ms_api_key.txt`

> 两个文件都已在 `.gitignore` 里，不会被提交。云端用的是 GitHub Secrets，不是这两个文件。

---

## 第 2 步：建一个 GitHub 仓库

1. 登录 https://github.com → 右上角 + → New repository
2. 名称随意，例如 `news-digest`
3. **建议选 Public**：私有仓库的 GitHub Pages 需要付费账号（Pro）才能公开访问；本项目内容只是公开资讯摘要，放 Public 没有敏感信息
4. 不要勾选 "Add a README"（保持空仓库），点 Create

---

## 第 3 步：把本地仓库推上去

在终端里执行（把 `<你的账号>` 换成你的 GitHub 用户名）：

```bash
cd "D:/Personal&Family/量化投资相关/学习资料/行业资讯更新/资讯工具"
git remote add origin https://github.com/<你的账号>/news-digest.git
git push -u origin main
```

第一次推送会弹出 GitHub 登录窗口，按提示授权即可。

---

## 第 4 步：配置 Secrets（模型 Key）

仓库页面 → Settings → Secrets and variables → Actions → New repository secret：

| Name | Value |
|---|---|
| `GLM_API_KEY` | 第 1 步智谱的 Key |
| `MODELSCOPE_API_KEY` | 第 1 步魔搭的令牌 |

（可选）`DEEPSEEK_API_KEY` 作第三备胎，不填不影响。

---

## 第 5 步：开启 Pages

仓库 Settings → Pages → Build and deployment → Source 选 **GitHub Actions**。
（不要选 "Deploy from a branch"）

---

## 第 6 步：手动跑一次验证

仓库页面 → Actions → 左侧 `daily-digest` → 右上「Run workflow」→ Run。

- 约 5-10 分钟跑完
- 绿勾后，同一页面会显示部署网址：`https://<你的账号>.github.io/news-digest/`
- 打开该网址确认内容正常

---

## 手机端

手机浏览器打开上面的网址 → 分享/菜单 → **添加到主屏幕**。
桌面上会出现一个图标，点开就是当天简报；页面里"信源设置"的选择会记在手机本地。

---

## 之后怎么维护

| 想做的事 | 做法 |
|---|---|
| 改信源开关/增删源 | 在电脑上改 `sources.json` → `git commit` → `git push`，下次运行生效（也可直接在 GitHub 网页上编辑该文件） |
| 改抓取条数、时间窗 | 改 `settings.json` 里 `per_source_daily_cap` / `items_per_module_cap` / `window_days` |
| 看某个源为什么没出稿 | 仓库里的 `logs/health.json`，看 `last_error` |
| 换运行时间 | 改 `.github/workflows/daily-digest.yml` 里的 `cron`（UTC 时间，比北京时间早 8 小时） |
| 临时补跑一次 | Actions 页面 → Run workflow |

---

## 需要注意的三点

1. **首次运行可能有个别源失败**：云端 IP 与国内不同，个别站点会限流；失败不影响整体，健康日志会记录，稳定后我再做替换。
2. **定时可能延迟**：GitHub 免费额度在整点高峰会排队，7:00 的任务常在 7:05-7:30 完成。
3. **公众号仍无通道**：云端也没有微信 RSS，这 7 个源保持"未启用"，需要 RSSHub 实例，另行处理。
