#!/usr/bin/env python3
"""发布：把当天整合好的单集 MP3 托管到 GitHub Pages（同源，国内可访问），更新 docs/feed.xml。

每天一期（北京 20:00 定时生成）：四类新闻整合为一段、全局连续编号，
故每次只发布「一个」音频 + 「一条」item。

音频统一放在 docs/audio/{日期}.mp3，由 Pages 同源提供。同日重跑按 guid={日期}
精确去重替换，不会误删历史各期。
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
FEED = Path("docs/feed.xml")
AUDIO_DIR = Path("docs/audio")
NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", NS_ITUNES)
KEEP_ITEMS = 28  # 每天 1 期，约保留最近 28 天，控制仓库体积

# 跨天去重记录用的类目键（与 fetch_news.py 的 CATS 一致）；仅用于写 docs/seen.json
SEEN_CATS = ["international", "politics_mil", "culture_edu_health", "sports"]


def run(cmd, check=True, **kw):
    print(">", " ".join(cmd) if isinstance(cmd, list) else cmd)
    try:
        return subprocess.run(cmd, check=check, **kw)
    except subprocess.CalledProcessError as e:
        print(f"!! 命令失败（退出码 {e.returncode}）: {cmd}", file=sys.stderr)
        raise


def pubdate_for():
    """固定的北京时间 20:00 pubDate，让播放器排序稳定、时间显示整洁。"""
    dt = datetime.datetime.strptime(TAG, "%Y-%m-%d").replace(
        hour=20, minute=0, second=0, tzinfo=BEIJING)
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


# 1) 找出本次要发布的单集音频
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
src = Path("episode_final.mp3")
if not src.exists():
    print("!! 未找到 episode_final.mp3（请先运行 fetch → polish → merge_scripts → tts），发布中止",
          file=sys.stderr)
    sys.exit(1)
pending = [(TAG, src)]


# 2) 复制音频到 Pages 托管目录（与网页同源，国内可访问）
for tag, s in pending:
    shutil.copy(s, AUDIO_DIR / f"{tag}.mp3")
    print(f"音频已托管: {BASE_URL}/audio/{tag}.mp3（{s.stat().st_size} 字节）")


# 3) 更新 feed.xml
tree = ET.parse(FEED)
channel = tree.find("channel")

# 兜底：确保 channel 含 link 与 itunes:image（封面）
if channel.find("link") is None:
    ET.SubElement(channel, "link").text = BASE_URL + "/"
if channel.find("{%s}image" % NS_ITUNES) is None:
    ET.SubElement(channel, "{%s}image" % NS_ITUNES).set("href", BASE_URL + "/cover.png")

# 同步频道简介：每天一期整合简报，全局连续编号，不凑时长
CHANNEL_DESC = ("每天 20:00 一期整合语音简报：覆盖过去 24 小时国际、国内时政·军事、文教卫、体育，"
                "第1条到第N条连续播报、不加评论，时长随当天素材自适应。")
_ch_desc = channel.find("description")
if _ch_desc is None:
    ET.SubElement(channel, "description").text = CHANNEL_DESC
else:
    _ch_desc.text = CHANNEL_DESC

# 3a) 去重：只删除本次要发布的 guid（同日重跑替换，不误删历史各期）
new_guids = {tag for tag, _ in pending}
for it in list(channel.findall("item")):
    if it.findtext("guid") in new_guids:
        channel.remove(it)

# 3b) 新建单条 item，插到第一个已有 item 之前（保持频道元数据在最前）
for tag, s in pending:
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"每日新闻 {tag}"
    ET.SubElement(item, "pubDate").text = pubdate_for()
    ET.SubElement(item, "description").text = (
        f"每日整合简报 {tag}，覆盖过去 24 小时国际、国内时政·军事、文教卫、体育，"
        f"第1条到第N条连续播报、不加评论。")
    enc = ET.SubElement(item, "enclosure")
    enc.set("url", f"{BASE_URL}/audio/{tag}.mp3")
    enc.set("length", str(s.stat().st_size))
    enc.set("type", "audio/mpeg")
    ET.SubElement(item, "guid").text = tag
    itunes_dur = ET.SubElement(item, "{%s}duration" % NS_ITUNES)
    itunes_dur.text = f"{int(s.stat().st_size * 8 / 64000 / 60):02d}:00"
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


# 3e) 记录本次已播标题指纹，供后续运行做「跨天」去重。
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
for cat in SEEN_CATS:
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
commit = subprocess.run(["git", "commit", "-m", f"update feed & audio {TAG}"],
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

print("发布完成：", TAG)
