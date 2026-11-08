#!/usr/bin/env python3
"""调用 DeepSeek（OpenAI 兼容接口）把每个类目的新闻条目分别润色成独立口语稿。

读取 news.json，对其中每个非空类目：
  - 加载对应的 prompt_<cat>.md 作为 system 提示
  - 生成 script_<cat>.txt
每条新闻只用 1–2 句话讲清核心事实，不设字数/时长下限、不做「嫌短就重写扩充」，
避免为凑时长而注水、铺陈或重复（2026-11-08 调整）。
成品只保留逐条新闻内容：不说来源、无开场白、无结尾套话（双层清洗兜底）。
"""
import os
import re
import json
import time
from openai import OpenAI, RateLimitError, APIError

client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.deepseek.com",
)

# 类目 -> (prompt 文件, 中文标签)
CATS = {
    "international": ("prompt_intl.md", "国际新闻"),
    "politics_mil": ("prompt_politics_mil.md", "国内时政·军事"),
    "culture_edu_health": ("prompt_edu.md", "文教卫"),
    "sports": ("prompt_sports.md", "体育"),
}

# 不再设字数/时长下限：篇幅由新闻条数自然决定，宁短勿注水。
# 下面这个系数仅用于日志里估算朗读时长（实测中文 TTS 约 4.2–4.8 字/秒）。
CHARS_PER_SEC = 4.5

# 结尾套话：仅当「最后一句」较短且整句命中时才丢弃，避免误伤最后一条新闻正文
_CLOSING_PATTERNS = [
    r"全部内容",
    r"以上是[^。\n]{0,25}(简报|播报|新闻|报道|内容|播送)",
    r"以上就是",
    r"(本期|今日|今天|本日)[^。\n]{0,20}(简报|播报|新闻)[^。\n]{0,12}(到此|结束|完毕|就到这里)",
    r"[^。\n]{0,12}(简报|播报|新闻)[^。\n]{0,8}(到此|结束|完毕|播送完毕)",
    r"感谢(您|大家|各位)?[^。\n]{0,8}(收听|收看|聆听|关注|陪伴)",
    r"(下期|明天|下次|下回|我们)[^。\n]{0,10}(再见|再会|不见不散|继续收听)",
    r"欢迎(您|大家|各位)?[^。\n]{0,12}(收听|订阅|继续收听|收看)",
]

# 来源/电头前缀：只清理「一段文本开头」，用 ^ 锚定，绝不误伤正文中的机构名
_ELECTRIC_SRC = re.compile(
    r"^\s*(?:中新网|中新社|新华社|人民网|央视网|央视|环球网|参考消息网|中国新闻网|路透社|法新社|美联社|共同社|BBC|CNN)?"
    r"[^\d，。\n]{0,8}?\d{1,2}月\d{1,2}日(?:电|讯|消息|报道)[，,]?\s*"
)
_QUOTE_SRC = re.compile(
    r"^\s*(?:据|综合|另据|又据)[^，。\n：:]{0,24}?(?:报道|消息|电|讯|称|获悉|了解)[，,]?\s*"
    r"|^\s*(?:据悉|据了解|据介绍|综合报道|综合外媒报道|另据报道)[，,]?\s*"
)
_BRACKET_SRC = re.compile(r"[（(]\s*(?:来源|消息来源)[:：]?[^）)]{0,30}[）)]\s*")
# 开头的短括注：记者署名、「新华社发」等图片/电头署名，剥掉（^ 锚定、限长，避免误伤正文括号）
_LEAD_PAREN_SRC = re.compile(r"^\s*[（(][^）)]{0,20}[）)]\s*")
_LINE_HEAD = re.compile(r"^(\s*第[一二三四五六七八九十百零〇两\d]+条\s*[：:]\s*)(.*)$")


def strip_source(text):
    """剥掉一段文本开头的来源/电头前缀（可多重嵌套）。"""
    if not text:
        return text
    prev = None
    while text != prev:
        prev = text
        text = _ELECTRIC_SRC.sub("", text, count=1)
        text = _QUOTE_SRC.sub("", text, count=1)
        text = _BRACKET_SRC.sub("", text)
        text = _LEAD_PAREN_SRC.sub("", text, count=1)
    return text.strip()


def clean_script(text):
    """兜底清洗：砍掉开场白、来源字样、结尾套话，成品只保留逐条新闻内容。"""
    if not text:
        return text
    t = text.strip()
    # 1) 去 Markdown 强调/标题符号
    t = re.sub(r"[*`#]+", "", t)
    # 2) 以第一个「第N条：」为正文起点，砍掉之前所有开场白/问候/栏目名/日期铺垫
    m = re.search(r"第[一二三四五六七八九十百零〇两\d]+条\s*[：:]", t)
    if m and m.start() > 0:
        t = t[m.start():]
    # 3) 逐行剥掉条首/句首的来源前缀与电头（保留「第N条：」编号）
    lines = []
    for ln in t.split("\n"):
        hm = _LINE_HEAD.match(ln)
        if hm:
            lines.append(hm.group(1) + strip_source(hm.group(2)))
        else:
            lines.append(strip_source(ln))
    t = "\n".join(lines)
    # 4) 丢弃结尾套话句（从末尾往前，仅短句且命中特征才删）
    parts = re.split(r"(?<=[。！？\n])", t)
    while parts:
        last = parts[-1].strip()
        if not last:
            parts.pop()
            continue
        if len(last) <= 45 and any(re.search(p, last) for p in _CLOSING_PATTERNS):
            parts.pop()
            continue
        break
    return "".join(parts).strip()


def generate(prompt_template, items, label, extra=""):
    """带限流重试地调用模型，返回文稿文本。extra 为追加的强化指令。"""
    user_content = (
        f"【{label}新闻条目】\n"
        f"{json.dumps(items, ensure_ascii=False, indent=2)}"
    )
    system = prompt_template
    if extra:
        system = prompt_template.rstrip() + "\n\n" + extra
    last_err = None
    for attempt in range(4):
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.7,
                max_tokens=6000,
            )
            return resp.choices[0].message.content
        except (RateLimitError, APIError) as e:
            last_err = e
            if attempt < 3:
                wait = 5 * (2 ** attempt)
                print(f"  [retry] {label} 限流/错误，{wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                raise
    raise last_err


def main():
    data = json.load(open("news.json", encoding="utf-8"))
    for cat, (prompt_file, label) in CATS.items():
        items = data.get(cat, [])
        if not items:
            print(f"[skip] {label}：无新闻条目，跳过")
            continue
        print(f"→ 生成 {label}（{len(items)} 条候选）…")
        # ① 注入前清洗：只保留标题/摘要/时间，并剥掉摘要自带的电头与来源前缀，
        #    让模型根本看不到「新闻来源」，从源头避免念出来源。
        items = [
            {
                "title": strip_source(it.get("title", "")),
                "summary": strip_source(it.get("summary", "")),
                "published": it.get("published", ""),
            }
            for it in items
        ]
        prompt_template = open(prompt_file, encoding="utf-8").read()

        # 一次成稿，不因「偏短」而重写扩充：宁可短，也不要为凑时长注水。
        script = generate(prompt_template, items, label)

        # ② 生成后兜底清洗：确保「直接第一条、只有内容、无来源、无收尾套话」
        before = len(script)
        script = clean_script(script)
        if before != len(script):
            print(f"  [清洗] {label} 去除开场/来源/收尾共 {before - len(script)} 字")
        print(f"  [首/尾] {label}: 「{script[:16]}」…「{script[-16:]}」")

        out = f"script_{cat}.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(script)
        n = len(script)
        minutes = n / CHARS_PER_SEC / 60
        print(f"✓ {label} 文稿已生成（{out}），约 {n} 字，估算朗读 {minutes:.1f} 分钟（不设时长下限）")


if __name__ == "__main__":
    main()
