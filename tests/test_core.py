#!/usr/bin/env python3
"""Test suite for the deterministic core. Stdlib unittest, zero dependencies.

Run:  python3 -m unittest discover -s tests
 or:  python3 tests/run.py
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "core"
sys.path.insert(0, str(CORE))

import change_detect  # noqa: E402
import mem as mem_cli  # noqa: E402
import reconcile  # noqa: E402
from memlib import bm25, compile as compile_mod, frontmatter, graph, pages  # noqa: E402
from memlib.store import MemoryPaths  # noqa: E402


def make_page(meta_extra=None, body="# T\n\nText.\n"):
    meta = {"id": "x", "type": "decision", "status": "active", "title": "T",
            "tags": ["a"], "sources": ["raw/x.md"], "created": "2026-01-01",
            "updated": "2026-01-01"}
    if meta_extra:
        meta.update(meta_extra)
    return frontmatter.with_frontmatter(meta, body)


class TestFrontmatter(unittest.TestCase):
    def test_inline_and_block_lists(self):
        text = make_page({"tags": ["x", "y"]})
        meta, body, malformed = frontmatter.parse(text)
        self.assertFalse(malformed)
        self.assertEqual(meta["tags"], ["x", "y"])
        self.assertEqual(meta["sources"], ["raw/x.md"])
        self.assertIn("Text.", body)

    def test_round_trip(self):
        meta = {"id": "a", "tags": ["one", "two"], "title": "Hello"}
        reparsed, _, _ = frontmatter.parse(frontmatter.dump(meta) + "\nbody\n")
        self.assertEqual(reparsed["tags"], ["one", "two"])
        self.assertEqual(reparsed["id"], "a")
        self.assertEqual(reparsed["title"], "Hello")

    def test_malformed_flag(self):
        _, _, malformed = frontmatter.parse("---\nnot closed\n")
        self.assertTrue(malformed)

    def test_no_frontmatter(self):
        meta, body, malformed = frontmatter.parse("# just a body\n")
        self.assertEqual(meta, {})
        self.assertFalse(malformed)


class TestPages(unittest.TestCase):
    def test_wikilinks_ignore_code(self):
        body = "Real [[alpha]] link.\n\n`code [[notalink]]`\n\n```\n[[alsonot]]\n```\n"
        self.assertEqual(pages.extract_wikilinks(body), ["alpha"])

    def test_tokenize_normalization(self):
        # IT/EN inflections unify (symmetric: docs and queries use this)
        self.assertEqual(pages.tokenize("fonti"), pages.tokenize("fonte"))
        self.assertEqual(pages.tokenize("decisioni"), ["decisione"])
        self.assertEqual(pages.tokenize("files"), pages.tokenize("file"))
        self.assertEqual(pages.tokenize("flags"), ["flag"])
        # stopwords + single chars dropped
        self.assertEqual(pages.tokenize("il the di of a e"), [])
        # short / technical words preserved (not over-stemmed)
        self.assertEqual(pages.tokenize("git repo class press"),
                         ["git", "repo", "class", "press"])

    def test_collect(self):
        with tempfile.TemporaryDirectory() as d:
            w = Path(d) / "wiki" / "decisions"
            w.mkdir(parents=True)
            (w / "a.md").write_text(make_page({"id": "a"}, "# A\n\nLink [[b]].\n"))
            (w / "b.md").write_text(make_page({"id": "b"}))
            ps = pages.collect_pages(Path(d) / "wiki")
            self.assertEqual({p["slug"] for p in ps}, {"a", "b"})
            a = pages.find_by_slug(ps, "a")
            self.assertEqual(a["links"], ["b"])


class TestBM25(unittest.TestCase):
    def _pages(self):
        return [
            {"slug": "git", "tokens": pages.tokenize("storage markdown git repo version")},
            {"slug": "bm25", "tokens": pages.tokenize("bm25 search lexical ranking tokens")},
        ]

    def test_ranking(self):
        idx = bm25.BM25.build(self._pages())
        hits = idx.search("git storage", top=2)
        self.assertEqual(hits[0][0], "git")
        self.assertGreater(hits[0][1], 0)

    def test_empty_query(self):
        self.assertEqual(bm25.BM25.build(self._pages()).search(""), [])

    def test_persist_round_trip(self):
        idx = bm25.BM25.build(self._pages())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bm25.idx"
            idx.save(p)
            loaded = bm25.BM25.load(p)
        self.assertEqual(loaded.search("bm25 search")[0][0], "bm25")


class TestGraph(unittest.TestCase):
    def test_backlinks_orphans_broken(self):
        ps = [
            {"slug": "a", "type": "decision", "title": "A", "links": ["b", "ghost"]},
            {"slug": "b", "type": "concept", "title": "B", "links": []},
        ]
        g = graph.build_graph(ps)
        self.assertEqual(g["backlinks"]["b"], ["a"])
        self.assertEqual(g["orphans"], ["a"])           # nothing links to a
        self.assertEqual(g["broken_links"], [{"from": "a", "to": "ghost"}])
        self.assertIn("b", graph.neighbors(g, "a"))


class TestCompile(unittest.TestCase):
    RAW = ("# Decisione: storage in git\n\nData: 2026-03-04\n\n"
           "Scelta: **markdown nel repo, niente database.**\n\n"
           "- pagine atomiche\n- diff piccoli\n")

    def test_slug_and_date(self):
        slug, created = compile_mod.slug_and_date(Path("2026-03-04-storage-in-git.md"))
        self.assertEqual(slug, "storage-in-git")
        self.assertEqual(created, "2026-03-04")

    def test_offline_produces_valid_page(self):
        page = compile_mod.compile_offline("raw/2026-03-04-storage-in-git.md", self.RAW)
        meta, body, malformed = frontmatter.parse(page["text"])
        self.assertFalse(malformed)
        self.assertEqual(meta["type"], "decision")
        self.assertEqual(meta["status"], "draft")
        self.assertEqual(meta["sources"], ["raw/2026-03-04-storage-in-git.md"])
        self.assertEqual(meta["created"], "2026-03-04")
        self.assertTrue(meta["tags"])
        # The summary is the explicit choice; no self-inflicted broken wikilink.
        self.assertIn("markdown nel repo", body)
        self.assertEqual(pages.extract_wikilinks(body), [])

    def test_llm_backend_parses_model_output(self):
        # Stub the model call — tests never hit the network / `claude`.
        from memlib import llm
        canned = ("---\nid: storage-in-git\ntype: decision\nstatus: active\n"
                  "title: Storage in git\ntags: [storage, git]\n"
                  "sources:\n  - raw/2026-03-04-storage-in-git.md\n"
                  "created: 2026-03-04\nupdated: 2026-03-04\n---\n"
                  "# Storage in git\n\nSintesi densa con [[altra-pagina]].\n")
        orig = llm.run_claude
        llm.run_claude = lambda *a, **k: canned
        try:
            page = compile_mod.compile_llm("raw/2026-03-04-storage-in-git.md",
                                           self.RAW, "schema", [{"slug": "altra-pagina"}])
        finally:
            llm.run_claude = orig
        self.assertEqual(page["slug"], "storage-in-git")
        meta, body, _ = frontmatter.parse(page["text"])
        self.assertEqual(meta["status"], "active")
        self.assertEqual(pages.extract_wikilinks(body), ["altra-pagina"])

    def test_llm_backend_rejects_garbage(self):
        from memlib import llm
        orig = llm.run_claude
        llm.run_claude = lambda *a, **k: "Sure! Here is your page: hello"
        try:
            with self.assertRaises(llm.LLMError):
                compile_mod.compile_llm("raw/x.md", "x", "", [])
        finally:
            llm.run_claude = orig


class TestChangeDetect(unittest.TestCase):
    def test_detect_new_changed_removed(self):
        snapshot = {"raw/a.md": "h1", "raw/b.md": "h2"}
        current = {"raw/a.md": "h1", "raw/b.md": "CHANGED", "raw/c.md": "h3"}
        changes = change_detect.detect_changes(current, snapshot, None)
        by = {c["source"]: c["status"] for c in changes}
        self.assertEqual(by, {"raw/b.md": "changed", "raw/c.md": "new"})

        snapshot2 = {"raw/a.md": "h1"}
        changes2 = change_detect.detect_changes({}, snapshot2, None)
        self.assertEqual(changes2[0]["status"], "removed")

    def test_sources_signal_wins(self):
        ps = [
            {"slug": "cited", "rel_path": "decisions/cited.md", "type": "decision",
             "title": "Cited", "tags": [], "sources": ["raw/s.md"],
             "links": [], "tokens": pages.tokenize("unrelated words here")},
            {"slug": "lexical", "rel_path": "decisions/lexical.md", "type": "decision",
             "title": "Lexical", "tags": [], "sources": [],
             "links": [], "tokens": pages.tokenize("storage git markdown repo")},
        ]
        idx = bm25.BM25.build(ps)
        g = graph.build_graph(ps)
        cands = change_detect.select_candidates(
            "raw/s.md", "storage git markdown repo", ps, idx, g, limit=8)
        self.assertEqual(cands[0]["slug"], "cited")
        self.assertIn("sources", cands[0]["reasons"])


class TestRanking(unittest.TestCase):
    def test_adamic_adar_prefers_rare_common_neighbours(self):
        from memlib import ranking
        # hub h links many; rare r links few. cand shares r with seed -> high AA.
        g = graph.build_graph([
            {"slug": "seed", "type": "decision", "title": "s", "links": ["h", "r"]},
            {"slug": "cand", "type": "decision", "title": "c", "links": ["h", "r"]},
            {"slug": "noise", "type": "decision", "title": "n", "links": ["h"]},
            {"slug": "h", "type": "concept", "title": "h", "links": []},
            {"slug": "r", "type": "concept", "title": "r", "links": []},
        ])
        scores = ranking.adamic_adar_scores(g, ["seed"])
        self.assertIn("cand", scores)
        # cand (shares rare r + hub h) scores higher than noise (shares only hub h)
        self.assertGreater(scores["cand"], scores.get("noise", 0))

    def test_source_overlap(self):
        from memlib import ranking
        pages = [
            {"slug": "seed", "sources": ["raw/a.md", "raw/shared.md"]},
            {"slug": "cand", "sources": ["raw/shared.md"]},
            {"slug": "other", "sources": ["raw/z.md"]},
        ]
        scores = ranking.source_overlap_scores(pages, ["seed"], exclude_source="raw/a.md")
        self.assertEqual(scores.get("cand"), 1)
        self.assertNotIn("other", scores)

    def test_select_candidates_uses_new_signals(self):
        # A page tied to the seed only via shared source + graph (no bm25 overlap)
        # still surfaces, tagged with the new reasons.
        pages = [
            {"slug": "cited", "rel_path": "decisions/cited.md", "type": "decision",
             "title": "Cited", "sources": ["raw/s.md", "raw/common.md"],
             "links": ["sibling"], "tokens": pages_tokens("alpha")},
            {"slug": "sibling", "rel_path": "decisions/sibling.md", "type": "decision",
             "title": "Sibling", "sources": ["raw/common.md"],
             "links": ["cited"], "tokens": pages_tokens("beta")},
            {"slug": "far", "rel_path": "decisions/far.md", "type": "decision",
             "title": "Far", "sources": ["raw/z.md"], "links": [],
             "tokens": pages_tokens("gamma")},
        ]
        idx = bm25.BM25.build(pages)
        g = graph.build_graph(pages)
        cands = change_detect.select_candidates("raw/s.md", "alpha", pages, idx, g, limit=8)
        slugs = [c["slug"] for c in cands]
        self.assertEqual(slugs[0], "cited")               # direct citation wins
        sibling = next(c for c in cands if c["slug"] == "sibling")
        self.assertTrue({"overlap", "graph"} & set(sibling["reasons"]))
        self.assertNotIn("far", slugs)                    # unrelated stays out


def pages_tokens(text):
    return pages.tokenize(text)


class TestReconcilePlumbing(unittest.TestCase):
    def _mem(self, d):
        m = MemoryPaths(Path(d) / ".memory")
        (m.wiki / "decisions").mkdir(parents=True)
        m.log.write_text("# log\n")
        return m

    def test_apply_patch_statuses(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "p.md"
            p.write_text("alpha beta gamma")
            self.assertEqual(reconcile.apply_patch(p, "beta", "BETA"), reconcile.APPLIED)
            self.assertEqual(p.read_text(), "alpha BETA gamma")
            self.assertEqual(reconcile.apply_patch(p, "nope", "x"), reconcile.NOT_FOUND)
            p.write_text("dup dup")
            self.assertEqual(reconcile.apply_patch(p, "dup", "x"), reconcile.AMBIGUOUS)

    def test_apply_patch_whitespace_tolerant(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "p.md"
            p.write_text("the quick\nbrown fox")
            # patch uses different whitespace than the file — still applies
            self.assertEqual(reconcile.apply_patch(p, "quick   brown", "Q B"),
                             reconcile.APPLIED)
            self.assertEqual(p.read_text(), "the Q B fox")

    def test_reconcile_apply_retries_until_match(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._mem(d)
            page = m.wiki / "decisions" / "a.md"
            page.write_text(make_page({"id": "a", "status": "active"},
                                      "# A\n\nold line here.\n"))
            ctx = {"source": "raw/x.md", "schema": "", "source_text": "new truth",
                   "candidate_pages": [{"slug": "a", "rel_path": "decisions/a.md",
                                        "text": page.read_text()}]}
            bad = lambda c, model=None: [{"slug": "a", "action": "update",
                                          "patches": [{"old": "DOES NOT EXIST", "new": "x"}]}]
            good = lambda c, f, model=None: [{"slug": "a", "action": "update",
                                              "patches": [{"old": "old line here.",
                                                           "new": "new line here."}]}]
            o1, o2 = reconcile.llm_reconcile, reconcile.llm_fix_patches
            reconcile.llm_reconcile, reconcile.llm_fix_patches = bad, good
            try:
                res = reconcile.reconcile_apply(m, ctx, max_retries=2)
            finally:
                reconcile.llm_reconcile, reconcile.llm_fix_patches = o1, o2
            self.assertTrue(res["applied"])
            self.assertEqual(res["retries"], 1)
            self.assertIn("new line here.", page.read_text())

    def test_patch_tolerates_llm_mangling(self):
        """Anchors that an LLM subtly rewrites still apply uniquely."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "p.md"
            base = 'Scelta: "markdown nel repo", niente database.'
            p.write_text("# A\n\n%s\n" % base)
            # smart quotes + extra spaces + en-dash instead of nothing: still matches
            mangled = 'Scelta:  “markdown   nel repo”,  niente database.'
            self.assertEqual(reconcile.apply_patch(p, mangled, "Scelta: solo git."),
                             reconcile.APPLIED)
            self.assertIn("Scelta: solo git.", p.read_text())

    def test_patch_dash_variants(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "p.md"
            p.write_text("limite - accettato")
            self.assertEqual(reconcile.apply_patch(p, "limite — accettato", "ok"),
                             reconcile.APPLIED)

    def test_reconcile_apply_converges_with_sloppy_model(self):
        """End-to-end: a model that returns a whitespace/quote-mangled anchor
        still lands on the FIRST attempt (no retry needed) thanks to tolerance."""
        with tempfile.TemporaryDirectory() as d:
            m = self._mem(d)
            page = m.wiki / "decisions" / "a.md"
            page.write_text(make_page({"id": "a", "status": "active"},
                                      '# A\n\nScelta: "file nel repo", versionati.\n'))
            ctx = {"source": "raw/x.md", "schema": "", "source_text": "new",
                   "candidate_pages": [{"slug": "a", "rel_path": "decisions/a.md",
                                        "text": page.read_text()}]}
            sloppy = lambda c, model=None: [{"slug": "a", "action": "update",
                "patches": [{"old": 'Scelta:  “file   nel repo”, versionati.',
                             "new": "Scelta: database condiviso."}]}]
            o1 = reconcile.llm_reconcile
            reconcile.llm_reconcile = sloppy
            try:
                res = reconcile.reconcile_apply(m, ctx, max_retries=2)
            finally:
                reconcile.llm_reconcile = o1
            self.assertTrue(res["applied"])
            self.assertEqual(res["retries"], 0)
            self.assertIn("Scelta: database condiviso.", page.read_text())

    def test_reconcile_apply_gives_up_gracefully(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._mem(d)
            page = m.wiki / "decisions" / "a.md"
            page.write_text(make_page({"id": "a"}, "# A\n\nbody.\n"))
            ctx = {"source": "raw/x.md", "schema": "", "source_text": "x",
                   "candidate_pages": [{"slug": "a", "rel_path": "decisions/a.md",
                                        "text": page.read_text()}]}
            always_bad = lambda *a, **k: [{"slug": "a", "action": "update",
                                           "patches": [{"old": "NOPE", "new": "y"}]}]
            o1, o2 = reconcile.llm_reconcile, reconcile.llm_fix_patches
            reconcile.llm_reconcile = lambda c, model=None: always_bad()
            reconcile.llm_fix_patches = lambda c, f, model=None: always_bad()
            try:
                res = reconcile.reconcile_apply(m, ctx, max_retries=2)
            finally:
                reconcile.llm_reconcile, reconcile.llm_fix_patches = o1, o2
            self.assertFalse(res["applied"])
            self.assertEqual(res["retries"], 2)
            self.assertEqual(res["failures"][0]["status"], reconcile.NOT_FOUND)

    def test_set_status_and_log(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._mem(d)
            page = m.wiki / "decisions" / "a.md"
            page.write_text(make_page({"id": "a", "status": "active"}))
            reconcile.set_status(page, "contradicted")
            meta, _, _ = frontmatter.parse(page.read_text())
            self.assertEqual(meta["status"], "contradicted")
            reconcile.append_log(m, "contradiction", "a", "because reasons")
            self.assertIn("## [", m.log.read_text())
            self.assertIn("contradiction | a", m.log.read_text())

    def test_estimate_tokens_bounded(self):
        ctx = {"schema": "x" * 400, "source_text": "y" * 400,
               "candidate_pages": [{"text": "z" * 400}]}
        self.assertEqual(reconcile.estimate_tokens(ctx), 300)  # 1200 chars / 4


class TestLLM(unittest.TestCase):
    def test_strip_code_fence(self):
        from memlib import llm
        self.assertEqual(llm.strip_code_fence("```json\n[1,2]\n```"), "[1,2]")
        self.assertEqual(llm.strip_code_fence("plain"), "plain")

    def test_extract_json_tolerant(self):
        from memlib import llm
        self.assertEqual(llm.extract_json('Here: [{"a":1}] done'), [{"a": 1}])
        self.assertEqual(llm.extract_json("```\n{\"x\":2}\n```"), {"x": 2})
        with self.assertRaises(llm.LLMError):
            llm.extract_json("no json at all")

    def test_parse_stream_json(self):
        from memlib import llm
        stream = "\n".join([
            '{"type":"system","subtype":"init"}',
            '{"type":"assistant","message":{"content":"thinking"}}',
            'not json — ignored',
            '{"type":"result","subtype":"success","result":"final answer",'
            '"total_cost_usd":0.01,"usage":{"input_tokens":10,"output_tokens":5}}',
        ])
        text, obj = llm.parse_stream_json(stream)
        self.assertEqual(text, "final answer")
        self.assertEqual(obj["total_cost_usd"], 0.01)

    def test_parse_stream_json_no_result(self):
        from memlib import llm
        text, obj = llm.parse_stream_json('{"type":"system"}\n')
        self.assertIsNone(text)
        self.assertEqual(llm._fallback_parse('{"result":"x"}'), "x")
        self.assertEqual(llm._fallback_parse("plain text"), "plain text")

    def test_run_claude_missing_binary(self):
        from memlib import llm
        orig = llm.claude_available
        llm.claude_available = lambda: False
        try:
            with self.assertRaises(llm.LLMError):
                llm.run_claude("hi")
        finally:
            llm.claude_available = orig

    def test_reconcile_parses_decisions(self):
        from memlib import llm
        ctx = {"schema": "s", "source": "raw/x.md", "source_text": "new truth",
               "candidate_pages": [{"slug": "p", "rel_path": "decisions/p.md",
                                    "text": "old body"}]}
        orig = llm.run_claude
        llm.run_claude = lambda *a, **k: '[{"slug":"p","action":"no-op"}]'
        try:
            decisions = reconcile.llm_reconcile(ctx)
        finally:
            llm.run_claude = orig
        self.assertEqual(decisions, [{"slug": "p", "action": "no-op"}])


class TestIndexCache(unittest.TestCase):
    def _build(self, d):
        mem = MemoryPaths(Path(d) / ".memory")
        (mem.wiki / "decisions").mkdir(parents=True)
        mem.raw.mkdir(parents=True)
        mem.index_dir.mkdir(parents=True)
        mem.log.write_text("# log\n")
        (mem.root / "raw" / "s1.md").write_text("Scelta: uno.\n")
        (mem.root / "raw" / "s2.md").write_text("Scelta: due.\n")
        (mem.wiki / "decisions" / "a.md").write_text(
            make_page({"id": "a", "sources": ["raw/s1.md"]}, "# A\n\nstorage git [[b]]\n"))
        (mem.wiki / "decisions" / "b.md").write_text(
            make_page({"id": "b", "sources": ["raw/s2.md"]}, "# B\n\nsearch bm25 [[a]]\n"))
        return mem

    def _index(self, mem):
        with contextlib.redirect_stdout(io.StringIO()):
            mem_cli.cmd_index(argparse.Namespace(memory=mem.root))

    def test_validity_and_invalidation(self):
        from memlib import index_store
        with tempfile.TemporaryDirectory() as d:
            mem = self._build(d)
            self.assertIsNone(index_store.load_valid(mem))     # no manifest yet
            self._index(mem)
            self.assertIsNotNone(index_store.load_valid(mem))  # fresh -> valid
            page = mem.wiki / "decisions" / "a.md"
            page.write_text(page.read_text() + "\nextra line\n")
            self.assertIsNone(index_store.load_valid(mem))      # wiki changed -> invalid

    def test_compute_plan_cache_equals_live(self):
        with tempfile.TemporaryDirectory() as d:
            mem = self._build(d)
            self._index(mem)
            snap = change_detect.current_source_hashes(mem.raw)
            mem.sources_sha.write_text(json.dumps(snap))
            # mutate a SOURCE only (wiki unchanged -> cache stays valid)
            (mem.root / "raw" / "s1.md").write_text("Scelta: uno modificato.\n")
            cached = change_detect.compute_plan(mem, None, 8, use_cache=True)
            live = change_detect.compute_plan(mem, None, 8, use_cache=False)
            self.assertEqual(cached, live)
            self.assertEqual(cached["items"][0]["source"], "raw/s1.md")


class TestMerge(unittest.TestCase):
    def test_no_conflict_passthrough(self):
        from memlib import merge
        self.assertFalse(merge.has_conflicts("a\nb\n"))
        out, n = merge.resolve("a\nb\n")
        self.assertEqual(n, 0)

    def test_union_dedup_by_slug(self):
        from memlib import merge
        text = ("## decisions\n"
                "<<<<<<< HEAD\n"
                "- [[a]] — ours.\n- [[b]] — only ours.\n"
                "=======\n"
                "- [[a]] — theirs (dup slug).\n- [[c]] — only theirs.\n"
                ">>>>>>> branch\n")
        self.assertTrue(merge.has_conflicts(text))
        out, n = merge.resolve(text, dedup="slug")
        self.assertEqual(n, 1)
        self.assertNotIn("<<<<<<<", out)
        # a appears once (deduped by slug), b and c both kept
        self.assertEqual(out.count("[[a]]"), 1)
        self.assertIn("[[b]]", out)
        self.assertIn("[[c]]", out)

    def test_diff3_base_ignored(self):
        from memlib import merge
        text = ("<<<<<<< HEAD\nX\n||||||| base\nORIG\n=======\nY\n>>>>>>> b\n")
        out, n = merge.resolve(text, dedup="line")
        self.assertEqual(n, 1)
        self.assertIn("X", out)
        self.assertIn("Y", out)
        self.assertNotIn("ORIG", out)   # base is dropped, not unioned

    def test_union_files_slug_dedup(self):
        from memlib import merge
        ours = "## decisions\n- [[a]] — ours.\n- [[b]] — only ours.\n"
        theirs = "## decisions\n- [[a]] — theirs (dup).\n- [[c]] — only theirs.\n"
        out = merge.union_files(ours, theirs, dedup="slug")
        self.assertEqual(out.count("[[a]]"), 1)   # same slug collapses
        self.assertIn("[[b]]", out)
        self.assertIn("[[c]]", out)
        self.assertEqual(out.count("## decisions"), 1)  # header deduped
        self.assertTrue(out.endswith("\n"))

    def test_union_files_line_dedup_log(self):
        from memlib import merge
        ours = "## [2026-01-01] add | A\nbody A\n"
        theirs = "## [2026-01-02] add | B\nbody B\n"
        out = merge.union_files(ours, theirs, dedup="line")
        self.assertIn("add | A", out)
        self.assertIn("add | B", out)


class TestCliEndToEnd(unittest.TestCase):
    def _run(self, *args, cwd):
        return subprocess.run([sys.executable, str(CORE / "mem.py"), *args],
                              cwd=cwd, capture_output=True, text=True)

    def test_init_ingest_lint(self):
        with tempfile.TemporaryDirectory() as d:
            self._run("init", ".", cwd=d)
            raw = Path(d) / ".memory" / "raw" / "2026-04-01-cache-redis.md"
            raw.write_text("# Decisione: cache con Redis\n\n"
                           "Scelta: **usare Redis come cache condivisa.**\n\n"
                           "- bassa latenza\n- TTL nativo\n")
            r = self._run("ingest", "--memory", ".memory", cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            page = Path(d) / ".memory" / "wiki" / "decisions" / "cache-redis.md"
            self.assertTrue(page.exists())
            meta, _, _ = frontmatter.parse(page.read_text())
            self.assertEqual(meta["sources"], ["raw/2026-04-01-cache-redis.md"])
            # detect is now clean (snapshot updated by ingest)
            r2 = self._run("detect", "--memory", ".memory", cwd=d)
            self.assertIn("Nothing to reconcile", r2.stdout)
            # index.json exists and has the page
            idx = json.loads((Path(d) / ".memory" / "index" / "index.json").read_text())
            self.assertEqual(idx[0]["slug"], "cache-redis")

    def test_init_template_research(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run("init", ".", "--template", "research", cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            schema = (Path(d) / ".memory" / "schema.md").read_text()
            self.assertIn("research", schema.lower())
            self.assertIn("paper", schema.lower())   # research-specific entity

    def test_review_surfaces_items(self):
        with tempfile.TemporaryDirectory() as d:
            self._run("init", ".", cwd=d)
            wiki = Path(d) / ".memory" / "wiki" / "decisions"
            # a contradicted page (cites a real source) + a page missing sources
            (Path(d) / ".memory" / "raw" / "s.md").write_text("x")
            (wiki / "c.md").write_text(
                "---\nid: c\ntype: decision\nstatus: contradicted\ntitle: Cache scelta\n"
                "tags: [cache]\nsources:\n  - raw/s.md\ncreated: 2026-01-01\n"
                "updated: 2026-01-01\n---\n# Cache\nbody\n")
            (wiki / "b.md").write_text(
                "---\nid: b\ntype: decision\nstatus: active\ntitle: Bad\n"
                "tags: [x]\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n# Bad\nbody\n")
            r = self._run("review", "--memory", ".memory", "--json", cwd=d)
            items = json.loads(r.stdout)
            kinds = {i["kind"] for i in items}
            self.assertIn("contradicted", kinds)
            self.assertIn("missing-source", kinds)
            contradicted = next(i for i in items if i["kind"] == "contradicted")
            self.assertEqual(contradicted["slug"], "c")
            self.assertTrue(contradicted["do"])     # has a suggested command
            self.assertTrue(contradicted["query"])  # has a pre-generated search

    def test_review_empty_on_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            self._run("init", ".", cwd=d)
            r = self._run("review", "--memory", ".memory", cwd=d)
            self.assertIn("empty", r.stdout.lower())

    def test_add_synthesis_grounds_in_linked_sources(self):
        with tempfile.TemporaryDirectory() as d:
            self._run("init", ".", cwd=d)
            raw = Path(d) / ".memory" / "raw"
            (raw / "2026-01-01-alpha.md").write_text("# A\n\nScelta: **alpha.**\n")
            (raw / "2026-01-02-beta.md").write_text("# B\n\nScelta: **beta.**\n")
            self._run("ingest", "--memory", ".memory", cwd=d)
            r = self._run("add-synthesis", "--memory", ".memory",
                          "--title", "Alpha vs Beta", "--links", "alpha,beta",
                          "--body", "Confronto tra [[alpha]] e [[beta]].", cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            page = Path(d) / ".memory" / "wiki" / "synthesis" / "alpha-vs-beta.md"
            self.assertTrue(page.exists())
            meta, _, _ = frontmatter.parse(page.read_text())
            self.assertEqual(meta["type"], "synthesis")
            # grounded in the union of the linked pages' raw sources
            self.assertIn("raw/2026-01-01-alpha.md", meta["sources"])
            self.assertIn("raw/2026-01-02-beta.md", meta["sources"])
            # the memory stays lint-clean after filing the answer
            self.assertEqual(self._run("lint", "--memory", ".memory", cwd=d).returncode, 0)

    def test_lint_catches_bad_page(self):
        with tempfile.TemporaryDirectory() as d:
            self._run("init", ".", cwd=d)
            bad = Path(d) / ".memory" / "wiki" / "decisions" / "bad.md"
            bad.write_text("---\nid: bad\ntype: nope\nstatus: active\n---\n# Bad\n[[ghost]]\n")
            r = self._run("lint", "--memory", ".memory", cwd=d)
            self.assertEqual(r.returncode, 1)
            self.assertIn("no source", r.stdout)
            self.assertIn("Invalid type", r.stdout)


class TestPlugin(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent / "plugin"

    def test_manifest_valid(self):
        manifest = json.loads((self.ROOT / ".claude-plugin" / "plugin.json").read_text())
        for key in ("name", "version", "description", "commands"):
            self.assertIn(key, manifest)
        self.assertEqual(manifest["commands"], "./commands")

    def test_commands_present_and_wired(self):
        from memlib import frontmatter
        for name in ("ingest", "query", "lint"):
            path = self.ROOT / "commands" / "mem" / ("%s.md" % name)
            self.assertTrue(path.exists(), "missing command: %s" % name)
            text = path.read_text(encoding="utf-8")
            meta, body, malformed = frontmatter.parse(text)
            self.assertFalse(malformed, "%s: malformed frontmatter" % name)
            self.assertTrue(meta.get("description"), "%s: no description" % name)
            # commands drive the installed CLI, not the source-tree path
            self.assertIn("mem ", body, "%s: doesn't invoke the mem CLI" % name)
            self.assertNotIn("python3 core/mem.py search", body)  # old hardcoded path


class TestMergeHook(unittest.TestCase):
    """End-to-end: a real `git merge` fires post-merge, which ingests the new
    source (offline) and auto-commits the memory. No LLM involved."""

    def _mem(self, *args, cwd, env):
        return subprocess.run([sys.executable, str(CORE / "mem.py"), *args],
                              cwd=cwd, capture_output=True, text=True, env=env)

    def test_post_merge_ingests_and_autocommits(self):
        if shutil.which("git") is None:
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            env = {**os.environ,
                   "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                   "MEM_BACKEND": "offline", "MEM_AUTORECONCILE": "1",
                   "MEM_CANONICAL_BRANCH": "main"}

            def git(*a):
                return subprocess.run(["git", "-C", str(d), *a],
                                      capture_output=True, text=True, env=env)

            subprocess.run(["git", "init", str(d)], capture_output=True, env=env)
            git("checkout", "-b", "main")
            self._mem("init", ".", cwd=str(d), env=env)
            git("add", "-A")
            git("commit", "-m", "init memory")
            # install the hook (bakes the absolute CLI path into .git/hooks)
            r = self._mem("install-hooks", str(d), cwd=str(d), env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((d / ".git" / "hooks" / "post-merge").exists())

            # a feature branch contributes a new curated source
            git("checkout", "-b", "feature")
            (d / ".memory" / "raw" / "2026-07-01-cdn-asset.md").write_text(
                "# Decisione: CDN per gli asset\n\n"
                "Scelta: **usare una CDN per gli asset statici.**\n")
            git("add", "-A")
            git("commit", "-m", "add source")

            # merge into main (no-ff so the hook fires and there's a merge commit)
            git("checkout", "main")
            m = git("merge", "--no-ff", "-m", "merge feature", "feature")
            self.assertEqual(m.returncode, 0, m.stderr)

            # the hook compiled the source into a page (slug from the filename)...
            page = d / ".memory" / "wiki" / "decisions" / "cdn-asset.md"
            self.assertTrue(page.exists(),
                            "hook didn't compile the source.\n%s\n%s" % (m.stdout, m.stderr))
            # ...and auto-committed the memory update
            log = git("log", "--oneline").stdout
            self.assertIn("memory: reconcile after merge", log)
            # working tree is clean (everything committed)
            self.assertEqual(git("status", "--porcelain").stdout.strip(), "")


class TestRelink(unittest.TestCase):
    """Deterministic auto-linking: orphans → connected graph, no fabricated links."""

    def _page(self, slug, title, text, sources=None):
        return {"slug": slug, "title": title, "text": text,
                "tokens": pages.tokenize(title + " " + text),
                "sources": sources or ["raw/%s.md" % slug], "links": []}

    def test_symmetric_and_no_self_link(self):
        from memlib import relink
        ps = [
            self._page("postgres", "PostgreSQL database", "relational sql database postgres"),
            self._page("mysql", "MySQL database", "relational sql database mysql"),
            self._page("react", "React UI", "frontend javascript ui component react"),
        ]
        rel = relink.compute_related(ps, top_k=2)
        # postgres <-> mysql are mutual (symmetric closure); never links to self
        self.assertIn("mysql", rel["postgres"])
        self.assertIn("postgres", rel["mysql"])
        self.assertNotIn("postgres", rel.get("postgres", []))

    def test_no_fabricated_link_for_isolated_page(self):
        from memlib import relink
        ps = [
            self._page("a", "Alpha topic", "alpha alpha distinct vocabulary one"),
            self._page("b", "Beta topic", "beta beta separate vocabulary two"),
            self._page("iso", "Zeta", "zzz qqq xxx wholly unrelated terms"),
        ]
        rel = relink.compute_related(ps, top_k=2)
        # 'iso' shares no terms with a/b → no link invented for it
        self.assertEqual(rel.get("iso", []), [])

    def test_upsert_idempotent(self):
        from memlib import relink
        page = make_page(body="# T\n\nBody.\n")
        once = relink.upsert_section(page, ["foo", "bar"])
        twice = relink.upsert_section(once, ["foo", "bar"])
        self.assertEqual(once, twice)
        self.assertEqual(once.count(relink.START), 1)
        self.assertIn("[[foo]]", once)

    def test_upsert_replaces_not_appends(self):
        from memlib import relink
        page = make_page(body="# T\n\nBody.\n")
        v1 = relink.upsert_section(page, ["foo"])
        v2 = relink.upsert_section(v1, ["baz"])
        self.assertIn("[[baz]]", v2)
        self.assertNotIn("[[foo]]", v2)
        self.assertEqual(v2.count("## Correlate"), 1)

    def test_relink_clears_orphans_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mem_cli.cmd_init(argparse.Namespace(root=str(d), template="software"))
            dec = d / ".memory" / "wiki" / "decisions"
            for slug, kw in [("postgres", "relational sql database"),
                             ("mysql", "relational sql database"),
                             ("redis", "in memory key value cache store")]:
                (dec / (slug + ".md")).write_text(
                    make_page({"id": slug, "title": slug},
                              "# %s\n\n%s technology choice.\n" % (slug, kw)),
                    encoding="utf-8")
            g0 = graph.build_graph(pages.collect_pages(d / ".memory" / "wiki"))
            self.assertGreaterEqual(len(g0["orphans"]), 3)
            from memlib.store import resolve as resolve_mem
            mem_cli._relink_wiki(resolve_mem(d / ".memory"), top_k=2)
            g1 = graph.build_graph(pages.collect_pages(d / ".memory" / "wiki"))
            self.assertLess(len(g1["orphans"]), len(g0["orphans"]))
            self.assertEqual(g1["broken_links"], [])


class TestAliases(unittest.TestCase):
    """`aliases:` are indexed so a query with words NOT in the body still matches."""

    def test_aliases_feed_tokens(self):
        page = make_page({"aliases": ["zzqqmarker synonym"]},
                         body="# Monorepo\n\nWe keep all code together.\n")
        with tempfile.TemporaryDirectory() as d:
            wiki = Path(d) / "decisions"
            wiki.mkdir(parents=True)
            (wiki / "monorepo.md").write_text(page, encoding="utf-8")
            rec = pages.collect_pages(Path(d))[0]
            self.assertEqual(rec["aliases"], ["zzqqmarker synonym"])
            # the alias word is NOT in the body but IS indexed in tokens
            self.assertNotIn("zzqqmarker", rec["body"].lower())
            self.assertIn("zzqqmarker", rec["tokens"])

    def test_alias_makes_page_findable(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mem_cli.cmd_init(argparse.Namespace(root=str(d), template="software"))
            dec = d / ".memory" / "wiki" / "decisions"
            (dec / "monorepo.md").write_text(
                make_page({"id": "monorepo", "title": "Monorepo"},
                          "# Monorepo\n\nAll code in one tree.\n"), encoding="utf-8")
            from memlib.store import resolve as rmem
            mem = rmem(d / ".memory")
            ps = pages.collect_pages(mem.wiki)
            bm0 = bm25.BM25.build(ps)
            self.assertEqual(bm0.search("single repository"), [])  # no match yet
            mem_cli.cmd_alias(argparse.Namespace(
                memory=d / ".memory", slug="monorepo",
                aliases=["single repository"], remove=False, replace=False))
            ps2 = pages.collect_pages(mem.wiki)
            bm1 = bm25.BM25.build(ps2)
            self.assertEqual(bm1.search("single repository")[0][0], "monorepo")


class TestHubs(unittest.TestCase):
    """Disambiguation hubs: cluster by shared term, drop boilerplate, link members."""

    def _p(self, slug, title, sources=None):
        return {"slug": slug, "title": title, "tags": [],
                "sources": sources or ["raw/%s.md" % slug],
                "type": "decision", "tokens": [], "links": []}

    def test_detect_cluster_and_drop_boilerplate(self):
        from memlib import hubs
        # 8 pages: 3 about databases, all titled "ADR: ..." (boilerplate).
        ps = [
            self._p("postgresql-database", "ADR: PostgreSQL database"),
            self._p("mysql-database", "ADR: MySQL database"),
            self._p("choosing-a-database", "ADR: choosing a database"),
            self._p("react-ui", "ADR: React interface"),
            self._p("vue-ui", "ADR: Vue interface"),
            self._p("go-lang", "ADR: Go language"),
            self._p("python-lang", "ADR: Python language"),
            self._p("css-styling", "ADR: CSS styling"),
        ]
        clusters = dict(hubs.detect_clusters(ps, min_size=3))
        # 'database' clusters its three; 'adr' is in ALL 8 titles -> boilerplate dropped
        self.assertIn("database", clusters)
        self.assertEqual(len(clusters["database"]), 3)
        self.assertNotIn("adr", clusters)

    def test_label_is_readable_surface_form(self):
        from memlib import hubs
        ps = [self._p("go-programming-language", "Go programming language"),
              self._p("rust-programming-language", "Rust programming language"),
              self._p("java-programming-language", "Java programming language")]
        clusters = dict(hubs.detect_clusters(ps, min_size=3))
        # stemmed key would be "programm"; label restores "programming"
        self.assertIn("programming", clusters)

    def test_hub_page_anchored_to_member_sources(self):
        from memlib import hubs
        ps = [self._p("a-db", "ADR a database", ["raw/a.md"]),
              self._p("b-db", "ADR b database", ["raw/b.md"]),
              self._p("c-db", "ADR c database", ["raw/c.md"])]
        hub = hubs.build_hub_page("database", ["a-db", "b-db", "c-db"], ps)
        meta, body, _ = frontmatter.parse(hub["text"])
        self.assertEqual(meta["type"], "concept")
        self.assertIn("hub", meta["tags"])
        self.assertEqual(set(meta["sources"]), {"raw/a.md", "raw/b.md", "raw/c.md"})
        for m in ["a-db", "b-db", "c-db"]:
            self.assertIn("[[%s]]" % m, body)


class TestMergeDriver(unittest.TestCase):
    """`mem merge-driver` wired via install-hooks: a real `git merge` unions the
    catalogue automatically and flags a conflicting prose page for review."""

    def _setup(self, d, env, git):
        subprocess.run(["git", "init", str(d)], capture_output=True, env=env)
        git("checkout", "-b", "main")
        subprocess.run([sys.executable, str(CORE / "mem.py"), "init", "."],
                       cwd=str(d), capture_output=True, text=True, env=env)
        r = subprocess.run([sys.executable, str(CORE / "mem.py"),
                            "install-hooks", str(d)],
                           cwd=str(d), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("merge=engram",
                      (d / ".memory" / ".gitattributes").read_text(encoding="utf-8"))
        git("add", "-A"); git("commit", "-m", "baseline")

    def test_catalogue_unions_and_page_conflicts_flagged(self):
        if shutil.which("git") is None:
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            env = {**os.environ,
                   "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                   "MEM_AUTORECONCILE": "0", "MEM_CANONICAL_BRANCH": "main"}

            def git(*a):
                return subprocess.run(["git", "-C", str(d), *a],
                                      capture_output=True, text=True, env=env)

            self._setup(d, env, git)
            idx = d / ".memory" / "index.md"

            # Branch A and B append different catalogue entries at the same tail.
            git("checkout", "-b", "featA")
            idx.write_text(idx.read_text() + "- [[decision-a]] — A\n", encoding="utf-8")
            git("commit", "-am", "A entry")
            git("checkout", "main"); git("checkout", "-b", "featB")
            idx.write_text(idx.read_text() + "- [[decision-b]] — B\n", encoding="utf-8")
            git("commit", "-am", "B entry")

            m = git("merge", "featA", "-m", "merge A")
            self.assertEqual(m.returncode, 0, m.stderr + m.stdout)  # driver resolved
            body = idx.read_text(encoding="utf-8")
            self.assertNotIn("<<<<<<<", body)
            self.assertIn("[[decision-a]]", body)
            self.assertIn("[[decision-b]]", body)

            # A prose page edited differently on two branches → conflict + markers.
            page = d / ".memory" / "wiki" / "decisions" / "db.md"
            git("checkout", "main"); git("checkout", "-b", "pageA")
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text("title: X\n\nPostgres.\n", encoding="utf-8")
            git("add", "-A"); git("commit", "-m", "pageA")
            git("checkout", "main"); git("checkout", "-b", "pageB")
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text("title: X\n\nMySQL.\n", encoding="utf-8")
            git("add", "-A"); git("commit", "-m", "pageB")

            m2 = git("merge", "pageA", "-m", "merge pages")
            self.assertNotEqual(m2.returncode, 0)  # left for human/LLM resolve
            self.assertIn("<<<<<<<", page.read_text(encoding="utf-8"))
            self.assertIn("AA", git("status", "--porcelain").stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
