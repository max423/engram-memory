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

DEFAULT_MODEL = "sonnet"   # cheap/fast is plenty for compile/reconcile synthesis


def claude_available() -> bool:
    return shutil.which("claude") is not None


class LLMError(RuntimeError):
    pass


def run_claude(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 240) -> str:
    """Run `claude -p` headless and return the assistant's text result.

    Uses --output-format json so we get a clean `result` field instead of
    having to scrape stdout. Raises LLMError on any failure.
    """
    if not claude_available():
        raise LLMError("`claude` CLI not found on PATH. Install Claude Code, or "
                       "use --backend offline.")
    if os.environ.get("CLAUDECODE"):
        raise LLMError(
            "you're inside a Claude Code session — `claude -p` can't nest. "
            "Either run this from a normal terminal, or use the in-session path: "
            "the /mem:ingest plugin command (Claude does the synthesis directly).")
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise LLMError("claude -p timed out after %ss" % timeout) from e
    if proc.returncode != 0:
        raise LLMError("claude -p failed (exit %d): %s"
                       % (proc.returncode, (proc.stderr or proc.stdout)[:500]))
    out = proc.stdout.strip()
    # --output-format json wraps the answer; fall back to raw stdout if needed.
    try:
        data = json.loads(out)
        result = data.get("result", data) if isinstance(data, dict) else out
        return result if isinstance(result, str) else json.dumps(result)
    except (ValueError, TypeError):
        return out


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
