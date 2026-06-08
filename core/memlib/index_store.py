"""index_store.py — persist and validate the generated index, for O(change) reads.

`mem index` writes index.json + bm25.idx + graph.json + manifest.json. The
manifest is a cheap signature of the wiki (one stat() per page: rel_path, mtime,
size — no content read). `load_valid` recomputes that signature and, if it
matches, loads the cached artifacts instead of walking + tokenizing the wiki.

Effect: when the wiki pages are unchanged (the common case at merge time, where
only `raw/` sources moved), `search` and `detect` cost a few small file reads +
N stat() calls — not O(total wiki content). When a page *did* change, the
signature differs and the caller rebuilds live.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .bm25 import BM25
from .store import NON_PAGE_DIRS, NON_PAGE_FILES, MemoryPaths

MANIFEST = "manifest.json"


def wiki_signature(wiki: Path) -> list:
    """Cheap fingerprint of the wiki: [[rel_path, mtime_ns, size], ...] sorted.

    Uses stat() only — no file is opened, so this stays cheap even at scale.
    """
    sig = []
    wiki = Path(wiki)
    if not wiki.exists():
        return sig
    for md in wiki.rglob("*.md"):
        rel = md.relative_to(wiki)
        if rel.parts[0] in NON_PAGE_FILES or rel.parts[0] in NON_PAGE_DIRS:
            continue
        if rel.name.startswith("."):
            continue
        st = md.stat()
        sig.append([str(rel), st.st_mtime_ns, st.st_size])
    sig.sort()
    return sig


def save_manifest(mem: MemoryPaths) -> None:
    mem.index_dir.mkdir(parents=True, exist_ok=True)
    (mem.index_dir / MANIFEST).write_text(
        json.dumps({"signature": wiki_signature(mem.wiki)}), encoding="utf-8")


def load_valid(mem: MemoryPaths) -> dict | None:
    """Return {records, bm25, graph} from disk iff the manifest still matches the
    wiki on disk; else None (caller should rebuild live)."""
    man = mem.index_dir / MANIFEST
    if not (man.exists() and mem.index_json.exists()
            and mem.bm25_idx.exists() and mem.graph_json.exists()):
        return None
    try:
        saved = json.loads(man.read_text(encoding="utf-8")).get("signature")
    except (ValueError, OSError):
        return None
    if saved != wiki_signature(mem.wiki):
        return None
    try:
        return {
            "records": json.loads(mem.index_json.read_text(encoding="utf-8")),
            "bm25": BM25.load(mem.bm25_idx),
            "graph": json.loads(mem.graph_json.read_text(encoding="utf-8")),
        }
    except (ValueError, OSError):
        return None
