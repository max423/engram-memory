# Lint Policy

## Purpose

Linting keeps the KB coherent, navigable, source-backed, and useful over time.

Lint is not only Markdown formatting. It includes structural, semantic, provenance, freshness, and safety checks.

Agents may run lint when:

- the user explicitly asks;
- a large ingestion has just happened;
- many new notes were created;
- a note appears duplicated, stale, orphaned, or unsupported;
- before a major synthesis, proposal, study plan, or deliverable.

## Lint modes

Use three levels.

### Light lint

Use after normal ingestion or small edits.

Checks:

- broken Markdown links;
- missing index updates;
- processed `sources/` files without Obsidian-visible incoming links, or referenced only from `log.md`, YAML raw paths, or inline code spans;
- missing YAML frontmatter in structured notes;
- missing `type`;
- missing `status`;
- naming convention violations;
- obvious duplicate files.

### Standard lint

Use periodically or after substantial ingestion.

Checks:

- all light lint checks;
- orphan notes;
- orphan sources;
- dead links;
- shallow notes;
- duplicate or near-duplicate notes;
- missing backlinks;
- missing source references;
- missing source-to-derived-note provenance links;
- stale `draft` or `tentative` notes;
- open loops that should be linked from entity/project briefs;
- decisions hidden inside meeting notes but missing decision records;
- reusable concepts trapped inside local project notes;
- missing bridge concepts between source-backed cross-domain topics.

### Deep lint

Use monthly, before major deliverables, or when the KB feels inconsistent.

Checks:

- all standard lint checks;
- contradictions between notes;
- obsolete claims;
- conflicting decisions;
- duplicated concepts across domains;
- global wiki pages containing context-specific sensitive information;
- notes that incorrectly depend on another domain namespace without authorization;
- missing concepts that deserve canonical wiki pages;
- excessive compression or summaries that lost important nuance;
- notes that should be split, merged, archived, or promoted.

## Frontmatter exemptions

The frontmatter checks (missing frontmatter / `type` / `status`) apply to structured content notes only. The following files are exempt:

- `index.md` files (navigational catalogs);
- `AGENTS.md` files (operational instructions);
- root `README.md`, root `index.md`, `log.md`;
- everything under `_schema/` (policies and templates);
- raw files under `sources/` (immutable source material may lack frontmatter).

Structured notes under `wiki/`, `areas/`, and `session-notes/` are still expected to carry `type` and `status`.

## Agent permissions

Agents may automatically:

- create lint reports;
- update indexes;
- fix broken links when the target is unambiguous;
- add missing backlinks;
- add missing source provenance links when the source-to-derived-note relationship is unambiguous;
- add missing frontmatter fields when values are obvious;
- mark lint findings as `proposed`;
- create merge proposals;
- create archive proposals;
- create wiki extraction proposals;
- create or update sanitized global wiki notes for source-backed reusable concepts;
- create source-backed backlinks.

Agents must ask before:

- deleting files;
- merging notes;
- archiving notes;
- marking notes as `superseded`;
- rewriting substantive content;
- moving non-sanitized sensitive content into global `wiki/`;
- changing `_schema/`;
- changing root `AGENTS.md`;
- committing to git.

## Context isolation

When linting one domain namespace, do not inspect other domain namespaces unless explicitly requested.

Allowed default context:

- root `AGENTS.md`;
- `_schema/`;
- `_global/`;
- target namespace;
- global sanitized `wiki/`.

## Finding severity

### `critical`

Must be reviewed soon.

Examples:

- sensitive data leaked into global `wiki/`;
- unsupported claim presented as fact in a structured note;
- raw source modified or overwritten;
- cross-namespace contamination of sensitive material;
- broken decision chain;
- contradictory active decisions;
- a recently processed source exists only in `sources/` with no derived note, index entry, or documented deferred status.

### `major`

Should be fixed.

Examples:

- important orphan note;
- processed source missing backlinks from derived notes or indexes;
- missing source for important claim;
- stale `project-brief` or `entity-brief`;
- duplicate concept pages;
- dead link in important index;
- meeting decision not reflected in a decision record or project brief.

### `minor`

Can be fixed opportunistically.

Examples:

- naming convention drift;
- shallow note;
- missing backlink;
- old `draft` note;
- inconsistent heading style;
- Markdown formatting issue.

## Finding format

Lint reports must use this structure:

```markdown
## Finding ID

- severity:
- type:
- status: proposed
- files:
- evidence:
- why it matters:
- proposed fix:
- requires user approval: yes/no
```

## Report location

Save lint reports under:

```
session-notes/lint/
```

Use filename:

```
YYYY-MM-DD_lint-report.md
```

## Required lint categories

A complete standard/deep lint report should include these sections:

1. Scope
2. Commands/tools used
3. Structural issues
4. Link issues
5. Orphan notes
6. Orphan sources
7. Duplicate or overlapping notes
8. Unsupported claims
9. Contradictions
10. Stale or obsolete notes
11. Missing concepts
12. Context leaks
13. Suggested automatic fixes
14. Fixes requiring approval
15. Next recommended lint date

## Source orphan rules

A processed source is not properly linked if it is:

- unreferenced outside `sources/`;
- referenced only from `log.md`;
- referenced only as a raw YAML path;
- referenced only inside inline code spans;
- listed in an ingestion report but missing from the nearest namespace index;
- used to create or update a note, but absent from that note's YAML `sources:` fields or source section;
- missing at least one Obsidian-visible incoming link.

Source orphan findings are usually `major`. Use `critical` when the source was just ingested and no derived note, index entry, or deferred status exists.

Safe automatic fixes:

- add a missing source link to a clearly derived note;
- add a missing raw source entry to the nearest namespace index;
- add a backlink between a derived note and the related project/entity index.

Fixes requiring approval:

- moving source files;
- merging duplicate sources;
- deleting stale sources;
- moving sensitive derived material into or out of global `wiki/`.

## Deterministic checks

Prefer deterministic tools for mechanical checks when available.

```bash
find . -name '*.md' -not -path './.git/*'
grep -R "\[\[" . --include='*.md'
grep -R "TODO\|TBD\|Unverified:\|tentative" . --include='*.md'
```

## Fix policy

For each finding, classify the fix as:

- `auto-fix`: safe additive/mechanical fix;
- `proposal`: needs user approval;
- `manual-review`: human judgment required.

| Issue | Fix class |
| --- | --- |
| Missing backlink | auto-fix |
| Broken link with obvious target | auto-fix |
| Missing index entry | auto-fix |
| Sanitized reusable concept missing from `wiki/` | auto-fix |
| Duplicate notes | proposal |
| Contradiction between active decisions | manual-review |
| Sensitive info in global wiki | manual-review |
| Stale project brief | proposal |
| Unsupported claim | proposal |

## Completion report

At the end of linting, report:

- scope;
- lint mode;
- files inspected;
- commands run;
- number of findings by severity;
- auto-fixes applied;
- proposals created;
- items requiring approval.
