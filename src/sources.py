"""Fetch new records from PubMed, bioRxiv and chemRxiv.

Every fetcher returns a list of plain dicts with a common shape:

    {
      "id":       stable unique id (doi preferred, else pmid/server id),
      "title":    str,
      "abstract": str,
      "authors":  [str, ...],
      "journal":  str,          # display name
      "source":   "pubmed" | "biorxiv" | "chemrxiv",
      "doi":      str | None,
      "pmid":     str | None,
      "date":     "YYYY-MM-DD",
      "url":      str,
    }

Any single source failing is logged and swallowed, so one dead API cannot
kill the morning brief.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

log = logging.getLogger(__name__)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT = 60

# NCBI asks for identification; also raises the anonymous rate limit.
NCBI_TOOL = "journal-brief"


def _session(contact_email: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {"User-Agent": f"journal-brief/1.0 (mailto:{contact_email})"}
    )
    return s


# --------------------------------------------------------------------------
# PubMed
# --------------------------------------------------------------------------

def fetch_pubmed(journals, start: date, end: date, contact_email: str,
                 api_key: str | None = None, retmax: int = 500):
    """Fetch everything published in `journals` between start and end (EDAT)."""
    sess = _session(contact_email)

    terms = " OR ".join(f'"{j["pubmed"]}"[Journal]' for j in journals)
    query = f"({terms})"

    params = {
        "db": "pubmed",
        "term": query,
        "retmax": retmax,
        "retmode": "json",
        "datetype": "edat",
        "mindate": start.strftime("%Y/%m/%d"),
        "maxdate": end.strftime("%Y/%m/%d"),
        "tool": NCBI_TOOL,
        "email": contact_email,
    }
    if api_key:
        params["api_key"] = api_key

    try:
        r = sess.post(f"{EUTILS}/esearch.fcgi", data=params, timeout=TIMEOUT)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as exc:  # noqa: BLE001
        log.error("PubMed esearch failed: %s", exc)
        return []

    log.info("PubMed: %d candidate PMIDs", len(ids))
    if not ids:
        return []

    # Map PubMed abbreviation -> display metadata for later enrichment.
    by_abbrev = {j["pubmed"].lower(): j for j in journals}

    records = []
    for chunk_start in range(0, len(ids), 200):
        chunk = ids[chunk_start:chunk_start + 200]
        records.extend(_efetch(sess, chunk, contact_email, api_key, by_abbrev))
        time.sleep(0.4)  # stay well under NCBI rate limits
    return records


def _efetch(sess, pmids, contact_email, api_key, by_abbrev):
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "tool": NCBI_TOOL,
        "email": contact_email,
    }
    if api_key:
        params["api_key"] = api_key

    try:
        r = sess.post(f"{EUTILS}/efetch.fcgi", data=params, timeout=TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as exc:  # noqa: BLE001
        log.error("PubMed efetch failed: %s", exc)
        return []

    out = []
    for art in root.findall(".//PubmedArticle"):
        try:
            out.append(_parse_pubmed_article(art, by_abbrev))
        except Exception as exc:  # noqa: BLE001
            log.warning("skipping unparseable PubMed record: %s", exc)
    return [r for r in out if r]


def _text(node) -> str:
    """Flatten an element and its children into plain text."""
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _parse_pubmed_article(art, by_abbrev):
    pmid = _text(art.find(".//PMID"))
    title = _text(art.find(".//ArticleTitle"))
    if not title:
        return None

    # Abstract may be split into labelled sections.
    parts = []
    for ab in art.findall(".//Abstract/AbstractText"):
        label = ab.get("Label")
        body = _text(ab)
        parts.append(f"{label}: {body}" if label else body)
    abstract = " ".join(p for p in parts if p)

    authors = []
    for a in art.findall(".//AuthorList/Author"):
        last = _text(a.find("LastName"))
        initials = _text(a.find("Initials"))
        if last:
            authors.append(f"{last} {initials}".strip())

    doi = None
    for aid in art.findall(".//ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi":
            doi = _text(aid)
            break

    abbrev = _text(art.find(".//Journal/ISOAbbreviation")) or _text(
        art.find(".//MedlineTA")
    )
    meta = by_abbrev.get(abbrev.lower().rstrip("."), {})
    journal_name = meta.get("name") or _text(art.find(".//Journal/Title")) or abbrev

    # Publication / entrez date
    d = art.find(".//PubMedPubDate[@PubStatus='entrez']")
    if d is None:
        d = art.find(".//PubMedPubDate")
    try:
        pub = date(
            int(_text(d.find("Year"))),
            int(_text(d.find("Month"))),
            int(_text(d.find("Day"))),
        ).isoformat()
    except Exception:  # noqa: BLE001
        pub = date.today().isoformat()

    return {
        "id": doi or f"pmid:{pmid}",
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal_name,
        "journal_meta": meta,
        "source": "pubmed",
        "doi": doi,
        "pmid": pmid,
        "date": pub,
        "url": f"https://doi.org/{doi}" if doi
               else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }


# --------------------------------------------------------------------------
# bioRxiv / medRxiv
# --------------------------------------------------------------------------

def fetch_biorxiv(server: str, start: date, end: date, contact_email: str,
                  max_pages: int = 25):
    sess = _session(contact_email)
    out, cursor = [], 0

    for _ in range(max_pages):
        url = (f"https://api.biorxiv.org/details/{server}/"
               f"{start.isoformat()}/{end.isoformat()}/{cursor}/json")
        try:
            r = sess.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.error("%s fetch failed: %s", server, exc)
            break

        coll = data.get("collection") or []
        if not coll:
            break

        for it in coll:
            doi = it.get("doi")
            authors = [a.strip() for a in (it.get("authors") or "").split(";")
                       if a.strip()]
            out.append({
                "id": doi or it.get("title", "")[:80],
                "title": (it.get("title") or "").strip(),
                "abstract": (it.get("abstract") or "").strip(),
                "authors": authors,
                "journal": f"{server} (preprint)",
                "journal_meta": {},
                "source": server,
                "doi": doi,
                "pmid": None,
                "date": it.get("date") or end.isoformat(),
                "url": f"https://doi.org/{doi}" if doi else "",
            })

        msgs = data.get("messages") or [{}]
        total = int(msgs[0].get("total", 0) or 0)
        cursor += len(coll)
        if cursor >= total:
            break
        time.sleep(0.3)

    log.info("%s: %d preprints in window", server, len(out))
    return out


# --------------------------------------------------------------------------
# chemRxiv
# --------------------------------------------------------------------------

def fetch_chemrxiv(start: date, end: date, contact_email: str,
                   max_pages: int = 10, page_size: int = 50):
    sess = _session(contact_email)
    base = "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items"
    out = []

    for page in range(max_pages):
        params = {
            "limit": page_size,
            "skip": page * page_size,
            "sort": "PUBLISHED_DATE_DESC",
            "searchDateFrom": start.isoformat(),
            "searchDateTo": end.isoformat(),
        }
        try:
            r = sess.get(base, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.error("chemRxiv fetch failed: %s", exc)
            break

        hits = data.get("itemHits") or []
        if not hits:
            break

        for h in hits:
            it = h.get("item", h)
            doi = it.get("doi")
            authors = []
            for a in it.get("authors") or []:
                nm = f"{a.get('lastName','')} {a.get('firstName','')[:1]}".strip()
                if nm:
                    authors.append(nm)
            pub = (it.get("publishedDate") or "")[:10] or end.isoformat()
            out.append({
                "id": doi or it.get("id") or it.get("title", "")[:80],
                "title": (it.get("title") or "").strip(),
                "abstract": (it.get("abstract") or "").strip(),
                "authors": authors,
                "journal": "chemRxiv (preprint)",
                "journal_meta": {},
                "source": "chemrxiv",
                "doi": doi,
                "pmid": None,
                "date": pub,
                "url": f"https://doi.org/{doi}" if doi
                       else f"https://chemrxiv.org/engage/chemrxiv/article-details/{it.get('id','')}",
            })

        if len(hits) < page_size:
            break
        time.sleep(0.3)

    log.info("chemRxiv: %d preprints in window", len(out))
    return out


def date_window(days_back: int):
    end = date.today()
    return end - timedelta(days=days_back), end
