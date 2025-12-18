from __future__ import annotations

import math
import os
import logging
import traceback

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from starlette.responses import JSONResponse

from app.core.logging import setup_logging
from app.models.schemas import GenerateTrailerRequest
from app.services.naver import NaverClient, collect_synopsis_links
from app.services.book_select import choose_best_book
from app.services.crawler import crawl_synopsis_pages
from app.services.llm_storyboard import make_storyboard
from app.services.imagen import generate_cut_images_to_dir  # discard는 이제 호출 안 함
from app.services.veo import generate_cut_clip_bytes  # ✅ 컷 단위 생성 함수로 교체
from app.services.tts import synthesize_narration_mp3_bytes
from app.services.storage import create_job_dir, write_bytes, cleanup_job_dir
from app.services.ffmpeg_video import concat_and_trim
from app.services.ffmpeg_mux import mux_video_audio

setup_logging()
log = logging.getLogger("book-trailer-ai")

app = FastAPI(title="book-trailer-ai (mp4 direct response)")


# =========================
# Logging helpers (STEP3/4 artifacts)
# =========================
def _log_multiline(prefix: str, text: str, limit: int = 1200) -> None:
    if not text:
        log.info("%s <empty>", prefix)
        return

    t = text.strip()
    if len(t) > limit:
        t = t[:limit] + f"\n...(truncated {len(text) - limit} chars)"

    for line in t.splitlines():
        line = line.strip()
        if line:
            log.info("%s %s", prefix, line)


def log_step3_artifacts(
    corpus: str,
    sources: list,
    corpus_preview_chars: int = 1200,
    max_sources: int = 8,
) -> None:
    log.info("STEP 3 ARTIFACTS: corpus_len=%d | sources=%d", len(corpus or ""), len(sources or []))
    _log_multiline("STEP3 corpus>>", corpus, limit=corpus_preview_chars)

    if sources:
        log.info("STEP3 sources>> (showing up to %d)", max_sources)
        for i, s in enumerate(sources[:max_sources], start=1):
            log.info("STEP3 source[%d] %s", i, s)


def log_step4_artifacts(
    storyboard,
    max_cuts: int = 8,
    synopsis_limit: int = 1200,
    narration_limit: int = 600,
    video_prompt_limit: int = 220,
) -> None:
    cuts = getattr(storyboard, "cuts", []) or []
    narration = getattr(storyboard, "narration_script", "") or ""

    log.info("STEP 4 ARTIFACTS: cuts=%d | narration_len=%d", len(cuts), len(narration))

    _log_multiline("STEP4 synopsis_ko>>", getattr(storyboard, "synopsis_ko", "") or "", limit=synopsis_limit)
    _log_multiline("STEP4 synopsis_en>>", getattr(storyboard, "synopsis_en", "") or "", limit=synopsis_limit)
    _log_multiline("STEP4 narration>>", narration, limit=narration_limit)

    log.info("STEP4 cuts>> (showing up to %d)", max_cuts)
    for c in cuts[:max_cuts]:
        idx = getattr(c, "index", None)
        scene = getattr(c, "scene_en", "") or ""
        vp = getattr(c, "video_prompt_en", "") or ""
        neg = getattr(c, "negative_prompt_en", "") or ""
        dur = getattr(c, "duration_seconds", None)

        log.info("CUT #%s duration=%s scene_en=%s", idx, dur, scene)
        if vp:
            preview = vp[:video_prompt_limit] + ("...(trunc)" if len(vp) > video_prompt_limit else "")
            log.info("CUT #%s video_prompt_en=%s", idx, preview)
        else:
            log.info("CUT #%s video_prompt_en=<empty>", idx)

        if neg:
            log.info("CUT #%s negative_prompt_en=%s", idx, neg)


# =========================
# API
# =========================
@app.post("/api/v1/trailer:generate")
async def generate_trailer(req: GenerateTrailerRequest, bg: BackgroundTasks):
    """
    Returns: video/mp4 (binary)
    """
    log.info("STEP 0: request received")

    job_dir = create_job_dir()
    log.info("JOB START | job_dir=%s | title=%s | author=%s", job_dir, req.title, req.author)

    try:
        # STEP 1 ─ Naver book search
        log.info("STEP 1: Naver book search")
        naver = NaverClient()
        book_json = await naver.search_books(
            f"{req.title} {req.author}",
            display=req.top_n_books,
        )

        selected = choose_best_book(
            book_json.get("items", []),
            req.title,
            req.author,
        )
        log.info("STEP 1 DONE: selected book = %s / %s", selected.title, selected.author)

        # STEP 2 ─ Collect synopsis links
        log.info("STEP 2: Collect synopsis links from Naver")
        links = await collect_synopsis_links(
            naver=naver,
            title=selected.title,
            author=selected.author,
            per_query_display=30,
            max_links=30,
        )

        if not links:
            raise HTTPException(status_code=404, detail="No synopsis pages found")

        log.info("STEP 2 DONE: collected %d links", len(links))

        # STEP 3 ─ Crawl synopsis pages
        log.info(
            "STEP 3: Crawl synopsis pages (max_pages=%d, timeout=%ds)",
            req.max_synopsis_pages,
            req.crawl_timeout_sec,
        )

        corpus, sources = await crawl_synopsis_pages(
            urls=links,
            max_pages=req.max_synopsis_pages,
            timeout_sec=req.crawl_timeout_sec,
        )

        if not corpus.strip():
            raise HTTPException(status_code=422, detail="Extracted synopsis corpus is empty")

        log.info("STEP 3 DONE: corpus length=%d chars | sources=%d", len(corpus), len(sources))

        log_step3_artifacts(
            corpus=corpus,
            sources=sources,
            corpus_preview_chars=1200,
            max_sources=8,
        )

        # ---- clip planning ----
        clip_duration = int(getattr(req, "clip_duration_seconds", 4) or 4)
        target_seconds = int(getattr(req, "target_seconds", 30) or 30)
        required_cuts = max(1, math.ceil(target_seconds / clip_duration))

        # req.cut_count가 부족하면 30초를 채울 수 없으므로 자동 상향
        requested_cut_count = int(getattr(req, "cut_count", required_cuts) or required_cuts)
        cut_count = max(requested_cut_count, required_cuts)

        if cut_count != requested_cut_count:
            log.info(
                "CUT COUNT ADJUSTED: requested=%d, required=%d (target=%ds, clip=%ds) -> using=%d",
                requested_cut_count,
                required_cuts,
                target_seconds,
                clip_duration,
                cut_count,
            )

        # STEP 4 ─ LLM storyboard (Veo-ready)
        log.info("STEP 4: Generate storyboard (cuts=%d, clip_duration=%ds)", cut_count, clip_duration)
        storyboard = await make_storyboard(
            corpus,
            cut_count=req.cut_count,
            target_seconds=req.target_seconds,          # ✅ 추가
            clip_duration_seconds=req.clip_duration_seconds,
        )

        log.info("STEP 4 DONE: cuts=%d | narration_len=%d", len(storyboard.cuts), len(storyboard.narration_script))

        log_step4_artifacts(
            storyboard=storyboard,
            max_cuts=min(len(storyboard.cuts), 8),
        )

        # STEP 5 ─ Optional Imagen (generate_cut_images=false면 절대 호출 X)
        if bool(getattr(req, "generate_cut_images", False)):
            log.info("STEP 5: Generate cut images (Imagen)")
            try:
                out_dir = os.path.join(job_dir, "imagen_cuts")
                paths = await generate_cut_images_to_dir(
                    storyboard.cuts,
                    out_dir=out_dir,
                    generate_images=True,  # ✅ 명시
                )
                log.info("STEP 5 DONE: saved %d pngs to %s", len(paths), out_dir)
            except Exception:
                log.warning("STEP 5 FAILED: Imagen error (ignored)", exc_info=True)
        else:
            log.info("STEP 5 SKIPPED: generate_cut_images=false")

        # STEP 6 ─ Veo clip generation (컷마다 4초씩)
        log.info(
            "STEP 6: Generate Veo clips per cut | cuts=%d | duration=%ds",
            len(storyboard.cuts),
            clip_duration,
        )

        clip_paths: list[str] = []

        for i, cut in enumerate(storyboard.cuts, start=1):
            log.info("STEP 6.%d: Veo cut clip START", i)

            video_prompt = (getattr(cut, "video_prompt_en", "") or "").strip()
            if not video_prompt:
                # 비어 있으면 scene_en으로라도 채움
                video_prompt = (getattr(cut, "scene_en", "") or "").strip()

            negative_prompt = (getattr(cut, "negative_prompt_en", "") or "").strip() or None
            dur = int(getattr(cut, "duration_seconds", clip_duration) or clip_duration)

            try:
                clip_bytes = await generate_cut_clip_bytes(
                    video_prompt_en=video_prompt,
                    negative_prompt_en=negative_prompt,
                    aspect_ratio=req.aspect_ratio,
                    resolution=req.resolution,
                    duration_seconds=dur,
                    fps=req.fps,
                )
            except RuntimeError as e:
                msg = str(e)
                if ("filtered" in msg.lower()) or ("rai" in msg.lower()) or ("raimediafiltered" in msg.lower()):
                    log.warning("STEP 6.%d FAILED: Veo RAI filtered: %s", i, msg)
                    raise HTTPException(status_code=422, detail=f"Veo output filtered (RAI). {msg}")
                raise

            clip_path = os.path.join(job_dir, f"cut_{i:02d}.mp4")
            write_bytes(clip_path, clip_bytes)
            clip_paths.append(clip_path)

            log.info("STEP 6.%d DONE: clip saved (%s, %d bytes)", i, clip_path, len(clip_bytes))

        # STEP 7 ─ ffmpeg concat + trim
        log.info("STEP 7: ffmpeg concat + trim (target=%ds)", target_seconds)
        merged_path = os.path.join(job_dir, f"merged_{target_seconds}s.mp4")
        concat_and_trim(clip_paths, target_seconds=target_seconds, out_path=merged_path)
        log.info("STEP 7 DONE: merged video = %s", merged_path)

        # STEP 8 ─ TTS
        log.info("STEP 8: TTS narration")
        mp3_bytes = await synthesize_narration_mp3_bytes(storyboard.narration_script)
        audio_path = os.path.join(job_dir, "narration.mp3")
        write_bytes(audio_path, mp3_bytes)
        log.info("STEP 8 DONE: narration saved (%d bytes)", len(mp3_bytes))

        # STEP 9 ─ mux video + audio
        log.info("STEP 9: ffmpeg mux video + audio")
        muxed_path = os.path.join(job_dir, f"final_{target_seconds}s.mp4")
        mux_video_audio(merged_path, audio_path, target_seconds=target_seconds, out_path=muxed_path)
        log.info("STEP 9 DONE: final mp4 = %s", muxed_path)

        # cleanup after response
        bg.add_task(cleanup_job_dir, job_dir)

        final_name = (
            f"{req.title}_trailer_{target_seconds}s.mp4".replace(" ", "_")
            if (req.title or "").strip()
            else f"trailer_{target_seconds}s.mp4"
        )

        log.info("JOB DONE | returning mp4")
        return FileResponse(
            path=muxed_path,
            media_type="video/mp4",
            filename=final_name,
            background=bg,
        )

    except Exception:
        log.exception("JOB FAILED")
        bg.add_task(cleanup_job_dir, job_dir)
        raise


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request, exc: FastAPIHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "trace": traceback.format_exc()},
    )
