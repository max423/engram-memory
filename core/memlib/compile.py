"""compile.py — turn a raw source into a wiki page (pluggable backend).

The architecture keeps the synthesis step *behind an interface* so you can mount
Claude Code today and any other agent tomorrow. This module is that interface,
with two backends:

  - "offline" (default): a DETERMINISTIC, zero-token compiler. It does not
    synthesize — it structures: it extracts a title, a one-line summary, and the
    key bullet points from the source and emits a `status: draft` page with a
    correct `sources:` anchor. This makes the whole pipeline runnable with no API
    key; the resulting draft is meant to be refined.
  - "llm": the real synthesis (dense, rewritten prose). Stubbed — see compile_llm.

Both produce the same page shape, so downstream (index/lint/graph) is identical.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from . import frontmatter

_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[-_](.+)$")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CHOICE_RE = re.compile(r"^\s*(?:Scelta|Decision|Decisione|Choice)\s*:\s*(.+)$",
                        re.IGNORECASE | re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.MULTILINE)
_TITLE_PREFIX_RE = re.compile(r"^(?:Decision|Decisione|Decisione:|ADR)\s*[:\-]?\s*",
                              re.IGNORECASE)

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "to", "and", "or", "is", "il", "lo",
    "la", "le", "di", "del", "della", "in", "e", "o", "un", "una", "per",
    "con", "memoria", "decisione", "decision",
}


def slug_and_date(raw_path: Path) -> tuple[str, str | None]:
    """Derive (slug, created_date) from the filename, stripping a date prefix."""
    stem = raw_path.stem
    m = _DATE_PREFIX_RE.match(stem)
    if m:
        return _slugify(m.group(2)), m.group(1)
    return _slugify(stem), None


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _clean(text: str) -> str:
    return _BOLD_RE.sub(r"\1", text).strip()


def extract_title(text: str, fallback: str) -> str:
    m = _H1_RE.search(text)
    if m:
        return _TITLE_PREFIX_RE.sub("", _clean(m.group(1))).strip() or fallback
    return fallback.replace("-", " ").capitalize()


def extract_summary(text: str) -> str:
    """One-line summary: the explicit choice line, else the first real paragraph."""
    m = _CHOICE_RE.search(text)
    if m:
        return _clean(m.group(1)).rstrip(".") + "."
    body = _H1_RE.sub("", text)
    for para in re.split(r"\n\s*\n", body):
        line = " ".join(para.split())
        if len(line) > 30 and not line.lower().startswith(("data", "date", "presenti")):
            return _clean(line)
    return "(da sintetizzare)"


def extract_bullets(text: str, limit: int = 8) -> list[str]:
    seen, out = set(), []
    for m in _BULLET_RE.finditer(text):
        b = _clean(m.group(1)).rstrip(";.")
        if b and b.lower() not in seen:
            seen.add(b.lower())
            out.append(b)
        if len(out) >= limit:
            break
    return out


def derive_tags(slug: str, limit: int = 3) -> list[str]:
    tags = [t for t in slug.split("-") if t and t not in _STOPWORDS and len(t) > 2]
    return tags[:limit] or ["da-taggare"]


def compile_offline(raw_rel: str, raw_text: str, page_type: str = "decision") -> dict:
    """Deterministic compile. Returns {slug, type, text}."""
    raw_path = Path(raw_rel)
    slug, created = slug_and_date(raw_path)
    created = created or date.today().isoformat()
    title = extract_title(raw_text, slug)
    summary = extract_summary(raw_text)
    bullets = extract_bullets(raw_text)
    tags = derive_tags(slug)

    meta = {
        "id": slug,
        "type": page_type,
        "status": "draft",
        "title": title,
        "tags": tags,
        "sources": [raw_rel],
        "created": created,
        "updated": date.today().isoformat(),
    }
    lines = ["# %s" % title, "", summary, ""]
    if bullets:
        lines.append("## Punti chiave")
        lines.extend("- %s" % b for b in bullets)
        lines.append("")
    lines.append("> Bozza compilata offline (estrattiva, non sintesi). "
                 "Fonte: `%s`. Da rifinire: sintetizzare e aggiungere collegamenti "
                 "wikilink alle pagine correlate." % raw_rel)
    body = "\n".join(lines) + "\n"
    return {"slug": slug, "type": page_type, "text": frontmatter.with_frontmatter(meta, body)}


_COMPILE_PROMPT = """\
You are the synthesis step of a curated project-memory tool. Compile ONE raw
source into ONE atomic wiki page. Output ONLY the page file content (a YAML
frontmatter block delimited by --- lines, then the markdown body). No preamble,
no code fence, no explanation.

Rules:
- Synthesize densely — do NOT copy the source verbatim. Density > completeness.
- Treat the raw source as the single source of truth.
- Frontmatter MUST include exactly these keys: id, type, status, title, tags,
  sources, created, updated. Use id=%(slug)s, type=%(ptype)s, status=active,
  created=%(created)s, updated=%(today)s, sources=[%(raw_rel)s].
- tags: 2-4 short lowercase tags (inline list).
- Body: an H1 title, a tight summary, then the rationale/consequences. If any of
  the candidate slugs below are genuinely related, link them inline as [[slug]]
  (at least one if a real relation exists). Keep under ~60 lines.

SCHEMA (for the page conventions):
%(schema)s

CANDIDATE SLUGS you may link to (already in the wiki): %(cands)s

RAW SOURCE (%(raw_rel)s):
%(raw_text)s
"""


def compile_llm(raw_rel: str, raw_text: str, schema: str = "",
                candidates: list | None = None, page_type: str = "decision",
                model: str | None = None) -> dict:
    """Real synthesis backend: one `claude -p` call (uses your subscription).

    Returns {slug, type, text}. Same shape as compile_offline, so downstream
    (index/lint/graph) is identical. Raises llm.LLMError on failure.
    """
    from . import llm

    slug, created = slug_and_date(Path(raw_rel))
    created = created or date.today().isoformat()
    cand_slugs = ", ".join(c.get("slug", "") for c in (candidates or [])) or "(none)"
    prompt = _COMPILE_PROMPT % {
        "slug": slug, "ptype": page_type, "created": created,
        "today": date.today().isoformat(), "raw_rel": raw_rel,
        "schema": (schema or "").strip()[:4000], "cands": cand_slugs,
        "raw_text": raw_text.strip(),
    }
    out = llm.run_claude(prompt, model=model or llm.DEFAULT_MODEL)
    text = llm.strip_code_fence(out)
    meta, _, malformed = frontmatter.parse(text)
    if malformed or "id" not in meta or "sources" not in meta:
        raise llm.LLMError("model output is not a valid page (missing/!malformed "
                           "frontmatter). Got:\n%s" % text[:400])
    return {"slug": meta.get("id", slug), "type": meta.get("type", page_type), "text": text}
