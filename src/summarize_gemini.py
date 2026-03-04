from __future__ import annotations
from typing import List, Tuple
from google import genai
from .sources import Item

def summarize_week(items_scored: List[Tuple[Item, int]], api_key: str, model: str = "gemini-2.0-flash") -> str:
    client = genai.Client(api_key=api_key)

    # Monta um “pacote” curto para o Gemini (top N)
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

    resp = client.models.generate_content(
        model=model,
        contents=prompt
    )
    return resp.text or ""