"""hubs.py — detect ambiguous decision clusters and build disambiguation hubs.

When several decisions are about the same category (PostgreSQL / MySQL / "choosing
a database"; React / Vue / Svelte), an ambiguous query ("which database?") has no
single right answer and retrieval scatters. A *hub* page collects the cluster:
one concept page per category that links every member, so the query lands on the
hub and fans out to the options — disambiguation by navigation, zero tokens.

Detection is deterministic: group pages by a salient token they share in the
title/tags/slug; a group of >= min_size distinct pages is a cluster. We never
invent membership — a page joins only clusters whose term it actually carries.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import frontmatter
from .pages import tokenize

# Tokens too generic or structural to be a meaningful category to disambiguate.
_GENERIC = {
    "framework", "library", "technology", "options", "option", "using", "based",
    "front", "end", "side", "stack", "full", "choosing", "choice", "tool", "tools",
    "page", "system", "data", "app", "application", "project", "team", "work",
}


def _salient_terms(page: dict) -> set:
    """Significant *stemmed* tokens a page carries (title + tags + slug).

    Everything goes through `tokenize` (the same stemmer/stopword list as search)
    so stopword slug-parts ("for") drop out and stem variants ("programming" /
    "programm") collapse to one cluster key.
    """
    blob = " ".join([
        page.get("title", ""),
        " ".join(page.get("tags", [])),
        page.get("slug", "").replace("-", " "),
    ])
    return {t for t in tokenize(blob) if len(t) >= 3 and t not in _GENERIC}


def detect_clusters(pages: list, min_size: int = 3, max_df_ratio: float = 0.5) -> list:
    """Return [(term, [slugs])] for each shared-term cluster >= min_size.

    A term shared by more than `max_df_ratio` of pages is corpus boilerplate
    ("record", "architecture" in an ADR set), not a category — dropped. Sorted by
    size desc then term; a cluster whose members are a subset of a larger one is
    dropped to avoid near-duplicate hubs.
    """
    real = [p for p in pages if "read_error" not in p
            and "hub" not in p.get("tags", [])]
    term_to_slugs: dict = defaultdict(set)
    for p in real:
        for t in _salient_terms(p):
            term_to_slugs[t].add(p["slug"])

    df_cap = max(min_size + 1, int(len(real) * max_df_ratio))
    clusters = [(t, frozenset(s)) for t, s in term_to_slugs.items()
                if min_size <= len(s) <= df_cap]
    # Drop a cluster whose member set is a subset of a strictly larger cluster.
    kept = []
    for t, members in sorted(clusters, key=lambda x: (-len(x[1]), x[0])):
        if any(members < bigger for _, bigger in kept):
            continue
        kept.append((t, members))
    return [(_label_for(t, sorted(m)), sorted(m)) for t, m in kept]


def _label_for(stem: str, members: list) -> str:
    """A readable surface form for a (stemmed) cluster key: the original word in
    the members' slugs that stems to `stem` (most frequent, then longest)."""
    counts: dict = defaultdict(int)
    for slug in members:
        for part in slug.split("-"):
            if tokenize(part) == [stem]:
                counts[part] += 1
    if not counts:
        return stem
    return sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]


def build_hub_page(term: str, members: list, pages: list) -> dict:
    """A concept page linking every cluster member, anchored to their sources."""
    by_slug = {p["slug"]: p for p in pages}
    sources: list = []
    for slug in members:
        for s in by_slug.get(slug, {}).get("sources", []):
            if s not in sources:
                sources.append(s)
    slug = "%s-options" % term
    title = "Opzioni: %s" % term
    meta = {
        "id": slug,
        "type": "concept",
        "status": "active",
        "title": title,
        "tags": [term, "hub"],
        "sources": sources,
        "created": date.today().isoformat(),
        "updated": date.today().isoformat(),
    }
    lines = [
        "# %s" % title,
        "",
        "Decisioni che riguardano **%s**. Scegli tra le alternative:" % term,
        "",
    ]
    lines += ["- [[%s]]" % s for s in members]
    lines += [
        "",
        "> Hub di disambiguazione generato deterministicamente da `mem hubs` "
        "(0 token). Rigenerato a ogni esecuzione.",
    ]
    body = "\n".join(lines) + "\n"
    return {"slug": slug, "members": members,
            "text": frontmatter.with_frontmatter(meta, body)}
