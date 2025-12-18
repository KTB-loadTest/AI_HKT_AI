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
    IMAGEN_MODEL: str = "imagen-3.0-fast"
    VEO_MODEL: str = "veo-3.0-fast"


settings = Settings()
