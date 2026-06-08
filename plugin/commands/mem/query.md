---
description: Answer a question from the project memory, citing the pages used.
---

Answer the user's question using the curated project memory, spending as few
tokens as possible. Follow the index-first protocol — do NOT read the whole wiki.

Question: $ARGUMENTS

Steps:
1. Read `.memory/index.md` first (the catalogue: one line per page).
2. Narrow with the deterministic core (zero tokens), e.g.:
   `python3 core/mem.py search "<key terms from the question>" --top 5`
   Use `--type decision`, `--tag <t>`, or `--backlinks <slug>` to focus.
3. Open ONLY the 1–4 pages the search surfaces. Read their `sources:` if you
   need to verify a claim against the raw source.
4. Answer concisely and **cite the pages** you used by slug (e.g.
   `[[reconcile-al-merge]]`). If the memory doesn't cover it, say so plainly —
   do not invent.
