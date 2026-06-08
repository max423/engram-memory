"""llm.py — the single model call, routed through Claude Code (no API key).

The "thin LLM layer" of the architecture is Claude Code itself. This module
shells out to the `claude` CLI in headless print mode (`claude -p`), which uses
your logged-in Claude subscription (e.g. Max) — there is NO Anthropic API key
and no per-token billing involved. For CI/servers without Claude installed, swap
this for a direct SDK call; everything above this module is unchanged.

Design rules kept here:
  - one call per event (compile a source / reconcile a change);
  - the prompt is fully self-contained (the deterministic core already selected
    the minimal context), so the call needs no tools and no repo access;
  - we capture stdout and write files ourselves — the model only returns text.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

DEFAULT_MODEL = "sonnet"   # cheap/fast is plenty for compile/reconcile synthesis


def claude_available() -> bool:
    return shutil.which("claude") is not None


class LLMError(RuntimeError):
    pass


def parse_stream_json(stdout: str):
    """Parse `claude -p --output-format stream-json` JSONL output.

    The stream is one JSON object per line; the terminal object has
    type=="result" with the final text in `result`. Returns (text, result_obj);
    text is None if no result event was seen. Tolerant of non-JSON noise lines.
    """
    text, result_obj = None, {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            text = obj.get("result", text)
            result_obj = obj
    return text, result_obj


def _fallback_parse(stdout: str) -> str:
    """If the stream had no result event, accept a single JSON object or raw text."""
    out = stdout.strip()
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return data.get("result", out)
    except ValueError:
        pass
    return out


def run_claude(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 240) -> str:
    """Run `claude -p` headless and return the assistant's text result.

    Uses --output-format stream-json (richer than plain json: surfaces per-turn
    progress and final cost/usage, which we log to stderr). Raises LLMError on
    any failure.
    """
    if not claude_available():
        raise LLMError("`claude` CLI not found on PATH. Install Claude Code, or "
                       "use --backend offline.")
    if os.environ.get("CLAUDECODE"):
        raise LLMError(
            "you're inside a Claude Code session — `claude -p` can't nest. "
            "Either run this from a normal terminal, or use the in-session path: "
            "the /mem:ingest plugin command (Claude does the synthesis directly).")
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise LLMError("claude -p timed out after %ss" % timeout) from e
    if proc.returncode != 0:
        raise LLMError("claude -p failed (exit %d): %s"
                       % (proc.returncode, (proc.stderr or proc.stdout)[:500]))

    text, result = parse_stream_json(proc.stdout)
    if text is None:
        text = _fallback_parse(proc.stdout)
    # Richer feedback: surface cost/usage if the result event carried it.
    cost = result.get("total_cost_usd")
    usage = result.get("usage") or {}
    if cost is not None or usage:
        toks = (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) if usage else 0
        print("[mem] llm: %s%s" % (
            ("~%d tokens" % toks) if toks else "",
            (" $%.4f" % cost) if cost is not None else ""), file=sys.stderr)
    return text if isinstance(text, str) else json.dumps(text)


def strip_code_fence(text: str) -> str:
    """If the model wrapped output in a ``` fence, return the inner content."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return t


def extract_json(text: str):
    """Parse a JSON value from model output, tolerating a code fence / prose."""
    t = strip_code_fence(text)
    try:
        return json.loads(t)
    except ValueError:
        pass
    # Last resort: grab the outermost [...] or {...}.
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = t.find(open_c), t.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except ValueError:
                continue
    raise LLMError("could not parse JSON from model output: %s" % t[:300])
