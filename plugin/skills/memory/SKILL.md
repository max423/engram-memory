---
name: project-memory
description: Use the project's engram memory to stay aligned with the codebase — recall past decisions, architecture and constraints, and record durable new facts. Invoke this whenever you need project context you don't already have, or when a decision/constraint worth remembering emerges. Backed by the `mem` CLI (zero-token deterministic core); no API key.
allowed-tools: Bash, Read
---

# Project memory (engram)

This project keeps a curated, git-native memory under `.memory/`. Use it instead
of scanning the whole repo. The `mem` CLI is the interface (if not on PATH, use
`python3 core/mem.py`). Everything here is token-minimal — **never read the whole
wiki**.

## When to READ from memory (do this proactively)

Before exploring the codebase or answering an architecture/decision question:

1. Get the big picture: read `.memory/context.md` (the code-aligned map) — or run
   `mem digest` for map + decisions catalogue in one shot.
2. Narrow deterministically (0 tokens): `mem search "<key terms>" --top 5`
   (`--type decision`, `--tag <t>`, `--backlinks <slug>` to focus).
3. Open ONLY the 1–4 pages the search surfaces. Check their `sources:` if you need
   to verify a claim against the raw source. Cite pages by slug, e.g.
   `[[reconcile-al-merge]]`. If memory doesn't cover it, say so — don't invent.

## When to WRITE to memory (record durable facts autonomously)

When a **durable** fact emerges during the work — a decision made, a constraint
discovered, "module X is responsible for Y", a tradeoff chosen — record it:

```bash
mem note "Postgres chosen over Mongo: we need transactions and team knows it"
```

`mem note` writes a `raw/` source (the source of truth, anti-drift intact) and
compiles it into a page. Record the **why**, compactly. Do NOT record trivia,
one-off lookups, or things already in memory (search first). Prefer one atomic
fact per note.

## Keeping memory aligned with the code

The code-aligned map refreshes automatically on commit (post-commit hook). If you
changed code and want the map current immediately: `mem context`. If you added or
edited a `raw/` source: `mem ingest` (then `mem lint`).

## Guardrails

- Index-first, minimal context: catalogue/search before reading pages.
- Every claim a page makes must trace to a `sources:` file — that's the anti-drift
  contract. When reconciling, re-read the **source**, never the old page.
- Keep diffs small; the memory lives in git and is reviewable.
