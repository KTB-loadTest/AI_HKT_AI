from __future__ import annotations

from google import genai
from google.genai import types

from app.core.config import settings
from app.models.schemas import StoryboardLLMOutput


SYSTEM = """You are a storyboard writer for a short-form book trailer.
Return ONLY valid JSON matching the schema.

Rules:
- No dialogue in cuts (visual-only).
- Avoid spoilers; focus on premise, mood, characters, stakes.
- Each cut must be suitable for text-to-video generation (Veo).
- Video prompts must forbid any on-screen text, subtitles, captions, speech bubbles, logos, watermarks, UI overlays.
- Prefer cinematic camera language: shot type, lens feel, lighting, motion, mood, composition.
- narration_script MUST be natural Korean for TTS with punctuation that controls pacing (commas, periods).
"""







def _client():
    if not settings.GOOGLE_CLOUD_PROJECT:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT not set")
    return genai.Client(
        vertexai=True,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.GOOGLE_CLOUD_LOCATION,
    )


async def make_storyboard(
    raw_synopsis_corpus: str,
    cut_count: int,
    target_seconds: int,
    clip_duration_seconds: int = 4,
) -> StoryboardLLMOutput:
    """
    raw_synopsis_corpus 기반으로 스토리보드(JSON)를 생성한다.
    - target_seconds: 최종 영상 길이(예: 32)
    - narration_script를 target_seconds에 맞춰 최대한 근접하게 유도한다(±1~2초).
    """
    client = _client()
    schema = StoryboardLLMOutput.model_json_schema()

    # TTS 한국어는 보통 1초당 8~12자 정도(개인/문장/쉼표에 따라 변동)
    # 너무 빡빡하게 '글자 수'를 고정하지 말고, 초 단위 + 스타일 가이드를 함께 준다.
    min_sec = max(4, target_seconds - 2)
    max_sec = target_seconds + 2

    prompt = f"""
[RAW_SYNOPSIS_CORPUS]
{raw_synopsis_corpus}

[TARGET]
- final_video_seconds: {target_seconds}
- cut_count: {cut_count}
- each_cut_duration_seconds: {clip_duration_seconds}
- total_cut_seconds: {cut_count * clip_duration_seconds}

[OUTPUT REQUIREMENTS]
- synopsis_ko: 6~10 lines Korean summary
- synopsis_en: 6~10 lines English summary

- narration_script:
  - Korean TTS script designed to last about {target_seconds} seconds
  - Aim for {min_sec}~{max_sec} seconds spoken time in a natural Korean pace
  - Use punctuation to control pacing:
    - Use commas to create short pauses
    - Use periods to create clear sentence boundaries
  - Keep it cinematic and trailer-like (premise → mood → stakes → hook)
  - Do NOT include dialogue lines or quotation marks
  - Do NOT include any on-screen text instructions (that's for video prompts)

- cuts: exactly {cut_count} items
  - index: 1..{cut_count}
  - duration_seconds: exactly {clip_duration_seconds}
  - scene_en: 1 sentence, present tense, visual-only
  - video_prompt_en: detailed cinematic text-to-video prompt (Veo-ready)
    Include: subject, setting, time of day, mood, lighting, camera shot, camera motion, realism/style.
    Must explicitly forbid on-screen text/subtitles/logos/watermarks/UI/speech bubbles.
  - negative_prompt_en: short list of negatives (e.g., text, subtitles, watermark, logo, UI, speech bubble, low quality)

Return JSON only.
"""

    resp = await client.aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.6,
        ),
    )
    return StoryboardLLMOutput.model_validate_json(resp.text)