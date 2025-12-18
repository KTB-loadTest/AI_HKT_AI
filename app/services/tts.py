from __future__ import annotations

from google.cloud import texttospeech

from app.core.config import settings


def _estimate_speaking_rate(script: str, target_seconds: int) -> float:
    """
    Roughly estimate how long the narration would take and bump the speaking rate
    if it is likely to exceed the target video length.
    """
    if not target_seconds or target_seconds <= 0:
        return 1.0

    effective_chars = sum(1 for c in (script or "") if not c.isspace())
    estimated_seconds = max(
        1.0,
        effective_chars / max(settings.NARRATION_BASE_CHARS_PER_SEC, 1e-3),
    )

    if estimated_seconds <= target_seconds:
        return 1.0

    rate = estimated_seconds / target_seconds
    return min(rate, settings.NARRATION_MAX_SPEAKING_RATE)


async def synthesize_narration_mp3_bytes(
    narration_script: str,
    target_seconds: int,
) -> bytes:
    """
    Cloud Text-to-Speech로 나레이션을 생성하고 mp3 bytes로 반환한다.
    필요 시 speaking_rate를 높여 target_seconds 안에 수렴하도록 시도한다.
    """
    client = texttospeech.TextToSpeechClient()

    speaking_rate = _estimate_speaking_rate(narration_script, target_seconds)

    synthesis_input = texttospeech.SynthesisInput(text=narration_script)
    voice = texttospeech.VoiceSelectionParams(
        language_code="ko-KR",
        name="ko-KR-Standard-A",
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
    )

    resp = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return resp.audio_content
