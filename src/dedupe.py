from __future__ import annotations
from typing import List, Tuple, Dict, DefaultDict
from collections import defaultdict
from rapidfuzz import fuzz
from .sources import Item

def _norm(s: str) -> str:
    return " ".join((s or "").lower().strip().split())

def dedupe(items: List[Item], title_threshold: int = 92) -> List[Item]:
    kept: List[Item] = []
    seen_urls = set()

    for it in items:
        if not it.title or not it.url:
            continue
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


# Regras simples de categorização (sem IA)
CATEGORY_RULES: Dict[str, List[str]] = {
    "REGULATORIO": [
        "anvisa", "fda", "ivdr", "mdr", "ce mark", "ce-ivd", "ema",
        "approval", "approved", "cleared", "clearance", "recall", "warning letter",
        "regulatory", "rdc", "instrução normativa", "consulta pública",
    ],
    "MERCADO": [
        "acquisition", "acquire", "merger", "m&a", "funding", "series a", "series b",
        "ipo", "earnings", "revenue", "guidance", "pipeline", "partnership",
        "collaboration", "launch", "released", "commercial", "distribution",
    ],
    "TECNOLOGIA": [
        "point-of-care", "poc", "microfluidic", "lab-on-a-chip", "biosensor",
        "pcr", "rt-pcr", "qpcr", "ngs", "sequencing", "crisper", "isothermal",
        "digital pcr", "ddpcr", "lateral flow", "immunoassay",
    ],
    "VETERINARIO": [
        "veterinary", "vet", "animal health", "zoonotic", "zoonose",
        "idexx", "zoetis", "companion animal", "livestock", "bovine", "canine", "feline",
    ],
    "CIENCIA": [
        "clinical", "trial", "sensitivity", "specificity", "validation", "meta-analysis",
        "biomarker", "assay", "limit of detection", "lod", "performance evaluation",
    ],
    "ACOES": [
        "ações saúde:", "stock", "shares", "ticker",
    ],
}

def categorize(it: Item) -> str:
    text = _norm(it.title + " " + (it.summary or "") + " " + (it.source or ""))
    # PubMed quase sempre é ciência/tecnologia clínica
    if (it.source or "").lower().startswith("pubmed"):
        return "CIENCIA"
    for cat, keys in CATEGORY_RULES.items():
        if any(k in text for k in keys):
            return cat
    return "OUTROS"


def score_item(it: Item, keywords: List[str]) -> int:
    """
    Score sem IA:
    - keywords gerais (do config)
    - sinais fortes (aprovação, recall, M&A, lançamento)
    - bônus por categoria (regulatório/mercado geralmente mais acionável)
    """
    text = _norm(it.title + " " + (it.summary or ""))

    score = 0

    # base: keywords
    for kw in keywords:
        if _norm(kw) in text:
            score += 3

    # sinais fortes
    strong = [
        "approval", "approved", "cleared", "recall", "warning letter",
        "anvisa", "fda", "ivdr", "mdr",
        "acquisition", "acquire", "merger", "funding", "ipo", "earnings", "revenue",
        "launch", "released", "commercial",
        "companion diagnostic", "point-of-care",
    ]
    for s in strong:
        if s in text:
            score += 5

    cat = categorize(it)
    if cat == "REGULATORIO":
        score += 6
    elif cat == "MERCADO":
        score += 5
    elif cat == "TECNOLOGIA":
        score += 3
    elif cat == "VETERINARIO":
        score += 3
    elif cat == "CIENCIA":
        score += 2

    # Se for PubMed, dá um empurrão (muitos títulos não batem keywords do config)
    if (it.source or "").lower().startswith("pubmed"):
        score += 2

    # Penaliza levemente títulos muito curtos/genéricos
    if len(_norm(it.title)) < 30:
        score -= 1

    return score


def rank(items: List[Item], keywords: List[str]) -> List[Tuple[Item, int]]:
    scored = [(it, score_item(it, keywords)) for it in items]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def pick_top_diverse(
    scored: List[Tuple[Item, int]],
    total: int = 25,
    max_per_source: int = 6,
    per_category: Dict[str, int] | None = None,
) -> List[Tuple[Item, int, str]]:
    """
    Seleciona Top N com diversidade:
    - evita 25 itens da mesma fonte
    - garante mix por categoria (mercado/regulatório/tech/vet/ciência)
    """
    if per_category is None:
        per_category = {
            "REGULATORIO": 6,
            "MERCADO": 6,
            "TECNOLOGIA": 5,
            "VETERINARIO": 4,
            "CIENCIA": 4,
            "ACOES": 2,
            "OUTROS": 2,
        }

    picked: List[Tuple[Item, int, str]] = []
    cat_count: DefaultDict[str, int] = defaultdict(int)
    source_count: DefaultDict[str, int] = defaultdict(int)

    for it, sc in scored:
        cat = categorize(it)

        # limite por fonte
        src = it.source or "Unknown"
        if source_count[src] >= max_per_source:
            continue

        # limite por categoria
        limit_cat = per_category.get(cat, per_category.get("OUTROS", 0))
        if limit_cat > 0 and cat_count[cat] >= limit_cat:
            continue

        picked.append((it, sc, cat))
        source_count[src] += 1
        cat_count[cat] += 1

        if len(picked) >= total:
            break

    # Se ainda não completou total, preenche com o resto (respeitando só max_per_source)
    if len(picked) < total:
        for it, sc in scored:
            cat = categorize(it)
            src = it.source or "Unknown"
            if any(p[0].url == it.url for p in picked):
                continue
            if source_count[src] >= max_per_source:
                continue
            picked.append((it, sc, cat))
            source_count[src] += 1
            if len(picked) >= total:
                break

    return picked
