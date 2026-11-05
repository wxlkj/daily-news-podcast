#!/usr/bin/env python3
"""调用 DeepSeek（OpenAI 兼容接口）把每个类目的新闻条目分别润色成独立口语稿。

读取 news.json，对其中每个非空类目：
  - 加载对应的 prompt_<cat>.md 作为 system 提示
  - 生成 script_<cat>.txt
每篇独立控制 10–20 分钟时长（提示词约束 + 字数硬下限 + 过短重试），无评论。
"""
import os
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

# 字数约束：实测中文 TTS 约 4.2 字/秒 → 10 分钟≈2520 字。
# 设置硬性下限，过短则重试展开，确保最终时长≥10 分钟。
HARD_MIN = 3600      # 低于此值强制重试
WARN_LOW = 3400      # 低于此值仍警告（重试后若仍偏短）
WARN_HIGH = 5500     # 高于此值警告可能超 20 分钟


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
                max_tokens=9000,
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
        prompt_template = open(prompt_file, encoding="utf-8").read()

        script = generate(prompt_template, items, label)

        # 过短则重试：要求覆盖更多条目并展开具体事实
        if len(script) < HARD_MIN:
            for r in range(1, 3):
                print(f"  [展开] {label} 仅 {len(script)} 字(<{HARD_MIN})，第 {r} 次重试扩充…")
                extra = (
                    f"（重要）你刚才生成的文稿只有约 {len(script)} 字，"
                    f"远未达到「不少于 {HARD_MIN} 字、时长 10 分钟以上」的硬性要求。"
                    f"请重新生成：①尽可能多覆盖提供的条目（10–15 条）；"
                    f"②把每条的关键事实（时间、地点、涉及方、数字、背景）充分展开说清楚；"
                    f"③确保全文达到至少 {HARD_MIN} 字。"
                )
                script = generate(prompt_template, items, label, extra=extra)
                if len(script) >= HARD_MIN:
                    break

        out = f"script_{cat}.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(script)
        n = len(script)
        if n < WARN_LOW:
            tail = f" [警告] 偏短({n}字)，朗读可能不足 10 分钟"
        elif n > WARN_HIGH:
            tail = f" [警告] 偏长({n}字)，朗读可能超过 20 分钟"
        else:
            tail = " [时长区间OK]"
        print(f"✓ {label} 文稿已生成（{out}），约 {n} 字{tail}")


if __name__ == "__main__":
    main()
