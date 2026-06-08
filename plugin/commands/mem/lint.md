---
description: Run the deterministic memory health check and report (and optionally fix) issues.
---

Check the structural and anti-drift health of the project memory. The lint
itself is deterministic and free — your job is to interpret and, if asked, fix.

Optional: $ARGUMENTS  (e.g. "fix" to apply corrections, otherwise just report)

Steps:
1. Run `python3 core/mem.py lint`. It reports: pages with no `sources:` or
   dangling sources (anti-drift), missing/malformed frontmatter, invalid
   type/status, broken wikilinks, orphans, oversized pages, duplicate slugs.
2. Summarize the findings for the user, worst-first (anti-drift issues matter
   most — they're how the memory rots).
3. If `$ARGUMENTS` asks to fix: address issues with **surgical edits** only —
   add a missing `sources:`, repair a broken `[[link]]`, split an oversized
   page into atomic ones, correct frontmatter. Re-read the raw source when a
   claim's truth is in question. Never mass-rewrite.
4. Re-run `python3 core/mem.py index && python3 core/mem.py lint` and confirm a
   clean report.
