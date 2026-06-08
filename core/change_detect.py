#!/usr/bin/env python3
"""
change_detect.py — Phase 1 of reconcile: WHAT to touch, at ZERO LLM tokens.

This is the deterministic half of the differentiator. Given the curated sources
in `raw/`, it:

  1. detects which sources are NEW / CHANGED / REMOVED, by SHA-256 against a
     snapshot in `index/sources.sha256` (idea from ktrysmt/llmwiki). Optionally
     scoped to a git ref with `--since`.
  2. for each changed source, selects the few wiki pages that might be impacted,
     using three independent signals:
        (a) sources:  — pages whose frontmatter cites this raw file
        (b) BM25      — pages lexically closest to the source content
        (c) graph     — 1-hop neighbours (backlinks) of the above
  3. emits a "reconcile plan": {source -> candidate pages}, capped small.

The plan is the entire input the LLM (Phase 2, reconcile.py) needs: it never
sees the rest of the wiki. Run with `--update-snapshot` after a successful
reconcile to record the new hashes.

Usage:
    python change_detect.py [--memory DIR] [--since GIT_REF]
                            [--max-candidates N] [--update-snapshot] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memlib import ranking  # noqa: E402
from memlib.bm25 import BM25  # noqa: E402
from memlib.graph import build_graph, neighbors  # noqa: E402
from memlib.pages import collect_pages, tokenize  # noqa: E402
from memlib.store import resolve  # noqa: E402

MAX_CANDIDATES = 8


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def current_source_hashes(raw_dir: Path) -> dict:
    """rel-path-from-memory-root -> sha256, for every file under raw/."""
    out = {}
    if not raw_dir.exists():
        return out
    mem_root = raw_dir.parent
    for f in sorted(raw_dir.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            rel = str(f.relative_to(mem_root))
            out[rel] = sha256_file(f)
    return out


def load_snapshot(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def git_changed_under(repo_root: Path, ref: str, raw_dir: Path) -> set | None:
    """Set of raw rel-paths changed since `ref` per git, or None if git fails."""
    try:
        rel_raw = os.path.relpath(raw_dir, repo_root)
        out = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-only", ref, "--", rel_raw],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    mem_root = raw_dir.parent
    changed = set()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        abs_p = (repo_root / line).resolve()
        try:
            changed.add(str(abs_p.relative_to(mem_root)))
        except ValueError:
            pass
    return changed


def detect_changes(current: dict, snapshot: dict, git_filter: set | None) -> list[dict]:
    changes = []
    for rel, sha in current.items():
        if rel not in snapshot:
            status = "new"
        elif snapshot[rel] != sha:
            status = "changed"
        else:
            continue
        if git_filter is not None and rel not in git_filter:
            continue
        changes.append({"source": rel, "status": status, "sha256": sha})
    for rel in snapshot:
        if rel not in current:
            if git_filter is not None and rel not in git_filter:
                continue
            changes.append({"source": rel, "status": "removed", "sha256": None})
    return changes


def select_candidates(source_rel: str, source_text: str, pages: list[dict],
                      bm25: BM25, graph: dict, limit: int) -> list[dict]:
    """Multi-signal candidate selection for one source. Deterministic, additive.

    Signals (scores accumulate, so a page hit by several outranks single-signal):
      sources (100) · BM25 (lexical) · graph 1-hop (1) · source-overlap (3·shared)
      · Adamic-Adar (2·aa). A direct citation always sorts first.
    """
    chosen: dict = {}  # slug -> {slug, rel_path, reasons:set, score}
    by_slug = {p["slug"]: p for p in pages}

    def add(slug, reason, score):
        page = by_slug.get(slug)
        if not page:
            return
        entry = chosen.setdefault(slug, {
            "slug": slug, "rel_path": page["rel_path"], "reasons": set(), "score": 0.0,
        })
        entry["reasons"].add(reason)
        entry["score"] += score            # additive across signals

    # (a) sources: pages that already cite this raw file — strongest signal.
    cited = [p["slug"] for p in pages if source_rel in p.get("sources", [])]
    for slug in cited:
        add(slug, "sources", 100.0)

    # (b) BM25: pages lexically closest to the source content.
    bm_hits = bm25.search(source_text, top=limit) if source_text.strip() else []
    for slug, score in bm_hits:
        add(slug, "bm25", score)

    # Seed set for the graph signals: the cited pages, else the top BM25 hits.
    seeds = set(cited) or {s for s, _ in bm_hits[:3]}

    # (c) graph: 1-hop neighbours of the seeds.
    for slug in seeds:
        for nb in neighbors(graph, slug):
            add(nb, "graph", 1.0)

    # (d) source-overlap: pages sharing other raw sources with the seeds.
    for slug, shared in ranking.source_overlap_scores(pages, seeds, source_rel).items():
        add(slug, "overlap", 3.0 * shared)

    # (e) Adamic-Adar: graph proximity to the seeds via rare common neighbours.
    for slug, aa in ranking.adamic_adar_scores(graph, seeds).items():
        add(slug, "adamic-adar", 2.0 * aa)

    ranked = sorted(
        chosen.values(),
        key=lambda e: (("sources" in e["reasons"]), e["score"]),
        reverse=True,
    )
    for e in ranked:
        e["reasons"] = sorted(e["reasons"])
    return ranked[:limit]


def build_plan(mem, changes: list[dict], pages: list[dict], limit: int,
               bm25=None, graph=None) -> dict:
    real = [p for p in pages if "read_error" not in p]
    if bm25 is None:
        bm25 = BM25.build(real)
    if graph is None:
        graph = build_graph(real)
    items = []
    for ch in changes:
        if ch["status"] == "removed":
            # The source is gone; candidates are pages that still cite it.
            cands = [
                {"slug": p["slug"], "rel_path": p["rel_path"],
                 "reasons": ["sources"], "score": 100.0}
                for p in real if ch["source"] in p.get("sources", [])
            ]
        else:
            text = (mem.root / ch["source"]).read_text(encoding="utf-8")
            cands = select_candidates(ch["source"], text, real, bm25, graph, limit)
        items.append({
            "source": ch["source"],
            "status": ch["status"],
            "action_hint": "compile" if ch["status"] == "new" and not _cited(ch["source"], real)
                           else "reconcile",
            "candidates": cands,
        })
    return {"changes": len(changes), "items": items}


def _cited(source_rel: str, pages: list[dict]) -> bool:
    return any(source_rel in p.get("sources", []) for p in pages)


def compute_plan(mem, since: str | None, max_candidates: int, use_cache: bool = True) -> dict:
    """Phase 1 end to end: hashes -> changes -> candidate plan. Zero tokens.

    O(change): hashing raw/ is the only mandatory work; if nothing changed we
    return before touching the wiki. When sources DID change but the wiki pages
    didn't, we load the validated persisted index instead of re-walking the wiki.
    """
    current = current_source_hashes(mem.raw)
    snapshot = load_snapshot(mem.sources_sha)
    git_filter = git_changed_under(mem.root.parent, since, mem.raw) if since else None
    changes = detect_changes(current, snapshot, git_filter)
    if not changes:
        return {"changes": 0, "items": []}

    if use_cache:
        from memlib import index_store
        cache = index_store.load_valid(mem)
        if cache is not None:
            return build_plan(mem, changes, cache["records"], max_candidates,
                              bm25=cache["bm25"], graph=cache["graph"])
    pages = collect_pages(mem.wiki)
    return build_plan(mem, changes, pages, max_candidates)


def print_plan(plan: dict) -> None:
    if not plan["items"]:
        print("No curated sources new or changed. Nothing to reconcile (0 tokens).")
        return
    print("Reconcile plan: %d changed source(s)\n" % plan["changes"])
    for item in plan["items"]:
        print("[%s] %s  -> %s" % (item["status"].upper(), item["source"], item["action_hint"]))
        if not item["candidates"]:
            print("    (no candidate pages)")
        for c in item["candidates"]:
            print("    - %-28s %-18s score=%.2f" % (
                c["slug"], "(" + ",".join(c["reasons"]) + ")", c["score"]))
        print()
    print("Next: feed this plan to reconcile (Phase 2, the only LLM call).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--memory", type=Path, default=None)
    ap.add_argument("--since", help="Restrict to raw files changed since this git ref.")
    ap.add_argument("--max-candidates", type=int, default=MAX_CANDIDATES)
    ap.add_argument("--update-snapshot", action="store_true",
                    help="Write current hashes to index/sources.sha256 and exit.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    mem = resolve(args.memory)
    current = current_source_hashes(mem.raw)

    if args.update_snapshot:
        mem.index_dir.mkdir(parents=True, exist_ok=True)
        mem.sources_sha.write_text(json.dumps(current, indent=2), encoding="utf-8")
        print("Snapshot updated: %d sources -> %s" % (len(current), mem.sources_sha))
        return 0

    plan = compute_plan(mem, args.since, args.max_candidates)
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print_plan(plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
