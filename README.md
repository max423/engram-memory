# engram — curated, git-native, token-minimal project memory

A markdown knowledge base of **decisions** that lives in the repo, grows on its
own at every merge, and is versioned in git. One principle: **code does the
deterministic work; the LLM only does synthesis** → token cost is proportional to
the *change*, not to the size of the wiki.

Zero dependencies, **Python 3.9+ stdlib only**.

---

## Quickstart

```bash
./install.sh                 # puts `mem` on PATH (~/.local/bin) + runs the tests
mem init .                   # creates .memory/  (--template software|research|product)
# drop a decision into .memory/raw/, e.g. 2026-06-08-choice.md
mem ingest                   # compile new sources into draft pages (offline, 0 tokens)
mem index && mem lint        # rebuild indexes + health (exits !=0 on problems)
mem search "your terms"      # BM25 search (+ --type/--tag/--backlinks)
mem install-hooks .          # auto-update on merge to main
```

Every command also runs as `python3 core/mem.py <cmd>`. A sample `.memory/`
(4 decisions + 1 concept, linked and cited) is included so you can try it now.

## Architecture

```
LLM (synthesis only) → compile(source) · reconcile(diff, pages)   minimal context
CORE CLI (0 tokens)  → init·index·search(BM25)·lint·graph·detect·review·merge…
STORAGE (git)        → .memory/ : raw/ · wiki/{decisions,concepts,entities,synthesis}
                                  · schema.md · index.md · log.md · context.md · index/ (gitignored)
```

### Repo layout

```
bin/mem · install.sh        # PATH wrapper + plug-and-play setup
core/
  mem.py                    # single CLI (init·index·search·lint·graph·detect·reconcile·ingest·context·
                            #  digest·note·relink·alias·hubs·review·add-synthesis·merge·merge-driver·install-hooks)
  change_detect.py          # Phase 1 reconcile: WHAT to touch (SHA-256 + signals), 0 tokens
  reconcile.py              # Phase 2 reconcile: HOW to edit (patches + retry, the LLM call)
  memlib/                   # stdlib library: frontmatter · pages · bm25 · graph · store
                            #  · compile · llm · index_store · ranking · relink · hubs · merge · context
hooks/                      # post-merge (reconcile at merge) · post-commit (update at commit)
plugin/                     # Claude Code plugin: commands /mem:* + auto-invoked `project-memory` skill
tests/                      # run.py (71 unit tests) · eval.py (scorecard) · bench.py
.memory/                    # sample memory
```

### The 2-phase reconcile

**Phase 1 — WHAT to touch (code, 0 tokens).** Detects new/changed sources
(SHA-256) and selects the few impacted pages with 5 signals: `sources:`, BM25,
graph backlinks, **source-overlap**, **Adamic-Adar** (additive scores). When no
source changed, it returns immediately without touching the wiki.

**Phase 2 — HOW to edit (LLM, 1 call, minimal context).** Receives schema +
source + candidate pages and classifies each page
`no-op / update / add / contradiction / deprecate`, applying surgical patches
(`str_replace`, tolerant to whitespace/quotes/dashes, with retry if the match is
missing/ambiguous). Pages follow the state machine
`draft → active → stale → contradicted → archived`.

### Two memory layers

Beyond curated **decisions** (the *why*), `mem context` maintains a
code-aligned **big-picture map** (`.memory/context.md`, the *what/how*): a compact
overview derived from the code — modules, languages, manifests, one-line
descriptions. It is **change-driven**: the deterministic core groups the tree and
hashes it at 0 tokens, and only modules whose code changed get their description
regenerated (offline from README/docstring, or `--backend llm` to enrich just
those). This is the layer meant to keep an assistant's view aligned with the code,
and what a SessionStart hook injects so it knows the project's shape upfront.

### Transparent in Claude Code (no commands)

`mem install-hooks` wires three touch-points so the memory just *works* while you
use Claude Code normally:

- **Read (automatic):** a Claude Code **SessionStart** hook injects `mem digest`
  (the context map + decisions catalogue) at the start of every session — the
  assistant knows the project's shape without reading the repo. Wired by merging
  `.claude/settings.json` (non-destructively).
- **Write (autonomous):** an auto-invoked **`project-memory` skill** tells the
  assistant to recall with `mem search` and record durable facts with `mem note`
  on its own — `mem note` writes a `raw/` source (anti-drift intact) and compiles it.
- **Align with code (on commit):** a **post-commit** git hook refreshes the
  context map and ingests changed sources, then auto-commits the memory update.
  The deterministic change-detect is the gate (0 tokens; no-op when nothing
  relevant changed), with a **double anti-loop guard** (env flag + commit-message
  sentinel). Inside a Claude Code session `claude -p` can't nest, so the hook stays
  deterministic and the in-session assistant does any enrichment itself; from a
  plain terminal it can use `claude -p`. Toggle with `MEM_POSTCOMMIT=0`.

## LLM backend — with your subscription, no API key

Synthesis goes through Claude Code, not the Anthropic API:
- **Interactive** (in-session): plugin commands `/mem:ingest` · `/mem:query` · `/mem:lint`.
- **Headless** (terminal/hook/CI): `mem ingest --backend llm`, `mem reconcile --apply`
  shell out to `claude -p`. (Not nestable inside an active session → use the plugin there.)

Without `--backend llm`, `mem ingest` uses the deterministic **offline** backend
(extractive, 0 tokens): `draft` pages to refine — it keeps the loop runnable anywhere.

## Useful commands

```bash
mem context                  # build/refresh the code-aligned big-picture map (change-driven)
mem digest                   # compact memory digest (map + decisions) — for SessionStart injection
mem note "a durable fact"    # record a fact as a source (+compile) — the assistant's write tool
mem detect                   # what changed (0 tokens); the "reconcile plan"
mem relink                   # deterministic auto-linking: `## Correlate` section (0 tokens)
mem alias <slug> "synonym"   # curate search aliases (against lexical miss)
mem hubs --apply             # create disambiguation hub pages for ambiguous clusters
mem reconcile --apply        # Phase 2 over changed sources (via claude -p)
mem review                   # review queue: contradicted/stale pages + anti-drift
mem add-synthesis --title T --links a,b   # file an answer as a synthesis/ page
mem merge                    # resolve git conflicts on index.md/log.md by union (post-hoc)
```

`mem install-hooks` also registers a **real git merge driver** (`mem
merge-driver %O %A %B %P`) via `.memory/.gitattributes` + `.git/config`: on
`git merge`, catalogue/log are **unioned automatically** (dedup by slug/line,
0 tokens), atomic pages auto-merge, and a page touched incompatibly on two
branches keeps its conflict markers → flagged to `mem review` (no LLM call inside
`git merge`: deterministic and non-blocking).

## Tests, evaluation, performance

```bash
python3 tests/run.py         # 71 unit tests (zero dependencies)
python3 tests/eval.py        # "does it retrieve the right thing?" → recall/MRR + health + anti-drift
python3 tests/bench.py       # benchmark 50→2000 pages
```

On the sample: **recall@1 1.00 · recall@3 1.00 · MRR 1.00**, clean health → `PASS`.
`search` ~9 ms at 2000 pages; candidate pages **constant (8)** at every scale
(token locality). Works on your own memory:
`python3 tests/eval.py --memory /path/.memory --labels yours.json`.

---

## Design decisions

| Dimension | Choice |
|---|---|
| **Purpose** | Memory of *curated decisions* (Karpathy's LLM Wiki pattern), not code auto-doc. The user decides what is a source (drop into `raw/`); the system processes it. |
| **Shape** | Deterministic core CLI (0 tokens for 90% of operations) + thin LLM layer only for synthesis. |
| **Update** | On **merge** to the canonical branch (hook), not on every commit of every branch. |
| **Storage** | All markdown in the repo, versioned. No database. |
| **Differentiator** | token-efficiency + git-native + reconcile pipeline at merge. |

**Git lifecycle.** Memory is **tied to the code**: it lives in `.memory/` in the
same repo, so it rides the code branches (branch the code → `.memory/` branches
with it) and is reviewed in the same PR. Reconcile fires **on merge** → feature
branches don't pollute the memory. Conflicts are handled via git with a
**dedicated merge driver** (`mem merge-driver`, wired by `install-hooks`): atomic
pages auto-merge, catalogue/log union automatically, prose conflicts keep their
markers → `mem review`. `mem merge` remains as a manual post-hoc resolver.

**Anti-drift** (the real risk: the wiki "re-reading its own output"):
`sources:` is mandatory on every page; in reconcile the LLM re-reads the
**updated source**, never the old page; surgical patches (small diffs, rollback
via git); lint on staleness; human-in-the-loop on the PR.

**Differentiation.** The space is crowded (DeepWiki, ~20 clones of the Karpathy
pattern, and mature products like `nashsu/llm_wiki`), but none combines
**token-efficiency + git-native + merge-hook-driven reconcile** in a
zero-dependency CLI installable in one command. That's the IP.

## Working conventions

- Core in **Python 3.9+ stdlib only**, zero runtime dependencies.
- Each wiki page = one concept (atomic): soft cap ~400 lines, hard cap ~800.
- `log.md` append-only, prefix `## [YYYY-MM-DD] <op> | <title>` (greppable).
- Every core operation produces small, clean diffs.
- Mandatory frontmatter: `id · type · status · title · tags · sources · created · updated`.
  Types: `decision · concept · entity · synthesis`. States: `draft · active · stale ·
  contradicted · archived`. Optional: `aliases` (search synonyms).

## Claude Code plugin

Thin commands that drive the CLI (synthesis runs in-session, with your
subscription — no API key):

| Command | What it does |
|---|---|
| `/mem:ingest [raw/file.md]` | Compile new/changed sources into wiki pages. |
| `/mem:query <question>` | Answer from memory, index-first, citing the pages. |
| `/mem:lint [fix]` | Health + anti-drift; optionally apply surgical fixes. |

Prerequisite: `./install.sh` puts `mem` on PATH. If absent, the commands also work
via `python3 core/mem.py …`.

## How it's built

Composed by forking an MIT core and reimplementing patterns (never copying
non-permissive code):

- **Base fork** → `praneybehl/llm-wiki-plugin` (BM25 + lint, stdlib, MIT).
- **Ideas** → SHA-256 change-detect (`ktrysmt`), merge hook (`balukosuri`),
  decision/memory schema (`Oshayr`), compilation principles (`virgiliojr94/book-to-skill`).
- **Studied, not copied** → `synthadoc`'s state machine (AGPL) and `nashsu/llm_wiki`'s
  4-signal relevance + review system (GPL).

Attribution details in [`NOTICE`](NOTICE).

## Status

Working and tested (71 tests, eval `PASS`): deterministic core, Phase 1, offline +
LLM ingest, Phase 2 reconcile (tolerant patches + retry), merge hook with
**auto-commit** + **git merge driver** (`mem merge-driver`, tested end-to-end with
real merges), plug-and-play, Claude Code plugin, review queue, `add-synthesis`,
scenario templates, 4-signal ranking.

**Real-corpus benchmark** (40 ADRs from `architecture-decision-record`):
ingest 40 sources in ~0.3 s (0 tokens); index build 0.9 ms; search 0.04 ms/query;
candidate locality **constant at 8** (Phase 2 sees 8 pages, not 40). Retrieval:
recall@1 **0.95** / recall@3 **1.00** / MRR **0.97** with domain-vocabulary
queries; drops to 0.60 on paraphrases with no lexical overlap — the known cost of
pure BM25 (zero deps, no embeddings). Three deterministic levers, 0 tokens:
- **`mem relink`** (also in offline `ingest`) takes orphans from **40 → 1**
  (only the genuinely isolated page remains: no fabricated links) and revives the
  graph signal in candidate selection.
- **`mem alias`** (curated synonyms in `aliases:`, indexed) recovers the lexical
  miss: on adversarial paraphrases recall@1 **0.60 → 0.70**, recall@3 0.85 →
  **0.95**, MRR 0.72 → **0.83**, by aliasing 4 pages.
- **`mem hubs`** detects ambiguous clusters (database, javascript, languages) and
  generates disambiguation hub pages that fan out (drops common boilerplate,
  readable label, anchored to the members' sources).

**Open:** a real LLM reconcile via `claude -p` from a terminal.

## License

MIT. Composes code from `praneybehl/llm-wiki-plugin` (MIT); reimplements patterns
from other projects — see [`NOTICE`](NOTICE).
