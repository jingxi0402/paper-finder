# Journal Brief

A self-updating website that tracks new papers from a whitelist of journals,
filtered by keyword relevance and gated on journal IF / 中科院分区. Rebuilds
itself every weekday morning on GitHub Actions and publishes to GitHub Pages.
No server, no cost, no email account involved.

```
PubMed + bioRxiv + chemRxiv  →  dedupe  →  keyword score  →  IF / 分区 gate  →  docs/data/items.json
```

The page reads that JSON and does everything else in the browser: search,
topic filters, tier and score thresholds, and a 45-day signal trace showing
volume and topic mix at a glance. Papers you have not seen since your last
visit are marked `NEW`.

---

## Setup (about 10 minutes)

### 1. Push to GitHub

**Read this before choosing public or private.** GitHub Pages only works on
private repos with a paid plan (Pro, Team, Enterprise). On a free account,
Pages requires the repo to be **public**.

- **Public repo** — simplest, works on free. What becomes visible: your
  keyword list and the papers you track. All of it is public metadata already,
  but it does broadcast what you are reading, which is worth a moment's thought
  pre-publication.
- **Private repo + Pro** — about $4/month. ETH affiliation may qualify you for
  GitHub Education, which includes Pro at no cost.
- **Private repo, no Pages** — still works. Clone the repo and open
  `docs/index.html` locally, or run `python -m http.server` inside `docs/`.
  You lose access from your phone.

### 2. Turn on Pages

Settings → Pages → Source: **Deploy from a branch** → branch `main`,
folder **`/docs`** → Save.

Your site appears at `https://<username>.github.io/<repo>/` within a minute or
two.

### 3. Optional secrets

Nothing is required. Two are worth adding:

| Secret | Why |
|---|---|
| `CONTACT_EMAIL` | NCBI asks API users to identify themselves. Polite, and reduces throttling. |
| `NCBI_API_KEY` | Free from your NCBI account. Raises the rate limit from 3 to 10 requests/sec. |

### 4. Fill it with something

Actions tab → *Daily Journal Brief* → **Run workflow** → set lookback to `7`.
Wait a minute, then open your Pages URL. Until this runs, the page correctly
shows an empty state.

Local testing without touching the site:

```bash
pip install -r requirements.txt
python src/main.py --days 7 --dry-run     # prints matches, writes nothing
```

`--dry-run` never modifies `docs/` or the dedup state, so run it as often as
you like while tuning keywords.

To preview the page locally after a real run:

```bash
cd docs && python -m http.server 8000     # then open localhost:8000
```

### 5. Schedule

Already set: **07:15 Zurich, weekdays** (`15 5 * * 1-5`, in UTC). Edit
`.github/workflows/daily-brief.yml` to change it. GitHub sometimes delays
scheduled jobs 5–20 minutes under load — harmless here.

---

## Tuning

**`config/topics.yaml`** — keywords, weights, thresholds.

Scoring: per topic, a term in the **title** scores 3, a term in the
**abstract** scores 1, times the topic weight, summed across topics. Trailing
`*` is a prefix match (`fluorinat*` catches fluorinated, fluorination).
Matching respects word boundaries, so `BSH` will not fire inside other words.

The knobs that matter:

- `min_keyword_score` (default 4.5) — the main volume dial. Too much noise?
  Raise to 6–8. Too little? Drop to 3.
- `min_if` and `allowed_tiers` — the hard IF / 分区 gate.
- `preprint_min_keyword_score` (default 7.5) — deliberately stricter, since
  preprints have no editorial filter and bioRxiv alone posts ~150/day.
- `max_items` — hard cap per run, so a bad config cannot flood the archive.
- `topic_colors` — maps each topic to blue / teal / orange / purple, matching
  the Fluxi-gut figure palette. Drives the accent rule on each item and the
  colours in the signal trace.

**`config/journals.yaml`** — the whitelist, and your IF / 分区 lookup table.

To add a journal you need its exact PubMed abbreviation. Search the journal on
PubMed, open any article, and copy the abbreviation from the citation line
(e.g. `Nat Chem Biol`). Get it wrong and that journal silently returns nothing
— the most likely failure mode in the whole system.

### Annual maintenance

**IF and 中科院分区 are proprietary and have no free API.** The values in
`journals.yaml` are approximate and need verifying against the official
releases. Update once a year: JCR lands around June, 中科院分区 around
March–April. Ten minutes, one file.

---

## How it behaves

- **Dedup** is by DOI, falling back to PMID, tracked in `state/seen.json`. The
  2-day default lookback deliberately overlaps to absorb PubMed's indexing lag;
  dedup removes the repeats.
- **Archive** lives in `docs/data/items.json`, pruned to `retain_days` (500)
  with abstracts trimmed to 420 characters. At a realistic ten hits a day that
  file reaches roughly 2 MB after a year, which the browser loads instantly.
- **A dead API** (NCBI maintenance, a chemRxiv schema change) is logged and
  skipped, not fatal. The other sources still publish.
- **RSS** is generated at `docs/feed.xml`, so you can also follow it in a
  reader if you want a push signal without checking the site.
- **`NEW` markers** use `localStorage`, so they are per-browser and reset if
  you clear site data. Nothing is tracked server-side.

## Known limits

- PubMed indexing lags online publication by 1–3 days for some publishers.
  Journal RSS feeds would be faster, but PubMed gives clean abstracts and
  uniform journal filtering, which the keyword scoring depends on.
- Keyword matching is literal. A paper describing reductive dehalogenation
  without ever using your terms will be missed. If recall matters more than
  precision, lower the threshold and accept noise — or add an LLM relevance
  pass in `scoring.py`, which is where it would go.
