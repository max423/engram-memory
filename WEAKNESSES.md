# Performance & weaknesses — honest assessment

Measured and reasoned limits of the current scaffold. Numbers from
`python3 tests/bench.py` on this machine (Python 3.9, best of 3).

## Performance (deterministic core, milliseconds)

| pages | collect | index | search | lint | detect | candidates |
|------:|--------:|------:|-------:|-----:|-------:|-----------:|
|    50 |    10.2 |  17.0 |  0.21  | 11.7 |   18.4 |          8 |
|   200 |    38.6 |  62.6 |  0.76  | 45.9 |   73.0 |          8 |
|  1000 |   203.4 | 332.2 |  4.20  |237.1 |  379.1 |          8 |
|  2000 |   414.5 | 691.4 |  8.75  |490.5 |  822.6 |          8 |

**What's good:**
- **`search` is the per-query hot path and stays single-digit ms** even at 2000
  pages (~9 ms). The interactive `/mem:query` path is effectively free.
- **`candidates` is constant (8) at every size.** This is the core promise: the
  context handed to the LLM is bounded by `--max-candidates`, never by wiki size.
  Token cost scales with the *change*, not the *wiki*.
- Everything is linear and predictable; no pathological cases observed.

**What's linear (and will eventually bite):** `index`, `lint`, and `detect` all
re-read and re-tokenize the whole wiki each run — O(total content). At 2000
pages that's ~0.5–0.8 s, which is fine at merge time. It is *not* fine at tens of
thousands of pages.

## Correctness, measured (not asserted)

`python3 tests/eval.py` turns "does it work?" into a scorecard. On the sample:
**recall@1 0.90 · recall@3 1.00 · MRR 0.95**, health clean, anti-drift on target.
The single retrieval miss is honest and instructive: *"attivare/disattivare una
feature senza deploy"* ranks `anti-drift` above `feature-flags-yaml` at rank 2 —
a paraphrase whose words overlap more with the wrong page. It's exactly the
lexical-BM25 limitation below, surfaced as a number rather than hidden.

What the harness can and cannot prove: checks 1–3 are deterministic and gate CI.
Check 4 (faithfulness — does a page invent/omit/contradict its source?) is the
one layer code can't settle alone; it needs an LLM judge (`--judge`) or a human.
That is the honest boundary of "automatically verified".

## How the LLM call is wired (no API key needed)

The "model call" is **not** the Anthropic API. The synthesis step
(`compile_llm`, `llm_reconcile`) routes through Claude Code, using your
subscription (e.g. Max). Two modes, by environment:

- **Interactive** (inside a Claude Code session): the `/mem:ingest|query` plugin
  commands — Claude *is* the LLM layer and does the synthesis directly, reading
  the minimal context the core selected. No subprocess.
- **Headless** (normal terminal / git hook / CI): `mem ingest --backend llm`
  and `mem reconcile --apply` shell out to `claude -p` ([core/memlib/llm.py](core/memlib/llm.py)),
  which also uses your subscription. A direct `anthropic` SDK call is only needed
  on a box where Claude Code isn't installed.

Caveat: `claude -p` refuses to nest inside an existing Claude Code session
(shared runtime). Inside a session, use the plugin command; the headless path is
for real terminals/hooks. `run_claude` detects this and says so.

## Weaknesses, by severity

### High — synthesis fidelity, not plumbing
- **Reconcile patches depend on the model emitting exact `str_replace` strings.**
  The applier is strict on purpose — `apply_patch` refuses a missing match and
  raises on an ambiguous (non-unique) one — so a sloppy patch is rejected, not
  mis-applied. That's safe but means some reconciles will no-op when they
  shouldn't until the prompt/patch loop is hardened (e.g. retry with anchored
  context). Verified offline with stubbed model output; the live patch loop wants
  more real-world testing.
- **Offline `compile` is extractive, not synthesis.** `mem ingest` *without*
  `--backend llm` structures a raw source into a `status: draft` page (title,
  choice line, key bullets, correct `sources:`). It does **not** densify/rewrite —
  that's the `llm` backend. Offline is the zero-token fallback that keeps the
  pipeline runnable with nothing installed; its output is a draft to refine.

### Medium — search quality and index freshness
- **Validated persisted index is in, but loading it is still O(wiki).**
  `detect`/`search` now load `index/` when a cheap manifest (one stat() per page,
  no content read) still matches the wiki, and rebuild live otherwise — verified
  cached≡live. Two regimes: when *no source changed* (the common merge), detect
  returns after hashing `raw/` without touching the wiki (truly O(change)); when a
  source changed but pages didn't, the cache avoids re-tokenizing the wiki (~2×
  at 2000 pages) but still parses the full term table. A postings-list index
  (term → [(doc, tf)]) would make BM25 load sub-linear; deferred.
- **BM25 is purely lexical, but normalized.** `tokenize` now drops IT/EN
  stopwords and applies a light symmetric stemmer (`fonti→fonte`,
  `decisioni→decisione`, `files→file`) — measured to lift sample recall@1 from
  0.90 to 1.00. It is still lexical: a page worded very differently from the query
  can be missed. The documented upgrade is hybrid BM25+vector with re-rank,
  deferred until scale demands it.

### Medium — git lifecycle edges
- **`index.md` is the merge-conflict soft spot — now with a helper.** `log.md`
  is append-only and wiki pages are atomic, but the catalogue insert edits
  `index.md` mid-file, so concurrent ingests on different branches can conflict.
  `mem merge` resolves such markers deterministically by unioning the two sides
  (deduping the catalogue by `[[slug]]`), handling 2-way and diff3 markers. Prose
  conflicts inside a wiki page are still out of scope (those want LLM reconcile).
  The `index/` artifacts and `sources.sha256` are git-ignored, so they never conflict.
- **`--since ORIG_HEAD` in the hook is best-effort.** Squash-merges and rebases
  may not leave `ORIG_HEAD` where expected; the SHA-256 snapshot (the default,
  git-independent path) is the robust fallback and catches what the ref diff misses.
- **Change detection is whole-file SHA.** Any whitespace edit to a source marks
  it `changed` and schedules a reconcile; there's no intra-file diff handed to
  the LLM yet (it receives the whole source).

### Low — parser and ingestion robustness
- **Frontmatter is a YAML *subset*.** Scalars, inline lists, and block lists
  only — no nested maps, multiline scalars, comments, or anchors. Round-trip is
  guaranteed for the shapes the tooling emits, not for arbitrary hand-written
  YAML. A `sources:` value containing a bare `:` must be quoted.
- **Slug collisions are filename-driven.** Two raw files that slugify to the same
  name would target the same page; the second is skipped unless `--force`.
- **Trust boundary.** The core only *reads* paths under `raw/` and `wiki/`; it
  never executes source content. Still, treat `raw/` as curated — a hand-written
  `sources:` with `..`/absolute paths is only existence-checked by lint, not
  sandboxed.

## Suggested next steps (in priority order)
1. Harden the reconcile patch loop: anchor `str_replace` targets, retry on a
   missing/ambiguous match, and exercise it on real changed sources from a normal
   terminal (the live `claude -p` path).
2. Go from the validated-load cache (done, ~2×) to a postings-list BM25 so a
   query loads only the relevant term lists → sub-linear `search`/`detect`.
3. ~~Light normalization in `tokenize`~~ (done: stopwords + light stemmer,
   recall@1 0.90→1.00). Next: hybrid BM25+vector re-rank when scale demands it.
4. ~~A `mem merge` helper for the residual `index.md` conflict~~ (done:
   deterministic union, slug-dedup, 2-way + diff3). Next: extend to prose
   conflicts inside a page via the reconcile prompt on the two sides.
