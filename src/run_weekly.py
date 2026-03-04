from __future__ import annotations
import os
import yaml
from .sources import collect_rss, collect_pubmed
from .dedupe import dedupe, rank
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

    rss_items = collect_rss(cfg["rss_sources"])
    pubmed_items = collect_pubmed(cfg["pubmed_queries"], days=7)

    all_items = rss_items + pubmed_items
    all_items = dedupe(all_items)

    scored = rank(all_items, cfg["keywords"])
    scored = scored[: cfg["limits"]["max_items_total"]]

    top_for_ai = scored[: cfg["limits"]["max_items_for_gemini"]]
    summary = summarize_week(
        top_for_ai,
        ai_enabled=ai_enabled,
        api_key=gemini_key,
        model=ai_model,
    )

    header = "📊 <b>Radar semanal — Diagnóstico humano & veterinário</b>\n"
    header += f"Itens analisados: {len(all_items)} | Selecionados: {len(scored)}\n\n"

    links = "\n".join([f"• {it.title} — <i>{it.source}</i>\n{it.url}" for (it, _) in scored[:25]])
    msg = header + summary.strip() + "\n\n<b>Links (Top 25)</b>\n" + links

    send_message(msg, chat_id=chat_id, bot_token=bot_token)

if __name__ == "__main__":
    main()