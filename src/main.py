"""Daily journal brief: fetch -> dedupe -> score -> publish to the site."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scoring  # noqa: E402
import publish  # noqa: E402
import sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
STATE = ROOT / "state" / "seen.json"
DATA = ROOT / "docs" / "data" / "items.json"
FEED = ROOT / "docs" / "feed.xml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("brief")


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.warning("state file unreadable, starting fresh")
    return {}


def save_state(state, retain_days=180):
    cutoff = (date.today() - timedelta(days=retain_days)).isoformat()
    pruned = {k: v for k, v in state.items() if v >= cutoff}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(pruned, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )
    log.info("state: %d ids retained", len(pruned))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int,
                    default=int(os.environ.get("LOOKBACK_DAYS", 2)),
                    help="how many days back to search (dedup handles overlap)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print results without writing the site or state")
    ap.add_argument("--no-preprints", action="store_true")
    args = ap.parse_args()

    journals_cfg = yaml.safe_load((CONFIG / "journals.yaml").read_text(encoding="utf-8"))
    topics_cfg = yaml.safe_load((CONFIG / "topics.yaml").read_text(encoding="utf-8"))

    contact = os.environ.get("CONTACT_EMAIL", "journal-brief@example.com")
    ncbi_key = os.environ.get("NCBI_API_KEY")
    site_url = os.environ.get("SITE_URL", "https://example.github.io/journal-brief/")

    start, end = sources.date_window(args.days)
    log.info("window %s -> %s", start, end)

    records = sources.fetch_pubmed(
        journals_cfg["journals"], start, end, contact, ncbi_key
    )

    pre = journals_cfg.get("preprints", {})
    if not args.no_preprints:
        if pre.get("biorxiv"):
            records += sources.fetch_biorxiv("biorxiv", start, end, contact)
        if pre.get("chemrxiv"):
            records += sources.fetch_chemrxiv(start, end, contact)

    scanned = len(records)
    log.info("scanned %d records", scanned)

    state = load_state()
    fresh = [r for r in records if r["id"] and r["id"] not in state]
    log.info("%d new after dedup", len(fresh))

    topics = scoring.compile_topics(topics_cfg["topics"])
    excludes = scoring.compile_excludes(topics_cfg.get("exclude"))
    journal_hits, preprint_hits = scoring.score_records(
        fresh, topics, excludes, topics_cfg
    )
    hits = journal_hits + preprint_hits
    log.info("%d journal hits, %d preprint hits",
             len(journal_hits), len(preprint_hits))

    if args.dry_run:
        for r in hits:
            meta = r.get("journal_meta") or {}
            print(f"{r['score']:6.2f}  {meta.get('tier','preprint'):8}  "
                  f"{r['journal'][:24]:26}  {r['title'][:70]}")
        print(f"\n{len(hits)} hits from {scanned} scanned (dry run, nothing written)")
        return

    publish.update_archive(DATA, hits, topics_cfg, scanned)
    publish.write_feed(FEED, DATA, site_url)

    for r in fresh:
        state[r["id"]] = r.get("date") or date.today().isoformat()
    save_state(state)
    log.info("done")


if __name__ == "__main__":
    main()
