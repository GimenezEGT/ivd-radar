from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
import feedparser
import requests
from dateutil import parser as dtparser

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

def pubmed_esearch(term: str, days: int = 7, retmax: int = 40) -> List[str]:
    # ESearch: busca PMIDs recentes.
    params = {
        "db": "pubmed",
        "term": term,
        "retmax": str(retmax),
        "sort": "pub+date",
        "retmode": "json",
        "reldate": str(days),
        "datetype": "pdat",
    }
    r = requests.get(f"{NCBI_EUTILS}/esearch.fcgi", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("esearchresult", {}).get("idlist", [])

def pubmed_esummary(pmids: List[str]) -> List[Item]:
    if not pmids:
        return []
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
    r = requests.get(f"{NCBI_EUTILS}/esummary.fcgi", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    result = data.get("result", {})
    items: List[Item] = []
    for pmid in pmids:
        rec = result.get(pmid)
        if not rec:
            continue
        title = (rec.get("title") or "").strip().rstrip(".")
        # Link direto para PubMed
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        pubdate = _parse_date(rec.get("pubdate"))
        source = rec.get("source") or "PubMed"
        items.append(Item(title=title, url=url, source=f"PubMed: {source}", published=pubdate))
    return items

def collect_pubmed(queries: List[dict], days: int = 7) -> List[Item]:
    all_items: List[Item] = []
    for q in queries:
        pmids = pubmed_esearch(q["query"], days=days, retmax=40)
        all_items.extend(pubmed_esummary(pmids))
    return all_items