# 云端运行（电脑关机也能每天出简报）

目标：每天早 7 点自动生成，生成结果发布成一个网址，手机和电脑随时打开。
本机不需要开机，也不占用本机网络。

---

## 方案对比

| 方案 | 成本 | 电脑关机可用 | 境外源（路透/经济学人） | 上手难度 |
|---|---|---|---|---|
| **GitHub Actions + Pages（推荐）** | 免费（公开仓库不限时长，私有仓库每月 2000 分钟） | ✅ | ✅ 出口在境外，直连 | 需一个 GitHub 账号，约 20 分钟配置 |
| 腾讯云函数 / 轻量服务器 | 约 ¥30-60/月起 | ✅ | ❌ 国内机房同样被墙，仍需代理 | 需实名与备案（用默认域名可免备案） |
| 本机定时任务 | 0 | ❌ | ❌ | 已具备 |

结论：**先用 GitHub Actions**。它一次解决三件事——电脑关机、手机访问、境外英文源。将来要加登录、检索、手动刷新，再迁到云服务器或 WorkBuddy 云服务。

---

## 一次性配置步骤（约 20 分钟）

1. 注册/登录 GitHub，新建一个仓库（建议 **Private**）。
2. 在本地把 `资讯工具/` 目录做成仓库并推上去：
   ```bash
   cd 资讯工具
   git init -b main
   git add .
   git commit -m "init digest"
   git remote add origin https://github.com/<你的账号>/<仓库名>.git
   git push -u origin main
   ```
3. 把 `cloud/github-actions.yml` 复制到仓库的 `.github/workflows/daily-digest.yml`。
4. 仓库 Settings → Secrets and variables → Actions → New repository secret：
   - `GLM_API_KEY`（智谱开放平台创建；免费模型即可）
   - 可选备胎：`MODELSCOPE_API_KEY`、`DEEPSEEK_API_KEY`
5. 仓库 Settings → Pages → Source 选 **GitHub Actions**。
6. 仓库 Actions 页面点 `daily-digest` → **Run workflow** 手动跑一次，看是否成功。
7. 成功后 Pages 会给一个网址：`https://<账号>.github.io/<仓库名>/`
   - 手机浏览器打开 → 分享/菜单 → **添加到主屏幕**，就得到一个图标；
   - 电脑直接收藏该网址。

之后每天北京时间 07:00 自动更新，不需要任何本机操作。

---

## 注意点

- **私有仓库 + Pages**：GitHub 对私有仓库的 Pages 需要 Pro 账号才能公开访问；若不想付费，把仓库设为 Public（内容只是资讯摘要，无敏感信息），或在设置里仅保留 Actions 产物下载。
- **定时精度**：GitHub 的 cron 在高峰期可能延迟几分钟到半小时，7:00 的任务通常 7:05-7:30 之间完成。
- **中文站点**：GitHub 机房在境外，个别国内站点（如部分地方媒体）可能限流，健康日志会记录；主力国内源（政府网、央视、中新网、财新等）实测可用。
- **公众号**：云端仍然没有公众号通道，需要 RSSHub 实例，见 README 第四节。
