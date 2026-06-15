# Engram Memory

> A project memory that stays aligned with your code — and a knowledge base when you need more.

engram gives Claude Code (or any assistant) a **persistent memory that lives in your
repo as Markdown**, updates itself as you work, and costs almost no tokens.
**Python 3.9+, stdlib only. Zero dependencies. No API key** (it uses your Claude
subscription).

The principle: **code does the deterministic work; the LLM only does synthesis.**
Token cost scales with what *changed*, not with the size of the memory.

---

## Install

```bash
git clone https://github.com/max423/engram-memory ~/tools/engram
cd ~/tools/engram && ./install.sh      # puts `mem` on your PATH, runs the tests
```

Every command also works as `python3 core/mem.py <cmd>`.

## Activate in a project

```bash
cd my-project
mem init .              # default: code memory   (or: --template kb)
mem install-hooks .     # read on session start, write on its own, align on commit
mem context             # build the initial code map (0 tokens)
git add .memory && git commit -m "add engram memory"
```

From here you don't run anything — just use Claude Code normally.

## Two profiles

| Profile | `mem init .` | `mem init . --template kb` |
|---|---|---|
| **Code memory** (default) | One repo: a **code map** + **decisions** (the *why*). | A **multi-domain knowledge base**. |
| Layout | `wiki/{decisions,concepts,entities,synthesis}/` | `wiki/<domain>/…` (work, study, research, …) |
| Types | decision · concept · entity · synthesis | + meeting · session-note · project-brief · open-loop · source · person · procedure · … |
| Code map | yes (`mem context`) | not used (it isn't code-coupled) |

Both run the **same engine**: BM25 search, wikilink graph, auto-linking, git merge
driver, SHA change-detection. See [Knowledge base](#knowledge-base) below.

## How it works

1. **Session start** → the assistant gets a compact `mem digest` (the map + the
   decisions catalogue), so it knows the project without reading the repo.
2. **You work** → it searches the memory itself (`mem search`) and records durable
   facts itself (`mem note`). No commands.
3. **You commit** → a post-commit hook refreshes only what changed and commits the
   update. You push when you want — engram never pushes for you.

Everything is Markdown in git: every change is a reviewable diff you can roll back.

## Update loop (2-phase, change-driven)

- **Phase 1 — what to touch (code, 0 tokens).** Detect changed sources (SHA-256),
  select the few impacted pages via 5 signals (sources, BM25, backlinks,
  source-overlap, Adamic-Adar). No change → does nothing.
- **Phase 2 — how to edit (LLM, 1 call).** The model sees only the changed source +
  the candidate pages and applies surgical patches. It never reads the whole wiki.

## Commands

```bash
mem init . [--template software|research|product|kb]   # bootstrap .memory/
mem context              # build/refresh the code map (0 tokens)
mem digest               # the compact digest injected at session start
mem note "a fact"        # record a durable fact (writes a source + compiles it)
mem search "terms"       # BM25 search (--type/--tag/--status/--backlinks)
mem ingest               # compile new raw/ sources into pages
mem detect               # what changed (0 tokens) — the reconcile plan
mem reconcile --apply    # phase 2 over changed sources
mem relink               # deterministic auto-linking (0 tokens)
mem lint                 # structural + anti-drift health
mem review               # what needs your judgment (stale/contradicted/missing)
mem install-hooks .      # wire the automations + git merge driver
```

## Knowledge base

`mem init . --template kb` runs the same engine over a broader, multi-domain KB —
the **kb-template methodology**, vendored under [`methodology/`](methodology/):

- **Domains as folders.** A domain is just a `wiki/<domain>/` subfolder; the
  collector already indexes them. Register domains in `methodology/_domains.md`.
- **Richer taxonomy.** Meetings, project/entity briefs, sources, open loops,
  procedures, people… plus states `complete · superseded · tentative · rejected`.
  Lint validates the union.
- **Policies & templates.** `ingest-policy`, `lint-policy` (severity
  critical/major/minor), `citation-policy`, `domain-policy`, and note templates.
  Tool-agnostic `AGENTS.md` included.

## Anti-drift

The real risk is a wiki that re-reads its own output. Every page has a mandatory
`sources:`; on update the LLM re-reads the **source**, never the old page; patches
keep diffs small and reversible; `mem lint` flags staleness; you review in the PR.

## Tests

```bash
python3 tests/run.py     # unit tests (zero dependencies)
python3 tests/eval.py    # retrieval recall/MRR + health
python3 tests/bench.py   # benchmark 50→2000 pages
```

## License

**MIT © 2026 max423** — see [`LICENSE`](LICENSE). Keep the attribution notice.
engram composes MIT-licensed code (`praneybehl/llm-wiki-plugin`) and reimplements
patterns from other projects; details in [`NOTICE`](NOTICE).

> **Note:** the `methodology/` directory (the `kb` profile) is vendored from a
> colleague's `kb-template`, which currently ships **without a license**. Until its
> author grants one (ideally MIT), do not redistribute that directory. See `NOTICE`.
