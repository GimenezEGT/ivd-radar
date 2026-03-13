from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
import os
import time
import feedparser
import requests
from dateutil import parser as dtparser
from urllib.parse import quote_plus

NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

@dataclass
class Item:
    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    summary: Optional[str] = None

def _parse_date(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = dtparser.parse(s)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def collect_rss(rss_urls: List[dict]) -> List[Item]:
    items: List[Item] = []
    for src in rss_urls:
        feed = feedparser.parse(src["url"])
        for e in feed.entries[:80]:
            title = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            if not title or not link:
                continue
            published = _parse_date(getattr(e, "published", None) or getattr(e, "updated", None))
            summary = getattr(e, "summary", None)
            items.append(Item(title=title, url=link, source=src["name"], published=published, summary=summary))
    return items

def _ncbi_params(extra: dict) -> dict:
    """
    NCBI recomenda incluir tool + email. API key é opcional e aumenta limites.
    """
    params = {
        "tool": "ivd-radar",
        "email": os.environ.get("NCBI_EMAIL", "example@example.com"),
    }
    api_key = os.environ.get("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    params.update(extra)
    return params

def _get_with_retry(url: str, params: dict, timeout: int = 30, max_tries: int = 5) -> requests.Response:
    """
    Retry com backoff para 429/5xx.
    """
    delay = 1.0
    last_exc = None
    for _ in range(max_tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                time.sleep(delay)
                delay = min(delay * 2, 16)
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
            time.sleep(delay)
            delay = min(delay * 2, 16)
    raise last_exc  # type: ignore[misc]

def pubmed_esearch(term: str, days: int = 7, retmax: int = 25) -> List[str]:
    params = _ncbi_params({
        "db": "pubmed",
        "term": term,
        "retmax": str(retmax),
        "sort": "pub+date",
        "retmode": "json",
        "reldate": str(days),
        "datetype": "pdat",
    })
    r = _get_with_retry(f"{NCBI_EUTILS}/esearch.fcgi", params=params)
    data = r.json()
    return data.get("esearchresult", {}).get("idlist", [])

def pubmed_esummary(pmids: List[str], batch_size: int = 10) -> List["Item"]:
    if not pmids:
        return []

    items: List[Item] = []

    # NCBI prefere chamadas menores (evita 429 em runners compartilhados)
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        params = _ncbi_params({
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "json",
        })

        r = _get_with_retry(f"{NCBI_EUTILS}/esummary.fcgi", params=params)
        data = r.json()
        result = data.get("result", {})

        for pmid in batch:
            rec = result.get(pmid)
            if not rec:
                continue
            title = (rec.get("title") or "").strip().rstrip(".")
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            pubdate = _parse_date(rec.get("pubdate"))
            source = rec.get("source") or "PubMed"
            items.append(Item(title=title, url=url, source=f"PubMed: {source}", published=pubdate))

        # pequeno delay para respeitar rate-limit (especialmente sem API key)
        time.sleep(0.34 if os.environ.get("NCBI_API_KEY") else 0.7)

    return items

def collect_pubmed(queries: List[dict], days: int = 7) -> List["Item"]:
    all_items: List["Item"] = []
    for q in queries:
        pmids = pubmed_esearch(q["query"], days=days, retmax=25)
        all_items.extend(pubmed_esummary(pmids, batch_size=10))
    return all_items

def collect_google_news_rss(news_queries: List[dict], days: int = 7) -> List[Item]:
    """
    Coleta notícias via Google News RSS Search e força janela (when:Xd).
    """
    items: List[Item] = []
    base = "https://news.google.com/rss/search?q="

    for nq in news_queries:
        q_raw = (nq.get("q") or "").strip()
        if not q_raw:
            continue

        # força janela de tempo (reduz muito notícias antigas)
        if days and f"when:{days}d" not in q_raw:
            q_raw = f"({q_raw}) when:{days}d"

        q = quote_plus(q_raw)
        hl = nq.get("hl", "pt-BR")
        gl = nq.get("gl", "BR")
        ceid = nq.get("ceid", "BR:pt-419")
        url = f"{base}{q}&hl={hl}&gl={gl}&ceid={ceid}"

        feed = feedparser.parse(url)
        for e in feed.entries[:80]:
            title = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            if not title or not link:
                continue
            published = _parse_date(getattr(e, "published", None) or getattr(e, "updated", None))
            summary = getattr(e, "summary", None)
            items.append(Item(
                title=title,
                url=link,
                source=f"Google News: {nq.get('name','Search')}",
                published=published,
                summary=summary,
            ))

    return items

def collect_stocks_weekly(symbols: List[str]) -> List[Item]:
    """
    Busca série semanal (Weekly) via Alpha Vantage e gera itens tipo "Ticker: variação semanal".
    Requer env ALPHAVANTAGE_API_KEY.
    """
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key or not symbols:
        return []

    out: List[Item] = []
    base = "https://www.alphavantage.co/query"
    for sym in symbols:
        params = {
            "function": "TIME_SERIES_WEEKLY_ADJUSTED",
            "symbol": sym,
            "apikey": api_key,
        }
        r = _get_with_retry(base, params=params, timeout=30, max_tries=5)
        data = r.json()

        series = data.get("Weekly Adjusted Time Series") or data.get("Weekly Time Series")
        if not series:
            continue

        # pega as 2 semanas mais recentes
        dates = sorted(series.keys(), reverse=True)
        if len(dates) < 2:
            continue

        d0, d1 = dates[0], dates[1]
        c0 = float(series[d0].get("5. adjusted close") or series[d0].get("4. close"))
        c1 = float(series[d1].get("5. adjusted close") or series[d1].get("4. close"))
        pct = ((c0 - c1) / c1) * 100.0

        title = f"Ações Saúde: {sym} fechou {c0:.2f} ({pct:+.2f}% na semana)"
        url = f"https://www.alphavantage.co/documentation/"  # doc do provedor
        out.append(Item(title=title, url=url, source="Alpha Vantage (weekly)"))
        time.sleep(12)  # free tier é bem limitado; evita 429

    return out
