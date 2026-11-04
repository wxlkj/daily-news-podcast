#!/usr/bin/env python3
"""发布：上传 MP3 到 GitHub Release，更新 docs/feed.xml，滚动清理 90 天前的旧 Release。"""
import subprocess
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

TAG = datetime.datetime.now().strftime("%Y-%m-%d")
FEED = Path("docs/feed.xml")
NS = {
    "rss": "http://purl.org/rss/2.0/",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}
ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")


def run(cmd):
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True)


# 1) 上传 MP3 到 Release（GITHUB_TOKEN 已对仓库认证）
run([
    "gh", "release", "create", TAG, "episode_final.mp3",
    "--title", f"时政简报 {TAG}",
    "--notes", "自动生成",
])
# 取得稳定下载链接
asset_url = (
    f"https://github.com/{subprocess.check_output(['gh','repo','view','--json','nameWithOwner','-q','.nameWithOwner']).decode().strip()}"
    f"/releases/download/{TAG}/episode_final.mp3"
)

# 2) 更新 feed.xml，插入新 item
tree = ET.parse(FEED)
channel = tree.find("channel")
item = ET.SubElement(channel, "item")
title = ET.SubElement(item, "title")
title.text = f"时政简报 {TAG}（国内5条 + 国际5条）"
pub = ET.SubElement(item, "pubDate")
pub.text = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime(
    "%a, %d %b %Y %H:%M:%S +0800"
)
enc = ET.SubElement(item, "enclosure")
enc.set("url", asset_url)
enc.set("length", str(Path("episode_final.mp3").stat().st_size))
enc.set("type", "audio/mpeg")
guid = ET.SubElement(item, "guid")
guid.text = TAG
# 把新 item 移到 channel 下第一个位置
channel.remove(item)
channel.insert(0, item)
tree.write(FEED, encoding="utf-8", xml_declaration=True)

# 3) 提交并推送 feed.xml
run(["git", "add", "docs/feed.xml"])
run(["git", "commit", "-m", f"update feed {TAG}"])
run(["git", "push"])

# 4) 滚动清理：删除 90 天前的 Release
cutoff = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
out = subprocess.check_output(["gh", "release", "list", "--limit", "200"]).decode()
for line in out.splitlines():
    parts = line.split("\t")
    if len(parts) < 3:
        continue
    tag = parts[0]
    if tag < cutoff:
        run(["gh", "release", "delete", tag, "-y"])

print("发布完成：", TAG)
