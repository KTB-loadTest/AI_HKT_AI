from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Optional, Tuple, Iterable

from google import genai
from google.genai import types

from app.core.config import settings

log = logging.getLogger("book-trailer-ai")


# -------------------------
# Client / helpers
# -------------------------
def _client():
    proj = (settings.GOOGLE_CLOUD_PROJECT or "").strip()
    loc = (settings.GOOGLE_CLOUD_LOCATION or "").strip()

    if (not proj) or (proj == "your-gcp-project-id"):
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set or still placeholder (your-gcp-project-id). "
            "Set GOOGLE_CLOUD_PROJECT in .env to your real GCP project id."
        )
    if not loc:
        raise RuntimeError("GOOGLE_CLOUD_LOCATION not set (e.g., asia-northeast3).")

    # NOTE: retry 비활성화 옵션은 SDK 버전에 따라 무시될 수 있음.
    return genai.Client(vertexai=True, project=proj, location=loc)


def _get(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_gs_uri(gs_uri: str) -> Tuple[str, str]:
    # gs://bucket/path/to/object.mp4
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// uri: {gs_uri}")
    path = gs_uri[len("gs://") :]
    bucket, _, blob = path.partition("/")
    if not bucket or not blob:
        raise ValueError(f"Invalid gs:// uri: {gs_uri}")
    return bucket, blob


def _download_gcs_bytes(gs_uri: str) -> bytes:
    """
    Veo 결과가 gs:// 로 내려오는 케이스 대응:
    저장(업로드)하는 게 아니라, 생성된 결과를 '다운로드'만 해서 bytes로 반환.
    """
    from google.cloud import storage  # pip: google-cloud-storage

    bucket_name, blob_name = _parse_gs_uri(gs_uri)
    gcs = storage.Client(project=settings.GOOGLE_CLOUD_PROJECT)
    blob = gcs.bucket(bucket_name).blob(blob_name)
    return blob.download_as_bytes()


def _inline_bytes(container: Any) -> Optional[bytes]:
    """
    다양한 Veo 응답 구조에서 영상 bytes 추출:
    - bytesBase64Encoded (base64 문자열)
    - bytes / video_bytes / content / data 등(환경별 차이)
    """
    if container is None:
        return None

    candidates = (
        _get(container, "video_bytes"),
        _get(container, "bytes"),
        _get(container, "content"),
        _get(container, "data"),
    )
    for value in candidates:
        if value:
            if isinstance(value, (bytes, bytearray)):
                return bytes(value)
            if isinstance(value, str):
                # 일부 케이스에서 bytes가 아니라 문자열이 오기도 함(방어적 처리)
                return value.encode("utf-8")

    b64_value = _get(container, "bytesBase64Encoded")
    if isinstance(b64_value, str) and b64_value.strip():
        try:
            return base64.b64decode(b64_value)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("Failed to decode Veo base64 payload") from exc

    return None


def _extract_video_bytes_from_op(op: Any) -> bytes:
    """
    operation(op)에서 실제 mp4 bytes를 최대한 견고하게 추출한다.
    - RAI 필터링 감지(raiMediaFilteredCount)
    - videos[0] 자체에 bytesBase64Encoded가 오는 케이스 지원
    - videos[0].video.* / uri(gs://) 케이스 지원
    """
    resp = _get(op, "response", op)

    if resp is None:
        err = _get(op, "error", None) or _get(op, "errors", None)
        raise RuntimeError(f"Veo response is None. error={err} op={repr(op)[:800]}")

    # ✅ RAI 필터링 감지 (영상 bytes가 내려오지 않는 대표 케이스)
    rai_count = _get(resp, "raiMediaFilteredCount", 0) or 0
    if isinstance(rai_count, (int, float)) and rai_count > 0:
        raise RuntimeError(f"RAI_FILTERED: raiMediaFilteredCount={rai_count}")

    # 1) generated_videos (혹시 있는 경우)
    gvs = _get(resp, "generated_videos")
    if gvs:
        first = gvs[0]
        video = _get(first, "video")

        vb = _inline_bytes(video)
        if vb:
            return vb

        uri = _get(video, "gcsUri") or _get(video, "gcs_uri") or _get(video, "uri")
        if isinstance(uri, str) and uri.startswith("gs://"):
            log.info("VEO returned gs:// uri (generated_videos). downloading: %s", uri)
            return _download_gcs_bytes(uri)

    # 2) videos (현재 가장 흔한 케이스)
    vids = _get(resp, "videos")
    if vids:
        first = vids[0]

        # ✅ videos[0] 자체에 bytesBase64Encoded/mimeType만 오는 케이스
        vb = _inline_bytes(first)
        if vb:
            return vb

        # (a) videos[0].video.* 형태
        video_obj = _get(first, "video", None)
        if video_obj is not None:
            vb = _inline_bytes(video_obj)
            if vb:
                return vb

            uri = _get(video_obj, "gcsUri") or _get(video_obj, "gcs_uri") or _get(video_obj, "uri")
            if isinstance(uri, str) and uri.startswith("gs://"):
                log.info("VEO returned gs:// uri (video). downloading: %s", uri)
                return _download_gcs_bytes(uri)

        # (b) videos[0].gcsUri / videos[0].uri 형태
        uri = _get(first, "gcsUri") or _get(first, "gcs_uri") or _get(first, "uri")
        if isinstance(uri, str) and uri.startswith("gs://"):
            log.info("VEO returned gs:// uri (videos[0]). downloading: %s", uri)
            return _download_gcs_bytes(uri)

        # (c) dict 구조 디버깅 힌트
        if isinstance(first, dict):
            raise RuntimeError(
                f"Veo videos[0] has no bytes; keys={list(first.keys())}. "
                f"Full response keys={list(resp.keys()) if isinstance(resp, dict) else type(resp)}"
            )

    # 3) 여기까지 오면 예상 외 포맷
    if isinstance(resp, dict):
        raise RuntimeError(f"Unexpected Veo response dict keys: {list(resp.keys())}")
    raise RuntimeError(f"Unexpected Veo response type: {type(resp)}")


# -------------------------
# Prompt helpers (Veo-ready)
# -------------------------
DEFAULT_NEGATIVE = (
    "text, subtitles, captions, logo, watermark, UI overlay, speech bubble, "
    "low quality, blurry, distorted, extra limbs, deformed faces"
)


def build_veo_prompt(video_prompt_en: str, negative_prompt_en: Optional[str] = None) -> str:
    """
    Veo는 config에 negative_prompt가 없을 수도 있어서
    '프롬프트 문장 자체'에 금지사항을 강제 주입하는 방식으로 안정화.
    """
    neg = (negative_prompt_en or "").strip()
    if not neg:
        neg = DEFAULT_NEGATIVE

    return (
        f"{video_prompt_en.strip()}\n\n"
        "Constraints: No on-screen text, no subtitles/captions, no logos, "
        "no watermarks, no UI overlays, no speech bubbles. "
        f"Negative: {neg}."
    )


# -------------------------
# Core: generate clip bytes
# -------------------------
async def generate_clip_bytes(
    prompt: str,
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    fps: int,
    *,
    poll_interval: int = 10,
    max_polls: int = 90,  # 15분 상한
) -> bytes:
    """
    Veo LRO(장기 실행 작업) 생성 → 같은 operation 상태를 polling → 최종 bytes 추출.
    - generate_videos()는 딱 1번만 호출(재생성 재시도 없음)
    - 이후는 operations.get()으로 상태 조회만 수행(추가 과금 없음)
    """
    client = _client()

    # ✅ 영상만 생성하도록 고정하고 싶으면 여기에 generate_audio=False를 켜면 됨
    # (SDK 버전에 따라 필드명이 다를 수 있어, 에러 나면 dict 강제 주입 방식으로 바꾸기)
    config = types.GenerateVideosConfig(
        number_of_videos=1,
        fps=fps,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        enhance_prompt=True,
        # generate_audio=False,  # ✅ 필요 시 활성화
    )

    op = await client.aio.models.generate_videos(
        model=settings.VEO_MODEL,
        prompt=prompt,
        config=config,
    )

    for _ in range(max_polls):
        done = bool(_get(op, "done", False))
        resp = _get(op, "response", None)
        err = _get(op, "error", None) or _get(op, "errors", None)

        if err:
            raise RuntimeError(f"Veo operation error: {err}")

        if done and resp is not None:
            break

        log.info("VEO polling... done=%s response=%s", done, "yes" if resp is not None else "no")
        await asyncio.sleep(poll_interval)
        op = await client.aio.operations.get(op)

    # 마지막 점검
    resp = _get(op, "response", None)
    err = _get(op, "error", None) or _get(op, "errors", None)
    if err:
        raise RuntimeError(f"Veo operation error: {err}")
    if resp is None:
        raise RuntimeError(f"Veo done but response is None. op_type={type(op)} op_repr={repr(op)[:800]}")

    video_bytes = _extract_video_bytes_from_op(op)
    log.info("VEO clip ready (%d bytes)", len(video_bytes))
    return video_bytes


# -------------------------
# Cut-level APIs
# -------------------------
async def generate_cut_clip_bytes(
    video_prompt_en: str,
    negative_prompt_en: Optional[str],
    *,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration_seconds: int = 4,
    fps: int = 24,
) -> bytes:
    """
    스토리보드 컷(영상 프롬프트) → Veo 클립 bytes 생성
    """
    prompt = build_veo_prompt(video_prompt_en, negative_prompt_en)
    return await generate_clip_bytes(
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration_seconds=duration_seconds,
        fps=fps,
    )


async def generate_cuts_clips_bytes(
    cuts: Iterable[Any],
    *,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    fps: int = 24,
    concurrency: int = 2,
) -> list[bytes]:
    """
    여러 컷을 연속/병렬로 생성.
    cuts는 StoryboardCut 같은 객체/딕셔너리 iterable을 받는다고 가정하고
    아래 키를 조회:
      - video_prompt_en
      - negative_prompt_en (optional)
      - duration_seconds (default=4)
    """
    cuts_list = list(cuts)  # iterable 1회 소비 방지
    sem = asyncio.Semaphore(max(1, concurrency))
    out: list[Optional[bytes]] = [None] * len(cuts_list)

    async def _one(i: int, cut: Any):
        async with sem:
            vp = _get(cut, "video_prompt_en") or _get(cut, "scene_en")
            if not vp:
                raise ValueError(f"cut[{i}] missing video_prompt_en/scene_en")

            neg = _get(cut, "negative_prompt_en")
            dur = int(_get(cut, "duration_seconds", 4) or 4)

            log.info("VEO generating cut %d (duration=%ss)", i + 1, dur)
            out[i] = await generate_cut_clip_bytes(
                video_prompt_en=str(vp),
                negative_prompt_en=str(neg) if neg else None,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=dur,
                fps=fps,
            )

    await asyncio.gather(*[_one(i, c) for i, c in enumerate(cuts_list)])
    return [b for b in out if b is not None]
