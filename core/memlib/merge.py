"""merge.py — deterministic resolution of git conflict markers in memory files.

Atomic wiki pages and the append-only log avoid most merge conflicts, but
`index.md` (the catalogue) is edited in the middle on every ingest, so two
branches can collide there. This resolves such conflicts WITHOUT an LLM by
*unioning* the two sides: keep every line from both, deduplicated. For the
catalogue we dedup by the page slug (`[[slug]]`), so the same page added on both
branches collapses to one entry; elsewhere we dedup by the whole line.

Handles both 2-way (`<<<<<<< ======= >>>>>>>`) and diff3 (`|||||||` base) markers.
Pages with real prose conflicts are out of scope here — those go through the LLM
reconcile path; this helper is for the catalogue/log case it was built for.
"""

from __future__ import annotations

import re

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_OURS = "<<<<<<<"
_BASE = "|||||||"
_SEP = "======="
_THEIRS = ">>>>>>>"


def has_conflicts(text: str) -> bool:
    return text.startswith(_OURS) or ("\n" + _OURS) in text


def parse_conflicts(text: str) -> list:
    """Split into segments: ('text', str) or ('conflict', [ours], [theirs])."""
    segments, buf = [], []
    lines = text.split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.startswith(_OURS):
            if buf:
                segments.append(("text", buf))
                buf = []
            ours, theirs = [], []
            i += 1
            while i < n and not lines[i].startswith((_SEP, _BASE)):
                ours.append(lines[i]); i += 1
            if i < n and lines[i].startswith(_BASE):       # skip diff3 base
                i += 1
                while i < n and not lines[i].startswith(_SEP):
                    i += 1
            if i < n and lines[i].startswith(_SEP):
                i += 1
            while i < n and not lines[i].startswith(_THEIRS):
                theirs.append(lines[i]); i += 1
            if i < n and lines[i].startswith(_THEIRS):
                i += 1
            segments.append(("conflict", ours, theirs))
        else:
            buf.append(line); i += 1
    if buf:
        segments.append(("text", buf))
    return segments


def _key(line: str, dedup: str) -> str:
    if dedup == "slug":
        m = WIKILINK_RE.search(line)
        if m:
            return "slug:" + m.group(1).strip()
    return line.strip()


def _union(ours: list, theirs: list, dedup: str) -> list:
    out, seen = [], set()
    for line in [*ours, *theirs]:
        if not line.strip():
            # keep at most one blank separator
            if out and not out[-1].strip():
                continue
            out.append(line); continue
        k = _key(line, dedup)
        if k in seen:
            continue
        seen.add(k); out.append(line)
    return out


def resolve(text: str, dedup: str = "line") -> tuple[str, int]:
    """Return (resolved_text, n_hunks_resolved)."""
    segments = parse_conflicts(text)
    n_hunks = sum(1 for s in segments if s[0] == "conflict")
    out_lines = []
    for seg in segments:
        if seg[0] == "text":
            out_lines.extend(seg[1])
        else:
            out_lines.extend(_union(seg[1], seg[2], dedup))
    return "\n".join(out_lines), n_hunks


def union_files(ours: str, theirs: str, dedup: str = "line") -> str:
    """3-way union of two whole files (no conflict markers), deduped by `dedup`.

    Used by the git merge *driver* for the catalogue/log: git hands us `ours`
    (%A) and `theirs` (%B) as full files; we keep every line from both, dropping
    duplicates (by slug for the catalogue, by whole line for the log). Order is
    preserved: all of `ours`, then the lines `theirs` adds. This never produces a
    conflict — append-only/atomic structure makes union the correct semantics.
    """
    trailing_nl = ours.endswith("\n") or theirs.endswith("\n")
    merged = _union(ours.split("\n"), theirs.split("\n"), dedup)
    out = "\n".join(merged)
    if trailing_nl and not out.endswith("\n"):
        out += "\n"
    return out
