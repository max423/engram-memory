# Ingest Policy

## Purpose

Ingest means transforming raw material from `inbox/` into durable KB content.

The user is not required to pre-create folders, domain namespaces, entity namespaces, indexes, or briefs.

The agent must infer the appropriate structure from:

- the user's short description;
- file names;
- file contents;
- existing KB conventions;
- `areas/_domains.md` (active domains and their descriptions).

## Default user interaction

The user may provide a short description such as:

```text
The files in inbox/project-x are notes and transcripts from a recent client project.
Proceed with ingestion.
```

The agent must autonomously:

1. Inspect the inbox batch.
2. Read `areas/_domains.md` and infer the target domain.
3. If no domain fits, propose a new one (see `_schema/domain-policy.md`).
4. Search for existing related content in the KB.
5. Create missing additive structure.
6. Preserve raw sources under `sources/`; remove from `inbox/` only files that were successfully processed and copied.
7. Create structured notes under `areas/`.
8. Create or update entity briefs, meetings, open loops, decisions, and indexes.
9. Update sanitized global `wiki/` notes and backlinks for source-backed concepts useful beyond the current namespace.
10. Update `log.md`.
11. Report what changed.

Ask follow-up questions only if ambiguity blocks safe ingestion.

## Domain inference

Before routing material:

1. Read `areas/_domains.md`.
2. Match content signals (file type, topic, user description) against existing domain descriptions and examples.
3. If a clear match exists: route to that domain.
4. If ambiguous: propose the best match, mark as `tentative`, and ask the user.
5. If no domain fits: propose a new domain slug and ask the user to confirm.

See `_schema/domain-policy.md` for the full domain lifecycle.

## Namespace inference

After determining the domain, infer the sub-namespace from the content:

```
sources/<domain-slug>/<entity-or-topic-slug>/
areas/<domain-slug>/<entity-or-topic-slug>/
```

Create sub-namespaces when material belongs to a distinct entity (client, project, course, person) with enough content to warrant its own folder. Flat placement under the domain root is fine for small or one-off material.

## Slug rules

Use lowercase kebab-case.

Examples:

```
Nuova Azienda        → nuova-azienda
Project Alpha        → project-alpha
Robust Control       → robust-control
```

Do not rename existing slugs unless explicitly asked.

## Source preservation

Raw source content is immutable.

The agent may copy files from `inbox/` to `sources/`, but must not rewrite raw source content.

After a file is successfully processed and preserved under `sources/`, remove it from `inbox/`. Any file that was not processed must remain in `inbox/` for a later ingestion pass.

If cleanup is useful, create a derived cleaned note outside `sources/`.

## Provenance and linking invariants

Every successfully processed source must be reachable from the KB.

During ingestion, for each source copied or reused under `sources/`:

- Add it to the nearest area/entity/project index with an Obsidian-visible link, unless a more specific source index exists.
- Link every directly derived note back to the raw source in YAML `sources:` and with an Obsidian-visible `[[sources/...]]` or Markdown link in an explicit `## Fonti` / `## Sources` section.
- Link related derived notes to each other when they describe the same event, decision, project, person, or reusable concept.
- Update the nearest index so the derived note is reachable from the namespace entry point.
- Update relevant global wiki notes and backlinks when the source supports a sanitized general concept.
- Do not count `log.md`, YAML raw paths, or inline code spans as the only backlink for a processed source.

If a source was preserved but no derived note was created, record why in the nearest index or ingestion report and mark the source as `unprocessed`, `deferred`, or `tentative`.

## Session note routing during ingestion

When an ingestion session produces a session note:

- Material belonging to one domain → `areas/<domain-slug>/session-notes/`
- Material spanning two or more unrelated domains → `session-notes/`

After creating the note, update `areas/<domain-slug>/session-notes/index.md`.

## Derived note rules

Create structured derived notes when useful.

| Raw material | Derived note |
| --- | --- |
| Transcript | Meeting note |
| Verbale / minutes | Meeting note |
| Raw personal notes | Source summary or project note |
| Online research | Research summary |
| Pricing / time notes | Pricing note |
| Slides / lecture material | Material analysis |
| Terminal output / logs | Troubleshooting note |
| Decision-heavy text | Draft decision record |

Use templates from `_schema/templates/` when applicable, but do not force templates when a simpler note is better.

## Autonomous actions allowed

The agent may automatically:

- create folders;
- create local `AGENTS.md` when local rules are needed;
- create `index.md`;
- copy raw files from `inbox/` to `sources/`;
- remove successfully processed files from `inbox/` after copying to `sources/` and creating derived notes;
- leave unprocessed files in `inbox/` for a later ingestion pass;
- create source summaries, meeting notes, entity/project briefs, open-loop lists, draft decision records, session/ingestion reports;
- update backlinks;
- update sanitized global `wiki/` notes for source-backed reusable concepts;
- update cross-domain backlinks when the content is generalizable and non-sensitive;
- update root `index.md`;
- update root `log.md`;
- update `areas/_domains.md` when a new domain is created.

These actions must be additive and auditable.

## Requires user approval

The agent must ask before:

- deleting files, except successfully processed files removed from `inbox/` after raw preservation;
- overwriting raw sources;
- moving or publishing non-sanitized, context-specific content into global `wiki/`;
- using another entity or domain namespace as context without permission;
- merging notes;
- marking notes as `superseded`;
- archiving notes;
- changing `_schema/`;
- changing root `AGENTS.md`;
- committing to git;
- generating final external deliverables.

## Context isolation

Default allowed context:

- root `AGENTS.md`;
- `_schema/`;
- `_global/`;
- target `inbox/` batch;
- inferred target domain namespace;
- global sanitized `wiki/`.

Forbidden by default:

- other entity or domain namespaces containing sensitive material;
- private unrelated project or personal material;
- confidential source material from unrelated contexts.

Use other namespaces only if the user explicitly asks.

Exception: agents may update sanitized global `wiki/` notes, indexes, and backlinks across domains when a source-backed concept is genuinely generalizable. Do not copy sensitive details from one namespace into another.

## Global wiki extraction

The agent should automatically create or update reusable global notes when an ingested source contains a source-backed concept that is useful beyond the current namespace.

The global note must be sanitized: it may generalize the concept, pattern, tool, procedure, or decision logic, but must not expose context-specific or private details unnecessarily.

Allowed extraction examples:

- generic procedures and workflows;
- generic concepts, methods, or tools;
- generic pricing-estimation methods;
- generic meeting-intake checklists.

Forbidden extraction examples:

- entity names where not needed for the generic concept;
- private quotes or confidential requirements;
- commercial strategy tied to one client;
- pricing tied to one engagement;
- sensitive personal information.

## Claim and provenance policy

Important claims must be source-backed.

Valid sources include:

- raw source files;
- meeting transcripts;
- user-provided descriptions;
- terminal output;
- logs;
- project files;
- official documentation;
- papers;
- web research with URLs and dates.

Use `tentative` for uncertain claims.

## Completion report

At the end of ingestion, report:

- inferred domain;
- inferred entity/project/topic;
- created paths;
- raw files copied;
- derived notes created;
- existing notes updated;
- decisions drafted;
- open loops added;
- proposed wiki extractions;
- global wiki notes updated;
- unresolved ambiguities;
- actions requiring approval.
