# Domain Policy

## What is a domain?

A domain is a named context that organizes material under `areas/`.

Domains are **not predefined**. They are created when the user or the agent identifies a distinct area of work, study, or life that benefits from its own namespace.

Common examples (not a fixed list):

| Slug | What it might cover |
| --- | --- |
| `work` | Professional work, clients, deliverables |
| `study` | Courses, exams, learning material |
| `personal` | Personal systems, habits, private admin |
| `research` | Research topics, papers, experiments |
| `dev` | Software projects, code, infrastructure |
| `health` | Health tracking, medical notes |
| `finance` | Budgets, financial planning |

## Domain registry

Active domains are listed in `areas/_domains.md`.

**The agent must read `areas/_domains.md` before routing any material.**

## Creating a new domain

When material does not fit any existing domain:

1. Propose a domain slug (lowercase kebab-case) and display name.
2. Ask the user to confirm or rename — unless the domain is unambiguous from clear user intent.
3. Once confirmed:
   - Create `areas/<domain-slug>/index.md`.
   - Create `areas/<domain-slug>/session-notes/index.md`.
   - Register the domain in `areas/_domains.md`.
   - Update root `index.md`.
4. Optionally create `areas/<domain-slug>/AGENTS.md` when domain-specific ingestion or confidentiality rules are needed.

## Domain inference

When new material arrives (inbox ingestion, user description, discovered content):

1. Read `areas/_domains.md`.
2. Match content signals against the description and examples of each registered domain.
3. If a match is clear: route to that domain.
4. If ambiguous: propose the best match, mark routing as `tentative`, and ask the user.
5. If no existing domain fits: propose a new domain.

When the user describes material, weight their explicit labels (e.g. "for work", "my thesis", "a personal project") over inferred signals.

## Namespace structure

Suggested structure inside each domain:

```
areas/<domain-slug>/                      # domain root
areas/<domain-slug>/index.md              # domain index (required)
areas/<domain-slug>/session-notes/        # domain session notes (required)
areas/<domain-slug>/session-notes/index.md
areas/<domain-slug>/<entity-slug>/        # optional: entity or project namespace
areas/<domain-slug>/<entity-slug>/index.md
```

Sources mirror the domain structure:

```
sources/<domain-slug>/
sources/<domain-slug>/<entity-slug>/
```

Adapt the namespace as needed for the domain's content. Not every domain needs entities.

## Local AGENTS.md

Create `areas/<domain-slug>/AGENTS.md` when the domain has specific rules such as:

- confidentiality constraints (e.g. client data);
- domain-specific required frontmatter fields;
- domain-specific ingestion patterns;
- additional authorized tools or context.

## Renaming a domain

Renaming a slug is destructive: it breaks all existing links. Always ask the user before renaming. After approval, update all affected links and update `areas/_domains.md`.

## Archiving a domain

To archive an inactive domain:

1. Mark it as `archived` in `areas/_domains.md`.
2. Ask the user before moving files to `archive/<domain-slug>/`.

## Cross-domain content

Content that genuinely spans multiple domains with no clear dominant one goes in `session-notes/` (for session notes) or `wiki/` (for reusable knowledge). Do not duplicate content into multiple domain namespaces.
