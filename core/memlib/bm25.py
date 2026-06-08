"""bm25.py — pure-stdlib BM25 index, build / score / persist / load.

BM25 is the deterministic relevance signal: it lets the core decide *which*
pages are candidates for a change without an LLM and without embeddings (good
up to a few hundred pages, per the index-first playbook). The index can be
persisted to `index/bm25.idx` so reruns and the change-detector are token-zero.

Adapted from praneybehl/llm-wiki-plugin (MIT).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from .pages import tokenize

K1 = 1.5
B = 0.75


class BM25:
    def __init__(self, slugs: list[str], df: dict, doc_lens: list[int],
                 term_freqs: list, avgdl: float):
        self.slugs = slugs
        self.df = df                    # term -> document frequency
        self.doc_lens = doc_lens        # parallel to slugs
        self.term_freqs = term_freqs    # list of Counter/dict, parallel to slugs
        self.avgdl = avgdl
        self.N = len(slugs)

    @classmethod
    def build(cls, pages: list[dict]) -> "BM25":
        slugs, doc_lens, term_freqs = [], [], []
        df: Counter = Counter()
        for p in pages:
            if "read_error" in p:
                continue
            tokens = p["tokens"]
            slugs.append(p["slug"])
            doc_lens.append(len(tokens))
            tf = Counter(tokens)
            term_freqs.append(tf)
            for term in tf:
                df[term] += 1
        avgdl = (sum(doc_lens) / len(doc_lens)) if doc_lens else 0.0
        return cls(slugs, dict(df), doc_lens, term_freqs, avgdl)

    def _score_doc(self, query_tokens: list[str], i: int) -> float:
        score = 0.0
        tf = self.term_freqs[i]
        dl = self.doc_lens[i]
        for term in query_tokens:
            dft = self.df.get(term)
            if not dft:
                continue
            f = tf.get(term, 0)
            if not f:
                continue
            idf = math.log(1 + (self.N - dft + 0.5) / (dft + 0.5))
            denom = f + K1 * (1 - B + B * (dl / self.avgdl if self.avgdl else 1))
            score += idf * (f * (K1 + 1)) / denom
        return score

    def search(self, query: str, top: int = 10) -> list[tuple[str, float]]:
        """Return [(slug, score)] sorted desc, positive scores only."""
        q = tokenize(query)
        if not q:
            return []
        scored = [(self.slugs[i], self._score_doc(q, i)) for i in range(self.N)]
        scored = [(s, sc) for s, sc in scored if sc > 0]
        scored.sort(key=lambda x: -x[1])
        return scored[:top]

    # --- persistence ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "slugs": self.slugs,
            "df": self.df,
            "doc_lens": self.doc_lens,
            "term_freqs": [dict(tf) for tf in self.term_freqs],
            "avgdl": self.avgdl,
        }

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BM25":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        term_freqs = [Counter(tf) for tf in d["term_freqs"]]
        return cls(d["slugs"], d["df"], d["doc_lens"], term_freqs, d["avgdl"])
