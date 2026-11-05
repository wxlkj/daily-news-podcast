#!/usr/bin/env python3
"""调用 DeepSeek（OpenAI 兼容接口）把每个类目的新闻条目分别润色成独立口语稿。

读取 news.json，对其中每个非空类目：
  - 加载对应的 prompt_<cat>.md 作为 system 提示
  - 生成 script_<cat>.txt
每篇独立控制 10–20 分钟时长（提示词约束 + 字数软校验），无评论。
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


def generate(prompt_template, items, label):
    """带限流重试地调用模型，返回文稿文本。"""
    user_content = (
        f"【{label}新闻条目】\n"
        f"{json.dumps(items, ensure_ascii=False, indent=2)}"
    )
    last_err = None
    for attempt in range(4):
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": prompt_template},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.7,
                max_tokens=7000,
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
        out = f"script_{cat}.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(script)
        n = len(script)
        if n < 2600:
            tail = " [警告] 偏短，朗读可能不足 10 分钟"
        elif n > 5200:
            tail = " [警告] 偏长，朗读可能超过 20 分钟"
        else:
            tail = " [时长区间OK]"
        print(f"✓ {label} 文稿已生成（{out}），约 {n} 字{tail}")


if __name__ == "__main__":
    main()
