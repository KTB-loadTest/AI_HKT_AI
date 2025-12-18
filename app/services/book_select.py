from __future__ import annotations
from typing import Any, Dict, List
from app.models.schemas import SelectedBook
from app.utils.text import strip_html, normalize_korean, token_jaccard


def choose_best_book(items: List[Dict[str, Any]], title: str, author: str) -> SelectedBook:
    if not items:
        raise ValueError("No book candidates returned from Naver")

    title_n = normalize_korean(title)
    author_n = normalize_korean(author)

    best_score = -1.0
    best = None

    for it in items:
        cand_title = strip_html(it.get("title", ""))
        cand_author = strip_html(it.get("author", ""))
        publisher = strip_html(it.get("publisher", "")) or None
        pubdate = it.get("pubdate") or None
        link = it.get("link") or None
        isbn = it.get("isbn") or None

        t_sim = token_jaccard(normalize_korean(cand_title), title_n)
        a_sim = token_jaccard(normalize_korean(cand_author), author_n)

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
