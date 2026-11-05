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

# 字数约束：实测中文 TTS 约 4.2–4.8 字/秒 → 10 分钟≈2520–2880 字。
# 硬性下限随当天条数自适应：条数少则下调（避免强行注水编造），条数多则保底 3600 字（≈13 分钟）。
WARN_LOW = 3000      # 低于此值警告可能不足 10 分钟
WARN_HIGH = 5200     # 高于此值警告可能超过 20 分钟


def hard_min(n_items):
    """根据当天条数计算字数硬下限：至少 3000 字（≈10 分钟），至多 3600 字。"""
    return min(3600, max(3000, n_items * 400))


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
        HARD_MIN = hard_min(len(items))

        script = generate(prompt_template, items, label)

        # 过短则多次重试：给出按条数折算的硬性字数目标，要求每条铺开具体事实
        if len(script) < HARD_MIN:
            per = max(250, HARD_MIN // max(1, len(items)))  # 每条至少应写的字数
            for r in range(1, 6):
                print(f"  [展开] {label} 仅 {len(script)} 字(<{HARD_MIN})，第 {r} 次重试扩充…")
                extra = (
                    f"（非常重要）你刚才的文稿只有约 {len(script)} 字，"
                    f"远未达到「不少于 {HARD_MIN} 字、朗读 10 分钟以上」的硬性要求，这是绝不允许的。\n"
                    f"请重新撰写：当前共有 {len(items)} 条新闻，请为【每一条】都写满约 {per}–{per+100} 字、"
                    f"把该条的时间、地点、涉及方、数字、背景、来龙去脉用完整连贯的口语充分展开，"
                    f"不要只复述标题或摘要原话，也不要省略任何一条。全文合计必须达到至少 {HARD_MIN} 字。"
                    f"逐条编号、逐条写满，是确保时长的关键。"
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
