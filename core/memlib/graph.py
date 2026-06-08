"""graph.py — the wikilink graph: nodes, edges, backlinks, orphans, broken.

Computed deterministically from page wikilinks. Backlinks are what let the
change-detector expand from a touched page to its neighbourhood at zero token
cost (Phase 1, signal (c) in the reconcile design).
"""

from __future__ import annotations

from collections import defaultdict


def build_graph(pages: list[dict]) -> dict:
    real = [p for p in pages if "read_error" not in p]
    slugs = {p["slug"] for p in real}

    nodes = [
        {"slug": p["slug"], "type": p.get("type", ""), "title": p.get("title", p["slug"])}
        for p in real
    ]

    edges = []
    backlinks: dict = defaultdict(list)
    broken = []
    for p in real:
        for link in p["links"]:
            edges.append({"from": p["slug"], "to": link})
            if link in slugs:
                backlinks[link].append(p["slug"])
            else:
                broken.append({"from": p["slug"], "to": link})

    orphans = sorted(p["slug"] for p in real if not backlinks.get(p["slug"]))

    return {
        "nodes": nodes,
        "edges": edges,
        "backlinks": {k: sorted(v) for k, v in backlinks.items()},
        "orphans": orphans,
        "broken_links": broken,
    }


def neighbors(graph: dict, slug: str) -> list[str]:
    """Slugs directly connected to `slug` (out-links + in-links)."""
    out = [e["to"] for e in graph["edges"] if e["from"] == slug]
    incoming = graph["backlinks"].get(slug, [])
    seen, result = set(), []
    for s in [*out, *incoming]:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result
