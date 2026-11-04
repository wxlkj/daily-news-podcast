#!/usr/bin/env python3
"""抓取国内外时政新闻。

国内：网页抓取央视新闻多个频道页（国内 RSS 时间字段不可靠/已停用，改用网页抓取，
      发布日期从文章 URL 中提取，如 news.cctv.com/2026/10/31/...shtml）。
      同一篇新闻在页面上有标题(短链接)与摘要(长链接)指向同一 URL，
      按 URL 聚合并取最短文本作标题、最长文本作摘要。
      多频道合并、跨页按 URL 去重，优先选取「带摘要」的条目——
      这样交给 LLM 的是真实素材，避免其仅凭标题编造细节（满足"客观真实"要求）。
国际：RSS 聚合（GitHub Actions 境外 runner 可正常抓取 BBC/Reuters/AP/DW；
      本地/沙箱若连不上境外则为 0 条，属正常）。
评论：可选，暂不强加（找不到合适来源则不加，避免编造）。
"""
import re
import json
import yaml
import socket
import feedparser
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

# 防止不可达的 RSS 源卡死整个流程
socket.setdefaulttimeout(10)

SOURCES = yaml.safe_load(open("config/sources.yaml"))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 国内抓取的央视频道页（按重要性排序；均为真实要闻，含带日期 URL 的新闻）
DOMESTIC_URLS = [
    "https://news.cctv.com/",          # 首页头条
    "https://news.cctv.com/china/",    # 国内
    "https://news.cctv.com/society/",  # 社会（补充来源）
]


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_page(url):
    """解析单个央视页面，返回该页所有新闻条目（已按 URL 聚合，标题/摘要配对）。"""
    items = []
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")
        # 先按 URL 聚合同一新闻的所有文本片段
        groups = {}
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"cctv\.com/(\d{4})/(\d{2})/(\d{2})/", href)
            if not m:
                continue
            t = clean(a.get_text())
            if len(t) < 6:
                continue
            g = groups.setdefault(href, {"y": int(m.group(1)), "mo": int(m.group(2)),
                                         "d": int(m.group(3)), "texts": []})
            g["texts"].append(t)
        # 聚合后构造条目：最短文本=标题，最长文本=摘要
        for href, g in groups.items():
            texts = [t for t in g["texts"] if 6 <= len(t) <= 200]
            if not texts:
                continue
            title = min(texts, key=len)
            summary = max(texts, key=len)
            summary = summary if summary != title else ""
            pub = datetime(g["y"], g["mo"], g["d"], tzinfo=timezone.utc)
            items.append({"title": title, "summary": summary,
                          "published": pub.isoformat(), "url": href})
    except Exception as e:
        print(f"[warn] 抓取失败 {url}: {e}")
    return items


def fetch_domestic(urls, limit=5):
    """多频道合并、跨页按 URL 去重，优先取「带摘要」的条目。"""
    merged = {}
    for rank, u in enumerate(urls):
        for it in parse_page(u):
            if it["url"] not in merged:
                it["rank"] = rank
                merged[it["url"]] = it
    items = list(merged.values())
    # 排序：带摘要优先，其次按源重要性(rank)，取前 limit
    items.sort(key=lambda x: (x["summary"] == "", x.get("rank", 9)))
    return items[:limit]


def fetch_rss(urls):
    items = []
    for u in urls:
        try:
            d = feedparser.parse(u)
            for e in d.entries:
                pp = e.get("published_parsed") or e.get("updated_parsed")
                if not pp:
                    continue
                pub = datetime(*pp[:6], tzinfo=timezone.utc)
                items.append({
                    "title": clean(e.get("title", "")),
                    "summary": clean(e.get("summary", e.get("description", "")))[:400],
                    "published": pub.isoformat(),
                })
        except Exception as ex:
            print(f"[warn] RSS 失败 {u}: {ex}")
    return items


def top5(items):
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        if it["title"] in seen:
            continue
        seen.add(it["title"])
        out.append(it)
        if len(out) >= 5:
            break
    return out


# 国内：多频道合并，优先带摘要（给 LLM 真实素材，避免编造）
domestic = fetch_domestic(DOMESTIC_URLS, limit=5)
# 国际：RSS 聚合（真机在境外 runner 上验证）
international = top5(fetch_rss([s["url"] for s in SOURCES.get("international", [])]))

result = {"domestic": domestic, "international": international, "commentary": []}
with open("news.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"国内 {len(domestic)} 条 / 国际 {len(international)} 条"
      f"（国内带摘要 {sum(1 for x in domestic if x['summary'])} 条）")
for i, it in enumerate(domestic, 1):
    print(f"  国内{i}: {it['title']}  ({it['published'][:10]})")
for i, it in enumerate(international, 1):
    print(f"  国际{i}: {it['title']}  ({it['published'][:10]})")
