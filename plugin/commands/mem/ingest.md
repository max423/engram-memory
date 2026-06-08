---
description: Compile new/changed curated sources in .memory/raw/ into wiki pages.
---

Ingest the curated sources the deterministic core flags as new or changed.
Compile with minimal context — never read the whole wiki.

Optional focus: $ARGUMENTS  (a specific raw/ file; otherwise process all changes)

Steps:
1. Run Phase 1 (zero tokens) to get the reconcile plan:
   `python3 core/change_detect.py --json`
   (If `$ARGUMENTS` names a file, ingest just that one.)
2. For each item in the plan, read ONLY: `.memory/schema.md`, the changed raw
   source, and the candidate pages listed. That is your entire context.
3. Per candidate page choose one action, per the schema's status machine:
   **no-op** (default, most common) · **update** (surgical `str_replace`, never a
   rewrite) · **add** (new atomic page, with ≥1 inbound `[[link]]`) ·
   **contradiction** (flag + propose, never silently overwrite) · **deprecate**.
   Anti-drift rule: treat the **raw source** as truth, not the old page.
4. Every page you write/keep MUST have `sources:` pointing at the raw file, plus
   valid `id/type/status/title/tags/created/updated` frontmatter.
5. Update `.memory/index.md` (catalogue line) and append to `.memory/log.md`
   (`## [YYYY-MM-DD] <op> | <title>`).
6. Finish deterministically:
   `python3 core/mem.py index && python3 core/mem.py lint`
   Fix anything lint reports, then
   `python3 core/change_detect.py --update-snapshot`.
