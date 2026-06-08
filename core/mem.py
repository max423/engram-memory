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

    ensure_file(mem.schema, SCHEMA_TEMPLATE)
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


def cmd_search(args) -> int:
    mem = resolve(args.memory)
    pages = collect_pages(mem.wiki)
    real = [p for p in pages if "read_error" not in p]
    if not real:
        print("No wiki pages found under %s" % mem.wiki, file=sys.stderr)
        return 0

    if args.backlinks:
        inbound = [p for p in real if args.backlinks in p["links"]]
        if not inbound:
            print("No pages link to [[%s]]." % args.backlinks)
            return 0
        print("Pages linking to [[%s]] (%d):" % (args.backlinks, len(inbound)))
        for p in inbound:
            print("  - %s  (%s)" % (p["title"], p["rel_path"]))
        return 0

    if args.top_linked:
        graph = build_graph(pages)
        hubs = sorted(graph["backlinks"].items(), key=lambda kv: -len(kv[1]))[:args.top_linked]
        if not hubs:
            print("No links found in the wiki.")
            return 0
        print("Top %d most-linked-to pages (hubs):" % len(hubs))
        for slug, srcs in hubs:
            print("  %4d  %s" % (len(srcs), slug))
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
    by_slug = {p["slug"]: p for p in filtered}
    print("Top %d results for: %r\n" % (len(hits), args.query))
    for slug, score in hits:
        p = by_slug[slug]
        print("  [%6.2f] [%-9s] %s" % (score, p.get("type", "?"), p["title"]))
        print("           %s" % p["rel_path"])
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
    plan = change_detect.compute_plan(mem, args.since, args.max_candidates)
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


def cmd_ingest(args) -> int:
    import change_detect
    import reconcile
    from memlib import compile as compile_mod

    mem = resolve(args.memory)
    if not mem.exists():
        print("No wiki found at %s. Run `mem init` first." % mem.wiki, file=sys.stderr)
        return 1
    if args.backend == "llm":
        print("backend=llm is the synthesis stub (no API wired). Use --backend offline.",
              file=sys.stderr)
        return 2

    plan = change_detect.compute_plan(mem, args.since, args.max_candidates)
    new_items = [it for it in plan["items"] if it["action_hint"] == "compile"]
    changed = [it for it in plan["items"] if it["action_hint"] == "reconcile"]

    if not new_items and not changed:
        print("No new curated sources to ingest (0 tokens).")
        return 0

    written = []
    for it in new_items:
        if args.only and it["source"] != args.only:
            continue
        text = (mem.root / it["source"]).read_text(encoding="utf-8")
        page = compile_mod.compile_offline(it["source"], text, args.type)
        target = mem.wiki / TYPE_DIR[args.type] / (page["slug"] + ".md")
        if target.exists() and not args.force:
            print("  = %s (exists; --force to overwrite)" % target.relative_to(mem.root))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page["text"], encoding="utf-8")
        summary = compile_mod.extract_summary(text)
        _catalogue_insert(mem, args.type, page["slug"], summary)
        reconcile.append_log(mem, "ingest", page["slug"],
                             "source: %s -> %s (offline draft)"
                             % (it["source"], target.relative_to(mem.root)))
        written.append(page["slug"])
        print("  + %s  [draft]" % target.relative_to(mem.root))

    if changed and not args.only:
        print("\n%d changed/cited source(s) need the LLM reconcile (Phase 2 stub):"
              % len(changed))
        for it in changed:
            print("    ~ %s" % it["source"])

    # Refresh deterministic artifacts and the snapshot for what we processed.
    cmd_index(argparse.Namespace(memory=args.memory))
    change_detect.current_source_hashes(mem.raw)  # warm
    snap = change_detect.current_source_hashes(mem.raw)
    mem.sources_sha.write_text(json.dumps(snap, indent=2), encoding="utf-8")

    print("\nIngested %d page(s) as drafts. Refine them, then `mem lint`." % len(written))
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
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    dst.chmod(0o755)
    print("Installed post-merge hook -> %s" % dst)
    print("It runs Phase 1 on merge to '%s' (override with MEM_CANONICAL_BRANCH)."
          % os.environ.get("MEM_CANONICAL_BRANCH", "main"))
    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mem", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("init", help="Bootstrap a .memory/ layout.")
    p.add_argument("root", nargs="?", default=".", help="Project root (default: .).")
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
    p.add_argument("--backend", default="offline", choices=["offline", "llm"])
    p.add_argument("--only", help="Ingest only this raw source (rel path).")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("install-hooks", help="Install the git merge hook (plug-and-play).")
    p.add_argument("repo", nargs="?", default=".", help="Repo root (default: .).")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_install_hooks)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
