from __future__ import annotations
import httpx
from typing import Any, Dict, List, Set
from app.core.config import settings

from app.utils.text import strip_html

NAVER_API_BASE = "https://openapi.naver.com/v1/search"


class NaverClient:
    def __init__(self) -> None:
        if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
            raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET not set")

        self.headers = {
            "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
        }

    async def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{NAVER_API_BASE}/{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            return r.json()

    async def search_books(self, query: str, display: int = 10) -> Dict[str, Any]:
        return await self._get("book.json", {"query": query, "display": display})

    async def search_webkr(self, query: str, display: int = 10) -> Dict[str, Any]:
        return await self._get("webkr.json", {"query": query, "display": display})

    async def search_blog(self, query: str, display: int = 10) -> Dict[str, Any]:
        return await self._get("blog.json", {"query": query, "display": display})



def build_synopsis_queries(title: str, author: str | None = None) -> List[str]:
    """
    너무 빡센 쿼리(파이프 |, 따옴표 강제 등) 대신,
    한국 도서에서 잘 걸리는 키워드 조합을 여러 개로 나눠서 시도한다.
    """
    t = (title or "").strip()
    a = (author or "").strip()

    # 가장 잘 걸리는 조합들(순서 중요)
    base = [
        f"{t} 줄거리",
        f"{t} 책소개",
        f"{t} 시놉시스",
        f"{t} 내용",
        f"{t} 줄거리 요약",
        f"{t} 리뷰 줄거리",
    ]

    # 저자 포함(동명 도서/동명 웹문서 방지)
    if a:
        base = [
            f"{t} {a} 줄거리",
            f"{t} {a} 책소개",
            f"{t} {a} 시놉시스",
        ] + base

    # 너무 길면 검색 품질 떨어질 수 있어 title만 버전도 포함
    # (이미 base에 포함되어 있어 OK)
    return base


def _extract_links(items: list[dict]) -> List[str]:
    links: List[str] = []
    for it in items or []:
        link = (it.get("link") or "").strip()
        if link:
            links.append(link)
    return links


async def collect_synopsis_links(
    naver: "NaverClient",
    title: str,
    author: str | None = None,
    per_query_display: int = 20,
    max_links: int = 30,
) -> List[str]:
    """
    webkr + blog를 여러 완화된 query로 반복 검색해서 링크를 모은다.
    - 중복 제거
    - 최대 max_links개까지만 반환
    """
    queries = build_synopsis_queries(title, author)

    seen: Set[str] = set()
    out: List[str] = []

    for q in queries:
        # webkr
        try:
            w = await naver.search_webkr(q, display=per_query_display)
            for link in _extract_links(w.get("items", [])):
                if link not in seen:
                    seen.add(link)
                    out.append(link)
                    if len(out) >= max_links:
                        return out
        except Exception:
            pass

        # blog
        try:
            b = await naver.search_blog(q, display=per_query_display)
            for link in _extract_links(b.get("items", [])):
                if link not in seen:
                    seen.add(link)
                    out.append(link)
                    if len(out) >= max_links:
                        return out
        except Exception:
            pass

    return out