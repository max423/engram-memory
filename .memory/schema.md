# schema.md — node and relation types for this project's memory

> Domain config for a **software project**. The core reads only frontmatter;
> this file tells the LLM (and you) what shape a page should take. Co-evolve it
> by hand — the tooling never auto-overwrites it.

## Node types (`type:`)

| type        | what it is                                            | folder              |
|-------------|-------------------------------------------------------|---------------------|
| `decision`  | a choice that was made, with rationale + consequences | `wiki/decisions/`   |
| `concept`   | a recurring idea/pattern referenced by decisions      | `wiki/concepts/`    |
| `entity`    | a system, service, library, person, external thing    | `wiki/entities/`    |
| `synthesis` | an answer/overview stitched from several pages        | `wiki/synthesis/`   |

`decision` is the backbone of a project memory: most pages are decisions; the
other types exist to be linked *from* decisions.

## Frontmatter (required on every page)

```yaml
id: kebab-slug            # stable identity, == filename stem
type: decision            # decision | concept | entity | synthesis
status: active            # draft | active | stale | contradicted | archived
title: Human-readable title
tags: [storage, git]      # inline list
sources:                  # REQUIRED — anti-drift anchor; >= 1 file under raw/
  - raw/2026-01-15-storage-in-git.md
created: 2026-01-15
updated: 2026-01-15
```

`sources:` is non-negotiable: `mem lint` fails any page that has no source or
whose source file is missing. It is what lets reconcile re-read the *truth*
instead of trusting the previous page.

## Status machine

```
draft --(lint clean)--> active --(source SHA changed)--> stale
                           |                                |
                           +--(conflicting source ingested)--> contradicted
                                                                |
                                   (reconciled / superseded)--> archived
```

Transitions are append-logged in `log.md`. Reconcile actions drive them:
`update` keeps `active`, `contradiction` → `contradicted`, `deprecate` →
`archived`. Manual overrides (`activate`, `archive`, `restore`) exist for when
automation isn't enough.

## Relations (wikilinks)

A plain `[[slug]]` in the body is an edge in the graph. Conventions:

- a `decision` links the `concept`s it relies on and the `entity`s it touches;
- a `synthesis` links every page it draws from;
- every page should have at least one inbound link (no orphans).
