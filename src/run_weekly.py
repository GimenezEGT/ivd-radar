from __future__ import annotations

import os
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


def main():
    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    ai_cfg = cfg.get("ai", {})
    ai_enabled = bool(ai_cfg.get("enabled", False))
    ai_model = ai_cfg.get("model", "gemini-2.0-flash")

    bot_token = os.environ["BOT_TOKEN"]
    chat_id = os.environ["CHAT_ID"]
    gemini_key = os.environ.get("GEMINI_API_KEY")

    # 1) RSS “diretos” (quando forem feeds reais)
    rss_items = collect_rss(cfg.get("rss_sources", []))

    # 2) Notícias BR + internacional via Google News RSS Search
    news_items = collect_google_news_rss(cfg.get("news_queries", []))

    # 3) PubMed (não deixa o bot morrer se o NCBI limitar)
    try:
        pubmed_items = collect_pubmed(cfg.get("pubmed_queries", []), days=7)
    except Exception:
        pubmed_items = []

    # 4) Ações (opcional)
    stock_items = []
    stock_cfg = cfg.get("stocks", {})
    if stock_cfg.get("enabled", False):
        stock_items = collect_stocks_weekly(stock_cfg.get("symbols", []))

    # Junta tudo e deduplica
    all_items = rss_items + news_items + pubmed_items + stock_items
    all_items = dedupe(all_items)

    # Rank global
    scored = rank(all_items, cfg["keywords"])

    # Seleção final com diversidade (curadoria automática)
    limits = cfg.get("limits", {})
    total_to_send = int(limits.get("telegram_links", 25))
    max_per_source = int(limits.get("max_per_source", 6))

    picked = pick_top_diverse(
        scored,
        total=total_to_send,
        max_per_source=max_per_source,
    )

    # Para estatísticas e para o resumo (IA ou fallback)
    selected_items = [(it, sc) for (it, sc, _cat) in picked]
    top_for_ai = selected_items[: int(limits.get("max_items_for_gemini", 15))]

    summary = summarize_week(
        top_for_ai,
        ai_enabled=ai_enabled,
        api_key=gemini_key,
        model=ai_model,
    )

    header = "📊 <b>Radar semanal — Diagnóstico humano & veterinário</b>\n"
    header += f"Itens analisados: {len(all_items)} | Curadoria: {len(picked)}\n\n"

    links = "\n".join(
        [
            f"• <b>[{cat}]</b> {it.title} — <i>{it.source}</i>\n{it.url}"
            for (it, _sc, cat) in picked
        ]
    )

    msg = header + summary.strip() + f"\n\n<b>Curadoria (Top {len(picked)})</b>\n" + links

    send_message(msg, chat_id=chat_id, bot_token=bot_token)


if __name__ == "__main__":
    main()
