#!/usr/bin/env python3
"""
mem — deterministic core CLI for the curated project memory (zero LLM tokens).

    mem init   [root]            bootstrap a .memory/ layout (idempotent)
    mem index  [--memory DIR]    (re)build index/ artifacts from wiki/
    mem search QUERY [...]        BM25 search + backlinks/hubs over the wiki
    mem lint   [--memory DIR]     structural + anti-drift health check
    mem graph  [--memory DIR]     wikilink graph summary

Every subcommand here is deterministic: it never calls a model. The LLM only
ever runs in `ingest` (compile) and `reconcile`, which live in their own
modules and receive the minimal context this core selects for them.

Python 3.10+ by design (stdlib only); runs on 3.9 too via __future__ imports.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memlib import frontmatter  # noqa: E402
from memlib.bm25 import BM25  # noqa: E402
from memlib.graph import build_graph  # noqa: E402
from memlib.pages import VALID_STATUS, VALID_TYPES, collect_pages  # noqa: E402
from memlib.store import MemoryPaths, WIKI_SUBDIRS, resolve  # noqa: E402

REQUIRED_FM = ["id", "type", "status", "title", "tags", "sources", "created", "updated"]


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
SCHEMA_TEMPLATE = """\
# schema.md — node and relation types for this project's memory

> Domain config. The core reads only frontmatter; this file tells the LLM
> (and you) what shape a page should take. Co-evolve it — never auto-overwrite.

## Node types (`type:`)

- **decision** — a choice that was made, with rationale and consequences. The
  backbone of the memory. Lives in `wiki/decisions/`.
- **concept** — a recurring idea/pattern referenced by decisions. `wiki/concepts/`.
- **entity** — a system, service, library, person, or external thing. `wiki/entities/`.
- **synthesis** — an answer/overview stitched from several pages. `wiki/synthesis/`.

## Frontmatter (every page)

```yaml
id: kebab-slug            # stable, == filename stem
type: decision            # one of: decision | concept | entity | synthesis
status: active            # draft | active | stale | contradicted | archived
title: Human title
tags: [storage, git]
sources:                  # REQUIRED — anti-drift anchor; >=1 raw/ file
  - raw/2026-01-15-storage.md
created: 2026-01-15
updated: 2026-01-15
links: [other-slug]       # optional; wikilinks in the body are authoritative
```

## Status machine

    draft --(lint clean)--> active --(source SHA changed)--> stale
                               |                                |
                               +--(conflicting source)--> contradicted
                                                                |
                                       (reconciled / superseded)--> archived

Transitions are logged in `log.md`. The reconcile actions
(no-op/update/add/contradiction/deprecate) drive them.

## Relations (wikilinks `[[slug]]`)

Plain `[[slug]]` in the body is the edge. Keep links meaningful: a decision
should link the concepts it relies on and the entities it touches.
"""

INDEX_MD_TEMPLATE = """\
# index.md — content catalogue (read this FIRST)

> One line per page: slug + summary. Index-first navigation: the query path
> reads this before opening any page, so it spends tokens only on what matters.
> Maintained on every ingest.

## decisions

## concepts

## entities

## synthesis
"""

LOG_MD_TEMPLATE = """\
# log.md — append-only memory log

> Grep-able timeline. Every entry: `## [YYYY-MM-DD] <op> | <title>`.
> Query it with unix: `grep '^## \\[' log.md | tail -10`.
"""


SCHEMA_RESEARCH = """\
# schema.md — node and relation types (research / literature memory)

> The 4 node types are fixed (the lint enforces them); only their meaning is
> tuned for research. Co-evolve this file by hand.

## Node types (`type:`)

| type        | research meaning                                   | folder            |
|-------------|----------------------------------------------------|-------------------|
| `decision`  | a **finding/claim** you accept as true (with why)  | `wiki/decisions/` |
| `concept`   | a theory, method, or recurring idea                | `wiki/concepts/`  |
| `entity`    | a paper, author, dataset, or tool                  | `wiki/entities/`  |
| `synthesis` | a literature review / cross-paper comparison       | `wiki/synthesis/` |

## Frontmatter (required): id · type · status · title · tags · sources · created · updated

`sources:` must point at the raw paper/note in `raw/` — anti-drift: a finding is
only as good as the source it cites. Status machine + reconcile actions
(no-op/update/add/contradiction/deprecate) work as in the default schema; a new
paper that conflicts with a finding moves it to `contradicted`.

## Relations (`[[slug]]`)

A finding links the concepts/methods it relies on and the papers it draws from.
A synthesis links every paper and finding it compares.
"""

SCHEMA_PRODUCT = """\
# schema.md — node and relation types (product memory)

> The 4 node types are fixed (the lint enforces them); only their meaning is
> tuned for product work. Co-evolve this file by hand.

## Node types (`type:`)

| type        | product meaning                                     | folder            |
|-------------|-----------------------------------------------------|-------------------|
| `decision`  | a **product/roadmap decision** (with rationale)     | `wiki/decisions/` |
| `concept`   | a user need, principle, or guideline                | `wiki/concepts/`  |
| `entity`    | a feature, competitor, segment, or metric           | `wiki/entities/`  |
| `synthesis` | a PRD, strategy doc, or release overview            | `wiki/synthesis/` |

## Frontmatter (required): id · type · status · title · tags · sources · created · updated

`sources:` must point at the raw input in `raw/` (user interview, ticket, memo).
Status machine + reconcile actions work as in the default schema; a decision the
team reverses moves to `contradicted` or `archived`.

## Relations (`[[slug]]`)

A decision links the user needs it serves and the features/segments it touches.
A synthesis links every decision and entity it rolls up.
"""

SCHEMA_TEMPLATES = {
    "software": SCHEMA_TEMPLATE,
    "research": SCHEMA_RESEARCH,
    "product": SCHEMA_PRODUCT,
}


def cmd_init(args) -> int:
    root = Path(args.root).resolve()
    mem = MemoryPaths(root / ".memory" if root.name != ".memory" else root)
    created, skipped = [], []

    def ensure_dir(p: Path):
        if p.exists():
            skipped.append(str(p.relative_to(root.parent)) + "/")
        else:
            p.mkdir(parents=True)
            created.append(str(p.relative_to(root.parent)) + "/")

    ensure_dir(mem.raw)
    for sub in WIKI_SUBDIRS:
        ensure_dir(mem.wiki / sub)
    ensure_dir(mem.index_dir)

    def ensure_file(p: Path, content: str):
        if p.exists():
            skipped.append(str(p.relative_to(root.parent)))
        else:
            p.write_text(content, encoding="utf-8")
            created.append(str(p.relative_to(root.parent)))

    ensure_file(mem.schema, SCHEMA_TEMPLATES.get(getattr(args, "template", "software"),
                                                 SCHEMA_TEMPLATE))
    ensure_file(mem.index_md, INDEX_MD_TEMPLATE)
    ensure_file(mem.log, LOG_MD_TEMPLATE)
    ensure_file(mem.index_dir / ".gitignore", "# generated, regenerable by `mem index`\n*.json\n*.idx\nsources.sha256\n")

    print("Initializing project memory in: %s" % mem.root)
    if created:
        print("Created:")
        for p in created:
            print("  + %s" % p)
    if skipped:
        print("Already existed:")
        for p in skipped:
            print("  = %s" % p)
    print("\nNext: drop a source into %s/, then `mem index` and ingest it." % mem.raw.name)
    return 0


# --------------------------------------------------------------------------- #
# index
# --------------------------------------------------------------------------- #
def build_index_record(p: dict) -> dict:
    """The token-zero view of a page: frontmatter only, never the body."""
    return {
        "id": p.get("meta", {}).get("id", p["slug"]),
        "slug": p["slug"],
        "type": p.get("type", ""),
        "status": p.get("status", ""),
        "title": p.get("title", p["slug"]),
        "tags": p.get("tags", []),
        "sources": p.get("sources", []),
        "updated": p.get("meta", {}).get("updated", ""),
        "rel_path": p["rel_path"],
        "links": p.get("links", []),
    }


def cmd_index(args) -> int:
    mem = resolve(args.memory)
    if not mem.exists():
        print("No wiki found at %s. Run `mem init` first." % mem.wiki, file=sys.stderr)
        return 1
    pages = collect_pages(mem.wiki)
    real = [p for p in pages if "read_error" not in p]

    mem.index_dir.mkdir(parents=True, exist_ok=True)
    records = [build_index_record(p) for p in real]
    mem.index_json.write_text(json.dumps(records, indent=2), encoding="utf-8")

    BM25.build(real).save(mem.bm25_idx)

    graph = build_graph(pages)
    mem.graph_json.write_text(json.dumps(graph, indent=2), encoding="utf-8")

    from memlib import index_store
    index_store.save_manifest(mem)

    print("Indexed %d pages -> %s" % (len(real), mem.index_dir))
    print("  index.json  (%d records)" % len(records))
    print("  bm25.idx    (%d terms)" % len(BM25.build(real).df))
    print("  graph.json  (%d edges, %d orphans, %d broken links)"
          % (len(graph["edges"]), len(graph["orphans"]), len(graph["broken_links"])))
    return 0


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def _passes_filters(p: dict, args) -> bool:
    if args.type and p.get("type") != args.type:
        return False
    if args.status and p.get("status") != args.status:
        return False
    if args.tag:
        page_tags = set(p.get("tags", []))
        if not all(t in page_tags for t in args.tag):
            return False
    if args.since:
        updated = p.get("meta", {}).get("updated", "")
        if not updated or updated[:10] < args.since:
            return False
    return True


def _emit_hits(query, hits, by_slug) -> None:
    print("Top %d results for: %r\n" % (len(hits), query))
    for slug, score in hits:
        p = by_slug.get(slug)
        if not p:
            continue
        print("  [%6.2f] [%-9s] %s" % (score, p.get("type", "?"), p.get("title", slug)))
        print("           %s" % p.get("rel_path", ""))


def _emit_backlinks(target, items) -> None:
    print("Pages linking to [[%s]] (%d):" % (target, len(items)))
    for p in items:
        print("  - %s  (%s)" % (p.get("title", p["slug"]), p.get("rel_path", "")))


def _emit_hubs(hubs) -> None:
    print("Top %d most-linked-to pages (hubs):" % len(hubs))
    for slug, srcs in hubs:
        print("  %4d  %s" % (len(srcs), slug))


def cmd_search(args) -> int:
    mem = resolve(args.memory)
    has_filters = bool(args.type or args.status or args.tag or args.since)

    # Fast path: validated persisted index, when no filters are in play.
    if not getattr(args, "no_cache", False) and not has_filters:
        from memlib import index_store
        cache = index_store.load_valid(mem)
        if cache is not None:
            records = cache["records"]
            by_slug = {r["slug"]: r for r in records}
            if args.backlinks:
                inbound = [r for r in records if args.backlinks in r.get("links", [])]
                (_emit_backlinks(args.backlinks, inbound) if inbound
                 else print("No pages link to [[%s]]." % args.backlinks))
                return 0
            if args.top_linked:
                hubs = sorted(cache["graph"]["backlinks"].items(),
                              key=lambda kv: -len(kv[1]))[:args.top_linked]
                _emit_hubs(hubs) if hubs else print("No links found in the wiki.")
                return 0
            if not args.query:
                print("Empty query. Provide terms, or --backlinks / --top-linked.",
                      file=sys.stderr)
                return 1
            hits = cache["bm25"].search(args.query, top=args.top)
            _emit_hits(args.query, hits, by_slug) if hits \
                else print("No matches for %r." % args.query)
            return 0

    # Live path: filters present, or no valid cache.
    pages = collect_pages(mem.wiki)
    real = [p for p in pages if "read_error" not in p]
    if not real:
        print("No wiki pages found under %s" % mem.wiki, file=sys.stderr)
        return 0

    if args.backlinks:
        inbound = [p for p in real if args.backlinks in p["links"]]
        (_emit_backlinks(args.backlinks, inbound) if inbound
         else print("No pages link to [[%s]]." % args.backlinks))
        return 0

    if args.top_linked:
        graph = build_graph(pages)
        hubs = sorted(graph["backlinks"].items(), key=lambda kv: -len(kv[1]))[:args.top_linked]
        _emit_hubs(hubs) if hubs else print("No links found in the wiki.")
        return 0

    filtered = [p for p in real if _passes_filters(p, args)]
    if not filtered:
        print("No pages matched the filters.", file=sys.stderr)
        return 0
    if not args.query:
        print("Empty query. Provide terms, or use --backlinks / --top-linked.", file=sys.stderr)
        return 1

    idx = BM25.build(filtered)
    hits = idx.search(args.query, top=args.top)
    if not hits:
        print("No matches for %r." % args.query)
        return 0
    _emit_hits(args.query, hits, {p["slug"]: p for p in filtered})
    return 0


# --------------------------------------------------------------------------- #
# lint
# --------------------------------------------------------------------------- #
def run_lint(mem: MemoryPaths, soft_cap: int, hard_cap: int) -> dict:
    pages = collect_pages(mem.wiki)
    findings = {k: [] for k in [
        "orphans", "broken_links", "oversized_hard", "oversized_soft",
        "missing_frontmatter", "malformed_frontmatter", "duplicate_slugs",
        "invalid_type", "invalid_status", "missing_sources", "dangling_sources",
        "read_errors",
    ]}

    for p in pages:
        if "read_error" in p:
            findings["read_errors"].append({"path": p["rel_path"], "error": p["read_error"]})
    real = [p for p in pages if "read_error" not in p]

    slug_paths: dict = {}
    for p in real:
        slug_paths.setdefault(p["slug"], []).append(p["rel_path"])
    for slug, paths in slug_paths.items():
        if len(paths) > 1:
            findings["duplicate_slugs"].append({"slug": slug, "paths": paths})

    graph = build_graph(pages)
    findings["orphans"] = [{"slug": s} for s in graph["orphans"]]
    findings["broken_links"] = graph["broken_links"]

    for p in real:
        if p["line_count"] > hard_cap:
            findings["oversized_hard"].append({"path": p["rel_path"], "lines": p["line_count"]})
        elif p["line_count"] > soft_cap:
            findings["oversized_soft"].append({"path": p["rel_path"], "lines": p["line_count"]})

        if p["malformed_fm"]:
            findings["malformed_frontmatter"].append({"path": p["rel_path"]})
            continue
        missing = [f for f in REQUIRED_FM
                   if f not in p["meta"] or p["meta"].get(f) in ("", None, [])]
        if missing:
            findings["missing_frontmatter"].append({"path": p["rel_path"], "missing": missing})

        t = p.get("type")
        if t and t not in VALID_TYPES:
            findings["invalid_type"].append({"path": p["rel_path"], "type": t})
        st = p.get("status")
        if st and st not in VALID_STATUS:
            findings["invalid_status"].append({"path": p["rel_path"], "status": st})

        # Anti-drift: every page must cite >=1 raw source, and it must exist.
        if not p.get("sources"):
            findings["missing_sources"].append({"path": p["rel_path"]})
        else:
            for src in p["sources"]:
                src_path = (mem.root / src) if not os.path.isabs(src) else Path(src)
                if not src_path.exists():
                    findings["dangling_sources"].append({"path": p["rel_path"], "source": src})

    findings["summary"] = {k: len(v) for k, v in findings.items() if isinstance(v, list)}
    findings["summary"]["total_pages"] = len(real)
    return findings


def render_lint(f: dict) -> str:
    out = ["=" * 60, "Memory Lint Report", "=" * 60,
           "Total pages scanned: %d" % f["summary"]["total_pages"], ""]
    sections = [
        ("missing_sources", "ANTI-DRIFT: pages with no source (must cite raw/)",
         lambda x: "  - %s" % x["path"]),
        ("dangling_sources", "ANTI-DRIFT: source files that don't exist",
         lambda x: "  - %s -> %s" % (x["path"], x["source"])),
        ("missing_frontmatter", "Missing frontmatter fields",
         lambda x: "  - %s  missing: %s" % (x["path"], ", ".join(x["missing"]))),
        ("malformed_frontmatter", "Malformed frontmatter", lambda x: "  - %s" % x["path"]),
        ("invalid_type", "Invalid type", lambda x: "  - %s  (%s)" % (x["path"], x["type"])),
        ("invalid_status", "Invalid status", lambda x: "  - %s  (%s)" % (x["path"], x["status"])),
        ("broken_links", "Broken wikilinks",
         lambda x: "  - [[%s]] referenced from %s" % (x["to"], x["from"])),
        ("orphans", "Orphan pages (no inbound links)", lambda x: "  - %s" % x["slug"]),
        ("oversized_hard", "OVERSIZE (over hard cap — must split)",
         lambda x: "  - %s  (%d lines)" % (x["path"], x["lines"])),
        ("oversized_soft", "Oversize (over soft cap — consider splitting)",
         lambda x: "  - %s  (%d lines)" % (x["path"], x["lines"])),
        ("duplicate_slugs", "Duplicate slugs",
         lambda x: "  - %s: %s" % (x["slug"], ", ".join(x["paths"]))),
        ("read_errors", "Read errors", lambda x: "  - %s: %s" % (x["path"], x["error"])),
    ]
    issues = 0
    for key, label, fmt in sections:
        items = f[key]
        if not items:
            continue
        issues += len(items)
        out.append("%s (%d):" % (label, len(items)))
        out.extend(fmt(it) for it in items[:50])
        if len(items) > 50:
            out.append("  ... and %d more" % (len(items) - 50))
        out.append("")
    if issues == 0:
        out.append("No issues found. Memory is healthy.")
    return "\n".join(out)


def cmd_lint(args) -> int:
    mem = resolve(args.memory)
    if not mem.exists():
        print("No wiki found at %s." % mem.wiki, file=sys.stderr)
        return 1
    findings = run_lint(mem, args.soft_cap, args.hard_cap)
    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        print(render_lint(findings))
    # Non-zero exit if any anti-drift / structural error (useful in CI / hooks).
    hard = sum(findings["summary"].get(k, 0) for k in
               ("missing_sources", "dangling_sources", "malformed_frontmatter",
                "broken_links", "duplicate_slugs", "oversized_hard",
                "invalid_type", "invalid_status"))
    return 1 if hard else 0


# --------------------------------------------------------------------------- #
# graph
# --------------------------------------------------------------------------- #
def cmd_graph(args) -> int:
    mem = resolve(args.memory)
    pages = collect_pages(mem.wiki)
    graph = build_graph(pages)
    if args.json:
        print(json.dumps(graph, indent=2))
        return 0
    print("Graph: %d nodes, %d edges" % (len(graph["nodes"]), len(graph["edges"])))
    print("Orphans (%d): %s" % (len(graph["orphans"]), ", ".join(graph["orphans"]) or "-"))
    print("Broken links (%d): %s" % (
        len(graph["broken_links"]),
        ", ".join("%s->%s" % (b["from"], b["to"]) for b in graph["broken_links"]) or "-"))
    hubs = sorted(graph["backlinks"].items(), key=lambda kv: -len(kv[1]))[:5]
    if hubs:
        print("Top hubs:")
        for slug, srcs in hubs:
            print("  %4d  %s" % (len(srcs), slug))
    return 0


# --------------------------------------------------------------------------- #
# detect / reconcile (delegate to the Phase 1 / Phase 2 modules)
# --------------------------------------------------------------------------- #
def cmd_detect(args) -> int:
    import change_detect
    mem = resolve(args.memory)
    if args.update_snapshot:
        current = change_detect.current_source_hashes(mem.raw)
        mem.index_dir.mkdir(parents=True, exist_ok=True)
        mem.sources_sha.write_text(json.dumps(current, indent=2), encoding="utf-8")
        print("Snapshot updated: %d sources -> %s" % (len(current), mem.sources_sha))
        return 0
    plan = change_detect.compute_plan(mem, args.since, args.max_candidates,
                                      use_cache=not getattr(args, "no_cache", False))
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        change_detect.print_plan(plan)
    return 0


def cmd_reconcile(args) -> int:
    import reconcile
    mem = resolve(args.memory)
    return reconcile.run_reconcile(mem, args.since, args.max_candidates,
                                   args.show_context, args.apply)


# --------------------------------------------------------------------------- #
# ingest — compile NEW curated sources into draft pages (offline by default)
# --------------------------------------------------------------------------- #
TYPE_DIR = {"decision": "decisions", "concept": "concepts",
            "entity": "entities", "synthesis": "synthesis"}


def _catalogue_insert(mem: MemoryPaths, page_type: str, slug: str, summary: str) -> None:
    """Best-effort: add a one-line entry to index.md under the type's heading."""
    if not mem.index_md.exists():
        return
    heading = "## " + TYPE_DIR.get(page_type, page_type)
    line = "- [[%s]] — %s" % (slug, summary)
    text = mem.index_md.read_text(encoding="utf-8")
    if "[[%s]]" % slug in text:
        return
    out, inserted = [], False
    for ln in text.splitlines():
        out.append(ln)
        if not inserted and ln.strip() == heading:
            out.append(line)
            inserted = True
    if not inserted:
        out += ["", heading, line]
    mem.index_md.write_text("\n".join(out) + "\n", encoding="utf-8")


def _relink_wiki(mem, top_k: int = 3) -> int:
    """Rewrite each page's deterministic `## Correlate` section; return #changed."""
    from memlib import relink as relink_mod
    pages = collect_pages(mem.wiki)
    related = relink_mod.compute_related(pages, top_k=top_k)
    changed = 0
    for p in pages:
        if "read_error" in p:
            continue
        path = Path(p["path"])
        old = path.read_text(encoding="utf-8")
        new = relink_mod.upsert_section(old, related.get(p["slug"], []))
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def cmd_relink(args) -> int:
    mem = resolve(args.memory)
    if not mem.exists():
        print("No wiki at %s. Run `mem init` first." % mem.wiki, file=sys.stderr)
        return 1
    n = _relink_wiki(mem, top_k=args.top_k)
    print("Relinked %d page(s) (deterministic Correlate, top_k=%d)." % (n, args.top_k))
    cmd_index(argparse.Namespace(memory=args.memory))
    return 0


def cmd_hubs(args) -> int:
    """Detect ambiguous decision clusters; with --apply, write disambiguation hubs."""
    from memlib import hubs
    mem = resolve(args.memory)
    if not mem.exists():
        print("No wiki at %s. Run `mem init` first." % mem.wiki, file=sys.stderr)
        return 1
    pages = collect_pages(mem.wiki)
    clusters = hubs.detect_clusters(pages, min_size=args.min_size)
    if not clusters:
        print("No clusters of >= %d related decisions found." % args.min_size)
        return 0

    if not args.apply:
        print("Detected %d cluster(s) (use --apply to create hub pages):\n" % len(clusters))
        for term, members in clusters:
            print("  %s-options  (%d):  %s" % (term, len(members), ", ".join(members)))
        return 0

    import reconcile
    concepts = mem.wiki / TYPE_DIR["concept"]
    concepts.mkdir(parents=True, exist_ok=True)
    written = 0
    for term, members in clusters:
        hub = hubs.build_hub_page(term, members, pages)
        target = concepts / (hub["slug"] + ".md")
        existed = target.exists()
        target.write_text(hub["text"], encoding="utf-8")
        _catalogue_insert(mem, "concept", hub["slug"],
                          "hub: %d opzioni per %s" % (len(members), term))
        reconcile.append_log(mem, "hub", hub["slug"],
                             "disambiguation hub over: %s" % ", ".join(members))
        written += 1
        print("  %s %s  (%d options)"
              % ("~" if existed else "+", target.relative_to(mem.root), len(members)))
    # Reconnect: relink so members link back to their hub (symmetric) — else the
    # freshly written hubs are themselves orphans (nobody links TO them).
    _relink_wiki(mem, top_k=3)
    cmd_index(argparse.Namespace(memory=args.memory))
    print("\nWrote %d hub page(s). Then `mem lint`." % written)
    return 0


def cmd_alias(args) -> int:
    """Curate a page's `aliases:` — synonyms indexed for search (anti lexical-miss)."""
    from memlib.pages import find_by_slug
    mem = resolve(args.memory)
    pages = collect_pages(mem.wiki)
    page = find_by_slug(pages, args.slug)
    if not page or "read_error" in page:
        print("No page with slug '%s'." % args.slug, file=sys.stderr)
        return 1
    path = Path(page["path"])
    meta, body, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
    current = page["aliases"]
    incoming = [a.strip() for a in args.aliases if a.strip()]
    if args.remove:
        new = [a for a in current if a not in incoming]
    elif args.replace:
        new = incoming
    else:  # add (dedup, preserve order)
        new, seen = [], set()
        for a in [*current, *incoming]:
            if a.lower() not in seen:
                seen.add(a.lower()); new.append(a)
    if new:
        meta["aliases"] = new
    else:
        meta.pop("aliases", None)
    path.write_text(frontmatter.with_frontmatter(meta, body), encoding="utf-8")
    print("%s aliases: %s" % (args.slug, new or "(none)"))
    cmd_index(argparse.Namespace(memory=args.memory))
    return 0


def cmd_ingest(args) -> int:
    import change_detect
    import reconcile
    from memlib import compile as compile_mod

    mem = resolve(args.memory)
    if not mem.exists():
        print("No wiki found at %s. Run `mem init` first." % mem.wiki, file=sys.stderr)
        return 1

    schema_text = mem.schema.read_text(encoding="utf-8") if mem.schema.exists() else ""
    backend_label = "LLM (claude -p)" if args.backend == "llm" else "offline draft"

    plan = change_detect.compute_plan(mem, args.since, args.max_candidates)
    new_items = [it for it in plan["items"] if it["action_hint"] == "compile"]
    changed = [it for it in plan["items"] if it["action_hint"] == "reconcile"]

    if not new_items and not changed:
        print("No new curated sources to ingest (0 tokens).")
        return 0

    print("Compiling with backend: %s" % backend_label)
    written = []
    for it in new_items:
        if args.only and it["source"] != args.only:
            continue
        text = (mem.root / it["source"]).read_text(encoding="utf-8")
        try:
            if args.backend == "llm":
                page = compile_mod.compile_llm(it["source"], text, schema_text,
                                               it["candidates"], args.type, args.model)
            else:
                page = compile_mod.compile_offline(it["source"], text, args.type)
        except Exception as e:  # llm.LLMError or parse failure
            print("  ! %s: %s" % (it["source"], e), file=sys.stderr)
            continue
        target = mem.wiki / TYPE_DIR[args.type] / (page["slug"] + ".md")
        if target.exists() and not args.force:
            print("  = %s (exists; --force to overwrite)" % target.relative_to(mem.root))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page["text"], encoding="utf-8")
        summary = compile_mod.extract_summary(text)
        _catalogue_insert(mem, args.type, page["slug"], summary)
        status_meta, _, _ = frontmatter.parse(page["text"])
        status = status_meta.get("status", "draft")
        reconcile.append_log(mem, "ingest", page["slug"],
                             "source: %s -> %s (%s)"
                             % (it["source"], target.relative_to(mem.root), backend_label))
        written.append(page["slug"])
        print("  + %s  [%s]" % (target.relative_to(mem.root), status))

    if changed and not args.only:
        verb = ("run `mem reconcile --apply`" if args.backend == "llm"
                else "need the LLM reconcile (`mem reconcile --apply`)")
        print("\n%d changed/cited source(s) %s:" % (len(changed), verb))
        for it in changed:
            print("    ~ %s" % it["source"])

    # Offline pages are born unconnected — link them deterministically (0 tokens)
    # so the wiki is a graph, not a pile. The LLM backend links inline already.
    if written and args.backend == "offline" and not args.no_relink:
        n = _relink_wiki(mem, top_k=args.relink_top_k)
        if n:
            print("  linked %d page(s) (deterministic Correlate)" % n)

    # Refresh deterministic artifacts and the snapshot for what we processed.
    cmd_index(argparse.Namespace(memory=args.memory))
    snap = change_detect.current_source_hashes(mem.raw)
    mem.sources_sha.write_text(json.dumps(snap, indent=2), encoding="utf-8")

    print("\nIngested %d page(s) [%s]. Then `mem lint`." % (len(written), backend_label))
    return 0


# --------------------------------------------------------------------------- #
# review — async review queue: items needing human judgment (derived from state)
# --------------------------------------------------------------------------- #
def _review_query(title: str) -> str:
    from memlib.pages import tokenize
    terms = " ".join(tokenize(title)[:4]) or title
    return 'mem search "%s" --top 5' % terms


def build_review_items(mem: MemoryPaths) -> list:
    """Derive open review items from the current memory state. Zero tokens.

    No separate queue file: the page status machine + lint ARE the queue, so an
    item disappears the moment it's actually resolved (single source of truth).
    """
    pages = [p for p in collect_pages(mem.wiki) if "read_error" not in p]
    items = []
    for p in pages:
        st = p.get("status")
        if st == "contradicted":
            items.append({"kind": "contradicted", "slug": p["slug"], "where": p["rel_path"],
                          "why": "a source conflicts with this page",
                          "action": "re-read the source, then reconcile or archive",
                          "do": "mem reconcile --apply", "query": _review_query(p["title"])})
        elif st == "stale":
            items.append({"kind": "stale", "slug": p["slug"], "where": p["rel_path"],
                          "why": "its source changed after the page was written",
                          "action": "re-ingest the changed source",
                          "do": "mem ingest --backend llm", "query": _review_query(p["title"])})
    findings = run_lint(mem, 400, 800)
    for f in findings["missing_sources"]:
        items.append({"kind": "missing-source", "slug": Path(f["path"]).stem,
                      "where": f["path"], "why": "no sources: (anti-drift)",
                      "action": "add a sources: line citing the raw/ file", "do": None,
                      "query": None})
    for f in findings["dangling_sources"]:
        items.append({"kind": "dangling-source", "slug": Path(f["path"]).stem,
                      "where": f["path"], "why": "cites a source that doesn't exist: %s" % f["source"],
                      "action": "fix the source path or restore the file", "do": None,
                      "query": None})
    return items


def cmd_review(args) -> int:
    mem = resolve(args.memory)
    if not mem.exists():
        print("No wiki found at %s." % mem.wiki, file=sys.stderr)
        return 1
    items = build_review_items(mem)
    if args.json:
        print(json.dumps(items, indent=2))
        return 1 if (args.strict and items) else 0
    if not items:
        print("Review queue empty — nothing needs human judgment.")
        return 0
    print("Review queue: %d item(s) need human judgment\n" % len(items))
    order = {"contradicted": 0, "dangling-source": 1, "missing-source": 2, "stale": 3}
    for it in sorted(items, key=lambda x: order.get(x["kind"], 9)):
        print("[%s] %s  (%s)" % (it["kind"].upper(), it["slug"], it["where"]))
        print("    why:    %s" % it["why"])
        print("    action: %s" % it["action"])
        if it.get("do"):
            print("    run:    %s" % it["do"])
        if it.get("query"):
            print("    find:   %s" % it["query"])
        print()
    return 1 if args.strict else 0


# --------------------------------------------------------------------------- #
# add-synthesis — file a worthy answer back into the memory as a synthesis page
# --------------------------------------------------------------------------- #
def cmd_add_synthesis(args) -> int:
    from memlib.compile import _slugify

    mem = resolve(args.memory)
    if not mem.exists():
        print("No wiki found at %s. Run `mem init` first." % mem.wiki, file=sys.stderr)
        return 1
    links = [s.strip() for s in (args.links or "").split(",") if s.strip()]
    if not links:
        print("A synthesis must cite the pages it draws from (--links a,b).",
              file=sys.stderr)
        return 1

    pages = {p["slug"]: p for p in collect_pages(mem.wiki) if "read_error" not in p}
    missing = [l for l in links if l not in pages]
    if missing:
        print("Unknown linked pages: %s" % ", ".join(missing), file=sys.stderr)
        return 1

    # Anti-drift: ground the synthesis in the union of its sources' raw files.
    sources, tags = [], []
    for l in links:
        for s in pages[l].get("sources", []):
            if s not in sources:
                sources.append(s)
        for t in pages[l].get("tags", []):
            if t not in tags:
                tags.append(t)
    if not sources:
        print("Linked pages carry no sources; cannot ground the synthesis.",
              file=sys.stderr)
        return 1

    body = args.body if args.body is not None else sys.stdin.read()
    body = body.strip() or "(sintesi)"
    slug = args.slug or _slugify(args.title)
    # Ensure every cited page appears as a wikilink (graph edges + justifies sources).
    if not all(("[[%s]]" % l) in body for l in links):
        body += "\n\nDeriva da: " + " · ".join("[[%s]]" % l for l in links)

    today = date.today().isoformat()
    meta = {"id": slug, "type": "synthesis", "status": "active",
            "title": args.title, "tags": tags[:4] or ["sintesi"],
            "sources": sources, "created": today, "updated": today}
    target = mem.wiki / "synthesis" / (slug + ".md")
    if target.exists() and not args.force:
        print("%s already exists (use --force)." % target.relative_to(mem.root),
              file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(frontmatter.with_frontmatter(meta, "# %s\n\n%s\n" % (args.title, body)),
                      encoding="utf-8")
    _catalogue_insert(mem, "synthesis", slug, args.title)
    import reconcile
    reconcile.append_log(mem, "synthesis", slug,
                         "filed answer citing: %s" % ", ".join(links))
    cmd_index(argparse.Namespace(memory=args.memory))
    print("  + %s  [synthesis]  sources: %s" % (target.relative_to(mem.root),
                                                ", ".join(sources)))
    return 0


# --------------------------------------------------------------------------- #
# install-hooks — wire the merge hook into .git/hooks (plug-and-play)
# --------------------------------------------------------------------------- #
def cmd_install_hooks(args) -> int:
    repo = Path(args.repo).resolve()
    git_dir = repo / ".git"
    if not git_dir.is_dir():
        print("Not a git repo: %s (run `git init` first)." % repo, file=sys.stderr)
        return 1
    src = Path(__file__).resolve().parent.parent / "hooks" / "post-merge"
    if not src.exists():
        print("Hook source missing: %s" % src, file=sys.stderr)
        return 1
    dst = git_dir / "hooks" / "post-merge"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not args.force:
        print("%s already exists (use --force)." % dst, file=sys.stderr)
        return 1
    # Bake the absolute CLI path so the hook works from a repo without core/.
    core_dir = Path(__file__).resolve().parent
    text = (src.read_text(encoding="utf-8")
            .replace("__PYTHON__", sys.executable)
            .replace("__CORE__", str(core_dir)))
    dst.write_text(text, encoding="utf-8")
    dst.chmod(0o755)
    print("Installed post-merge hook -> %s" % dst)
    print("  CLI: %s %s/mem.py" % (sys.executable, core_dir))
    print("  On merge to '%s' (MEM_CANONICAL_BRANCH): Phase 1 + Phase 2 ingest "
          "(MEM_BACKEND=offline|llm) + auto-commit (MEM_AUTORECONCILE=1)."
          % os.environ.get("MEM_CANONICAL_BRANCH", "main"))

    if not args.no_merge_driver:
        _wire_merge_driver(repo, core_dir)
    return 0


def _wire_merge_driver(repo: Path, core_dir: Path) -> None:
    """Make `git merge` route .memory files through `mem merge-driver`.

    Two halves of the standard git pattern (cf. git-lfs):
      * `.memory/.gitattributes` (committed, travels with the repo) maps the
        files to the `engram` driver — a clone WITHOUT the driver registered
        just falls back to git's default merge, so this is always safe.
      * the driver definition lives in `.git/config` (per-clone, references the
        absolute CLI path) — registered here.
    """
    mem_dir = repo / ".memory"
    if not mem_dir.is_dir():
        print("  (no .memory/ here — skipped merge-driver wiring)")
        return

    attrs = mem_dir / ".gitattributes"
    want = [
        "# engram: route catalogue/log/pages through `mem merge-driver` (see .git/config).",
        "index.md   merge=engram",
        "log.md     merge=engram",
        "wiki/**    merge=engram",
    ]
    existing = attrs.read_text(encoding="utf-8").splitlines() if attrs.exists() else []
    if not any("merge=engram" in ln for ln in existing):
        merged = existing + ([""] if existing and existing[-1].strip() else []) + want
        attrs.write_text("\n".join(merged).rstrip("\n") + "\n", encoding="utf-8")
        print("  Wrote merge attributes -> %s" % attrs)
    else:
        print("  Merge attributes already present -> %s" % attrs)

    driver = '%s %s/mem.py merge-driver %%O %%A %%B %%P' % (sys.executable, core_dir)
    try:
        subprocess.check_call(
            ["git", "-C", str(repo), "config", "merge.engram.name",
             "engram memory merge driver"])
        subprocess.check_call(
            ["git", "-C", str(repo), "config", "merge.engram.driver", driver])
        print("  Registered git merge driver 'engram' -> %s" % driver)
    except (subprocess.CalledProcessError, OSError) as e:
        print("  ! could not register merge driver (%s); run manually:" % e,
              file=sys.stderr)
        print('    git config merge.engram.driver "%s"' % driver, file=sys.stderr)


# --------------------------------------------------------------------------- #
# merge — resolve git conflict markers in catalogue/log files (zero token)
# --------------------------------------------------------------------------- #
def cmd_merge(args) -> int:
    from memlib import merge as merge_mod
    mem = resolve(args.memory)
    if args.files:
        targets = [Path(f) for f in args.files]
    else:
        targets = [p for p in (mem.index_md, mem.log) if p.exists()]

    any_resolved = False
    for path in targets:
        if not path.exists():
            print("  ? %s (not found)" % path, file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        if not merge_mod.has_conflicts(text):
            print("  = %s (no conflict)" % path)
            continue
        # Default dedup: slug for the catalogue, whole-line elsewhere (log etc.).
        dedup = args.dedup or ("slug" if path.name == "index.md" else "line")
        resolved, n = merge_mod.resolve(text, dedup=dedup)
        if args.dry_run:
            print("  ~ %s (%d hunk(s), dedup=%s) — dry run, not written" % (path, n, dedup))
        else:
            path.write_text(resolved, encoding="utf-8")
            print("  + %s (%d hunk(s) unioned, dedup=%s)" % (path, n, dedup))
            any_resolved = True
    if any_resolved:
        print("\nResolved by union. Review the diff, then `git add` the files.")
    return 0


# --------------------------------------------------------------------------- #
# merge-driver — a REAL git merge driver: `mem merge-driver %O %A %B %P`
# --------------------------------------------------------------------------- #
def cmd_merge_driver(args) -> int:
    """Resolve a 3-way merge of a .memory file, invoked by git during `git merge`.

    git passes the base (%O), ours/output (%A), theirs (%B) temp files and the
    real pathname (%P). We write the result into %A and exit 0 (resolved) or
    non-zero (conflict left as markers — git marks the file conflicted).

    Routing by filename, mirroring the design (deterministic, no LLM in git):
      * index.md / log.md  → deterministic union (catalogue/log never conflict).
      * wiki/** prose page  → standard git 3-way; on real conflict leave markers
        and exit 1 so it surfaces in `git status` / `mem review` for an explicit
        (optionally LLM-assisted) reconcile — we never block `git merge` on a model.
    """
    from memlib import merge as merge_mod
    base, ours, theirs = Path(args.base), Path(args.ours), Path(args.theirs)
    name = os.path.basename(args.path or str(ours))

    def _read(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    if name in ("index.md", "log.md"):
        dedup = "slug" if name == "index.md" else "line"
        merged = merge_mod.union_files(_read(ours), _read(theirs), dedup=dedup)
        ours.write_text(merged, encoding="utf-8")
        print("[mem] merge-driver: unioned %s (dedup=%s)" % (name, dedup), file=sys.stderr)
        return 0

    # Prose page (or anything else): delegate to git's own 3-way merge.
    rc = subprocess.call(
        ["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs",
         str(ours), str(base), str(theirs)])
    if rc != 0:
        print("[mem] merge-driver: conflict in %s — left markers; resolve then "
              "`mem review`." % (args.path or name), file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mem", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("init", help="Bootstrap a .memory/ layout.")
    p.add_argument("root", nargs="?", default=".", help="Project root (default: .).")
    p.add_argument("--template", default="software", choices=list(SCHEMA_TEMPLATES),
                   help="Domain schema preset (default: software).")
    p.set_defaults(func=cmd_init)

    def add_memory(pp):
        pp.add_argument("--memory", type=Path, default=None,
                        help="Path to .memory/ (default: auto-discover upward).")

    p = sub.add_parser("index", help="Rebuild index/ artifacts.")
    add_memory(p)
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("search", help="BM25 search over the wiki.")
    add_memory(p)
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--type")
    p.add_argument("--status")
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--since")
    p.add_argument("--backlinks")
    p.add_argument("--top-linked", type=int, dest="top_linked")
    p.add_argument("--no-cache", action="store_true", dest="no_cache",
                   help="Ignore the persisted index; scan the wiki live.")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("lint", help="Structural + anti-drift health check.")
    add_memory(p)
    p.add_argument("--soft-cap", type=int, default=400)
    p.add_argument("--hard-cap", type=int, default=800)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("graph", help="Wikilink graph summary.")
    add_memory(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_graph)

    p = sub.add_parser("detect", help="Phase 1: which curated sources changed (0 tokens).")
    add_memory(p)
    p.add_argument("--since", help="Restrict to raw files changed since this git ref.")
    p.add_argument("--max-candidates", type=int, default=8)
    p.add_argument("--update-snapshot", action="store_true",
                   help="Record current source hashes as processed and exit.")
    p.add_argument("--no-cache", action="store_true", dest="no_cache",
                   help="Ignore the persisted index; scan the wiki live.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("reconcile", help="Phase 2: assemble minimal LLM context (stub).")
    add_memory(p)
    p.add_argument("--since")
    p.add_argument("--max-candidates", type=int, default=8)
    p.add_argument("--show-context", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_reconcile)

    p = sub.add_parser("ingest", help="Compile NEW curated sources into draft pages (offline).")
    add_memory(p)
    p.add_argument("--since")
    p.add_argument("--max-candidates", type=int, default=8)
    p.add_argument("--type", default="decision", choices=list(TYPE_DIR))
    p.add_argument("--backend", default="offline", choices=["offline", "llm"],
                   help="offline = deterministic draft (0 tokens); llm = synthesis via `claude -p`.")
    p.add_argument("--model", default=None, help="Model for --backend llm (default: sonnet).")
    p.add_argument("--only", help="Ingest only this raw source (rel path).")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-relink", action="store_true",
                   help="Skip deterministic auto-linking of offline pages.")
    p.add_argument("--relink-top-k", type=int, default=3, dest="relink_top_k",
                   help="Neighbours per page for auto-linking (default: 3).")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("relink",
                       help="Auto-link pages by a deterministic `## Correlate` section (0 tokens).")
    add_memory(p)
    p.add_argument("--top-k", type=int, default=3, dest="top_k",
                   help="Neighbours per page (default: 3).")
    p.set_defaults(func=cmd_relink)

    p = sub.add_parser("hubs",
                       help="Detect ambiguous decision clusters; --apply writes disambiguation hubs.")
    add_memory(p)
    p.add_argument("--min-size", type=int, default=3, dest="min_size",
                   help="Min decisions sharing a term to form a cluster (default: 3).")
    p.add_argument("--apply", action="store_true", help="Write hub pages (else just list).")
    p.set_defaults(func=cmd_hubs)

    p = sub.add_parser("alias", help="Curate a page's search aliases (synonyms).")
    add_memory(p)
    p.add_argument("slug", help="Page slug to edit.")
    p.add_argument("aliases", nargs="*", help="Alias phrases (quote multi-word).")
    p.add_argument("--remove", action="store_true", help="Remove the given aliases.")
    p.add_argument("--replace", action="store_true", help="Replace all aliases with the given ones.")
    p.set_defaults(func=cmd_alias)

    p = sub.add_parser("install-hooks", help="Install the git merge hook (plug-and-play).")
    p.add_argument("repo", nargs="?", default=".", help="Repo root (default: .).")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-merge-driver", action="store_true",
                   help="Skip wiring the .memory merge driver (.gitattributes + git config).")
    p.set_defaults(func=cmd_install_hooks)

    p = sub.add_parser("review", help="List memory items needing human judgment.")
    add_memory(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="Exit non-zero if any item is open.")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("add-synthesis", help="File a worthy answer as a synthesis page.")
    add_memory(p)
    p.add_argument("--title", required=True)
    p.add_argument("--links", required=True, help="Comma-separated slugs the answer draws from.")
    p.add_argument("--body", default=None, help="Answer body (default: read stdin).")
    p.add_argument("--slug", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_add_synthesis)

    p = sub.add_parser("merge", help="Resolve conflict markers in index.md/log.md by union.")
    add_memory(p)
    p.add_argument("files", nargs="*", help="Files to resolve (default: index.md + log.md).")
    p.add_argument("--dedup", choices=["slug", "line"], help="Dedup key (default: auto).")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("merge-driver",
                       help="git merge driver: `mem merge-driver %%O %%A %%B %%P`.")
    p.add_argument("base", help="ancestor version (%%O)")
    p.add_argument("ours", help="current version / output target (%%A)")
    p.add_argument("theirs", help="other version (%%B)")
    p.add_argument("path", nargs="?", default="", help="real pathname (%%P)")
    p.set_defaults(func=cmd_merge_driver)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
