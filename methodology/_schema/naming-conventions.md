# Naming Conventions

## Files

Use lowercase kebab-case.

Good:

```
project-brief.md
2026-05-07_kickoff-call.md
entity-brief.md
debug-network-issue.md
```

Avoid:

```
My Notes.md
final FINAL 2.md
Project Alpha Notes.md
```

## Dates

Use ISO dates:

```
YYYY-MM-DD
```

For chronological files:

```
2026-05-07_kickoff-call.md
```

## Slugs

Use stable slugs for domains, entities, and projects:

```
domain-name
entity-name
project-name
```

Do not rename slugs casually. Renaming breaks links.

## Frontmatter IDs

Use readable IDs:

```yaml
id: meeting-entity-project-2026-05-07-kickoff
id: decision-project-alpha-architecture-001
id: concept-distributed-systems
id: session-2026-05-07-domain-short-title
```

## Domain slugs

Use short, stable, lowercase kebab-case slugs for domain names:

```
work
study
personal
research
dev
health
```

See `areas/_domains.md` for registered domains.
