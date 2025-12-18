from __future__ import annotations
from google.cloud import texttospeech


async def synthesize_narration_mp3_bytes(narration_script: str) -> bytes:
    """
    Cloud Text-to-Speech로 나레이션을 생성하고 mp3 bytes로 반환한다.
    (GCS 저장/URL 생성 없음)
    """
    client = texttospeech.TextToSpeechClient()

    synthesis_input = texttospeech.SynthesisInput(text=narration_script)
    voice = texttospeech.VoiceSelectionParams(
        language_code="ko-KR",
        name="ko-KR-Standard-A",
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    resp = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return resp.audio_content
