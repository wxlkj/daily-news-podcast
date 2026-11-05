#!/usr/bin/env python3
"""用 Edge TTS 把每个类目的文稿朗读为 MP3，再转码为 64kbps 单声道以省空间。

遍历当前目录下所有 script_<cat>.txt，逐个生成 episode_<cat>.mp3，
转码为 episode_final_<cat>.mp3（供 publish.py 托管到 Pages）。
"""
import asyncio
import glob
import os
import subprocess
import edge_tts

VOICE = "zh-CN-YunxiNeural"  # 男声，沉稳新闻感；备选 zh-CN-XiaoxiaoNeural


async def synth(text, out_mp3):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(out_mp3)


def main():
    scripts = sorted(glob.glob("script_*.txt"))
    if not scripts:
        print("!! 未找到任何 script_*.txt，TTS 中止")
        return
    for sc in scripts:
        cat = sc[len("script_"):-len(".txt")]  # e.g. international / sports
        text = open(sc, encoding="utf-8").read().strip()
        if not text:
            print(f"[skip] {sc} 为空，跳过")
            continue
        raw = f"episode_{cat}.mp3"
        final = f"episode_final_{cat}.mp3"
        print(f"→ 合成 {cat}（{len(text)} 字）…")
        asyncio.run(synth(text, raw))
        subprocess.run(
            ["ffmpeg", "-y", "-i", raw, "-b:a", "64k", "-ac", "1", final],
            check=True,
        )
        size = os.path.getsize(final)
        est_min = size * 8 / 64000 / 60
        print(f"✓ {cat} 音频已生成：{final}（{size} 字节，约 {est_min:.1f} 分钟）")


if __name__ == "__main__":
    main()
