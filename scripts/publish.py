#!/usr/bin/env python3
"""发布：上传 MP3 到 GitHub Release，更新 docs/feed.xml，滚动清理 90 天前的旧 Release。"""
import os
import subprocess
import sys
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = "wxlkj/daily-news-podcast"
TAG = datetime.datetime.now().strftime("%Y-%m-%d")
FEED = Path("docs/feed.xml")
NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", NS_ITUNES)


def run(cmd, check=True, **kw):
    print(">", " ".join(cmd) if isinstance(cmd, list) else cmd)
    try:
        return subprocess.run(cmd, check=check, **kw)
    except subprocess.CalledProcessError as e:
        print(f"!! 命令失败（退出码 {e.returncode}）: {cmd}", file=sys.stderr)
        raise


# 0) 认证：GitHub Actions 中通过 GITHUB_TOKEN 登录 gh，并配置 git 远程以便推送
token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if token:
    # 显式登录，避免依赖 runner 默认的 gh 认证状态
    login = subprocess.run(
        f"echo '{token}' | gh auth login --with-token --hostname github.com",
        shell=True,
        capture_output=True,
        text=True,
    )
    if login.returncode != 0:
        print("警告：gh auth login 失败，回退到 GH_TOKEN 环境变量：", login.stderr, file=sys.stderr)
    # 配置 git 远程，确保 git push 使用 token 认证
    run(["git", "remote", "set-url", "origin", f"https://x-access-token:{token}@github.com/{REPO}.git"])
    # 配置 git 提交者身份（GitHub Actions 默认没有，不配置 git commit 会失败）
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])
    run(["git", "config", "safe.directory", "."])
else:
    print("警告：未检测到 GH_TOKEN / GITHUB_TOKEN，gh 与 git 可能认证失败", file=sys.stderr)


# 1) 上传 MP3 到 Release（如当天已存在则先删除，支持手动重跑）
asset_url = f"https://github.com/{REPO}/releases/download/{TAG}/episode_final.mp3"
# 先尝试删除当天已存在的 release（重跑场景），不存在则忽略
delp = subprocess.run(
    ["gh", "release", "delete", TAG, "-y"],
    capture_output=True, text=True,
)
if delp.returncode != 0:
    print(f"（未找到已存在的 release {TAG}，直接创建）")
run([
    "gh", "release", "create", TAG, "episode_final.mp3",
    "--title", f"时政简报 {TAG}",
    "--notes", "自动生成",
])

# 2) 更新 feed.xml，插入新 item（放到最前）
tree = ET.parse(FEED)
channel = tree.find("channel")
item = ET.SubElement(channel, "item")
title = ET.SubElement(item, "title")
title.text = f"时政简报 {TAG}（国内5条 + 国际5条）"
pub = ET.SubElement(item, "pubDate")
pub.text = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime(
    "%a, %d %b %Y %H:%M:%S +0800"
)
desc = ET.SubElement(item, "description")
desc.text = f"每日时政简报 {TAG}：国内与国际各5条要闻，约10-12分钟。"
enc = ET.SubElement(item, "enclosure")
enc.set("url", asset_url)
try:
    enc.set("length", str(Path("episode_final.mp3").stat().st_size))
except FileNotFoundError:
    enc.set("length", "0")
enc.set("type", "audio/mpeg")
guid = ET.SubElement(item, "guid")
guid.text = TAG
channel.remove(item)
channel.insert(0, item)
tree.write(FEED, encoding="utf-8", xml_declaration=True)

# 3) 提交并推送 feed.xml
run(["git", "add", "docs/feed.xml"])
# 即使无变更也不报错退出
commit = subprocess.run(["git", "commit", "-m", f"update feed {TAG}"], capture_output=True, text=True)
print(commit.stdout, commit.stderr)
# 显式推送当前分支（避免 detached HEAD 场景）
branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode().strip()
if branch in ("HEAD", ""):
    branch = "main"
run(["git", "push", "origin", f"HEAD:{branch}"])

# 4) 滚动清理：删除 90 天前的 Release
cutoff = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
out = subprocess.run(["gh", "release", "list", "--limit", "200"], capture_output=True, text=True).stdout
for line in out.splitlines():
    parts = line.split("\t")
    if len(parts) < 3:
        continue
    tag = parts[0]
    if tag < cutoff:
        run(["gh", "release", "delete", tag, "-y"])

print("发布完成：", TAG)
