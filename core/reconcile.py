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
def llm_reconcile(ctx: dict) -> list[dict]:
    """Return a decision per candidate page (+ possible 'add').

    TODO(LLM): replace this stub with a single model call. Send `ctx` (schema +
    raw source + candidate pages) and require structured output:

        [{ "slug": "...", "action": "update",
           "patches": [{"old": "<exact text>", "new": "<replacement>"}],
           "rationale": "..." }, ...]

    Prompt invariants:
      - treat ctx["source_text"] as the source of truth; do NOT trust the page.
      - prefer no-op (the ~95% case); only patch what the source actually changed.
      - patches must be surgical str_replace, never full-page rewrites.
      - 'add' requires the new page to carry >=1 inbound wikilink.
      - 'contradiction' flags + proposes; it never silently overwrites.
    """
    raise NotImplementedError(
        "reconcile Phase 2 LLM call is not wired yet — this is the MVP stub.")


# --------------------------------------------------------------------------- #
# Deterministic plumbing — REAL (this is what runs after the LLM decides).
# --------------------------------------------------------------------------- #
def apply_patch(page_path: Path, old: str, new: str) -> bool:
    text = page_path.read_text(encoding="utf-8")
    if old not in text:
        return False
    if text.count(old) > 1:
        raise ValueError("ambiguous patch: %r occurs %d times in %s"
                         % (old[:40], text.count(old), page_path))
    page_path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def set_status(page_path: Path, status: str) -> None:
    text = page_path.read_text(encoding="utf-8")
    meta, body, _ = frontmatter.parse(text)
    meta["status"] = status
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

    # Phase 1 (deterministic, zero token) — reuse the change detector.
    current = change_detect.current_source_hashes(mem.raw)
    snapshot = change_detect.load_snapshot(mem.sources_sha)
    git_filter = (change_detect.git_changed_under(mem.root.parent, args.since, mem.raw)
                  if args.since else None)
    changes = change_detect.detect_changes(current, snapshot, git_filter)
    pages = collect_pages(mem.wiki)
    plan = change_detect.build_plan(mem, changes, pages, args.max_candidates)

    if not changes:
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
        if args.show_context:
            _dump_context(ctx)
        if args.apply:
            try:
                decisions = llm_reconcile(ctx)
                _apply_decisions(mem, ctx, decisions)
            except NotImplementedError as e:
                print("    [STUB] %s" % e)
        print()

    n_pages = len([p for p in pages if "read_error" not in p])
    print("Total estimated LLM cost for this reconcile: ~%d tokens." % total_tokens)
    print("Context is bounded by --max-candidates (%d pages), not by wiki size "
          "(%d pages here, ~%d tokens of bodies): the cost scales with the "
          "change, not the wiki." % (args.max_candidates, n_pages, _whole_wiki_tokens(mem)))
    if not args.apply:
        print("Dry run. Re-run with --apply once the Phase 2 LLM call is wired.")
    return 0


def _apply_decisions(mem, ctx: dict, decisions: list[dict]) -> None:
    """Real applier — invoked once llm_reconcile returns. Unused until wired."""
    for d in decisions:
        action = d.get("action")
        if action == "no-op":
            continue
        page_path = mem.wiki / next(
            (p["rel_path"] for p in ctx["candidate_pages"] if p["slug"] == d["slug"]), "")
        if action == "update":
            for patch in d.get("patches", []):
                apply_patch(page_path, patch["old"], patch["new"])
            append_log(mem, "update", d["slug"], "source: %s" % ctx["source"])
        elif action == "contradiction":
            set_status(page_path, "contradicted")
            append_log(mem, "contradiction", d["slug"], d.get("rationale", ""))
        elif action == "deprecate":
            set_status(page_path, "archived")
            append_log(mem, "deprecate", d["slug"], d.get("rationale", ""))
        # 'add' would write a new page file; omitted in the stub.


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
