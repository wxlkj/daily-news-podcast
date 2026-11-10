# 每日新闻语音简报（自动播客）

每天 **20:00（北京时间）自动生成一期**整合语音简报，四类新闻（国际、国内时政·军事、文教卫、体育）
**合并为一段、全局连续编号「第1条…第N条」直接播报**，在手机网页播放器收听，无需订阅任何 App。
只播报**过去 24 小时**的新闻，**不加评论**，条数与时长随当天素材自适应，不设时长下限、不为凑时长注水；
同一事件跨类目去重，只播一次。

| 时段（北京时间） | 内容 |
|---|---|
| 每天 20:00 | 一期整合简报：国际 + 国内时政·军事 + 文教卫 + 体育，连续编号、依次播报 |

## 收听方式

手机 Chrome 打开 **https://wxlkj.github.io/daily-news-podcast/** ，
菜单选「添加到主屏幕」，之后点桌面图标即可收听。
列表卡片右侧「↓」直接下载到本机，底部播放条支持**拖动进度条**。

> 音频与播放器都托管在 GitHub Pages 同一域名下，国内可直接访问；
> 不再依赖 Release（其下载域名在国内不可达），也不依赖小宇宙/喜马拉雅。

## 架构

```
GitHub Actions（每天一次定时）
  └─ UTC 12:00（北京 20:00）EDITION=all  → 当天一期整合简报
        抓取 fetch_news.py（四类）
          → 分类目润色 polish.py(DeepSeek) 各成 script_<cat>.txt
          → merge_scripts.py 拼接四段并按全局重编号为 script_combined.txt
          → tts.py(Edge TTS + ffmpeg) 合成单集 episode_final.mp3
          → publish.py 把 MP3 放进 docs/audio/{日期}.mp3 并更新 docs/feed.xml → git push
```

四类新闻先各自独立成稿，再合并为一篇、统一从「第1条」连续编号到结尾（段间仅换行留自然停顿，
不插入类目小标题）；每天只发布**一个**音频 + **一条** feed item（`guid={日期}`），
同日重跑按 guid 去重替换，不会误删历史各期。

## 部署（一次性）

1. 公开仓库 `wxlkj/daily-news-podcast`，开启 **Pages**：`main` 分支 `/docs` 目录。
2. 配置 Secret：`LLM_API_KEY`（DeepSeek key）。
3. 推送全部文件；在 Actions 页 **Run workflow** 手动验证一次。

## 维护

- `config/sources.yaml`：国际 RSS 源与国内频道登记，源失效时替换。
- `scripts/fetch_news.py`：频道 URL、军事关键词、每类候选条数。
- `scripts/merge_scripts.py`：顶部 `ORDER` 常量控制整合后四类先后（默认 国际→时政军事→文教卫→体育）。
- `prompt_intl.md` / `prompt_politics_mil.md` / `prompt_edu.md` / `prompt_sports.md`：四类播报提示词。
- `scripts/tts.py` 的 `VOICE` 可换音色。
- `scripts/publish.py` 的 `KEEP_ITEMS=28`（每天 1 期，约最近 28 天）滚动清理旧音频，控制仓库体积。
- `docs/seen.json`：发布流程自动维护，记录最近 3 天已播标题指纹，供次日去重，不要手工编辑。

## 成本

GitHub Actions / Pages 免费额度内，Edge TTS 免费，LLM 用 DeepSeek 低费模型，**约 0 元/月**。
