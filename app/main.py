from __future__ import annotations

import logging
import math
import os

from fastapi import FastAPI, HTTPException, BackgroundTasks, Response, Request
from fastapi.responses import FileResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException

from app.core.config import settings
from app.core.logging import setup_logging
from app.models.schemas import GenerateTrailerRequest
from app.services.naver import NaverClient, collect_synopsis_links
from app.services.book_select import choose_best_book
from app.services.crawler import crawl_synopsis_pages
from app.services.llm_storyboard import make_storyboard
from app.services.veo import generate_cut_clip_bytes
from app.services.tts import synthesize_narration_mp3_bytes
from app.services.storage import create_job_dir, write_bytes, cleanup_job_dir
from app.services.ffmpeg_video import concat_and_trim
from app.services.ffmpeg_mux import mux_video_audio


print("ddd")

setup_logging()
log = logging.getLogger("book-trailer-ai")

app = FastAPI(title="book-trailer-ai")


def _log_multiline(prefix: str, text: str, limit: int = 1200) -> None:
    if not text:
        log.info("%s <empty>", prefix)
        return

    t = text.strip()
    if len(t) > limit:
        t = t[:limit] + f"\n...(truncated {len(text) - limit} chars)"

    for line in t.splitlines():
        if line.strip():
            log.info("%s %s", prefix, line.strip())


def _is_rai_filtered_error(msg: str) -> bool:
    m = (msg or "").lower()
    return ("rai" in m) or ("filtered" in m) or ("raimediafiltered" in m)


def _clean_negative_prompt(neg: str | None) -> str | None:
    t = (neg or "").strip()
    return t or None


def _soften_video_prompt(original: str, max_chars: int = 420, strength: str = "normal") -> str:
    """
    Veo RAI에 덜 걸리도록 프롬프트를 '안전/평화/비폭력' 톤으로 완화.
    - normal: 기본 완화(품질 유지)
    - strong: 더 강한 완화(필터 걸렸을 때 재시도용)
    """
    core = (original or "").strip()

    if strength == "strong":
        safe_prefix = (
            "Ultra family-friendly, cheerful, cozy cinematic scene. "
            "Soft pastel lighting, gentle slow camera movement, calm wholesome mood. "
            "Absolutely no violence, no weapons, no blood, no injury, no fear, no threats, no crime, "
            "no conflict, no chasing, no falling, no danger, no scary imagery. "
            "Only peaceful actions like walking, smiling, looking around, reading, holding hands, "
            "breathing calmly, enjoying nature. "
            "No on-screen text, no subtitles, no captions, no speech bubbles, no logos, no watermarks, "
            "no UI overlays. "
        )
    else:
        safe_prefix = (
            "Family-friendly, calm, heartwarming cinematic scene. "
            "Gentle atmosphere, cozy mood, soft lighting, smooth camera motion. "
            "No violence, no weapons, no blood, no injury, no fear, no threats, no crime. "
            "No scary imagery. "
            "No on-screen text, no subtitles, no captions, no speech bubbles, no logos, no watermarks, "
            "no UI overlays. "
        )

    out = (safe_prefix + core).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out


@app.post("/api/v1/trailer/jobs")
async def create_trailer_job(req: GenerateTrailerRequest, bg: BackgroundTasks, request: Request):
    
    raw = await request.body()
    print("RAW BODY bytes=%d text=%s", len(raw), raw.decode("utf-8", errors="replace"))
    log.info("PARSED | title=%s | author=%s", req.title, req.author)
    #log.info("REQUEST | title=%s | author=%s", req.title, req.author)
    job_dir = create_job_dir()

    try:
        # ----- defaults -----
        top_n_books = settings.DEFAULT_TOP_N_BOOKS
        max_synopsis_pages = settings.DEFAULT_MAX_SYNOPSIS_PAGES
        crawl_timeout_sec = settings.DEFAULT_CRAWL_TIMEOUT_SEC
        clip_duration = settings.DEFAULT_CLIP_DURATION_SECONDS  # <- 4 유지
        target_seconds = settings.DEFAULT_TARGET_SECONDS
        aspect_ratio = settings.DEFAULT_ASPECT_RATIO
        resolution = settings.DEFAULT_RESOLUTION
        fps = settings.DEFAULT_FPS
        requested_cut_count = settings.DEFAULT_CUT_COUNT

        # STEP 1 ─ Naver search
        naver = NaverClient()
        book_json = await naver.search_books(
            f"{req.title} {req.author}",
            display=top_n_books,
        )

        selected = choose_best_book(
            book_json.get("items", []),
            req.title,
            req.author,
        )

        # STEP 2 ─ synopsis links
        links = await collect_synopsis_links(
            naver=naver,
            title=selected.title,
            author=selected.author,
            per_query_display=30,
            max_links=30,
        )
        if not links:
            raise HTTPException(
                status_code=404, 
                detail="No link exist"
            )

        # STEP 3 ─ crawl
        corpus, sources = await crawl_synopsis_pages(
            urls=links,
            max_pages=max_synopsis_pages,
            timeout_sec=crawl_timeout_sec,
        )
        if not corpus.strip():
            raise HTTPException(
                status_code=422,
                detail="Crawling Error: no usable synopsis text extracted"
            
            )


        # STEP 4 ─ cut planning
        required_cuts = max(1, math.ceil(target_seconds / clip_duration))
        cut_count = max(requested_cut_count, required_cuts)

        log.info(
            "STEP 4: cut plan | target_seconds=%d clip_duration=%d required_cuts=%d requested_cut_count=%d final_cut_count=%d",
            target_seconds, clip_duration, required_cuts, requested_cut_count, cut_count
        )

        storyboard = await make_storyboard(
            corpus,
            cut_count=cut_count,
            target_seconds=target_seconds,
            clip_duration_seconds=clip_duration,
        )

        log.info(
            "STEP 4 DONE: storyboard received | cuts=%d (expected=%d) narration_chars=%d",
            len(storyboard.cuts),
            cut_count,
            len(storyboard.narration_script or "")
        )

        # STEP 5 ─ Veo clips
        log.info("STEP 5 START: generating veo clips | cuts=%d", len(storyboard.cuts))
        clip_paths: list[str] = []

        for i, cut in enumerate(storyboard.cuts, start=1):
            log.info("STEP 5.%d/%d: Veo request start", i, len(storyboard.cuts))

            raw_prompt = (cut.video_prompt_en or cut.scene_en or "").strip()
            if not raw_prompt:
                raw_prompt = "A calm, heartwarming cinematic scene."

            # ✅ 항상 기본 완화 프롬프트로 1차 시도
            video_prompt = _soften_video_prompt(raw_prompt, strength="normal")
            negative_prompt = _clean_negative_prompt(getattr(cut, "negative_prompt_en", None))
            dur = int(clip_duration)

            log.info(
                "STEP 5.%d/%d: prompt lens | raw=%d softened=%d dur=%ds",
                i, len(storyboard.cuts), len(raw_prompt), len(video_prompt), dur
            )

            try:
                clip_bytes = await generate_cut_clip_bytes(
                    video_prompt_en=video_prompt,
                    negative_prompt_en=negative_prompt,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    duration_seconds=dur,
                    fps=fps,
                )
            except RuntimeError as exc:
                msg = str(exc)
                if _is_rai_filtered_error(msg):
                    log.warning("STEP 5.%d/%d: Veo RAI filtered on softened(normal): %s", i, len(storyboard.cuts), msg)

                    # ✅ 2차: 더 강한 완화 프롬프트로 재시도
                    video_prompt_strong = _soften_video_prompt(raw_prompt, strength="strong")
                    log.info(
                        "STEP 5.%d/%d: retry with softened(strong) (len=%d)",
                        i, len(storyboard.cuts), len(video_prompt_strong)
                    )

                    try:
                        clip_bytes = await generate_cut_clip_bytes(
                            video_prompt_en=video_prompt_strong,
                            negative_prompt_en=negative_prompt,
                            aspect_ratio=aspect_ratio,
                            resolution=resolution,
                            duration_seconds=dur,
                            fps=fps,
                        )
                    except RuntimeError as exc2:
                        msg2 = str(exc2)
                        if _is_rai_filtered_error(msg2):
                            log.warning("STEP 5.%d/%d: Veo RAI filtered again (strong): %s", i, len(storyboard.cuts), msg2)
                            raise HTTPException(status_code=422, detail=f"Veo output filtered (RAI). {msg2}")
                        raise
                else:
                    raise

            log.info("STEP 5.%d/%d: Veo clip saved | bytes=%d", i, len(storyboard.cuts), len(clip_bytes))
            clip_path = os.path.join(job_dir, f"cut_{i:02d}.mp4")
            write_bytes(clip_path, clip_bytes)
            clip_paths.append(clip_path)

        log.info("STEP 5 DONE: veo clips generated | clips=%d", len(clip_paths))

        # STEP 6 ─ concat + trim
        merged_path = os.path.join(job_dir, f"merged_{target_seconds}s.mp4")
        concat_and_trim(clip_paths, merged_path, target_seconds)

        # STEP 7 ─ TTS
        mp3_bytes = await synthesize_narration_mp3_bytes(
            storyboard.narration_script,
            target_seconds,
        )
        audio_path = os.path.join(job_dir, "narration.mp3")
        write_bytes(audio_path, mp3_bytes)

        # STEP 8 ─ mux
        final_path = os.path.join(job_dir, f"final_{target_seconds}s.mp4")
        mux_video_audio(
            merged_path,
            audio_path,
            final_path,
            target_seconds,
        )

        bg.add_task(cleanup_job_dir, job_dir)

        filename = f"{req.title}_trailer_{target_seconds}s.mp4".replace(" ", "_")
        return FileResponse(
            path=final_path,
            media_type="video/mp4",
            filename=filename,
            background=bg,
        )

    except HTTPException:
        bg.add_task(cleanup_job_dir, job_dir)
        raise
    except Exception:
        log.exception("JOB FAILED")
        bg.add_task(cleanup_job_dir, job_dir)
        raise HTTPException(status_code=500)


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(_, exc: FastAPIHTTPException):
    return Response(status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_, __):
    return Response(status_code=500)