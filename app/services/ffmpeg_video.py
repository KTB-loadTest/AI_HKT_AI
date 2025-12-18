from __future__ import annotations
import os
import subprocess
from typing import List

from app.core.config import settings


def _run(cmd: List[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed\nCMD: {' '.join(cmd)}\nSTDERR:\n{p.stderr}")


def concat_and_trim(
    clip_paths: List[str],
    out_path: str,
    target_seconds: int,
) -> None:
    """
    여러 mp4 클립을 concat해서 하나의 영상으로 만든 뒤, target_seconds로 trim한다.
    출력은 '영상-only mp4' (오디오 없음)로 둔다.
    """
    if not clip_paths:
        raise ValueError("clip_paths is empty")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # ffmpeg concat demuxer용 list 파일 생성
    list_path = out_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            abs_p = os.path.abspath(p)
            f.write(f"file '{abs_p}'\n")

    # 1) concat (재인코딩 없이)
    merged_path = out_path + ".merged.mp4"
    _run([
        settings.FFMPEG_PATH,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        merged_path,
    ])

    # 2) trim (정확한 길이 위해 재인코딩)
    _run([
        settings.FFMPEG_PATH,
        "-y",
        "-i", merged_path,
        "-t", str(target_seconds),
        "-an",  # 오디오 제거(혹시 클립에 오디오가 있어도)
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        out_path,
    ])

    # 정리(선택)
    try:
        os.remove(list_path)
        os.remove(merged_path)
    except OSError:
        pass
