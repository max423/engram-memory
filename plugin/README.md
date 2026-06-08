# project-memory — Claude Code plugin

Thin slash commands that drive the `engram` CLI. The deterministic work
(index/search/lint/graph/change-detect) runs at zero tokens in the CLI; these
commands invoke the model **only** for synthesis, with minimal context.

## Commands

| Command | What it does |
|---|---|
| `/mem:ingest [raw/file.md]` | Compile new/changed curated sources into wiki pages (in-session synthesis: Claude *is* the LLM layer — no API key). |
| `/mem:query <question>` | Answer from the memory, index-first, citing the pages used. |
| `/mem:lint [fix]` | Run the health + anti-drift check; optionally apply surgical fixes. |

## Prerequisite

Install the CLI so `mem` is on PATH (the commands call it):

```bash
./install.sh           # links `mem` into ~/.local/bin and runs the tests
```

If `mem` isn't on PATH, the commands also work via `python3 core/mem.py …`.

## Why a plugin at all

The CLI covers everything deterministic and the headless LLM path (`mem ingest
--backend llm` / `mem reconcile --apply` via `claude -p`). This plugin is the
**interactive** path: inside a Claude Code session `claude -p` can't nest, so the
synthesis runs directly through the session you're already in — using your
subscription, no API key. See the repo `README.md` and `WEAKNESSES.md` for the
full architecture and honest limits.
