from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import yaml

from .sources import (
    collect_rss,
    collect_pubmed,
    collect_google_news_rss,
    collect_stocks_weekly,
)
from .dedupe import dedupe, rank, pick_top_diverse
from .summarize_gemini import summarize_week
from .telegram_send import send_message


def _load_keywords_txt(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            out = []
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                out.append(s.lower())
            return out
    except FileNotFoundError:
        return []


def _load_market_queries_yaml(path: str) -> tuple[list[dict], list[dict]]:
    """
    Lê data/news_market_queries.yaml e devolve duas listas:
    - br_queries: lista de dicts {name, q, hl, gl, ceid}
    - global_queries: idem
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    br = []
    for q in (data.get("br") or []):
        br.append({
            "name": q.get("name", "BR"),
            "q": q.get("q", ""),
            "hl": "pt-BR",
            "gl": "BR",
            "ceid": "BR:pt-419",
        })

    glob = []
    for q in (data.get("global") or []):
        glob.append({
            "name": q.get("name", "Global"),
            "q": q.get("q", ""),
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        })

    return br, glob


def _filter_recent(items, days: int = 7):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [it for it in items if it.published and it.published >= cutoff]


def _is_pubmed(it) -> bool:
    return (it.source or "").lower().startswith("pubmed")


def _market_filter_news(items, market_keywords: list[str], exclude_terms: list[str]) -> list:
    """
    Aplica filtro apenas em NOTÍCIAS (não PubMed):
    - remove itens com termos de "cara de ciência"
    - mantém itens que batem pelo menos 1 keyword do dicionário
    """
    if not market_keywords:
        return items

    ex = [t.lower() for t in (exclude_terms or [])]
    out = []
    for it in items:
        if _is_pubmed(it):
            out.append(it)
            continue

        text = (it.title + " " + (it.summary or "") + " " + (it.source or "")).lower()

        # remove se parece ciência pesada (para a parte de notícias)
        if any(t in text for t in ex):
            continue

        # exige pelo menos 1 keyword do dicionário
        if any(k in text for k in market_keywords):
            out.append(it)

    return out


def _format_section(title: str, picked_items) -> str:
    if not picked_items:
        return f"<b>{title}</b>\n<i>(sem itens)</i>\n"
    lines = [f"<b>{title}</b>"]
    for it, sc, cat in picked_items:
        lines.append(f"• <b>[{cat}]</b> {it.title} — <i>{it.source}</i>\n{it.url}")
    return "\n".join(lines) + "\n"


def main():
    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # IA (opcional)
    ai_cfg = cfg.get("ai", {})
    ai_enabled = bool(ai_cfg.get("enabled", False))
    ai_model = ai_cfg.get("model", "gemini-2.0-flash")

    bot_token = os.environ["BOT_TOKEN"]
    chat_id = os.environ["CHAT_ID"]
    gemini_key = os.environ.get("GEMINI_API_KEY")

    limits = cfg.get("limits", {})
    total_to_send = int(limits.get("telegram_links", 25))
    max_per_source = int(limits.get("max_per_source", 6))
    max_items_for_gemini = int(limits.get("max_items_for_gemini", 15))

    # Config de notícias de mercado (BR/Global)
    mkt = cfg.get("market_news", {})
    mkt_enabled = bool(mkt.get("enabled", True))
    mkt_days = int(mkt.get("days", 7))
    mkt_keywords = _load_keywords_txt(mkt.get("keywords_file", "")) if mkt_enabled else []
    exclude_terms = mkt.get("exclude_if_contains", [])

    # 1) RSS diretos (se forem feeds reais)
    rss_items = collect_rss(cfg.get("rss_sources", []))

    # 2) Notícias via queries YAML (BR + Global) usando Google News RSS
    br_queries = []
    global_queries = []
    if mkt_enabled and mkt.get("queries_file"):
        br_queries, global_queries = _load_market_queries_yaml(mkt["queries_file"])

    br_news = collect_google_news_rss(br_queries, days=mkt_days) if br_queries else []
    global_news = collect_google_news_rss(global_queries, days=mkt_days) if global_queries else []

    # (opcional) também manter suas news_queries antigas, se quiser
    legacy_news = collect_google_news_rss(cfg.get("news_queries", []), days=mkt_days) if cfg.get("news_queries") else []

    # 3) PubMed (não deixar o bot morrer se NCBI limitar)
    try:
        pubmed_items = collect_pubmed(cfg.get("pubmed_queries", []), days=7)
    except Exception:
        pubmed_items = []

    # 4) Ações (opcional)
    stock_items = []
    stock_cfg = cfg.get("stocks", {})
    if stock_cfg.get("enabled", False):
        stock_items = collect_stocks_weekly(stock_cfg.get("symbols", []))

    # Junta e aplica filtro de tempo (últimos 7 dias) para notícias/RSS
    all_news = rss_items + br_news + global_news + legacy_news
    all_news = _filter_recent(all_news, days=mkt_days)

    # Filtra notícias por dicionário (não afeta PubMed)
    all_news = _market_filter_news(all_news, mkt_keywords, exclude_terms)

    # Junta tudo (notícias + pubmed + ações)
    all_items = all_news + pubmed_items + stock_items
    all_items = dedupe(all_items)

    # Rank global
    scored = rank(all_items, cfg["keywords"])

    # Seleção diversa (Top N)
    picked = pick_top_diverse(
        scored,
        total=total_to_send,
        max_per_source=max_per_source,
    )

    # Resumo (IA opcional / fallback)
    selected_for_ai = [(it, sc) for (it, sc, _cat) in picked][:max_items_for_gemini]
    summary = summarize_week(
        selected_for_ai,
        ai_enabled=ai_enabled,
        api_key=gemini_key,
        model=ai_model,
    )

    # Separação BR vs Global vs PubMed vs Ações
    def _bucket(it):
        src = (it.source or "").lower()
        if src.startswith("pubmed"):
            return "PUBMED"
        if "alpha vantage" in src:
            return "ACOES"
        if "google news" in src:
            # usa o "name" das queries para decidir BR vs Global
            if "br" in src or "brasil" in src:
                return "BR"
            # heurística: se o query foi em pt-BR, geralmente aparece BR nos nomes
            # então, se não tiver, cai como Global
            return "GLOBAL"
        # RSS: decide por idioma/fonte (heurística simples)
        if "anvisa" in src or "b3" in src:
            return "BR"
        return "GLOBAL"

    buckets = defaultdict(list)
    for it, sc, cat in picked:
        buckets[_bucket(it)].append((it, sc, cat))

    header = "📊 <b>Radar semanal — Mercado de Saúde (BR & Global) + Vet</b>\n"
    header += f"Itens analisados: {len(all_items)} | Curadoria: {len(picked)} | Janela: {mkt_days} dias\n\n"

    parts = [header]
    if summary.strip():
        parts.append(summary.strip() + "\n")

    parts.append(_format_section("🇧🇷 Notícias Brasil (mercado)", buckets.get("BR", [])))
    parts.append(_format_section("🌍 Notícias Global (mercado)", buckets.get("GLOBAL", [])))
    parts.append(_format_section("📚 PubMed (ciência/avanç̧os)", buckets.get("PUBMED", [])))
    if stock_cfg.get("enabled", False):
        parts.append(_format_section("📈 Ações (variação semanal)", buckets.get("ACOES", [])))

    msg = "\n".join(parts).strip()
    send_message(msg, chat_id=chat_id, bot_token=bot_token)


if __name__ == "__main__":
    main()
