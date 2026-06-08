#!/usr/bin/env python3
"""bench.py — performance of the deterministic core across wiki sizes.

Generates synthetic memories and times index / search / detect / lint, plus the
context-locality claim (candidate pages stay bounded as the wiki grows). All
deterministic; no external deps.

Run:  python3 tests/bench.py [sizes...]   (default: 50 200 1000)
"""

from __future__ import annotations

import contextlib
import io
import json
import random
import sys
import tempfile
import time
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "core"
sys.path.insert(0, str(CORE))

import change_detect  # noqa: E402
from memlib import bm25, frontmatter, graph, pages  # noqa: E402
from memlib.store import MemoryPaths  # noqa: E402
import mem as mem_cli  # noqa: E402

VOCAB = ("storage git markdown reconcile bm25 search token graph backlink lint "
         "merge hook anti drift source schema decision concept entity synthesis "
         "cache redis router model cheap expensive embedding vector index atomic "
         "conflict branch fork canonical commit patch surgical staleness audit").split()


def gen_memory(root: Path, n: int, seed: int = 7) -> MemoryPaths:
    rng = random.Random(seed)
    mem = MemoryPaths(root / ".memory")
    (mem.wiki / "decisions").mkdir(parents=True)
    mem.raw.mkdir(parents=True)
    mem.index_dir.mkdir(parents=True)
    slugs = ["page-%04d" % i for i in range(n)]
    for i, slug in enumerate(slugs):
        body_words = " ".join(rng.sample(VOCAB, k=min(20, len(VOCAB))))
        links = rng.sample(slugs, k=min(3, n))
        link_md = " ".join("[[%s]]" % s for s in links if s != slug)
        raw_rel = "raw/%s.md" % slug
        (mem.root / raw_rel).write_text("# %s\n\nScelta: %s\n" % (slug, body_words))
        meta = {"id": slug, "type": "decision", "status": "active", "title": slug,
                "tags": rng.sample(VOCAB, k=2), "sources": [raw_rel],
                "created": "2026-01-01", "updated": "2026-01-01"}
        body = "# %s\n\n%s\n\n%s\n" % (slug, body_words, link_md)
        (mem.wiki / "decisions" / (slug + ".md")).write_text(
            frontmatter.with_frontmatter(meta, body))
    return mem


def timed(fn, repeat=3):
    best = float("inf")
    out = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - t0)
    return best * 1000, out  # ms


def bench_size(n: int) -> dict:
    with tempfile.TemporaryDirectory() as d:
        mem = gen_memory(Path(d), n)

        quiet = contextlib.redirect_stdout(io.StringIO())

        def run_index():
            with quiet:
                return mem_cli.cmd_index(_ns(mem))

        t_collect, ps = timed(lambda: pages.collect_pages(mem.wiki))
        t_index, _ = timed(run_index)
        idx = bm25.BM25.build([p for p in ps if "read_error" not in p])
        t_search, hits = timed(lambda: idx.search("storage git reconcile", top=5))
        t_lint, _ = timed(lambda: mem_cli.run_lint(mem, 400, 800))

        # change-detect locality: snapshot, mutate ONE source, time the plan.
        change_detect.current_source_hashes(mem.raw)
        snap = change_detect.current_source_hashes(mem.raw)
        mem.sources_sha.write_text(json.dumps(snap))
        target = next(mem.raw.glob("*.md"))
        target.write_text(target.read_text() + "\nmodifica storage git\n")
        t_detect, plan = timed(lambda: change_detect.compute_plan(mem, None, 8))
        n_cand = len(plan["items"][0]["candidates"]) if plan["items"] else 0

        return {"n": n, "collect": t_collect, "index": t_index, "search": t_search,
                "lint": t_lint, "detect": t_detect, "candidates": n_cand}


def _ns(mem):
    import argparse
    return argparse.Namespace(memory=mem.root)


def main():
    sizes = [int(a) for a in sys.argv[1:]] or [50, 200, 1000]
    print("Deterministic core performance (best of 3, milliseconds)\n")
    hdr = ("pages", "collect", "index", "search", "lint", "detect", "candidates")
    print("%7s %9s %9s %9s %9s %9s %11s" % hdr)
    print("-" * 72)
    rows = [bench_size(n) for n in sizes]
    for r in rows:
        print("%7d %9.1f %9.1f %9.3f %9.1f %9.1f %11d"
              % (r["n"], r["collect"], r["index"], r["search"],
                 r["lint"], r["detect"], r["candidates"]))
    print("\nNotes:")
    print("- search/detect stay sub-linear-feeling and candidates stay bounded by")
    print("  --max-candidates (8) regardless of wiki size: that is the token-locality")
    print("  guarantee — the LLM context never grows with the wiki.")
    print("- index/lint/detect are O(total content): full re-read each run. Fine to")
    print("  thousands of pages; see WEAKNESSES.md for the persisted-index path beyond.")


if __name__ == "__main__":
    main()
