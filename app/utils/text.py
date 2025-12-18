from __future__ import annotations
import re

_ws = re.compile(r"\s+")
_non = re.compile(r"[^0-9a-zA-Z가-힣\s]")
_tag = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    return _tag.sub("", s or "").strip()


def normalize_korean(s: str) -> str:
    s = (s or "").strip().lower()
    s = _non.sub(" ", s)
    s = _ws.sub(" ", s).strip()
    return s


def token_jaccard(a: str, b: str) -> float:
    sa = set(a.split()) if a else set()
    sb = set(b.split()) if b else set()
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0
