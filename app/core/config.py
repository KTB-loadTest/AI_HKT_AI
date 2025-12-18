# app/core/config.py
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ===== Local temp / ffmpeg =====
    TEMP_DIR: str = "./.tmp"
    KEEP_TEMP: bool = False
    FFMPEG_PATH: str = "ffmpeg"

    # ===== Naver =====
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""

    # ===== Google / Vertex =====
    GOOGLE_CLOUD_PROJECT: str = ""
    GOOGLE_CLOUD_LOCATION: str = "us-central1"

    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    VEO_MODEL: str = "veo-3.0-fast"

    # ===== Trailer defaults =====
    DEFAULT_TOP_N_BOOKS: int = 5
    DEFAULT_MAX_SYNOPSIS_PAGES: int = 8
    DEFAULT_CRAWL_TIMEOUT_SEC: int = 15

    DEFAULT_CUT_COUNT: int = 8
    DEFAULT_CLIP_DURATION_SECONDS: int = 4
    DEFAULT_FPS: int = 24
    DEFAULT_ASPECT_RATIO: str = "9:16"
    DEFAULT_RESOLUTION: str = "720p"
    DEFAULT_TARGET_SECONDS: int = 32

    # ===== Narration pacing =====
    NARRATION_BASE_CHARS_PER_SEC: float = 11.0
    NARRATION_MAX_SPEAKING_RATE: float = 1.3


settings = Settings()
