#!/usr/bin/env python3
"""发布：把 MP3 托管到 GitHub Pages（与网页同源，国内可访问），更新 docs/feed.xml，滚动清理旧期。"""
import os
import json
import shutil
import subprocess
import sys
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = "wxlkj/daily-news-podcast"
TAG = datetime.datetime.now().strftime("%Y-%m-%d")
FEED = Path("docs/feed.xml")
AUDIO_DIR = Path("docs/audio")
NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", NS_ITUNES)
KEEP_DAYS = 14  # 滚动保留最近 14 期


def run(cmd, check=True, **kw):
    print(">", " ".join(cmd) if isinstance(cmd, list) else cmd)
    try:
        return subprocess.run(cmd, check=check, **kw)
    except subprocess.CalledProcessError as e:
        print(f"!! 命令失败（退出码 {e.returncode}）: {cmd}", file=sys.stderr)
        raise


# 0) 认证：GitHub Actions 中通过 GITHUB_TOKEN 配置 git 远程以便推送
token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if token:
    run(["git", "remote", "set-url", "origin", f"https://x-access-token:{token}@github.com/{REPO}.git"])
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])
    run(["git", "config", "safe.directory", "."])
else:
    print("警告：未检测到 GH_TOKEN / GITHUB_TOKEN，git 推送可能失败", file=sys.stderr)


# 1) 复制 MP3 到 Pages 托管目录（与网页同源，国内可访问）
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
src = Path("episode_final.mp3")
if not src.exists():
    print("!! 未找到 episode_final.mp3，发布中止", file=sys.stderr)
    sys.exit(1)
shutil.copy(src, AUDIO_DIR / f"{TAG}.mp3")
audio_size = src.stat().st_size
# 关键：使用 GitHub Pages 域名，国内可访问（与播放器页面同源）
asset_url = f"https://wxlkj.github.io/daily-news-podcast/audio/{TAG}.mp3"
print("音频已托管到 Pages:", asset_url)


# 2) 上传 Release 作备份（可选，失败不影响 Pages 托管）
try:
    r = subprocess.run(
        ["gh", "api", "GET", f"/repos/{REPO}/releases/tags/{TAG}"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        rid = json.loads(r.stdout).get("id")
        if rid:
            subprocess.run(["gh", "api", "DELETE", f"/repos/{REPO}/releases/{rid}"],
                           capture_output=True, text=True)
    subprocess.run(["gh", "api", "DELETE", f"/repos/{REPO}/git/refs/tags/{TAG}"],
                   capture_output=True, text=True)
    run([
        "gh", "release", "create", TAG, "episode_final.mp3",
        "--title", f"时政简报 {TAG}", "--notes", "自动生成（备份）",
    ], check=False)
    print("Release 备份完成")
except Exception as e:
    print("（Release 备份失败，忽略，不影响 Pages 托管）:", e)


# 3) 更新 feed.xml
tree = ET.parse(FEED)
channel = tree.find("channel")

# 兜底：确保 channel 含 link 与 itunes:image（封面）
COVER = "https://wxlkj.github.io/daily-news-podcast/cover.png"
if channel.find("link") is None:
    lk = ET.SubElement(channel, "link")
    lk.text = "https://wxlkj.github.io/daily-news-podcast/"
if channel.find("{%s}image" % NS_ITUNES) is None:
    img = ET.SubElement(channel, "{%s}image" % NS_ITUNES)
    img.set("href", COVER)

# 重跑去重：删除当天已存在的 item（避免同一天累积多条重复）
for it in list(channel.findall("item")):
    if (it.findtext("guid") == TAG) or (TAG in (it.findtext("title") or "")):
        channel.remove(it)

# 新建 item
item = ET.SubElement(channel, "item")
try:
    _n = json.load(open("news.json", encoding="utf-8"))
    _nd = len(_n.get("domestic", []))
    _ni = len(_n.get("international", []))
except Exception:
    _nd = _ni = 10
title = ET.SubElement(item, "title")
title.text = f"时政简报 {TAG}（国内{_nd}条 + 国际{_ni}条）"
pub = ET.SubElement(item, "pubDate")
pub.text = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime(
    "%a, %d %b %Y %H:%M:%S +0800"
)
desc = ET.SubElement(item, "description")
desc.text = f"每日时政简报 {TAG}：国内与国际各{_nd}条要闻，约10-12分钟。"
enc = ET.SubElement(item, "enclosure")
enc.set("url", asset_url)
enc.set("length", str(audio_size))
enc.set("type", "audio/mpeg")
guid = ET.SubElement(item, "guid")
guid.text = TAG
# 把新 item 插到第一个已有 item 之前（保持频道元数据在最前）
channel.remove(item)
children = list(channel)
idx = len(children)
for i, c in enumerate(children):
    if c.tag == "item":
        idx = i
        break
channel.insert(idx, item)

# 滚动保留最近 KEEP_DAYS 期：删除更早的 item 及其本地音频文件
items = channel.findall("item")

def parse_date(it):
    try:
        return datetime.datetime.strptime(it.findtext("pubDate"),
                                          "%a, %d %b %Y %H:%M:%S +0800")
    except Exception:
        return datetime.datetime.min

items_sorted = sorted(items, key=parse_date, reverse=True)
for old in items_sorted[KEEP_DAYS:]:
    g = old.findtext("guid") or (old.findtext("title") or "")[:10]
    channel.remove(old)
    af = AUDIO_DIR / f"{g}.mp3"
    if af.exists():
        af.unlink()
        print("已清理旧音频:", af.name)

tree.write(FEED, encoding="utf-8", xml_declaration=True)


# 4) 提交并推送 feed.xml + 新音频（git add 目录会同步增删）
run(["git", "add", "docs/feed.xml", "docs/audio/"])
commit = subprocess.run(["git", "commit", "-m", f"update feed & audio {TAG}"],
                        capture_output=True, text=True)
print(commit.stdout, commit.stderr)
branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
if branch in ("HEAD", ""):
    branch = "main"
run(["git", "push", "origin", f"HEAD:{branch}"])

print("发布完成：", TAG)
