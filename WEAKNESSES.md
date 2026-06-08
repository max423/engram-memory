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

## Weaknesses, by severity

### High — the differentiator is still a stub
- **`reconcile` Phase 2 (the LLM call) is not wired.** The plumbing around it is
  real and tested (`apply_patch` with str_replace + ambiguity guard, status
  machine, append-only log), but the actual model decision
  (`no-op/update/add/contradiction/deprecate`) is a `NotImplementedError`. Until
  it's wired, the memory does not truly "update itself" on a *changed* source.
- **Offline `compile` is extractive, not synthesis.** `mem ingest` (default
  backend) structures a raw source into a `status: draft` page — title, the
  explicit choice line, key bullets, a correct `sources:` anchor. It does **not**
  rewrite/densify. "Grows by itself" is only fully true once `compile_llm` is
  wired; today offline ingest gives you drafts a human (or the LLM) refines.

### Medium — search quality and index freshness
- **`detect` and `search` rebuild BM25 every run** instead of loading the
  persisted `index/bm25.idx`. This is a deliberate correctness choice (a stale
  persisted index would miss new/edited pages), but it's why `detect` is O(wiki).
  The right fix is an incremental/validated persisted index (rebuild only changed
  docs); the artifact format already supports it.
- **BM25 is purely lexical: no stemming, no stopwords, mixed IT/EN.**
  `decisione`/`decisioni`, `merge`/`merging` are different terms; recall can miss
  a relevant page whose wording differs from the source. Tags + title are folded
  into the document tokens to soften this. The documented upgrade is hybrid
  BM25+vector with re-rank, deferred until scale demands it.

### Medium — git lifecycle edges
- **`index.md` is the merge-conflict soft spot.** `log.md` is strictly
  append-only (conflict-free) and wiki pages are atomic (one concept = one file),
  but the catalogue insert edits `index.md` in the middle, so concurrent ingests
  on different branches can conflict there. The `index/` artifacts and
  `sources.sha256` snapshot are git-ignored, so they never conflict.
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
1. Wire `compile_llm` + `llm_reconcile` (the single model call each). Everything
   downstream already exists and is tested.
2. Make `detect`/`search` load a *validated* persisted index (rebuild only the
   docs whose mtime/SHA changed) → `detect` drops from O(wiki) to O(change).
3. Light normalization in `tokenize` (lowercasing is done; add a small IT/EN
   stopword list + optional stemming) before reaching for vectors.
4. A `mem merge` helper for the residual `index.md` conflict case (reuse the
   reconcile prompt on the two sides).
