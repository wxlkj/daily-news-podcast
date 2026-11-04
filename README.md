# 每日时政语音简报（自动播客）

每天凌晨自动生成一集「国内外时政」语音简报（约 10–12 分钟），国内 5 条 + 国际 5 条，
含权威/官方网站评论引用，发布为播客 RSS，可在**小宇宙**订阅收听。

## 架构
GitHub Actions 定时触发 → 抓取 RSS → LLM 润色 → Edge TTS 转语音 →
上传 GitHub Release + 更新 GitHub Pages 上的 `feed.xml`。

## 部署步骤（一次性的）
1. 在 GitHub 新建**公开仓库** `daily-news-podcast`。
2. 开启 **GitHub Pages**：Settings → Pages → Source 选 `main` 分支的 `/docs` 目录。
3. 配置密钥：Settings → Secrets → Actions → 新建 `LLM_API_KEY`，值为 DeepSeek 的 key。
4. 把本仓库全部文件推送到 `main` 分支（Actions 的 `GITHUB_TOKEN` 已具备 push 权限）。
5. 在 Actions 页面点 **Run workflow** 手动触发一次，验证生成成功。

## 日常使用
- 每天 05:30（北京时间）自动出新集。
- 小宇宙 App → 搜索框 → 输入 `https://wxlkj.github.io/daily-news-podcast/feed.xml` → 订阅。

## 维护
- `config/sources.yaml`：RSS 源易失效，请定期实测替换。
- 想换音色改 `scripts/tts.py` 的 `VOICE`。
- 旧集按 90 天滚动清理，仓库体积稳定在 ~520MB 内。

## 成本
GitHub Actions / Pages / Release 均在免费额度内，Edge TTS 免费，LLM 用 DeepSeek 低费模型，
**整体约 0 元/月**。
