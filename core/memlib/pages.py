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


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


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
