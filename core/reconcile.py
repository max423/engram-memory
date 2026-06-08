#!/usr/bin/env python3
"""
reconcile.py — Phase 2 of reconcile: HOW to modify (the ONLY LLM call).

STUB. The deterministic plumbing here is real and tested; the single model call
is stubbed with a clear TODO. That separation is the whole point: by the time we
reach this file, Phase 1 (change_detect.py) has already picked the few candidate
pages, so the LLM context is just {schema + changed source + those pages} — never
the rest of the wiki.

Flow per changed source:
  1. build the minimal context bundle (schema, raw source, candidate pages)
  2. >>> LLM CALL (TODO) <<< : classify each candidate as one of
       no-op | update | add | contradiction | deprecate
     and, for update, return surgical str_replace patches.
  3. apply patches deterministically (real code below), drive the status
     machine, and append to log.md.

Anti-drift rule the LLM prompt MUST enforce: re-read the *raw source* as truth,
never the old page. Patches are surgical (str_replace), never full rewrites.

Usage:
    python reconcile.py [--memory DIR] [--since GIT_REF] [--show-context] [--apply]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import change_detect  # noqa: E402
from memlib import frontmatter  # noqa: E402
from memlib.pages import collect_pages  # noqa: E402
from memlib.store import resolve  # noqa: E402

ACTIONS = ["no-op", "update", "add", "contradiction", "deprecate"]


# --------------------------------------------------------------------------- #
# Context assembly — token-minimal by construction.
# --------------------------------------------------------------------------- #
def build_context(mem, item: dict) -> dict:
    schema_text = mem.schema.read_text(encoding="utf-8") if mem.schema.exists() else ""
    source_text = ""
    if item["status"] != "removed":
        source_text = (mem.root / item["source"]).read_text(encoding="utf-8")
    candidate_pages = []
    for c in item["candidates"]:
        page_path = mem.wiki / c["rel_path"]
        if page_path.exists():
            candidate_pages.append({
                "slug": c["slug"],
                "rel_path": c["rel_path"],
                "reasons": c["reasons"],
                "text": page_path.read_text(encoding="utf-8"),
            })
    return {
        "schema": schema_text,
        "source": item["source"],
        "source_text": source_text,
        "status": item["status"],
        "candidate_pages": candidate_pages,
    }


def estimate_tokens(ctx: dict) -> int:
    chars = len(ctx["schema"]) + len(ctx["source_text"])
    chars += sum(len(p["text"]) for p in ctx["candidate_pages"])
    return chars // 4  # rough chars-per-token heuristic


# --------------------------------------------------------------------------- #
# The LLM call — STUB.
# --------------------------------------------------------------------------- #
_RECONCILE_PROMPT = """\
You are the reconcile step of a curated project-memory tool. A curated source
changed. Decide, for EACH candidate page, the minimal action. Output ONLY a JSON
array (no prose, no code fence). Each element:

  {"slug": "<page slug>",
   "action": "no-op" | "update" | "contradiction" | "deprecate",
   "patches": [{"old": "<exact substring of the page>", "new": "<replacement>"}],
   "rationale": "<one short line>"}

Rules:
- Treat the RAW SOURCE below as the source of truth, NOT the existing pages.
- Prefer "no-op" — it is the common case. Only act on what the source changed.
- "update": surgical str_replace. Each "old" MUST be an EXACT, unique substring
  of that page's current text. Never rewrite the whole page. Omit patches for
  no-op.
- "contradiction": the source conflicts with the page — flag it, do not rewrite.
- "deprecate": the source makes the page obsolete.
- Only include pages that actually need action; you may return [] for all no-op.

SCHEMA:
%(schema)s

CHANGED RAW SOURCE (%(source)s):
%(source_text)s

CANDIDATE PAGES:
%(pages)s
"""


def llm_reconcile(ctx: dict, model: str | None = None) -> list[dict]:
    """One `claude -p` call (uses your subscription). Returns decisions list.

    Decision shape consumed by _apply_decisions:
      [{slug, action, patches:[{old,new}], rationale}]
    """
    from memlib import llm

    pages_blob = "\n\n".join(
        "### page slug=%s (%s)\n%s" % (p["slug"], p["rel_path"], p["text"])
        for p in ctx["candidate_pages"])
    prompt = _RECONCILE_PROMPT % {
        "schema": (ctx.get("schema") or "").strip()[:4000],
        "source": ctx["source"],
        "source_text": ctx["source_text"].strip(),
        "pages": pages_blob or "(none)",
    }
    out = llm.run_claude(prompt, model=model or llm.DEFAULT_MODEL)
    decisions = llm.extract_json(out)
    if not isinstance(decisions, list):
        raise llm.LLMError("expected a JSON array of decisions, got: %r" % type(decisions))
    return decisions


# --------------------------------------------------------------------------- #
# Deterministic plumbing — REAL (this is what runs after the LLM decides).
# --------------------------------------------------------------------------- #
# apply_patch outcomes.
APPLIED = "applied"
NOT_FOUND = "not_found"
AMBIGUOUS = "ambiguous"


def find_patch_span(text: str, old: str):
    """Locate `old` in `text`, tolerating whitespace differences.

    LLM-produced patches usually mismatch only on whitespace/newlines, so after
    an exact attempt we retry with runs of whitespace collapsed to `\\s+`.
    Returns (start, end) for a UNIQUE match, or AMBIGUOUS / NOT_FOUND.
    """
    if not old:
        return NOT_FOUND
    # 1. exact, unique
    c = text.count(old)
    if c == 1:
        i = text.find(old)
        return (i, i + len(old))
    if c > 1:
        return AMBIGUOUS
    # 2. whitespace-tolerant (anchored on the non-space tokens, in order)
    parts = old.split()
    if not parts:
        return NOT_FOUND
    rx = re.compile(r"\s+".join(re.escape(p) for p in parts))
    spans = [m.span() for m in rx.finditer(text)]
    if len(spans) == 1:
        return spans[0]
    if len(spans) > 1:
        return AMBIGUOUS
    return NOT_FOUND


def apply_patch(page_path: Path, old: str, new: str) -> str:
    """Apply one surgical patch. Returns APPLIED / NOT_FOUND / AMBIGUOUS.

    Never raises on a bad patch and never applies an ambiguous one — a failed
    patch is reported so the caller can re-prompt the model with feedback.
    """
    text = page_path.read_text(encoding="utf-8")
    span = find_patch_span(text, old)
    if span in (NOT_FOUND, AMBIGUOUS):
        return span
    i, j = span
    page_path.write_text(text[:i] + new + text[j:], encoding="utf-8")
    return APPLIED


def set_status(page_path: Path, status: str) -> None:
    text = page_path.read_text(encoding="utf-8")
    meta, body, _ = frontmatter.parse(text)
    meta["status"] = status
    meta["updated"] = _today()
    page_path.write_text(frontmatter.with_frontmatter(meta, body), encoding="utf-8")


def set_status_updated(page_path: Path) -> None:
    """Bump only `updated` (an in-place edit keeps the page active)."""
    text = page_path.read_text(encoding="utf-8")
    meta, body, _ = frontmatter.parse(text)
    meta["updated"] = _today()
    page_path.write_text(frontmatter.with_frontmatter(meta, body), encoding="utf-8")


def append_log(mem, op: str, title: str, detail: str = "") -> None:
    line = "\n## [%s] %s | %s\n" % (_today(), op, title)
    if detail:
        line += detail.rstrip() + "\n"
    with mem.log.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _today() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--memory", type=Path, default=None)
    ap.add_argument("--since", help="Restrict to raw files changed since this git ref.")
    ap.add_argument("--max-candidates", type=int, default=change_detect.MAX_CANDIDATES)
    ap.add_argument("--show-context", action="store_true",
                    help="Print the exact minimal context that would go to the LLM.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually run the (stubbed) LLM call and apply patches.")
    args = ap.parse_args()
    mem = resolve(args.memory)
    return run_reconcile(mem, args.since, args.max_candidates,
                         args.show_context, args.apply)


def run_reconcile(mem, since, max_candidates, show_context=False, apply=False) -> int:
    # Phase 1 (deterministic, zero token) — reuse the change detector.
    plan = change_detect.compute_plan(mem, since, max_candidates)
    pages = collect_pages(mem.wiki)

    if not plan["items"]:
        print("No curated sources new or changed. Nothing to reconcile (0 tokens).")
        return 0

    total_tokens = 0
    for item in plan["items"]:
        ctx = build_context(mem, item)
        tok = estimate_tokens(ctx)
        total_tokens += tok
        print("[%s] %s" % (item["status"].upper(), item["source"]))
        print("    candidate pages: %s" % (
            ", ".join(p["slug"] for p in ctx["candidate_pages"]) or "(none)"))
        print("    LLM context: ~%d tokens (schema + source + %d page(s))"
              % (tok, len(ctx["candidate_pages"])))
        if show_context:
            _dump_context(ctx)
        if apply:
            try:
                res = reconcile_apply(mem, ctx)
                if res["applied"]:
                    print("    applied (retries: %d)" % res["retries"])
                else:
                    print("    %d patch(es) still unmatched after %d retries: %s"
                          % (len(res["failures"]), res["retries"],
                             ", ".join("%s/%s" % (f["slug"], f["status"])
                                       for f in res["failures"])))
            except Exception as e:  # llm.LLMError etc.
                print("    [LLM] %s" % e)
        print()

    n_pages = len([p for p in pages if "read_error" not in p])
    print("Total estimated LLM cost for this reconcile: ~%d tokens." % total_tokens)
    print("Context is bounded by --max-candidates (%d pages), not by wiki size "
          "(%d pages here, ~%d tokens of bodies): the cost scales with the "
          "change, not the wiki." % (max_candidates, n_pages, _whole_wiki_tokens(mem)))
    if not apply:
        print("Dry run. Re-run with --apply once the Phase 2 LLM call is wired.")
    return 0


def _page_path(mem, ctx, slug):
    rel = next((p["rel_path"] for p in ctx["candidate_pages"] if p["slug"] == slug), None)
    return (mem.wiki / rel) if rel else None


def apply_decisions(mem, ctx: dict, decisions: list[dict]) -> list[dict]:
    """Apply decisions; return the patches that did NOT cleanly apply.

    Each failure: {slug, old, status}. status/contradiction/deprecate always
    succeed; only 'update' patches can fail (not_found / ambiguous), and a failed
    patch is left untouched so the caller can re-prompt for a corrected one.
    """
    failures = []
    for d in decisions:
        action = d.get("action")
        if action in (None, "no-op"):
            continue
        page_path = _page_path(mem, ctx, d.get("slug"))
        if page_path is None or not page_path.exists():
            failures.append({"slug": d.get("slug"), "old": None, "status": NOT_FOUND})
            continue
        if action == "update":
            applied_any = False
            for patch in d.get("patches", []):
                status = apply_patch(page_path, patch.get("old", ""), patch.get("new", ""))
                if status == APPLIED:
                    applied_any = True
                else:
                    failures.append({"slug": d["slug"], "old": patch.get("old", ""),
                                     "status": status})
            if applied_any:
                set_status_updated(page_path)
                append_log(mem, "update", d["slug"], "source: %s" % ctx["source"])
        elif action == "contradiction":
            set_status(page_path, "contradicted")
            append_log(mem, "contradiction", d["slug"], d.get("rationale", ""))
        elif action == "deprecate":
            set_status(page_path, "archived")
            append_log(mem, "deprecate", d["slug"], d.get("rationale", ""))
        # 'add' would write a new page file; omitted in the MVP.
    return failures


def reconcile_apply(mem, ctx: dict, model=None, max_retries: int = 2) -> dict:
    """Full apply loop: decide → apply → on patch failure, re-prompt up to N times.

    Returns {applied: bool, retries: int, failures: [...]}. The retry feeds the
    exact failed `old` strings + current page text back to the model so it can
    produce a uniquely-matching patch — this is what makes surgical patches
    survive an LLM that's slightly off on whitespace/context.
    """
    decisions = llm_reconcile(ctx, model=model)
    failures = apply_decisions(mem, ctx, decisions)
    retries = 0
    while failures and retries < max_retries:
        decisions = llm_fix_patches(ctx, failures, model=model)
        failures = apply_decisions(mem, ctx, decisions)
        retries += 1
    return {"applied": not failures, "retries": retries, "failures": failures}


_FIXUP_PROMPT = """\
Some str_replace patches you proposed did not apply (the "old" text was not found
or was not unique). Fix ONLY these. Output ONLY a JSON array of decisions
[{"slug","action":"update","patches":[{"old","new"}]}]. Each "old" MUST be an
EXACT, UNIQUE substring of the CURRENT page text shown below — copy it verbatim,
including punctuation and spacing, and extend it with surrounding context until
it is unique.

FAILED PATCHES (status): %(failures)s

CURRENT PAGES:
%(pages)s
"""


def llm_fix_patches(ctx: dict, failures: list[dict], model=None) -> list[dict]:
    from memlib import llm
    fail_blob = "; ".join("%s [%s]: %r" % (f.get("slug"), f.get("status"),
                                           (f.get("old") or "")[:60]) for f in failures)
    pages_blob = "\n\n".join(
        "### page slug=%s\n%s" % (p["slug"], p["text"]) for p in ctx["candidate_pages"])
    prompt = _FIXUP_PROMPT % {"failures": fail_blob, "pages": pages_blob}
    decisions = llm.extract_json(llm.run_claude(prompt, model=model or llm.DEFAULT_MODEL))
    return decisions if isinstance(decisions, list) else []


def _dump_context(ctx: dict) -> None:
    print("    " + "-" * 50)
    print("    SCHEMA: %d chars" % len(ctx["schema"]))
    print("    SOURCE (%s): %d chars" % (ctx["source"], len(ctx["source_text"])))
    for p in ctx["candidate_pages"]:
        print("    PAGE %s [%s]: %d chars"
              % (p["slug"], ",".join(p["reasons"]), len(p["text"])))
    print("    " + "-" * 50)


def _whole_wiki_tokens(mem) -> int:
    total = 0
    for p in collect_pages(mem.wiki):
        if "read_error" not in p:
            total += len(p["body"])
    return total // 4


if __name__ == "__main__":
    sys.exit(main())
