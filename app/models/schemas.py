from pydantic import BaseModel, Field
from typing import List, Optional


class GenerateTrailerRequest(BaseModel):
    title: str
    author: str

    top_n_books: int = Field(5, ge=1, le=20)
    max_synopsis_pages: int = Field(8, ge=1, le=30)
    crawl_timeout_sec: int = Field(15, ge=5, le=60)

    cut_count: int = Field(8, ge=3, le=15)

    # Veo Fast clips
    clip_duration_seconds: int = Field(8, ge=4, le=8)
    fps: int = Field(24, ge=12, le=60)
    aspect_ratio: str = Field("9:16")
    resolution: str = Field("720p")

    # final length
    target_seconds: int = Field(30, ge=10, le=60)

    # optional: generate images (not returned)
    generate_cut_images: bool = False

    generate_cut_images: bool = Field(default=False, description="If true, generate cut images with Imagen (non-fatal).")
class SelectedBook(BaseModel):
    title: str
    author: str
    publisher: Optional[str] = None
    pubdate: Optional[str] = None
    isbn: Optional[str] = None
    naver_link: Optional[str] = None


class Cut(BaseModel):
    index: int
    scene_en: str
    image_prompt_en: str


class StoryboardLLMOutput(BaseModel):
    synopsis_ko: str
    synopsis_en: str
    narration_script: str
    cuts: List[Cut]


class CrawlSource(BaseModel):
    url: str
    ok: bool
    chars: int = 0
    title: Optional[str] = None
