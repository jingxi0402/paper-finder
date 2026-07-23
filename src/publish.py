"""Write the static site's data file and RSS feed.

The site shell (docs/index.html, docs/assets/*) is static and committed once.
This module only regenerates docs/data/items.json and docs/feed.xml, so the
daily job touches as little of the repo as possible.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SITE_TITLE = "Journal Brief"


def _trim(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:n].rstrip() + "…" if len(text) > n else text


def _slim(rec: dict, abstract_chars: int, added: str) -> dict:
    """Reduce a scored record to what the page actually renders."""
    meta = rec.get("journal_meta") or {}
    return {
        "id": rec["id"],
        "title": rec.get("title", ""),
        "abstract": _trim(rec.get("abstract", ""), abstract_chars),
        "authors": (rec.get("authors") or [])[:6],
        "journal": rec.get("journal", ""),
        "tier": meta.get("tier"),
        "if": meta.get("if"),
        "source": rec.get("source"),
        "preprint": rec.get("source") != "pubmed",
        "doi": rec.get("doi"),
        "pmid": rec.get("pmid"),
        "url": rec.get("url"),
        "date": rec.get("date"),
        "added": added,
        "score": rec.get("score"),
        "kw": rec.get("keyword_score"),
        "terms": (rec.get("matched_terms") or [])[:8],
        "topics": rec.get("matched_topics") or [],
    }


def update_archive(data_path: Path, new_items, cfg, scanned: int):
    """Merge today's hits into the archive, prune, and write items.json."""
    archive_cfg = cfg.get("archive", {})
    retain = int(archive_cfg.get("retain_days", 500))
    abstract_chars = int(archive_cfg.get("abstract_chars", 420))

    payload = {"items": [], "runs": []}
    if data_path.exists():
        try:
            payload = json.loads(data_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.warning("items.json unreadable, rebuilding from scratch")
            payload = {"items": [], "runs": []}

    existing = {it["id"]: it for it in payload.get("items", [])}
    today = date.today().isoformat()

    added_count = 0
    for rec in new_items:
        if rec["id"] in existing:
            continue
        existing[rec["id"]] = _slim(rec, abstract_chars, today)
        added_count += 1

    cutoff = (date.today() - timedelta(days=retain)).isoformat()
    items = [it for it in existing.values() if (it.get("added") or today) >= cutoff]
    items.sort(key=lambda it: (it.get("added", ""), it.get("score") or 0),
               reverse=True)

    runs = [r for r in payload.get("runs", []) if r["date"] >= cutoff]
    runs = [r for r in runs if r["date"] != today]
    runs.append({"date": today, "scanned": scanned, "added": added_count})
    runs.sort(key=lambda r: r["date"])

    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "topic_colors": cfg.get("topic_colors", {}),
        "runs": runs,
        "items": items,
    }

    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")
    log.info("archive: +%d new, %d total (%.0f KB)",
             added_count, len(items), data_path.stat().st_size / 1024)
    return added_count, len(items)


def write_feed(feed_path: Path, data_path: Path, site_url: str, limit: int = 60):
    """Write an RSS feed so the brief can also be followed in a reader."""
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("cannot build feed: %s", exc)
        return

    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        f"<title>{html.escape(SITE_TITLE)}</title>",
        f"<link>{html.escape(site_url)}</link>",
        "<description>New papers matching my research keywords</description>",
        f"<lastBuildDate>{now}</lastBuildDate>",
    ]

    for it in payload.get("items", [])[:limit]:
        badge = " · ".join(x for x in [
            it.get("journal"), it.get("tier"),
            f"IF {it['if']}" if it.get("if") else None,
            f"score {it.get('score')}",
        ] if x)
        desc = f"{badge}<br>{html.escape(it.get('abstract',''))}"
        link = it.get("url") or site_url
        parts += [
            "<item>",
            f"<title>{html.escape(it.get('title',''))}</title>",
            f"<link>{html.escape(link)}</link>",
            f"<guid isPermaLink=\"false\">{html.escape(it['id'])}</guid>",
            f"<description>{html.escape(desc)}</description>",
            "</item>",
        ]

    parts.append("</channel></rss>")
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text("".join(parts), encoding="utf-8")
    log.info("feed written: %s", feed_path.name)
