"""pages.py — walk a wiki/ tree into structured page records.

A "page" is one atomic concept (one decision, one concept, ...). This module is
the single source of truth for what counts as a page, how it tokenizes, and how
its wikilinks/sources are extracted. Everything downstream (bm25, graph, lint,
index) consumes `collect_pages`.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import frontmatter
from .store import NON_PAGE_DIRS, NON_PAGE_FILES

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
TOKEN_RE = re.compile(r"[a-z0-9]+")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")

VALID_TYPES = {"decision", "concept", "entity", "synthesis"}
VALID_STATUS = {"draft", "active", "stale", "contradicted", "archived"}

# Small IT+EN stopword list — high-frequency words that carry no retrieval
# signal. Removing them is a clear, low-risk recall win.
STOPWORDS = {
    # English
    "the", "a", "an", "of", "in", "on", "to", "and", "or", "is", "are", "be",
    "for", "with", "without", "as", "at", "by", "it", "this", "that", "we",
    "you", "not", "no", "if", "so", "but", "from", "can", "will", "do", "does",
    # Italian
    "il", "lo", "la", "le", "i", "gli", "un", "una", "uno", "di", "del", "della",
    "dei", "delle", "dello", "e", "o", "ed", "od", "che", "non", "per", "con",
    "su", "tra", "fra", "come", "se", "ma", "al", "alla", "ai", "alle", "dal",
    "dalla", "nel", "nella", "sul", "sulla", "si", "ci", "quando", "ogni", "una",
    "anche", "più", "meno", "già", "solo", "sono", "essere", "viene", "fa",
}

# Ordered suffixes for a light, symmetric stemmer (applied to docs AND queries).
# "es" is intentionally absent — it turned "files" into "fil"; plural-s handles it.
_SUFFIXES = ("azioni", "azione", "zioni", "zione", "mente", "ing", "ed")


def _stem(w: str) -> str:
    """Conservative stemmer: unify common IT/EN inflections, length-guarded so
    short words (git, repo, file) stay intact. Deliberately does NOT strip lone
    romance vowels — that over-collapses unrelated words on small corpora and
    measured worse on the eval. Suffixes + IT plural-i + plural-s are the safe win:
    fonti->fonte, decisioni->decisione, files->file, flags->flag."""
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    if len(w) >= 5 and w.endswith("i") and not w.endswith("ii"):
        return w[:-1] + "e"   # IT plural: fonti->fonte, decisioni->decisione
    if len(w) >= 5 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]         # EN plural: files->file, flags->flag
    return w


def tokenize(text: str) -> list[str]:
    out = []
    for tok in TOKEN_RE.findall(text.lower()):
        if tok in STOPWORDS or len(tok) == 1:
            continue
        out.append(_stem(tok))
    return out


def strip_code(md: str) -> str:
    """Remove fenced and inline code so we never parse links/structure inside it."""
    return _INLINE_CODE_RE.sub(" ", _FENCE_RE.sub(" ", md))


def extract_wikilinks(body: str) -> list[str]:
    """Wikilinks in real prose only — links inside code spans are not edges."""
    return [m.group(1).strip() for m in WIKILINK_RE.finditer(strip_code(body))]


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def collect_pages(wiki_root: Path) -> list[dict]:
    """Return one record per wiki page.

    Record keys: path, rel_path, slug, type, status, title, tags, sources,
    links, meta, body, tokens, line_count, malformed_fm, read_error.
    """
    wiki_root = Path(wiki_root)
    pages: list[dict] = []
    if not wiki_root.exists():
        return pages
    for md_path in sorted(wiki_root.rglob("*.md")):
        rel = md_path.relative_to(wiki_root)
        if rel.parts[0] in NON_PAGE_FILES or rel.parts[0] in NON_PAGE_DIRS:
            continue
        if rel.name.startswith("."):
            continue
        try:
            text = md_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            pages.append({
                "path": str(md_path),
                "rel_path": str(rel),
                "slug": md_path.stem,
                "read_error": str(e),
            })
            continue
        meta, body, malformed = frontmatter.parse(text)
        links = extract_wikilinks(body)
        title = meta.get("title") or md_path.stem
        pages.append({
            "path": str(md_path),
            "rel_path": str(rel),
            "slug": md_path.stem,
            "type": meta.get("type", ""),
            "status": meta.get("status", ""),
            "title": title,
            "tags": _as_list(meta.get("tags")),
            "sources": _as_list(meta.get("sources")),
            "links": links,
            "meta": meta,
            "body": body,
            "tokens": tokenize(body + " " + title + " " + " ".join(_as_list(meta.get("tags")))),
            "line_count": text.count("\n") + 1,
            "malformed_fm": malformed,
        })
    return pages


def find_by_slug(pages: list[dict], slug: str) -> dict | None:
    return next((p for p in pages if p.get("slug") == slug), None)
