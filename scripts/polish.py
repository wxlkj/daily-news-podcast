#!/usr/bin/env python3
"""调用 DeepSeek（OpenAI 兼容接口）把新闻条目润色成单集口语稿，含权威评论引用。"""
import os
import json
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url="https://api.deepseek.com",
)

prompt_template = open("prompt.md", encoding="utf-8").read()
data = json.load(open("news.json", encoding="utf-8"))

user_content = (
    f"【国内新闻条目】\n{json.dumps(data['domestic'], ensure_ascii=False, indent=2)}\n\n"
    f"【国际新闻条目】\n{json.dumps(data['international'], ensure_ascii=False, indent=2)}\n\n"
    f"【权威评论素材（仅作引用参考，须标注来源）】\n"
    f"{json.dumps(data['commentary'], ensure_ascii=False, indent=2)}"
)

resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": user_content},
    ],
    temperature=0.7,
    # 硬上限保护：约 20 分钟对应的 token 量，避免输出过长为时长超上限
    max_tokens=7000,
)

script = resp.choices[0].message.content
with open("script.txt", "w", encoding="utf-8") as f:
    f.write(script)

n = len(script)
print(f"文稿已生成，约 {n} 字")
# 时长软校验：2800~4800 字约为 10~20 分钟区间
if n < 2600:
    print(f"[警告] 文稿偏短（{n} 字），朗读可能不足 10 分钟，请检查新闻素材是否过少")
elif n > 5200:
    print(f"[警告] 文稿偏长（{n} 字），朗读可能超过 20 分钟，建议缩短")
