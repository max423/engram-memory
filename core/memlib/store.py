"""store.py — layout and path resolution for a `.memory/` directory.

The whole memory is markdown in git; this module just centralizes the
conventional paths so every tool agrees on where things live.

    .memory/
      schema.md           # node/relation types (domain config)
      raw/                # curated immutable sources (one drop = one fact)
      wiki/
        decisions/  concepts/  entities/  synthesis/
      index.md            # content catalogue: page + 1-line summary (index-first)
      log.md              # append-only chronological log
      index/              # GENERATED, git-ignored:
        index.json        # frontmatter of every page (search without reading them)
        bm25.idx          # serialized BM25 index
        graph.json        # nodes + edges + backlinks
        sources.sha256    # raw-source content hashes (change detection)
"""

from __future__ import annotations

from pathlib import Path

MEMORY_DIRNAME = ".memory"

WIKI_SUBDIRS = ["decisions", "concepts", "entities", "synthesis"]

# Top-level files inside wiki/ that are catalogues, not pages.
NON_PAGE_FILES = {"schema.md", "index.md", "log.md", "README.md"}
NON_PAGE_DIRS = {"index"}


class MemoryPaths:
    """Resolved paths for a single `.memory/` root."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # --- containers ---
    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def wiki(self) -> Path:
        return self.root / "wiki"

    @property
    def index_dir(self) -> Path:
        return self.root / "index"

    # --- catalogue files ---
    @property
    def schema(self) -> Path:
        return self.root / "schema.md"

    @property
    def index_md(self) -> Path:
        return self.root / "index.md"

    @property
    def log(self) -> Path:
        return self.root / "log.md"

    # --- generated artifacts ---
    @property
    def index_json(self) -> Path:
        return self.index_dir / "index.json"

    @property
    def bm25_idx(self) -> Path:
        return self.index_dir / "bm25.idx"

    @property
    def graph_json(self) -> Path:
        return self.index_dir / "graph.json"

    @property
    def sources_sha(self) -> Path:
        return self.index_dir / "sources.sha256"

    def exists(self) -> bool:
        return self.wiki.exists()


def find_memory_root(start: Path | None = None) -> MemoryPaths | None:
    """Walk up from `start` (cwd by default) looking for a `.memory/` dir."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        mem = candidate / MEMORY_DIRNAME
        if mem.is_dir():
            return MemoryPaths(mem)
    return None


def resolve(memory_arg: Path | None) -> MemoryPaths:
    """Resolve an explicit --memory path, else auto-discover, else default."""
    if memory_arg is not None:
        return MemoryPaths(memory_arg)
    found = find_memory_root()
    if found is not None:
        return found
    return MemoryPaths(Path.cwd() / MEMORY_DIRNAME)
