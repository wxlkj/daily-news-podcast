#!/usr/bin/env python3
"""发布：把本次时段各类目 MP3 托管到 GitHub Pages（同源，国内可访问），更新 docs/feed.xml。

每天 4 篇，分两次运行：
  - morning（北京 06:00）：国际新闻
  - evening（北京 20:00）：国内时政·军事 / 文教卫 / 体育
本次只发布「本时段生成」的类目，其余时段的 item 原样保留；
同日同类目重跑按 guid 精确去重替换（不会误删同一天的其它三篇）。
音频统一放在 docs/audio/{日期}_{类目}.mp3，由 Pages 同源提供。
"""
import os
import re
import json
import shutil
import subprocess
import sys
import time
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = "wxlkj/daily-news-podcast"
BASE_URL = "https://wxlkj.github.io/daily-news-podcast"
BEIJING = datetime.timezone(datetime.timedelta(hours=8))
TAG = datetime.datetime.now(BEIJING).strftime("%Y-%m-%d")
EDITION = os.environ.get("EDITION", "evening").lower()
FEED = Path("docs/feed.xml")
AUDIO_DIR = Path("docs/audio")
NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", NS_ITUNES)
KEEP_ITEMS = 28  # 约保留最近 7 天（4 篇/天），控制仓库体积

# 类目 key -> (中文标签, 所属时段, pubDate 秒偏移：用于同类目内稳定排序)
CATS = {
    "international":      ("国际新闻",       "morning", 0),
    "politics_mil":       ("国内时政·军事",  "evening", 3),
    "culture_edu_health": ("文教卫",         "evening", 2),
    "sports":             ("体育",           "evening", 1),
}


def run(cmd, check=True, **kw):
    print(">", " ".join(cmd) if isinstance(cmd, list) else cmd)
    try:
        return subprocess.run(cmd, check=check, **kw)
    except subprocess.CalledProcessError as e:
        print(f"!! 命令失败（退出码 {e.returncode}）: {cmd}", file=sys.stderr)
        raise


def pubdate_for(edition, sec):
    """按发布时段生成固定的北京时间 pubDate，让播放器排序稳定、时间显示整洁。"""
    hour = 6 if edition == "morning" else 20
    dt = datetime.datetime.strptime(TAG, "%Y-%m-%d").replace(
        hour=hour, minute=0, second=sec, tzinfo=BEIJING)
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0800")


# 0) 认证：GitHub Actions 中通过 GITHUB_TOKEN 配置 git 远程以便推送
token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if token:
    run(["git", "remote", "set-url", "origin", f"https://x-access-token:{token}@github.com/{REPO}.git"])
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])
    run(["git", "config", "safe.directory", "."])
else:
    print("警告：未检测到 GH_TOKEN / GITHUB_TOKEN，git 推送可能失败", file=sys.stderr)


# 1) 找出本次要发布的类目：存在对应音频，且属于本时段
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
pending = []
for cat, (label, edition, sec) in CATS.items():
    src = Path(f"episode_final_{cat}.mp3")
    if not src.exists():
        continue
    # EDITION=all（调试）时全部发布；否则只发布属于本时段的类目
    if EDITION != "all" and edition != EDITION:
        print(f"[skip] {label} 属于 {edition} 时段，本次 EDITION={EDITION} 不发布")
        continue
    pending.append((cat, label, edition, sec, src))

if not pending:
    print("!! 本次没有可发布的音频，发布中止（检查 polish/tts 是否成功、EDITION 是否匹配）",
          file=sys.stderr)
    sys.exit(1)


# 2) 复制音频到 Pages 托管目录（与网页同源，国内可访问）
for cat, label, edition, sec, src in pending:
    shutil.copy(src, AUDIO_DIR / f"{TAG}_{cat}.mp3")
    print(f"音频已托管: {BASE_URL}/audio/{TAG}_{cat}.mp3（{label}，{src.stat().st_size} 字节）")


# 3) 更新 feed.xml
tree = ET.parse(FEED)
channel = tree.find("channel")

# 兜底：确保 channel 含 link 与 itunes:image（封面）
if channel.find("link") is None:
    ET.SubElement(channel, "link").text = BASE_URL + "/"
if channel.find("{%s}image" % NS_ITUNES) is None:
    ET.SubElement(channel, "{%s}image" % NS_ITUNES).set("href", BASE_URL + "/cover.png")

# 同步频道简介：不再写"约 10–20 分钟"（篇幅已改为随素材自适应，不凑时长）
CHANNEL_DESC = ("每天 4 篇语音简报：早 06:00 国际新闻，晚 20:00 国内时政·军事、文教卫、体育。"
                "只播报过去 24 小时新闻，逐条精简陈述、不加评论，时长随当天素材自适应。")
_ch_desc = channel.find("description")
if _ch_desc is None:
    ET.SubElement(channel, "description").text = CHANNEL_DESC
else:
    _ch_desc.text = CHANNEL_DESC

# 3a) 去重：只删除本次要发布的 guid（绝不能误删同一天其它时段的三篇）
new_guids = {f"{TAG}_{cat}" for cat, _, _, _, _ in pending}
for it in list(channel.findall("item")):
    if it.findtext("guid") in new_guids:
        channel.remove(it)

# 3b) 新建各类目 item，插到第一个已有 item 之前（保持频道元数据在最前）
for cat, label, edition, sec, src in pending:
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"{label} {TAG}"
    ET.SubElement(item, "category").text = cat
    ET.SubElement(item, "pubDate").text = pubdate_for(edition, sec)
    ET.SubElement(item, "description").text = (
        f"{label}简报 {TAG}，逐条精简陈述、不加评论。")
    enc = ET.SubElement(item, "enclosure")
    enc.set("url", f"{BASE_URL}/audio/{TAG}_{cat}.mp3")
    enc.set("length", str(src.stat().st_size))
    enc.set("type", "audio/mpeg")
    ET.SubElement(item, "guid").text = f"{TAG}_{cat}"
    itunes_dur = ET.SubElement(item, "{%s}duration" % NS_ITUNES)
    itunes_dur.text = f"{int(src.stat().st_size * 8 / 64000 / 60):02d}:00"
    channel.remove(item)
    children = list(channel)
    idx = next((i for i, c in enumerate(children) if c.tag == "item"), len(children))
    channel.insert(idx, item)


# 3c) 滚动保留最近 KEEP_ITEMS 条 item，删除更早的及其本地音频
def parse_date(it):
    try:
        return datetime.datetime.strptime(it.findtext("pubDate"),
                                          "%a, %d %b %Y %H:%M:%S +0800")
    except Exception:
        return datetime.datetime.min

for old in sorted(channel.findall("item"), key=parse_date, reverse=True)[KEEP_ITEMS:]:
    g = old.findtext("guid") or ""
    channel.remove(old)
    af = AUDIO_DIR / f"{g}.mp3"
    if af.exists():
        af.unlink()
        print("已清理旧音频:", af.name)

# 3d) 按 pubDate 倒序重排 item，使 RSS 阅读器顺序与播放器一致
ordered = sorted(channel.findall("item"), key=parse_date, reverse=True)
for it in ordered:
    channel.remove(it)
for it in ordered:
    channel.append(it)

tree.write(FEED, encoding="utf-8", xml_declaration=True)


# 3e) 记录本次已播标题指纹，供后续运行做「跨天 / 早晚」去重。
#     指纹算法须与 scripts/fetch_news.py 的 norm_title 保持一致。
SEEN = Path("docs/seen.json")


def _fp(t):
    s = re.sub(r"\s+", "", t or "")
    s = re.sub(r"^【[^】]{0,12}】|^\[[^\]]{0,12}\]", "", s)
    s = re.sub(r"^(?:独家|快讯|突发|重磅|最新|视频|图文|组图|直播|专访|评论|关注|热点)[：:]?", "", s)
    s = re.sub(
        r"^(?:中新网|中新社|新华社|人民网|央视网|央视新闻|央视|环球网|参考消息|中国新闻网|"
        r"路透社|法新社|美联社|共同社|BBC|CNN)[^：:|｜]{0,6}[：:|｜]?", "", s)
    return re.sub(r"\W", "", s, flags=re.UNICODE).lower()


try:
    seen = json.loads(SEEN.read_text(encoding="utf-8")) if SEEN.exists() else {}
except Exception:
    seen = {}
try:
    news = json.load(open("news.json", encoding="utf-8"))
except Exception:
    news = {}
for cat, *_ in pending:
    seen[f"{TAG}_{cat}"] = [_fp(it.get("title", "")) for it in news.get(cat, []) if it.get("title")]
# 只保留最近 3 天，控制文件体积
cutoff = (datetime.datetime.now(BEIJING) - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
seen = {k: v for k, v in seen.items() if k[:10] >= cutoff}
SEEN.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"已记录已播标题: {sum(len(v) for v in seen.values())} 条 / {len(seen)} 个批次")


# 4) 提交并推送 feed.xml + 音频（*.mp3 被 .gitignore 忽略，必须 -f 强制添加）
run(["git", "add", "docs/feed.xml"])
run(["git", "add", "-f", str(SEEN)])
run(["git", "add", "-A", "-f", "docs/audio/"])
commit = subprocess.run(["git", "commit", "-m", f"update feed & audio {TAG} ({EDITION})"],
                        capture_output=True, text=True)
print(commit.stdout, commit.stderr)
branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
if branch in ("HEAD", ""):
    branch = "main"
# git push 加重试：应对 GitHub 服务端瞬时 500
for attempt in range(1, 6):
    p = subprocess.run(["git", "push", "origin", f"HEAD:{branch}"],
                       capture_output=True, text=True)
    if p.returncode == 0:
        print("git push 成功")
        break
    print(f"!! git push 第{attempt}次失败（退出码 {p.returncode}），3 秒后重试…")
    print(p.stderr.strip()[:300])
    if attempt < 5:
        time.sleep(3)
else:
    print("!! git push 多次失败，音频与 feed 已在本地生成，可等下次运行重试", file=sys.stderr)

print("发布完成：", TAG, EDITION, [c for c, _, _, _, _ in pending])
