#!/usr/bin/env python3
"""用 Edge TTS 把整合文稿朗读为单个 MP3，再转码为 64kbps 单声道以省空间。

读取 script_combined.txt（由 merge_scripts.py 产出），合成 episode_final.mp3，
供 publish.py 托管到 Pages（单集：覆盖当天四类新闻、全局连续编号）。
"""
import asyncio
import os
import subprocess
import edge_tts

VOICE = "zh-CN-YunxiNeural"  # 男声，沉稳新闻感；备选 zh-CN-XiaoxiaoNeural

SRC = "script_combined.txt"
RAW = "episode.mp3"
FINAL = "episode_final.mp3"


async def synth(text, out_mp3):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(out_mp3)


def main():
    if not os.path.exists(SRC):
        print(f"!! 未找到 {SRC}（请先运行 fetch → polish → merge_scripts），TTS 中止")
        raise SystemExit(1)
    text = open(SRC, encoding="utf-8").read().strip()
    if not text:
        print(f"[skip] {SRC} 为空，跳过")
        raise SystemExit(1)
    print(f"→ 合成整集（{len(text)} 字）…")
    asyncio.run(synth(text, RAW))
    subprocess.run(
        ["ffmpeg", "-y", "-i", RAW, "-b:a", "64k", "-ac", "1", FINAL],
        check=True,
    )
    size = os.path.getsize(FINAL)
    est_min = size * 8 / 64000 / 60
    print(f"✓ 整集音频已生成：{FINAL}（{size} 字节，约 {est_min:.1f} 分钟）")


if __name__ == "__main__":
    main()
