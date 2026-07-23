"""Score and filter records: keywords first, then IF and 中科院分区."""

from __future__ import annotations

import re

TITLE_POINTS = 3.0
ABSTRACT_POINTS = 1.0


def _compile(term: str) -> re.Pattern:
    """Word-boundary matcher. Trailing '*' means prefix match."""
    if term.endswith("*"):
        body = re.escape(term[:-1]).replace(r"\ ", r"\s+")
        pattern = rf"\b{body}\w*"
    else:
        body = re.escape(term).replace(r"\ ", r"\s+")
        pattern = rf"\b{body}\b"
    return re.compile(pattern, re.IGNORECASE)


def compile_topics(topics_cfg):
    out = []
    for t in topics_cfg:
        out.append({
            "name": t["name"],
            "weight": float(t.get("weight", 1.0)),
            "patterns": [(term, _compile(term)) for term in t["terms"]],
        })
    return out


def compile_excludes(exclude_cfg):
    return [_compile(t) for t in (exclude_cfg or [])]


def keyword_score(record, topics):
    """Return (score, matched_terms, matched_topics)."""
    title = record.get("title") or ""
    abstract = record.get("abstract") or ""

    total = 0.0
    matched_terms, matched_topics = [], []

    for topic in topics:
        hit_title, hit_abs = [], []
        for term, pat in topic["patterns"]:
            if pat.search(title):
                hit_title.append(term)
            elif pat.search(abstract):
                hit_abs.append(term)

        if hit_title:
            total += TITLE_POINTS * topic["weight"]
            matched_terms.extend(hit_title)
            matched_topics.append(topic["name"])
        elif hit_abs:
            total += ABSTRACT_POINTS * topic["weight"]
            matched_terms.extend(hit_abs)
            matched_topics.append(topic["name"])

    # de-dup, preserve order
    seen = set()
    terms = [t for t in matched_terms if not (t in seen or seen.add(t))]
    return total, terms, matched_topics


def is_excluded(record, excludes):
    title = record.get("title") or ""
    return any(p.search(title) for p in excludes)


def score_records(records, topics, excludes, cfg):
    """Filter + score. Returns (journal_hits, preprint_hits), each sorted."""
    filters = cfg["filters"]
    tier_bonus = cfg.get("tier_bonus", {})
    div = float(cfg.get("if_bonus_divisor", 10.0))
    cap = float(cfg.get("if_bonus_cap", 3.0))

    journal_hits, preprint_hits = [], []

    for rec in records:
        if is_excluded(rec, excludes):
            continue

        kw, terms, topic_names = keyword_score(rec, topics)
        if kw <= 0:
            continue

        meta = rec.get("journal_meta") or {}
        is_preprint = rec["source"] != "pubmed"

        if is_preprint:
            if kw < float(filters["preprint_min_keyword_score"]):
                continue
            total = kw
        else:
            if kw < float(filters["min_keyword_score"]):
                continue
            jif = float(meta.get("if", 0.0))
            tier = meta.get("tier", "")
            if jif < float(filters["min_if"]):
                continue
            if tier not in filters["allowed_tiers"]:
                continue
            total = (kw
                     + float(tier_bonus.get(tier, 0.0))
                     + min(jif / div, cap))

        enriched = dict(rec)
        enriched.update({
            "keyword_score": round(kw, 2),
            "score": round(total, 2),
            "matched_terms": terms,
            "matched_topics": topic_names,
        })
        (preprint_hits if is_preprint else journal_hits).append(enriched)

    journal_hits.sort(key=lambda r: r["score"], reverse=True)
    preprint_hits.sort(key=lambda r: r["score"], reverse=True)

    max_items = int(cfg.get("max_items", 25))
    # Give journals priority for the quota, leave at least 5 preprint slots.
    j_quota = max(max_items - min(len(preprint_hits), 5), 0)
    journal_hits = journal_hits[:j_quota]
    preprint_hits = preprint_hits[:max(max_items - len(journal_hits), 0)]

    return journal_hits, preprint_hits
