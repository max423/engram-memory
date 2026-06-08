"""relink.py — deterministic auto-linking of wiki pages (zero tokens).

The offline compiler structures each source into an atomic page but cannot
*connect* them — so a freshly ingested wiki is a pile of orphans, and the graph
signals that sharpen ranking (backlinks, Adamic-Adar) stay dead until an LLM
hand-links the pages. This closes that gap with code: for each page, find its
nearest neighbours by the SAME machinery Phase 1 already uses (BM25 lexical
closeness + shared `sources:`) and write a regenerated `## Correlate` section of
`[[slug]]` links.

Orphans are defined by *backlinks* (pages nobody links TO), so directed top-k
links alone wouldn't clear them. We take the **symmetric closure**: if A lists B,
B also lists A. Every page that emits ≥1 link therefore gets ≥1 backlink → the
wiki goes from "pile" to connected graph, deterministically, at zero token cost.

The section lives between HTML-comment markers so re-running is idempotent and
never clobbers hand-authored prose or manual wikilinks elsewhere in the page.
"""

from __future__ import annotations

from collections import defaultdict

from .bm25 import BM25
from .ranking import source_overlap_scores

START = "<!-- correlate:auto -->"
END = "<!-- /correlate:auto -->"


def compute_related(pages: list, top_k: int = 3, min_score: float = 0.0) -> dict:
    """Return {slug: [related_slugs]} — symmetric, deterministic.

    Primary signal: BM25 similarity (each page queried against the corpus by its
    own title+text). Secondary additive boost: pages that share a raw source.
    Ties broken by slug for stable, reproducible output.
    """
    real = [p for p in pages if "read_error" not in p]
    if len(real) < 2:
        return {}
    bm = BM25.build(real)

    related: dict = defaultdict(set)
    for p in real:
        slug = p["slug"]
        query = "%s %s" % (p.get("title", ""), p.get("text", ""))
        scores: dict = defaultdict(float)
        for s, sc in bm.search(query, top=top_k + 1):
            if s != slug and sc > min_score:
                scores[s] += sc
        # Shared-source boost: pages discussing the same raw material.
        for s, n in source_overlap_scores(real, [slug], exclude_source="").items():
            if s != slug:
                scores[s] += float(n)  # additive, on top of lexical closeness
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        for s, _ in ranked[:top_k]:
            related[slug].add(s)

    # Symmetric closure: a link implies a backlink → no connected orphans.
    for a, outs in list(related.items()):
        for b in outs:
            related[b].add(a)
    return {s: sorted(v) for s, v in related.items()}


def render_section(slugs: list) -> str:
    body = ["%s" % START, "", "## Correlate", ""]
    body += ["- [[%s]]" % s for s in slugs]
    body += ["", END]
    return "\n".join(body)


def upsert_section(text: str, slugs: list) -> str:
    """Insert/replace the auto `## Correlate` block. Idempotent; no-op if empty."""
    if not slugs:
        return _strip_section(text)
    block = render_section(slugs)
    if START in text and END in text:
        pre = text[: text.index(START)].rstrip("\n")
        post = text[text.index(END) + len(END):].lstrip("\n")
        joined = pre + "\n\n" + block
        if post:
            joined += "\n\n" + post.rstrip("\n")
    else:
        joined = text.rstrip("\n") + "\n\n" + block
    return joined + "\n"


def _strip_section(text: str) -> str:
    if START in text and END in text:
        pre = text[: text.index(START)].rstrip("\n")
        post = text[text.index(END) + len(END):].lstrip("\n")
        return (pre + ("\n\n" + post if post else "\n")) if pre else post
    return text
