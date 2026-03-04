from __future__ import annotations
from typing import List, Tuple
from rapidfuzz import fuzz
from .sources import Item

def _norm(s: str) -> str:
    return " ".join(s.lower().strip().split())

def dedupe(items: List[Item], title_threshold: int = 92) -> List[Item]:
    kept: List[Item] = []
    seen_urls = set()
    for it in items:
        if it.url in seen_urls:
            continue
        nt = _norm(it.title)
        is_dup = False
        for k in kept:
            if fuzz.ratio(nt, _norm(k.title)) >= title_threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(it)
            seen_urls.add(it.url)
    return kept

def score_item(it: Item, keywords: List[str]) -> int:
    text = (it.title + " " + (it.summary or "")).lower()
    score = 0
    for kw in keywords:
        if kw.lower() in text:
            score += 2
    # bônus por regulatório/mercado
    for hot in ["anvisa", "fda", "ivdr", "mdr", "recall", "approval", "cleared", "merger", "acquisition", "ipo"]:
        if hot in text:
            score += 1
    return score

def rank(items: List[Item], keywords: List[str]) -> List[Tuple[Item, int]]:
    scored = [(it, score_item(it, keywords)) for it in items]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored