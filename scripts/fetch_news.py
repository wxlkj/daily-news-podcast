#!/usr/bin/env python3
"""抓取分类新闻，只保留「过去 N 小时」（默认 24）内发布的新闻，按 EDITION 输出。

  - morning : 仅国际新闻（供早上 06:00 发布）
  - evening : 国内时政·军事 + 文教卫 + 体育（供晚上 20:00 发布）
  - all     : 抓取全部四类（调试用，默认 evening）

信源策略：
  - 骨架：中国新闻网(chinanews.com.cn) 多类目 RSS，其 <pubDate> 时间戳准确(带+0800)、每条带真实摘要。
  - 补充：央视各频道网页抓取，按文章 URL 中的日期路径(cctv.com/YYYY/MM/DD/)做天粒度过滤，
    补充实时、带军事/体育热点的条目（央视网页条目多无摘要，故排序时摘要优先）。
  - 国际：境外 RSS（BBC/德国之声/Reuters/AP，线上 runner 可直达）+ 中新网国际兜底。
  - 已移除人民网：其 RSS 的 <pubDate> 是固定假常量(2025-06-05)，无法做时间过滤。

去重策略（2026-11-08 强化）：
  - 类目内：URL 规范化 + 标题规范化 + 标题相似度（最长公共连续字串 / 整体相似度）判定同一事件，
    重复组里保留「带摘要、时间新」的一条，避免同一事件的滚动报道被当成多条。
  - 跨类目：晚间三类目按「专门类目优先」（体育 → 文教卫 → 时政军事）认领条目，
    同一事件只留在最贴切的类目，避免同一条新闻出现在两篇简报里。

时间过滤：
  - 所有时间以「北京时间(Asia/Shanghai, UTC+8)」为基准，与用户的播报时区一致。
  - RSS 条目用 <pubDate> 精确过滤；网页条目用 URL 日期做天粒度过滤。
  - 丢弃未来时间（时钟偏差）与超出窗口的条目。
"""
import os
import re
import json
import email
import difflib
import yaml
import socket
import feedparser
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

# 防止不可达的源卡死整个流程
socket.setdefaulttimeout(12)

SHANGHAI = timezone(timedelta(hours=8))


def now_shanghai():
    """以北京时间(UTC+8)为基准的当前时间。"""
    return datetime.now(timezone.utc).astimezone(SHANGHAI)


SOURCES = yaml.safe_load(open("config/sources.yaml"))
HOURS = int(str(SOURCES.get("hours", os.environ.get("WINDOW_HOURS", 24))))
NOW = now_shanghai()
WINDOW = timedelta(hours=HOURS)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 军事/国防相关关键词：命中则视为"军事新闻"，在时政·军事类目排序中优先入选
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


def to_dt(iso):
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=SHANGHAI)


def in_window_rss(dt):
    """RSS 条目：基于精确时间戳判断是否在窗口内。"""
    if dt is None:
        return False
    if dt > NOW + timedelta(hours=1):   # 未来时间（时钟偏差），丢弃
        return False
    return (NOW - dt) <= WINDOW


def in_window_web(date_obj):
    """网页条目：基于 URL 日期（天粒度）判断是否在窗口内。

    与 RSS 不同，网页只有发布日期没有时刻，故按「日期 >= (现在-窗口).date()」
    过滤，保留当天及（若当前为凌晨）昨日的条目，避免把"今天的新闻"误判为未来。
    """
    if date_obj is None:
        return False
    return date_obj >= (NOW - WINDOW).date()


# ----------------------------- RSS 抓取（带时间过滤）-----------------------------
def parse_published(entry):
    """尽力解析条目发布时间：优先用 feedparser 的结构化字段，
    缺失时回退到字符串日期解析（部分境外源只提供 updated 或字符串）。"""
    for key in ("published_parsed", "updated_parsed"):
        pp = entry.get(key)
        if pp:
            return datetime(*pp[:6], tzinfo=timezone.utc).astimezone(SHANGHAI)
    for key in ("published", "updated", "pubDate"):
        s = entry.get(key)
        if not s:
            continue
        try:
            dt = email.utils.parsedate_to_datetime(s)
            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(SHANGHAI)
        except Exception:
            continue
    return None


def fetch_rss_feeds(feeds):
    items = []
    for f in feeds:
        try:
            d = feedparser.parse(f["url"])
            for e in d.entries:
                dt = parse_published(e)
                if not in_window_rss(dt):
                    continue
                title = clean(e.get("title", ""))
                if not title:
                    continue
                summary = clean(e.get("summary", e.get("description", "")))[:400]
                items.append({
                    "title": title,
                    "summary": summary,
                    "published": dt.isoformat(),
                    "url": e.get("link", ""),
                    "source": f.get("name", ""),
                })
        except Exception as ex:
            print(f"[warn] RSS 失败 {f.get('url')}: {ex}")
    return items


# ----------------------------- 央视网页抓取（按 URL 日期过滤）-----------------------------
def parse_page(url):
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
            y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            g = groups.setdefault(href, {"date": datetime(y, mo, dd).date(), "texts": []})
            g["texts"].append(t)
        for href, g in groups.items():
            texts = [t for t in g["texts"] if 4 <= len(t) <= 300]
            if not texts:
                continue
            if not in_window_web(g["date"]):
                continue
            title = min(texts, key=len)
            summary = max(texts, key=len)
            summary = summary if summary != title else ""
            pub = datetime(g["date"].year, g["date"].month, g["date"].day, 12, 0, tzinfo=SHANGHAI)
            items.append({"title": title, "summary": summary,
                          "published": pub.isoformat(), "url": href, "source": "央视"})
    except Exception as e:
        print(f"[warn] 网页抓取失败 {url}: {e}")
    return items


# ----------------------------- 去重与选取 -----------------------------
def norm_title(s):
    """标题规范化：去空白标点、去栏目/来源前缀，只留中英文数字，供相似度比较。"""
    s = re.sub(r"\s+", "", s or "")
    s = re.sub(r"^【[^】]{0,12}】", "", s)
    s = re.sub(r"^\[[^\]]{0,12}\]", "", s)
    s = re.sub(r"^(?:独家|快讯|突发|重磅|最新|视频|图文|组图|直播|专访|评论|关注|热点)[：:]?", "", s)
    s = re.sub(
        r"^(?:中新网|中新社|新华社|人民网|央视网|央视新闻|央视|环球网|参考消息|中国新闻网|"
        r"路透社|法新社|美联社|共同社|BBC|CNN)[^：:|｜]{0,6}[：:|｜]?", "", s)
    return re.sub(r"\W", "", s, flags=re.UNICODE).lower()


def url_key(u):
    u = (u or "").split("?")[0].split("#")[0].rstrip("/")
    return re.sub(r"^https?://", "", u).lower()


def same_event(a, b):
    """判定两条是否为同一事件：URL 相同 / 标题相同 / 标题高度相似。"""
    ua, ub = url_key(a.get("url")), url_key(b.get("url"))
    if ua and ua == ub:
        return True
    ta, tb = norm_title(a.get("title")), norm_title(b.get("title"))
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    # 一方是另一方的子串：网页抓取常产生短标题碎片，与完整标题指同一篇报道
    if min(len(ta), len(tb)) >= 8 and (ta in tb or tb in ta):
        return True
    sm = difflib.SequenceMatcher(None, ta, tb)
    # 最长公共连续字串足够长、且几乎占满较短标题 → 几乎就是同一个标题的改写。
    # 阈值刻意收紧：只合并"明显同一篇报道"的写法，避免把「高考报名通知」「高考体检通知」
    # 这类前半句相同、实为两条不同新闻的条目误杀掉。
    m = sm.find_longest_match(0, len(ta), 0, len(tb))
    return m.size >= 12 and m.size >= 0.8 * min(len(ta), len(tb))


def sort_unique(items):
    """类目内去重：先按「带摘要优先 + 时间倒序」排序，重复组保留信息最全的一条。"""
    ordered = sorted(items, key=lambda x: (
        0 if x.get("summary") else 1,
        -to_dt(x.get("published", "")).timestamp(),
    ))
    kept = []
    for it in ordered:
        if any(same_event(it, k) for k in kept):
            continue
        kept.append(it)
    return kept


def claim_cross_category(pools, order):
    """跨类目去重：按「专门类目优先」依次认领，同一事件只留在最贴切的类目。

    order 中越靠前的类目越专门（体育 > 文教卫 > 时政军事），
    这样泛 RSS 里串进来的体育/教育条目会归到专门类目，不会在两篇简报里重复播报。
    """
    claimed = []
    removed = {}
    for cat in order:
        if cat not in pools:
            continue
        kept, n_drop = [], 0
        for it in pools[cat]:
            if any(same_event(it, c) for c in claimed):
                n_drop += 1
                continue
            kept.append(it)
            claimed.append(it)
        pools[cat] = kept
        removed[cat] = n_drop
    return removed


def select(items, n, military_first=False):
    """排序后取前 n：时政·军事类目下军事优先，其余按摘要完整度与时间倒序。"""
    items = sorted(items, key=lambda x: (
        (0 if is_military(x) else 1) if military_first else 0,
        0 if x.get("summary") else 1,
        -to_dt(x.get("published", "")).timestamp(),
    ))
    return items[:n]


# ============================ 按 EDITION 抓取 ============================
EDITION = os.environ.get("EDITION", "evening").lower()
# 认领顺序：越专门的类目越先认领（同一事件不会被两篇简报重复播报）
CLAIM_ORDER = ["sports", "culture_edu_health", "politics_mil", "international"]


def main():
    result = {"international": [], "politics_mil": [], "culture_edu_health": [], "sports": []}

    if EDITION in ("morning", "all"):
        intl_rss = SOURCES.get("international", {}).get("rss", [])
        result["international"] = select(sort_unique(fetch_rss_feeds(intl_rss)), n=25)

    if EDITION in ("evening", "all"):
        pools = {}

        pm = SOURCES.get("politics_mil", {})
        pm_items = fetch_rss_feeds(pm.get("rss", []))
        for w in pm.get("web", []):
            pm_items += parse_page(w["url"])
        pools["politics_mil"] = pm_items

        ceh = SOURCES.get("culture_edu_health", {})
        # 文教卫以中新网 RSS 为骨架即已充足，不再叠加央视网页（其文化/健康子域不稳定）
        pools["culture_edu_health"] = fetch_rss_feeds(ceh.get("rss", []))

        sp = SOURCES.get("sports", {})
        sp_items = fetch_rss_feeds(sp.get("rss", []))
        for w in sp.get("web", []):
            sp_items += parse_page(w["url"])
        pools["sports"] = sp_items

        before = {c: len(v) for c, v in pools.items()}
        pools = {c: sort_unique(v) for c, v in pools.items()}
        dropped = claim_cross_category(pools, CLAIM_ORDER)

        result["politics_mil"] = select(pools["politics_mil"], n=18, military_first=True)
        result["culture_edu_health"] = select(pools["culture_edu_health"], n=18)
        result["sports"] = select(pools["sports"], n=18)
        for c in pools:
            print(f"[去重] {c}: {before[c]} → 类目内去重 {len(pools[c])} → 跨类目移除 {dropped.get(c,0)}")

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"EDITION={EDITION}  时区=Asia/Shanghai  窗口={HOURS}小时  现在={NOW.strftime('%Y-%m-%d %H:%M')}")
    for cat in ("international", "politics_mil", "culture_edu_health", "sports"):
        items = result[cat]
        n_sum = sum(1 for x in items if x.get("summary"))
        n_mil = sum(1 for x in items if is_military(x))
        print(f"  [{cat}] {len(items)} 条（带摘要 {n_sum}，军事 {n_mil}）")
        for i, it in enumerate(items[:6], 1):
            extra = " ★军事" if is_military(it) else ""
            src = f"[{it.get('source','')}]"
            print(f"    {i}. {src} {it['title']}{extra}")


if __name__ == "__main__":
    main()
