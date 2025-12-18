from __future__ import annotations

import base64
import os
from typing import Iterable, List

from google import genai
from google.genai import types

from app.core.config import settings
from app.models.schemas import Cut
from app.services.storage import write_bytes


def _client():
    if not settings.GOOGLE_CLOUD_PROJECT:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT not set")
    return genai.Client(
        vertexai=True,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.GOOGLE_CLOUD_LOCATION,
    )


def _extract_png_bytes(img_resp) -> bytes:
    """
    Vertex AI 이미지 응답에서 bytes를 최대한 견고하게 추출.
    - 환경/버전에 따라 b64 필드명이 다를 수 있어서 여러 케이스를 커버.
    """
    # 보통 첫 번째 이미지
    data0 = getattr(img_resp, "data", None)
    if not data0:
        raise RuntimeError("Imagen response has no data")

    item0 = data0[0]

    # 1) b64_json (OpenAI 스타일과 유사)
    b64_json = getattr(item0, "b64_json", None)
    if b64_json:
        return base64.b64decode(b64_json)

    # 2) 일부 응답은 bytes 필드가 직접 있을 수 있음
    image_bytes = getattr(item0, "image_bytes", None)
    if image_bytes:
        # bytes면 그대로, str이면 base64일 수 있음
        if isinstance(image_bytes, (bytes, bytearray)):
            return bytes(image_bytes)
        return base64.b64decode(image_bytes)

    # 3) dict 형태로 내려오는 경우
    if isinstance(item0, dict):
        if "b64_json" in item0 and item0["b64_json"]:
            return base64.b64decode(item0["b64_json"])
        if "image_bytes" in item0 and item0["image_bytes"]:
            v = item0["image_bytes"]
            if isinstance(v, (bytes, bytearray)):
                return bytes(v)
            return base64.b64decode(v)

    raise RuntimeError("Could not extract image bytes from Imagen response")


async def generate_cut_images_to_dir(
    cuts: Iterable[Cut],
    out_dir: str,
    *,
    generate_images: bool = True,
) -> List[str]:
    """
    generate_images=False 이면 Imagen 호출 자체를 하지 않고 빈 리스트 반환
    """
    if not generate_images:
        return []

    client = _client()
    paths: List[str] = []

    os.makedirs(out_dir, exist_ok=True)

    for i, cut in enumerate(cuts, start=1):
        prompt = (cut.image_prompt_en or cut.scene_en or "").strip()
        if not prompt:
            continue

        img = await client.aio.models.generate_images(
            model=settings.IMAGEN_MODEL,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
            ),
        )

        png_bytes = _extract_png_bytes(img)
        path = os.path.join(out_dir, f"cut_{i:02d}.png")
        write_bytes(path, png_bytes)
        paths.append(path)

    return paths



async def generate_cut_images_discard(
    cuts: Iterable[Cut],
    *,
    generate_images: bool = True,
) -> None:
    """
    generate_images=False 이면 Imagen API를 아예 호출하지 않음
    """
    if not generate_images:
        return

    client = _client()

    for cut in cuts:
        prompt = (cut.image_prompt_en or cut.scene_en or "").strip()
        if not prompt:
            continue

        await client.aio.models.generate_images(
            model=settings.IMAGEN_MODEL,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
            ),
        )
