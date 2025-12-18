from __future__ import annotations
from typing import Any, Dict, List
from app.models.schemas import SelectedBook
from app.utils.text import strip_html, normalize_korean, token_jaccard
# strip_html : HTML 태그 제거
# normalize_korean : 공백/특수문자/대소문자/조사 정규화
# token_jaccard : 단어 단위 유사도 계산


"""
items : 네이버 Book Search API 결과 리스트
반환값 : 가장 적합한 책 1권

- 입력값 정규화


"""

def choose_best_book(items: List[Dict[str, Any]], title: str, author: str) -> SelectedBook:
    if not items:
        raise ValueError("No book candidates returned from Naver")

    title_n = normalize_korean(title)
    author_n = normalize_korean(author)

    best_score = -1.0
    best = None

    # 필드 추출 + HTML 제거
    for it in items:
        cand_title = strip_html(it.get("title", ""))
        cand_author = strip_html(it.get("author", ""))
        publisher = strip_html(it.get("publisher", "")) or None
        pubdate = it.get("pubdate") or None
        link = it.get("link") or None
        isbn = it.get("isbn") or None

        # 제목/저자 유사도 계산
        # 문자열 -> 토큰 집합
        # 교집합/합집합 비율 계산
        t_sim = token_jaccard(normalize_korean(cand_title), title_n)
        a_sim = token_jaccard(normalize_korean(cand_author), author_n)

        # 가중치 기반 점수 계산
        # 제목 > 저자
        # 출판사 정보 있음 -> 정식 도서일 확률 높음
        # 동점 -> 정식 데이터 선정
        score = 0.75 * t_sim + 0.25 * a_sim
        if publisher:
            score += 0.01
        if pubdate and len(pubdate) == 8:
            score += 0.02

        if score > best_score:
            best_score = score
            best = (cand_title, cand_author, publisher, pubdate, isbn, link)

    if not best:
        raise ValueError("Failed to select best book candidate")

    cand_title, cand_author, publisher, pubdate, isbn, link = best
    return SelectedBook(
        title=cand_title,
        author=cand_author,
        publisher=publisher,
        pubdate=pubdate,
        isbn=isbn,
        naver_link=link,
    )
