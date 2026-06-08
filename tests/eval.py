#!/usr/bin/env python3
"""eval.py — does the memory actually WORK (not just run)?

Three measurable checks, plus one opt-in LLM judge. Exits non-zero if any
deterministic check is below threshold, so it doubles as a CI gate.

  1. RETRIEVAL  — labeled (question -> expected page). Measures recall@1,
     recall@3 and MRR. This is "does a query find the RIGHT memory?".
  2. HEALTH     — structural acceptance: lint clean, 0 orphans, every page cites
     an existing source, every wikilink resolves.
  3. ANTI-DRIFT — mutate one source on a throwaway copy; assert change-detect
     flags it and ranks the SOURCED page #1 (the change hits the right page).
  4. FAITHFULNESS (opt-in, --judge) — for each page, ask the model whether every
     claim is supported by its source. Needs a real terminal (`claude -p`).

Run:  python3 tests/eval.py            # deterministic checks 1-3
      python3 tests/eval.py --judge    # + LLM faithfulness (from a real shell)
      python3 tests/eval.py --memory /path/.memory --labels mylabels.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "core"
sys.path.insert(0, str(CORE))

import change_detect  # noqa: E402
from memlib import bm25, graph, pages  # noqa: E402
from memlib.store import MemoryPaths, resolve  # noqa: E402
import mem as mem_cli  # noqa: E402

DEFAULT_MEMORY = Path(__file__).resolve().parent.parent / ".memory"

# Labeled retrieval set for the shipped sample. Questions are PARAPHRASES, not
# keyword echoes — a real test of retrieval, not of copy-matching.
SAMPLE_LABELS = [
    ["dove vivono i dati: database o file versionati?", "storage-git-native"],
    ["perché non usiamo un database?", "storage-git-native"],
    ["come troviamo le pagine rilevanti senza embedding?", "ricerca-bm25"],
    ["motore di ricerca lessicale a costo zero", "ricerca-bm25"],
    ["quando si aggiorna la memoria, a ogni commit di ogni branch?", "reconcile-al-merge"],
    ["le due fasi dell'aggiornamento al merge", "reconcile-al-merge"],
    ["come evitiamo che il wiki amplifichi i propri errori?", "anti-drift"],
    ["perché ogni pagina deve citare la fonte grezza?", "anti-drift"],
    ["come gestiamo i toggle delle funzionalità?", "feature-flags-yaml"],
    ["attivare e disattivare una feature senza deploy", "feature-flags-yaml"],
]

THRESHOLDS = {"recall@1": 0.70, "recall@3": 0.90, "mrr": 0.80,
              "orphans": 0, "uncited": 0, "broken": 0, "lint_hard": 0}


def bar(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


# 1. RETRIEVAL ---------------------------------------------------------------
def eval_retrieval(mem: MemoryPaths, labels: list) -> dict:
    ps = [p for p in pages.collect_pages(mem.wiki) if "read_error" not in p]
    idx = bm25.BM25.build(ps)
    r1 = r3 = mrr = 0.0
    rows = []
    for q, expected in labels:
        hits = [s for s, _ in idx.search(q, top=5)]
        rank = (hits.index(expected) + 1) if expected in hits else 0
        r1 += 1 if rank == 1 else 0
        r3 += 1 if 0 < rank <= 3 else 0
        mrr += (1.0 / rank) if rank else 0.0
        rows.append((q, expected, hits[:3], rank))
    n = len(labels) or 1
    return {"recall@1": r1 / n, "recall@3": r3 / n, "mrr": mrr / n, "rows": rows, "n": n}


# 2. HEALTH ------------------------------------------------------------------
def eval_health(mem: MemoryPaths) -> dict:
    ps = [p for p in pages.collect_pages(mem.wiki) if "read_error" not in p]
    g = graph.build_graph(ps)
    uncited = [p["slug"] for p in ps if not p.get("sources")]
    dangling = []
    for p in ps:
        for s in p.get("sources", []):
            if not (mem.root / s).exists():
                dangling.append((p["slug"], s))
    findings = mem_cli.run_lint(mem, 400, 800)
    lint_hard = sum(findings["summary"].get(k, 0) for k in
                    ("missing_sources", "dangling_sources", "malformed_frontmatter",
                     "broken_links", "duplicate_slugs", "oversized_hard",
                     "invalid_type", "invalid_status"))
    return {"pages": len(ps), "orphans": len(g["orphans"]),
            "orphan_slugs": g["orphans"], "broken": len(g["broken_links"]),
            "uncited": len(uncited) + len(dangling), "lint_hard": lint_hard}


# 3. ANTI-DRIFT --------------------------------------------------------------
def eval_antidrift(mem: MemoryPaths) -> dict:
    """On a throwaway copy: snapshot, mutate one source, assert it's detected and
    the page that CITES it is ranked #1 candidate."""
    ps = [p for p in pages.collect_pages(mem.wiki) if p.get("sources")]
    if not ps:
        return {"ok": False, "reason": "no sourced pages"}
    # Prefer a source cited by exactly ONE page, so the expected #1 is unambiguous.
    cite_count: dict = {}
    for p in ps:
        for s in p["sources"]:
            cite_count[s] = cite_count.get(s, 0) + 1
    target_page, target_source = ps[0], ps[0]["sources"][0]
    for p in ps:
        uniq = next((s for s in p["sources"] if cite_count[s] == 1), None)
        if uniq:
            target_page, target_source = p, uniq
            break
    with tempfile.TemporaryDirectory() as d:
        dst = Path(d) / ".memory"
        shutil.copytree(mem.root, dst)
        m2 = MemoryPaths(dst)
        # snapshot current state as "processed"
        snap = change_detect.current_source_hashes(m2.raw)
        m2.index_dir.mkdir(parents=True, exist_ok=True)
        m2.sources_sha.write_text(json.dumps(snap))
        # mutate the one source
        src_path = m2.root / target_source
        src_path.write_text(src_path.read_text() + "\n\nAggiornamento: dettaglio nuovo.\n")
        plan = change_detect.compute_plan(m2, None, 8)
        detected = [it["source"] for it in plan["items"]]
        top = plan["items"][0]["candidates"][0]["slug"] if plan["items"] and \
            plan["items"][0]["candidates"] else None
    return {"ok": (target_source in detected and top == target_page["slug"]),
            "source": target_source, "expected_page": target_page["slug"],
            "detected": detected, "top_candidate": top, "n_changes": len(detected)}


# 4. FAITHFULNESS (opt-in) ---------------------------------------------------
def eval_faithfulness(mem: MemoryPaths) -> dict:
    from memlib import llm
    ps = [p for p in pages.collect_pages(mem.wiki)
          if "read_error" not in p and p.get("sources")]
    results = []
    for p in ps:
        src_texts = []
        for s in p["sources"]:
            sp = mem.root / s
            if sp.exists():
                src_texts.append(sp.read_text(encoding="utf-8"))
        prompt = (
            "You grade a memory page for faithfulness to its source. Output ONLY "
            "JSON: {\"supported\": true|false, \"unsupported_claims\": [..], "
            "\"omissions\": [..]}. A page is supported if every factual claim it "
            "makes is backed by the SOURCE (paraphrase is fine; new facts are not).\n\n"
            "SOURCE:\n%s\n\nPAGE:\n%s" % ("\n---\n".join(src_texts), p["body"]))
        try:
            verdict = llm.extract_json(llm.run_claude(prompt))
        except llm.LLMError as e:
            return {"ok": False, "error": str(e), "results": results}
        results.append({"slug": p["slug"], "supported": bool(verdict.get("supported")),
                        "unsupported": verdict.get("unsupported_claims", [])})
    ok = all(r["supported"] for r in results)
    return {"ok": ok, "results": results, "n": len(results)}


# REPORT ---------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--memory", type=Path, default=None)
    ap.add_argument("--labels", type=Path, help="JSON [[question, slug], ...] (default: sample set).")
    ap.add_argument("--judge", action="store_true", help="Also run the LLM faithfulness judge.")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    mem = resolve(args.memory) if args.memory else MemoryPaths(DEFAULT_MEMORY)
    labels = json.loads(args.labels.read_text()) if args.labels else SAMPLE_LABELS

    print("=" * 64)
    print("Memory evaluation — %s" % mem.root)
    print("=" * 64)

    failures = []

    r = eval_retrieval(mem, labels)
    print("\n[1] RETRIEVAL  (%d labeled queries)" % r["n"])
    for key in ("recall@1", "recall@3", "mrr"):
        ok = r[key] >= THRESHOLDS[key]
        failures += [] if ok else [key]
        print("    %-9s %.2f   (>= %.2f)  %s" % (key, r[key], THRESHOLDS[key], bar(ok)))
    if args.verbose:
        for q, exp, top3, rank in r["rows"]:
            flag = "ok" if 0 < rank <= 3 else "MISS"
            print("      [%-4s] r=%s  %-22s  top3=%s" % (flag, rank or "-", exp, top3))

    h = eval_health(mem)
    print("\n[2] HEALTH  (%d pages)" % h["pages"])
    for key in ("orphans", "uncited", "broken", "lint_hard"):
        ok = h[key] <= THRESHOLDS[key]
        failures += [] if ok else [key]
        extra = (" %s" % h["orphan_slugs"]) if key == "orphans" and h[key] else ""
        print("    %-9s %d   (<= %d)  %s%s" % (key, h[key], THRESHOLDS[key], bar(ok), extra))

    a = eval_antidrift(mem)
    print("\n[3] ANTI-DRIFT  (mutate 1 source on a copy)")
    print("    mutated %s -> expect page '%s' as #1 candidate" % (a.get("source"), a.get("expected_page")))
    print("    detected=%s  top_candidate=%s  %s"
          % (a.get("n_changes"), a.get("top_candidate"), bar(a.get("ok"))))
    failures += [] if a.get("ok") else ["anti-drift"]

    if args.judge:
        print("\n[4] FAITHFULNESS  (LLM judge via claude -p)")
        f = eval_faithfulness(mem)
        if "error" in f:
            print("    SKIPPED: %s" % f["error"])
        else:
            for res in f["results"]:
                print("    %-22s %s" % (res["slug"], bar(res["supported"])))
                for u in res["unsupported"]:
                    print("        unsupported: %s" % u)
            failures += [] if f["ok"] else ["faithfulness"]

    print("\n" + "=" * 64)
    if failures:
        print("RESULT: FAIL  (%s)" % ", ".join(failures))
        return 1
    print("RESULT: PASS — the memory retrieves correctly, is healthy, and a source")
    print("change targets the right page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
