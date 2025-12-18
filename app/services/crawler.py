"""
Playwright : 실제 브라우저로 페이지 열어 JS 렌더링까지 반영한 HTML 얻음 -> 동적 페이지에서 본문 뽑기 가능
readability : 복잡한 HTML에서 본문만 추출
BeautifulSoup : 추출된 HTML에서 태그 제거 후 텍스트만 뽑기


"""



from __future__ import annotations

from typing import List, Tuple

from bs4 import BeautifulSoup
from readability import Document
from playwright.async_api import async_playwright

from app.models.schemas import CrawlSource

KEYWORDS = ["줄거리", "책소개", "시놉시스", "소개", "내용", "요약"]


def _extract_main_text(html: str) -> Tuple[str, str]:
    doc = Document(html)
    title = doc.short_title() or ""
    cleaned_html = doc.summary(html_partial=True)

    soup = BeautifulSoup(cleaned_html, "lxml")
    text = soup.get_text("\n", strip=True)
    return text, title


def _keep_relevant(text: str, max_chars: int = 20000) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    picked: List[str] = []

    for ln in lines:
        if any(k in ln for k in KEYWORDS):
            picked.append(ln)
        elif 40 <= len(ln) <= 500:
            picked.append(ln)

        if sum(len(x) for x in picked) > max_chars:
            break

    if not picked:
        return text[:max_chars]
    return "\n".join(picked)[:max_chars]


async def crawl_synopsis_pages(
    urls: List[str],
    max_pages: int,
    timeout_sec: int,
) -> tuple[str, List[CrawlSource]]:
    """
    urls를 순회하며 페이지를 렌더링(Playwright)하고,
    본문 텍스트를 추출(readability)한 뒤,
    줄거리로 보이는 텍스트만 모아 corpus로 반환한다.
    """
    corpus_parts: List[str] = []
    sources: List[CrawlSource] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        for u in urls[:max_pages]:
            try:
                await page.goto(u, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
                html = await page.content()

                text, title = _extract_main_text(html)
                kept = _keep_relevant(text)

                if kept.strip():
                    corpus_parts.append(kept)
                    sources.append(CrawlSource(url=u, ok=True, chars=len(kept), title=title))
                else:
                    sources.append(CrawlSource(url=u, ok=False, chars=0, title=title))
            except Exception:
                sources.append(CrawlSource(url=u, ok=False, chars=0, title=None))

        await context.close()
        await browser.close()

    corpus = "\n\n---\n\n".join(corpus_parts)
    return corpus, sources
