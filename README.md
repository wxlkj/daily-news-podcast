# 每日新闻语音简报（自动播客）

每天自动生成 **4 篇独立语音报道**，直接在手机网页播放器收听，无需订阅任何 App。
每篇只播报**过去 24 小时**的新闻，**逐条精简陈述、不加评论**，条数与时长随当天素材自适应，
不设时长下限、不为凑时长注水；同一事件跨类目去重，只播一次。

| 时段（北京时间） | 篇目 | 内容 |
|---|---|---|
| 早 06:00 | 国际新闻 | BBC / 德国之声 / Reuters / AP 等国际 RSS |
| 晚 20:00 | 国内时政·军事 | 央视首页/国内/社会/军事 + 人民网·中新 RSS，军事热点优先 |
| 晚 20:00 | 文教卫 | 央视文化 / 教育 / 卫生健康频道 |
| 晚 20:00 | 体育 | 央视体育频道 |

## 收听方式

手机 Chrome 打开 **https://wxlkj.github.io/daily-news-podcast/** ，
菜单选「添加到主屏幕」，之后点桌面图标即可收听。
列表上方有「全部 / 国际 / 时政军事 / 文教卫 / 体育」标签可筛选，
底部播放条支持**拖动进度条**。

> 音频与播放器都托管在 GitHub Pages 同一域名下，国内可直接访问；
> 不再依赖 Release（其下载域名在国内不可达），也不依赖小宇宙/喜马拉雅。

## 架构

```
GitHub Actions（两次定时）
  ├─ UTC 22:00（北京 06:00）EDITION=morning  → 国际新闻 1 篇
  └─ UTC 12:00（北京 20:00）EDITION=evening  → 晚间 3 篇
        抓取 fetch_news.py → 分类目润色 polish.py(DeepSeek) → 逐篇 TTS tts.py(Edge TTS + ffmpeg)
        → publish.py 把 MP3 放进 docs/audio/ 并更新 docs/feed.xml → git push
```

四个类目各自独立成稿、独立音频、独立 feed item（`<category>` 区分类目），
同一天同类目重跑按 `guid={日期}_{类目}` 去重替换，不会误删其它三篇。

## 部署（一次性）

1. 公开仓库 `wxlkj/daily-news-podcast`，开启 **Pages**：`main` 分支 `/docs` 目录。
2. 配置 Secret：`LLM_API_KEY`（DeepSeek key）。
3. 推送全部文件；在 Actions 页 **Run workflow** 选 `edition` 手动验证一次。

## 维护

- `config/sources.yaml`：国际 RSS 源与国内频道登记，源失效时替换。
- `scripts/fetch_news.py`：频道 URL、军事关键词、每类候选条数。
- `prompt_intl.md` / `prompt_politics_mil.md` / `prompt_edu.md` / `prompt_sports.md`：四套播报提示词。
- `scripts/tts.py` 的 `VOICE` 可换音色。
- `scripts/publish.py` 的 `KEEP_ITEMS=28`（约最近 7 天）滚动清理旧音频，控制仓库体积。
- `docs/seen.json`：发布流程自动维护，记录最近 3 天已播标题指纹，供次日/次时段去重，不要手工编辑。

## 成本

GitHub Actions / Pages 免费额度内，Edge TTS 免费，LLM 用 DeepSeek 低费模型，**约 0 元/月**。
