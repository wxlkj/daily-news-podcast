#!/usr/bin/env python3
"""抓取分类新闻，按 EDITION 环境变量决定抓取哪些类目。

  - morning : 仅国际新闻（供早上 06:00 发布）
  - evening : 国内时政·军事 + 文教卫 + 体育（供晚上 20:00 发布）
  - all     : 抓取全部四类（调试用，默认 evening）

国内（时政军事 / 文教卫 / 体育）：央视各垂直频道网页抓取，发布日期从文章 URL 提取
  （如 culture.cctv.com/2026/11/04/...shtml）。同一新闻在页面上有标题(短)与摘要(长)
  指向同一 URL，按 URL 聚合并取最短文本作标题、最长文本作摘要，确保交给 LLM 的
  是真实素材，避免其凭标题编造细节（满足"客观真实"要求）。
  RSS 仅作补充（人民网/中新），其 pubDate 不可靠故不依赖。
文教卫：合并 文化(culture) / 教育(edu) / 卫生健康(health) 三个央视垂直频道。
国际：境外 RSS（BBC/Reuters/AP/DW，线上 runner 可抓）+ 境内 RSS（人民网/中新网国际，
  国内域名不依赖境外网络）。
各类目均配「境内 RSS 兜底」，保证候选条数充足，使每篇文稿能撑满 10–20 分钟而不必编造。
"""
import os
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

# ---- 频道 URL（均为真实要闻页，链接含 cctv.com/YYYY/MM/DD/ 日期路径，供 parse_page 解析）----
POLITICS_MIL_URLS = [
    "https://news.cctv.com/",          # 首页头条
    "https://news.cctv.com/china/",    # 国内
    "https://news.cctv.com/society/",  # 社会（补充来源）
    "https://news.cctv.com/military/",  # 军事（保证热点军事新闻覆盖）
]
# 文教卫：文化 / 教育 / 卫生健康 三个央视垂直频道
EDU_URLS = [
    "https://culture.cctv.com/",
    "https://edu.cctv.com/",
    "https://health.cctv.com/",
]
SPORTS_URLS = [
    "https://sports.cctv.com/",
    "https://sports.cctv.com/football/",
]
# 国内 RSS 补充（标题/摘要真实；pubDate 不可靠故不依赖）
DOMESTIC_RSS = [
    "http://www.people.com.cn/rss/politics.xml",   # 人民网时政
    "https://www.chinanews.com.cn/rss/china.xml",  # 中国新闻网国内
]
# 境内补充 RSS：国内域名、不依赖境外网络，保证各类目候选充足（朗读 10–20 分钟需要足量素材）
INTL_RSS = [
    "http://www.people.com.cn/rss/world.xml",       # 人民网国际
    "https://www.chinanews.com.cn/rss/world.xml",   # 中新网国际
]
EDU_RSS = [
    "http://www.people.com.cn/rss/edu.xml",         # 人民网教育
    "http://www.people.com.cn/rss/culture.xml",     # 人民网文化
]
SPORTS_RSS = [
    "http://www.people.com.cn/rss/sports.xml",      # 人民网体育
    "https://www.chinanews.com.cn/rss/sports.xml",  # 中新网体育
]

# 军事/国防相关关键词：命中则视为"军事新闻"，在排序中优先入选
MIL_KEYWORDS = ["军事", "军队", "国防", "武器", "导弹", "航母", "战机", "演习",
                "部队", "军演", "空军", "海军", "陆军", "火箭军", "征兵", "边防",
                "潜艇", "无人机", "坦克", "军舰", "军工", "退役军人", "维和",
                "反恐", "武警", "阅兵", "军费", "军备", "防务"]


def is_military(item):
    u = item.get("url", "")
    if "military.cctv.com" in u or "military.news.cn" in u or "military.people" in u:
        return True
    t = (item.get("title", "") + " " + item.get("summary", ""))
    return any(k in t for k in MIL_KEYWORDS)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_page(url):
    """解析单个央视页面，返回该页所有新闻条目（已按 URL 聚合，标题/摘要配对）。"""
    items = []
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")
        groups = {}
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "tv.cctv.com" in href:   # 跳过视频链接，保留文字新闻名额
                continue
            m = re.search(r"cctv\.com/(\d{4})/(\d{2})/(\d{2})/", href)
            if not m:
                continue
            t = clean(a.get_text())
            if len(t) < 4:
                continue
            g = groups.setdefault(href, {"y": int(m.group(1)), "mo": int(m.group(2)),
                                         "d": int(m.group(3)), "texts": []})
            g["texts"].append(t)
        for href, g in groups.items():
            texts = [t for t in g["texts"] if 4 <= len(t) <= 300]
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


def fetch_domestic(urls, limit=10):
    """多频道合并、跨页按 URL 去重。
    排序优先级：军事新闻 > 带摘要 > 源重要性(rank)，确保热点军事必入选。
    """
    merged = {}
    for rank, u in enumerate(urls):
        for it in parse_page(u):
            if it["url"] not in merged:
                it["rank"] = rank
                merged[it["url"]] = it
    items = list(merged.values())
    items.sort(key=lambda x: (not is_military(x), x["summary"] == "", x.get("rank", 9)))
    return items[:limit]


def fetch_rss_domestic(urls, per=12):
    """取国内 RSS 作为补充素材（标题/摘要真实；pubDate 不可靠故不依赖）。"""
    items = []
    for u in urls:
        try:
            d = feedparser.parse(u)
            for e in d.entries[:per]:
                items.append({
                    "title": clean(e.get("title", "")),
                    "summary": clean(e.get("summary", e.get("description", "")))[:400],
                    "published": datetime.now(timezone.utc).isoformat(),
                    "url": e.get("link", ""),
                })
        except Exception as ex:
            print(f"[warn] 国内RSS失败 {u}: {ex}")
    return items


def merge_dedup(items, n=10):
    """合并去重（按标题前若干字），军事优先 + 带摘要优先，取前 n。"""
    seen, out = set(), []
    for it in items:
        key = it.get("title", "")[:12]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=lambda x: (not is_military(x), x.get("summary", "") == ""))
    return out[:n]


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


def top_n(items, n=10):
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        if it["title"] in seen:
            continue
        seen.add(it["title"])
        out.append(it)
        if len(out) >= n:
            break
    return out


# ============================ 按 EDITION 抓取 ============================
EDITION = os.environ.get("EDITION", "evening").lower()
result = {"international": [], "politics_mil": [], "culture_edu_health": [], "sports": []}

if EDITION in ("morning", "all"):
    # 境外 RSS（BBC/DW/Reuters/AP，线上 runner 可抓）+ 境内国际 RSS（国内可访问，兜底）
    intl_urls = [s["url"] for s in SOURCES.get("international", [])] + INTL_RSS
    result["international"] = top_n(fetch_rss(intl_urls), n=15)

if EDITION in ("evening", "all"):
    # 国内时政·军事：央视时政/社会/军事网页 + 国内 RSS 补充，军事优先
    pm_web = fetch_domestic(POLITICS_MIL_URLS, limit=15)
    pm_rss = fetch_rss_domestic(DOMESTIC_RSS, per=15)
    result["politics_mil"] = merge_dedup(pm_web + pm_rss, n=15)

    # 文教卫：文化 + 教育 + 卫生健康 三个垂直频道，人民网教育/文化 RSS 兜底
    edu_web = fetch_domestic(EDU_URLS, limit=15)
    edu_rss = fetch_rss_domestic(EDU_RSS, per=15)
    result["culture_edu_health"] = merge_dedup(edu_web + edu_rss, n=15)

    # 体育：央视体育频道 + 人民网/中新网体育 RSS（网页条数偏少，RSS 补足以保证时长）
    sp_web = fetch_domestic(SPORTS_URLS, limit=15)
    sp_rss = fetch_rss_domestic(SPORTS_RSS, per=15)
    result["sports"] = merge_dedup(sp_web + sp_rss, n=15)

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"EDITION={EDITION}")
for cat in ("international", "politics_mil", "culture_edu_health", "sports"):
    items = result[cat]
    n_sum = sum(1 for x in items if x.get("summary"))
    n_mil = sum(1 for x in items if is_military(x))
    print(f"  [{cat}] {len(items)} 条（带摘要 {n_sum}，军事 {n_mil}）")
    for i, it in enumerate(items[:8], 1):
        extra = " ★军事" if is_military(it) else ""
        print(f"    {i}. {it['title']}{extra}")
