"""memlib — deterministic core for the curated project memory.

Everything here runs with zero LLM tokens: frontmatter parsing, page
collection, BM25 search, the wikilink graph, and the on-disk index. The LLM
layer (compile / reconcile) lives outside this package and only ever receives
the small, pre-selected context that these functions compute.

Adapted from praneybehl/llm-wiki-plugin (MIT) — see NOTICE.
"""

__all__ = ["frontmatter", "pages", "bm25", "graph", "store"]
