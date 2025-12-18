from __future__ import annotations
import os
import subprocess
from typing import List

from app.core.config import settings


def _run(cmd: List[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed\nCMD: {' '.join(cmd)}\nSTDERR:\n{p.stderr}")


def mux_video_audio(
    video_path: str,
    audio_path: str,
    out_path: str,
    target_seconds: int,
) -> None:
    """
    영상(mp4) + 오디오(mp3)를 합쳐 최종 mp4 생성.
    - 영상은 copy(재인코딩 최소화)
    - 오디오는 aac로 인코딩
    - 길이는 target_seconds로 맞춤 (오디오 짧으면 apad, 길면 atrim)
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    _run([
        settings.FFMPEG_PATH,
        "-y",
        "-i", video_path,
        "-i", audio_path,
        "-t", str(target_seconds),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-af", f"apad,atrim=0:{target_seconds}",
        "-shortest",
        out_path,
    ])
