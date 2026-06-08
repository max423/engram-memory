"""frontmatter.py — minimal YAML-ish frontmatter parse + serialize.

Deliberately a tiny subset of YAML (scalars, inline lists, block lists) so the
core stays stdlib-only. It is the one fragile piece inherited from the fork, so
it is kept small, explicit, and round-trippable: `dump(parse(x)) == x` for the
shapes we actually emit. Surgical patches in reconcile go through `replace`.
"""

from __future__ import annotations

import re

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.*)$")


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse(text: str) -> tuple[dict, str, bool]:
    """Return (metadata, body, malformed).

    malformed=True means a frontmatter block was opened (`---`) but could not be
    closed/parsed — a real lint signal, distinct from a page with no frontmatter.
    """
    if not text.startswith("---"):
        return {}, text, False
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text, True
    fm_text = m.group(1)
    body = text[m.end():]
    meta: dict = {}
    current_key = None
    for line in fm_text.split("\n"):
        if not line.strip():
            continue
        kv = _KV_RE.match(line)
        item = _LIST_ITEM_RE.match(line)
        if kv and not line.startswith(" "):
            key, value = kv.group(1), kv.group(2).strip()
            current_key = None
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1]
                meta[key] = [_strip_quotes(x) for x in inner.split(",") if x.strip()]
            elif value:
                meta[key] = _strip_quotes(value)
            else:
                meta[key] = []
                current_key = key
        elif item and current_key is not None:
            meta[current_key].append(_strip_quotes(item.group(1)))
    return meta, body, False


def _needs_quote(s: str) -> bool:
    return bool(re.search(r"[:#\[\]{}]|^\s|\s$", s))


def _fmt_scalar(v) -> str:
    s = str(v)
    return '"%s"' % s if _needs_quote(s) else s


def dump(meta: dict) -> str:
    """Serialize metadata back to a frontmatter block (block lists for arrays)."""
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, (list, tuple)):
            if not value:
                lines.append("%s: []" % key)
            else:
                lines.append("%s:" % key)
                for item in value:
                    lines.append("  - %s" % _fmt_scalar(item))
        else:
            lines.append("%s: %s" % (key, _fmt_scalar(value)))
    lines.append("---")
    return "\n".join(lines) + "\n"


def split(text: str) -> tuple[dict, str]:
    """Convenience: (meta, body) ignoring the malformed flag."""
    meta, body, _ = parse(text)
    return meta, body


def with_frontmatter(meta: dict, body: str) -> str:
    """Reassemble a full page from metadata + body."""
    body = body.lstrip("\n")
    return dump(meta) + "\n" + body
