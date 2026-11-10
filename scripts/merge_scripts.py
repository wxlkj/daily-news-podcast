#!/usr/bin/env python3
"""把四个类目的口语稿合并成一篇、并重编号为全局连续的「第1条…第N条」。

fetch_news.py 抓全四类 → polish.py 为每类生成 script_<cat>.txt
（每段各自从「第1条」开始、无来源、无收尾）→ 本脚本按固定顺序拼接四段，
用正则把每段自己的「第N条」整体重编号为跨全篇连续的「第1条…第N条」，
得到 script_combined.txt，交给 tts.py 合成单个 MP3、publish.py 发布单集。

整合后不插入任何类目小标题/过渡语（仅段间换行留自然停顿），
直接以「第1条」开头、连续编号到结尾，符合「第几条新闻直接说 1,2,3…」的要求。
"""
import re
import sys

# 整合后全局编号的先后：国际 → 国内时政军事 → 文教卫 → 体育
# 想换顺序改这一处即可（键须与 fetch_news.py / polish.py 的 CATS 一致）。
ORDER = ["international", "politics_mil", "culture_edu_health", "sports"]

# 段首编号：第[一二三四五六七八九十百零〇两\d]+条[：:]
_HEAD = re.compile(r"第[一二三四五六七八九十百零〇两\d]+条\s*[：:]")


def read_segment(cat):
    """读取某类目的口语稿；不存在或为空返回 None（跳过该类目）。"""
    path = f"script_{cat}.txt"
    try:
        text = open(path, encoding="utf-8").read().strip()
    except FileNotFoundError:
        return None
    return text or None


def renumber(text):
    """把整段里所有「第N条」按出现顺序重编号为连续的「第1条…第N条」。"""
    counter = {"n": 0}

    def _repl(m):
        counter["n"] += 1
        return f"第{counter['n']}条："

    return _HEAD.sub(_repl, text), counter["n"]


def main():
    segments = []
    for cat in ORDER:
        seg = read_segment(cat)
        if seg:
            segments.append(seg)
        else:
            print(f"[skip] {cat}：无文稿，跳过")

    if not segments:
        print("!! 没有任何类目文稿，合并中止", file=sys.stderr)
        sys.exit(1)

    # 段间仅用换行连接：TTS 在此处自然停顿，但不念出任何类目标签。
    combined = "\n".join(segments)

    combined, total = renumber(combined)
    out = "script_combined.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(combined + "\n")

    # 自检：编号必须严格 1..N 连续、无跳号、无重复
    heads = _HEAD.findall(combined)
    expected = [f"第{i}条：" for i in range(1, total + 1)]
    ok = heads == expected
    print(f"✓ 整合文稿已生成（{out}），共 {total} 条，{len(combined)} 字"
          f"{'  [校验OK 编号连续]' if ok else '  [警告] 编号不连续: ' + str(heads[:5])}")
    if not ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
