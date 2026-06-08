---
description: Compile new/changed curated sources in .memory/raw/ into wiki pages.
argument-hint: "[raw/file.md]  (optional: a single source; default: all changes)"
allowed-tools: Bash, Read, Edit, Write
---

Ingest the curated sources the deterministic core flags as new or changed.
Compile with minimal context — never read the whole wiki. This is the in-session
LLM path: **you** are the synthesis layer (no `claude -p`, no API key).

Optional focus: $ARGUMENTS  (a specific raw/ file; otherwise process all changes)

Steps:
1. Get the plan (zero tokens). `mem` is the CLI (installed via install.sh; if not
   on PATH, use `python3 core/mem.py`):
   `mem detect --json`
   (If `$ARGUMENTS` names a file, ingest just that one.)
2. For each item, read ONLY: `.memory/schema.md`, the changed raw source, and the
   candidate pages it lists. That is your entire context — nothing else.
3. Per candidate page choose one action, per the schema's status machine:
   **no-op** (default, most common) · **update** (surgical `str_replace`, never a
   rewrite) · **add** (new atomic page, with ≥1 inbound `[[link]]`) ·
   **contradiction** (flag + propose, never silently overwrite) · **deprecate**.
   Anti-drift rule: treat the **raw source** as truth, not the old page.
4. Every page you write/keep MUST have `sources:` pointing at the raw file, plus
   valid `id/type/status/title/tags/created/updated` frontmatter.
5. Update `.memory/index.md` (one catalogue line) and append to `.memory/log.md`
   (`## [YYYY-MM-DD] <op> | <title>`).
6. Finish deterministically, then record the sources as processed:
   `mem index && mem lint`  → fix anything lint flags →  `mem detect --update-snapshot`

Tip: for a fast, zero-token draft without synthesis, `mem ingest` (offline
backend) compiles new sources into `status: draft` pages you then refine here.
