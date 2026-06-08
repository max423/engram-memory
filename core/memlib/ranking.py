"""ranking.py — extra deterministic relevance signals for candidate selection.

Phase 1 of reconcile picks the few pages a changed source might impact. Beyond
direct citation (`sources:`), lexical closeness (BM25), and 1-hop graph
neighbours, two cheap graph signals (borrowed in spirit from nashsu/llm_wiki's
4-signal relevance model — studied, not copied; it is GPL) sharpen the pick:

  - source-overlap: pages that share *other* raw sources with the seed pages
    (they're discussing the same material).
  - Adamic-Adar: classic link-prediction — pages connected to the seeds through
    *rare* common neighbours score higher than those sharing a popular hub.

All O(edges); zero tokens.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .graph import neighbors


def adjacency(graph: dict) -> dict:
    """Undirected adjacency over real nodes only (ignores broken-link targets)."""
    nodes = {n["slug"] for n in graph.get("nodes", [])}
    adj = defaultdict(set)
    for e in graph.get("edges", []):
        a, b = e["from"], e["to"]
        if a in nodes and b in nodes:
            adj[a].add(b)
            adj[b].add(a)
    return adj


def adamic_adar_scores(graph: dict, seeds) -> dict:
    """For each non-seed node, sum 1/log(deg(c)) over common neighbours c it
    shares with any seed. Rare shared neighbours weigh more than popular hubs."""
    seeds = set(seeds)
    adj = adjacency(graph)
    deg = {k: len(v) for k, v in adj.items()}
    scores: dict = defaultdict(float)
    for s in seeds:
        for c in adj.get(s, ()):          # c is a neighbour of seed s
            d = deg.get(c, 0)
            if d > 1:                     # log(1)=0; skip degree-1 hubs
                w = 1.0 / math.log(d)
                for cand in adj.get(c, ()):   # cand also touches c
                    if cand not in seeds:
                        scores[cand] += w
    return dict(scores)


def source_overlap_scores(pages: list, seeds, exclude_source: str) -> dict:
    """For each non-seed page, how many raw sources it shares with the seed
    pages (excluding the changed source itself)."""
    seeds = set(seeds)
    seed_sources = set()
    for p in pages:
        if p["slug"] in seeds:
            seed_sources |= set(p.get("sources", []))
    seed_sources.discard(exclude_source)
    scores = {}
    if not seed_sources:
        return scores
    for p in pages:
        if p["slug"] in seeds:
            continue
        shared = set(p.get("sources", [])) & seed_sources
        if shared:
            scores[p["slug"]] = len(shared)
    return scores
