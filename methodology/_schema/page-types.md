# Page Types

## Core types

Use these values in YAML frontmatter under `type`.

| Type | Purpose | Typical location |
| --- | --- | --- |
| `source` | Raw or near-raw source description | `sources/` |
| `source-summary` | Structured summary of a raw source | near source or `areas/.../` |
| `concept` | Reusable conceptual knowledge | `wiki/concepts/` |
| `comparison` | Reusable side-by-side comparison of approaches/tools | `wiki/comparisons/` |
| `method` | Reusable method or technique | `wiki/methods/` |
| `procedure` | Repeatable operational workflow | `wiki/procedures/` or area-local `procedures/` |
| `decision` | Decision record with rationale | `areas/.../decisions/` or `wiki/decisions/` |
| `meeting` | Structured meeting or call note | `areas/<domain>/<entity>/meetings/` |
| `session-note` | Operational memory after a work session | `areas/<domain>/session-notes/` (domain) or `session-notes/` (cross-domain) |
| `project-brief` | Current compact state of a project | `areas/.../project-brief.md` |
| `entity-brief` | Current compact state of an entity (client, org, course, person) | `areas/<domain>/<entity>/entity-brief.md` |
| `claim` | Atomic factual claim with provenance | `wiki/claims/` or embedded in notes |
| `open-loop` | Pending question, action, or uncertainty | area-local or `_global/open-loops.md` |
| `person` | Canonical person entity | `wiki/people/` |
| `global-context` | Stable personal principles, tools, patterns, preferences | `_global/` |
| `lint-report` | KB lint/consistency report | `session-notes/lint/` |
| `project-note` | Project note (not a `project-brief`) | `areas/.../` |
| `planning-note` | Planning note for a project or study period | `areas/.../` |
| `topic-note` | Canonical note for a recurring topic within a domain | `areas/<domain>/` |

Additional descriptive types may appear when justified, but prefer the values above when applicable.

`index.md` files and operational files (`AGENTS.md`, `log.md`, `README.md`) are exempt from the `type` requirement. See the exempt-files list in `_schema/lint-policy.md`.

## Rule of thumb

- If it is original evidence, it is a `source`.
- If it is reusable knowledge, it is a `concept`, `comparison`, `method`, or `procedure`.
- If it records why a choice was made, it is a `decision`.
- If it records what happened in a call or meeting, it is a `meeting`.
- If it records where a work session ended, it is a `session-note`.
- If it is a canonical entity (person, topic), use `person` or `topic-note`.

## Status lifecycle

| Status | Meaning | Typical transition |
| --- | --- | --- |
| `draft` | Just created; not yet reviewed | Default on creation |
| `active` | Reviewed and in use; accepted version | `draft` → `active` once stable |
| `complete` | Finished point-in-time record; no further work expected | `draft` → `complete` for session notes and reports |
| `superseded` | Replaced by a newer note; kept for history | set via `superseded_by:` (requires user approval) |

Rules:

- Notes should not stay `draft` indefinitely: promote stable records to `active` and finished session notes/reports to `complete`.
- Templates under `_schema/templates/` legitimately keep `status: draft` as the placeholder default.
