from __future__ import annotations
from typing import List, Tuple
from .sources import Item

def fallback_summary(items_scored: List[Tuple[Item, int]]) -> str:
    top = items_scored[:10]
    lines = ["<b>Resumo semanal (sem IA)</b>"]
    for it, sc in top:
        lines.append(f"• ({sc}) {it.title} — <i>{it.source}</i>")
    lines.append("\n<i>Obs.: modo sem IA está ativado.</i>")
    return "\n".join(lines)

def summarize_week(
    items_scored: List[Tuple[Item, int]],
    ai_enabled: bool,
    api_key: str | None = None,
    model: str = "gemini-2.0-flash",
) -> str:
    # IA desligada: volta o fallback imediatamente
    if not ai_enabled:
        return fallback_summary(items_scored)

    # IA ligada: importa e usa Gemini só quando necessário
    try:
        from google import genai
        from google.genai.errors import ClientError
    except Exception:
        return fallback_summary(items_scored)

    if not api_key:
        return fallback_summary(items_scored)

    client = genai.Client(api_key=api_key)

    lines = []
    for i, (it, sc) in enumerate(items_scored, start=1):
        lines.append(f"{i}. [{sc}] {it.title} | {it.source} | {it.url}")
    payload = "\n".join(lines)

    prompt = f"""
Você é um analista de mercado de diagnóstico humano e veterinário.
Com base nas notícias abaixo, crie um resumo semanal em PT-BR com:
1) 10 bullets do que mais importa (cada bullet com: fato + por que importa).
2) Separar claramente em: MERCADO, REGULATÓRIO, CIÊNCIA/TECNOLOGIA, VETERINÁRIO.
3) Ao final, sugerir 3 tópicos para acompanhar na próxima semana (tendências).
Não invente fatos. Se algo estiver ambíguo, diga que está incerto.

NOTÍCIAS (título | fonte | link):
{payload}
""".strip()

    try:
        resp = client.models.generate_content(model=model, contents=prompt)
        return (resp.text or "").strip() or fallback_summary(items_scored)
    except ClientError:
        return fallback_summary(items_scored)
    except Exception:
        return fallback_summary(items_scored)