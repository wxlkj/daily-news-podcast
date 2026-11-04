#!/usr/bin/env python3
"""用 Edge TTS 把文稿朗读为 MP3，再转码为 64kbps 单声道以省空间。"""
import asyncio
import subprocess
import edge_tts

VOICE = "zh-CN-YunxiNeural"  # 男声，沉稳新闻感；备选 zh-CN-XiaoxiaoNeural


async def main():
    text = open("script.txt", encoding="utf-8").read()
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save("episode.mp3")


asyncio.run(main())

# 重编码为 64kbps 单声道
subprocess.run(
    ["ffmpeg", "-y", "-i", "episode.mp3", "-b:a", "64k", "-ac", "1", "episode_final.mp3"],
    check=True,
)
print("音频已生成：episode_final.mp3")
