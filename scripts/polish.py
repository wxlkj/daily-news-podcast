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
    max_tokens=8000,
)

script = resp.choices[0].message.content
with open("script.txt", "w", encoding="utf-8") as f:
    f.write(script)

print(f"文稿已生成，约 {len(script)} 字")
