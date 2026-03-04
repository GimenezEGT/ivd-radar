from __future__ import annotations
import requests

TELEGRAM_API = "https://api.telegram.org"
MAX_LEN = 4000  # margem de segurança (limite real ~4096) :contentReference[oaicite:7]{index=7}

def _split(text: str) -> list[str]:
    parts = []
    buf = ""
    for line in text.splitlines(True):
        if len(buf) + len(line) > MAX_LEN:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return parts

def send_message(text: str, chat_id: str, bot_token: str):
    url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
    for part in _split(text):
        payload = {
            "chat_id": chat_id,
            "text": part,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()