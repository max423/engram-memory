# Citation and Provenance Policy

## Principle

No important factual claim should be detached from its source.

No processed source should be detached from the notes it supports.

## Acceptable sources

- raw files in `sources/`;
- meeting transcripts;
- user-provided facts;
- terminal output;
- logs;
- project files;
- official documentation;
- papers;
- benchmark reports;
- code comments only when verified against code behavior.

## Claim language

Use explicit source language:

- "According to..."
- "The transcript states..."
- "The terminal output shows..."
- "The current project file defines..."
- "Assumption:"
- "Hypothesis:"
- "Unverified:"

## Frontmatter source fields

Use one or more:

```yaml
sources:
  - path: sources/...
    kind: transcript | pdf | terminal-log | user-input | code | docs | web | paper
    note: short explanation
```

## Unverified claims

If a claim lacks source support, mark it:

```yaml
confidence: low
status: tentative
```

and write `Unverified:` in the body.

## Source-to-note links

When a note is generated from, summarized from, corrected by, or materially updated because of a source, the note must link back to the source.

For graph visibility, the backlink must include an Obsidian-visible link: `[[sources/.../file]]` or a normal Markdown link. A raw path in YAML or an inline code span is provenance metadata, not a graph edge.

Preferred formats:

- YAML `sources:` entries for structured notes;
- `source:` / `source_transcript:` / `source_summary:` only when there is a single obvious source;
- a `## Fonti` or `## Sources` section with graph-visible links when body links are clearer than frontmatter.

For each processed file under `sources/`, at least one non-raw note or local index should reference it with a graph-visible link.

If a source supports multiple derived notes, link it from each note that directly relies on it.

## Wiki provenance

Global `wiki/` pages must be reusable and sanitized. Context-specific evidence should normally be linked through local area notes or sanitized extraction proposals, not copied into global wiki pages.

New prose content under `wiki/` should be written in the prose language defined in `_global/working-principles.md`.
