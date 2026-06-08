# engram — a project memory that stays aligned with your code

engram gives Claude Code (or any assistant) a **persistent, curated memory of your
project** that lives in your repo as markdown, updates itself as you work, and
costs almost no tokens. You install it once; from then on it just works while you
use Claude Code normally.

Two things it remembers:
- **Decisions** — the *why* (why Postgres over Mongo, why JWT, the tradeoffs).
- **A code map** — the *what/how* (modules, languages, what each part does), kept
  aligned with the code automatically.

One principle makes it cheap: **code does the deterministic work; the LLM only does
synthesis.** Token cost is proportional to what *changed*, not to the size of the
memory. Zero dependencies — **Python 3.9+, stdlib only**. No API key (it uses your
Claude subscription).

---

## How it works, in plain words

After a one-time setup, three things happen automatically while you use Claude Code:

1. **You open Claude Code** → it's handed a compact *digest* (the project map +
   the decisions already made), so it knows your project without reading the repo.
2. **You work normally** → when it needs context it searches the memory itself;
   when a durable decision/constraint comes up, it records it itself. No commands.
3. **You `git commit`** → a hook refreshes the memory and re-aligns it with the
   code (only the parts that changed), and commits the update.

You never run a command unless you want to. The memory is plain markdown in git,
so every change is a reviewable diff you can inspect or roll back.

---

## 1. Install (once)

Clone this repo somewhere and run the installer — it puts the `mem` command on your
PATH and runs the test suite:

```bash
git clone https://github.com/max423/engram.git ~/tools/engram
cd ~/tools/engram
./install.sh
mem --help          # if "command not found", add ~/.local/bin to your PATH
```

`install.sh` is the only setup. Every command also works as
`python3 core/mem.py <cmd>` if you'd rather not touch your PATH.

## 2. Activate it in your codebase (once per project)

```bash
cd ~/dev/my-project
mem init .             # create the .memory/ folder
mem install-hooks .    # turn on the 3 automations (read, write, align-on-commit)
mem context            # build the initial code map (0 tokens)
git add .memory && git commit -m "add engram memory"
```

That's it. From here on you don't have to run anything.

## 3. Use it — just work

Open Claude Code in your project as usual (`claude`). It receives the project
digest at startup, recalls and records on its own, and the memory re-aligns with
the code on every commit.

If you *want* to drive it by hand:

```bash
mem note "Chose Stripe for payments: lower fees, better SDK than PayPal"
mem search "how do we handle auth"
mem digest                 # what it currently knows about the project
mem review                 # what needs your judgment (stale/contradicted/missing source)
```

---

## Does the memory go into git? (yes — but you push)

The memory is **versioned with your code**, on purpose (it's git-native). But
engram **never pushes for you** — pushing stays your normal manual step.

**Committed** (travels with the repo on `git push`):

```
.memory/raw/         your sources (the source of truth)
.memory/wiki/        the pages (decisions, concepts, …)
.memory/context.md   the code map
.memory/index.md     the catalogue (one line per page)
.memory/log.md       append-only history
.memory/schema.md    the domain schema
```

**Not committed** (gitignored — regenerable, never the source of truth):

```
.memory/index/       BM25 index, graph, SHA snapshots
```

The **post-commit hook makes local commits only** (a follow-up `[mem] auto-update`
commit). You decide when it reaches the remote:

```bash
git commit -m "..."     # engram also makes a local [mem] auto-update commit
git push                # now the updated memory goes to the remote too
```

Because it's in the repo, **your whole team shares one project memory** — they get
it on `git pull`, and memory updates are reviewable in the same PR as the code. If
you'd rather *not* share it (e.g. personal notes), add `.memory/` to `.gitignore`
or keep it on a separate branch. To skip the auto-update on a specific commit:
`MEM_POSTCOMMIT=0 git commit ...`.

---

## The two memory layers

**Decisions (the *why*).** You drop a source into `.memory/raw/` (or let the
assistant do it with `mem note`), and `mem ingest` compiles it into an atomic page
with a mandatory `sources:` anchor. Pages link to each other and follow a state
machine `draft → active → stale → contradicted → archived`.

**Code map (the *what/how*).** `mem context` maintains `.memory/context.md`: a
compact overview derived from the code — modules, languages, manifests, a one-line
description each. It's **change-driven**: the deterministic core groups and hashes
the tree at 0 tokens, and only modules whose code changed get re-described (offline
from README/docstring, or `--backend llm` to enrich just those). This is the layer
that keeps an assistant's view aligned with the code, and what the digest injects.

---

## Transparent in Claude Code (the 3 automations)

`mem install-hooks` wires three touch-points so you don't run commands:

- **Read (automatic).** A Claude Code **SessionStart** hook injects `mem digest`
  (code map + decisions catalogue) at the start of every session. Wired by merging
  `.claude/settings.json` non-destructively.
- **Write (autonomous).** An auto-invoked **`project-memory` skill** tells the
  assistant to recall with `mem search` and record durable facts with `mem note` on
  its own. `mem note` writes a `raw/` source (anti-drift intact) and compiles it.
- **Align on commit.** A **post-commit** git hook refreshes the code map and ingests
  changed sources, then auto-commits. The deterministic change-detect is the gate
  (0 tokens; a no-op when nothing relevant changed), with a **double anti-loop
  guard** (env flag + commit-message sentinel). Inside a Claude Code session
  `claude -p` can't nest, so the hook stays deterministic and the in-session
  assistant does any enrichment itself; from a plain terminal it can use `claude -p`.
  Toggle with `MEM_POSTCOMMIT=0`.

`install-hooks` also installs a **post-merge** hook and registers a real **git merge
driver** (see below).

---

## How the update works (2-phase reconcile)

When a source or the code changes, engram updates only what's affected:

**Phase 1 — WHAT to touch (code, 0 tokens).** Detects changed sources (SHA-256) and
selects the few impacted pages with 5 signals: `sources:`, BM25, graph backlinks,
source-overlap, Adamic-Adar. No change → it returns immediately, touching nothing.

**Phase 2 — HOW to edit (LLM, 1 call, minimal context).** Gets schema + the changed
source + the candidate pages, and classifies each page
`no-op / update / add / contradiction / deprecate`, applying surgical patches
(`str_replace`, tolerant to whitespace/quotes/dashes, with retry if a match is
missing/ambiguous). The LLM never sees the whole wiki — only the few candidates.

---

## LLM backend — your subscription, no API key

Synthesis goes through Claude Code, not the Anthropic API:

- **Interactive** (in a session): plugin commands `/mem:ingest` · `/mem:query` ·
  `/mem:lint`, and the auto-invoked `project-memory` skill.
- **Headless** (terminal/hook/CI): `mem ingest --backend llm`, `mem reconcile
  --apply`, `mem context --backend llm` shell out to `claude -p`. (Can't nest inside
  an active session — there the in-session assistant is the LLM.)

Without `--backend llm`, the **offline** backend is deterministic and extractive
(0 tokens): it structures sources into `draft` pages and derives the code map from
README/docstrings — so the whole loop runs anywhere, even with no LLM at all.

---

## Command reference

```bash
mem init .                   # bootstrap .memory/ (--template software|research|product)
mem install-hooks .          # wire the 3 automations + merge driver + git hooks
mem context                  # build/refresh the code map (change-driven, 0 tokens)
mem digest                   # compact digest (map + decisions) — what SessionStart injects
mem note "a durable fact"    # record a fact as a source (+compile) — the write primitive
mem ingest                   # compile new raw/ sources into pages (--backend offline|llm)
mem search "terms"           # BM25 search (+ --type/--tag/--backlinks/--status)
mem detect                   # what changed (0 tokens); the reconcile plan
mem reconcile --apply        # Phase 2 over changed sources (via claude -p)
mem relink                   # deterministic auto-linking: `## Correlate` sections (0 tokens)
mem alias <slug> "synonym"   # curate search aliases (against lexical miss)
mem hubs --apply             # create disambiguation hubs for ambiguous clusters
mem review                   # queue: contradicted/stale pages + anti-drift problems
mem lint                     # structural + anti-drift health (exits !=0 on problems)
mem add-synthesis --title T --links a,b   # file a worthy answer as a synthesis/ page
mem merge                    # resolve git conflicts on index.md/log.md by union (post-hoc)
```

**Git merge driver.** `install-hooks` registers `mem merge-driver` via
`.memory/.gitattributes` + `.git/config`. On `git merge`, catalogue/log are unioned
automatically (dedup by slug/line, 0 tokens), atomic pages auto-merge, and a page
edited incompatibly on two branches keeps its conflict markers → flagged to
`mem review`. No LLM call inside `git merge`: deterministic and non-blocking.

---

## Tests, evaluation, performance

```bash
python3 tests/run.py         # 71 unit tests (zero dependencies)
python3 tests/eval.py        # "does it retrieve the right thing?" → recall/MRR + health
python3 tests/bench.py       # benchmark 50→2000 pages
```

On the sample memory: **recall@1 1.00 · recall@3 1.00 · MRR 1.00**, clean health →
`PASS`. `search` ~9 ms at 2000 pages; candidate pages **constant (8)** at every
scale — the LLM context never grows with the wiki.

**Real-corpus benchmark** (40 ADRs from `architecture-decision-record`): ingest in
~0.3 s (0 tokens); index build 0.9 ms; search 0.04 ms/query; candidate locality
constant at 8. Retrieval **recall@1 0.95 / recall@3 1.00 / MRR 0.97** with
domain-vocabulary queries; drops to 0.60 on paraphrases with no lexical overlap —
the known cost of pure BM25 (zero deps, no embeddings). Three deterministic levers
(0 tokens) recover it: `mem relink` takes orphans 40→1; `mem alias` lifts
adversarial recall@1 0.60→0.70; `mem hubs` adds disambiguation hubs.

---

## Design decisions

| Dimension | Choice |
|---|---|
| **Purpose** | A project memory tied to the code: curated *decisions* + an auto-maintained *code map*. |
| **Shape** | Deterministic core CLI (0 tokens for ~90% of operations) + a thin LLM layer for synthesis only. |
| **Update** | On commit (code map) and on merge (decisions) — change-driven, never the whole wiki. |
| **Storage** | All markdown in the repo, versioned. No database. |
| **Differentiator** | token-efficiency + git-native + transparent Claude Code integration. |

**Anti-drift** (the real risk — a wiki that "re-reads its own output"): every page
has a mandatory `sources:`; on update the LLM re-reads the **source**, never the old
page; surgical patches keep diffs small and rollback-able; lint flags staleness;
humans review in the PR.

**Git lifecycle.** The memory lives in `.memory/` in the same repo, so it rides the
code branches (branch the code → the memory branches with it) and is reviewed in the
same PR. Conflicts are handled by git via the merge driver.

---

## Working conventions

- Core in **Python 3.9+ stdlib only**, zero runtime dependencies.
- Each wiki page = one concept (atomic): soft cap ~400 lines, hard cap ~800.
- `log.md` append-only, prefix `## [YYYY-MM-DD] <op> | <title>` (greppable).
- Every core operation produces small, clean diffs.
- Mandatory frontmatter: `id · type · status · title · tags · sources · created ·
  updated`. Types: `decision · concept · entity · synthesis`. States: `draft ·
  active · stale · contradicted · archived`. Optional: `aliases` (search synonyms).

## Claude Code plugin

| Item | What it does |
|---|---|
| `project-memory` **skill** | Auto-invoked: recall with `mem search`, record with `mem note`, stay aligned. |
| `/mem:ingest [raw/file.md]` | Compile new/changed sources into wiki pages. |
| `/mem:query <question>` | Answer from memory, index-first, citing the pages. |
| `/mem:lint [fix]` | Health + anti-drift; optionally apply surgical fixes. |

## How it's built

Composed by forking an MIT core and reimplementing patterns (never copying
non-permissive code):

- **Base fork** → `praneybehl/llm-wiki-plugin` (BM25 + lint, stdlib, MIT).
- **Ideas** → SHA-256 change-detect (`ktrysmt`), merge hook (`balukosuri`),
  decision/memory schema (`Oshayr`), compilation principles (`virgiliojr94/book-to-skill`).
- **Studied, not copied** → `synthadoc`'s state machine (AGPL) and `nashsu/llm_wiki`'s
  4-signal relevance + review system (GPL).

Attribution details in [`NOTICE`](NOTICE).

## License

MIT. Composes code from `praneybehl/llm-wiki-plugin` (MIT); reimplements patterns
from other projects — see [`NOTICE`](NOTICE).
