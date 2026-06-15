"""context.py — the code-aligned big-picture map (change-driven, token-minimal).

This is the second memory layer (alongside curated decisions): a compact overview
of the codebase that stays aligned with the code. The deterministic core does the
structural work at ZERO tokens — walk the tree, group by top-level module, detect
languages, manifests and entry points, and extract a one-line description from
each module's README/docstring/leading comment. An optional LLM backend enriches
ONLY the modules whose code changed since the last snapshot (hybrid, change-driven).

The map is `.memory/context.md`, a first-class artifact like index.md — not a wiki
page (it is auto-derived, not curated). It is what a SessionStart hook injects so
the assistant has the project's shape without reading the whole repo.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path

LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".rb": "Ruby",
    ".sh": "Shell", ".bash": "Shell", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
    ".cs": "C#", ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala",
    ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".md": "Markdown", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".json": "JSON",
}
_DOC_LANGS = {"Markdown", "YAML", "TOML", "JSON", "HTML", "CSS"}  # not "primary" code

IGNORE_DIRS = {
    ".git", ".memory", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "target", "vendor", ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage", ".tox",
    ".claude", ".pnpm-store", ".pnpm", ".github", ".domscribe",
}
MANIFESTS = {
    "package.json": "Node", "pyproject.toml": "Python", "setup.py": "Python",
    "requirements.txt": "Python", "go.mod": "Go", "Cargo.toml": "Rust",
    "pom.xml": "Java", "build.gradle": "Java/Gradle", "Gemfile": "Ruby",
    "composer.json": "PHP", "Makefile": "Make",
}
ROOT_BUCKET = "(root)"
_MAX_BYTES = 1_000_000


def iter_code_files(root: Path, ignore: set | None = None):
    root = Path(root)
    ignore = IGNORE_DIRS if ignore is None else ignore
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored dirs *in place* so os.walk never descends into them —
        # critical on big trees (node_modules, .cache, GOPATH): we must not
        # traverse what we'd only discard.
        dirnames[:] = sorted(d for d in dirnames if d not in ignore)
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.suffix.lower() not in LANG_BY_EXT:
                continue
            try:
                if p.stat().st_size > _MAX_BYTES:
                    continue
            except OSError:
                continue
            yield p, p.relative_to(root)


# Container dirs in a monorepo whose immediate children are independent
# packages/services. Descend one level so each child becomes its own module
# (apps/frontend, packages/ui) instead of one giant 'apps' bucket.
_MONOREPO_CONTAINERS = {"apps", "packages", "services", "libs", "modules", "plugins"}


def _module_of(rel: Path, containers: set | None = None) -> str:
    containers = _MONOREPO_CONTAINERS if containers is None else containers
    parts = rel.parts
    if len(parts) <= 1:
        return ROOT_BUCKET
    if parts[0] in containers and len(parts) > 2:
        return "%s/%s" % (parts[0], parts[1])
    return parts[0]


def scan(root: Path, ignore: set | None = None, containers: set | None = None) -> list:
    """Group code files by top-level module. Returns sorted module dicts."""
    root = Path(root)
    mods: dict = {}
    for _p, rel in iter_code_files(root, ignore):
        name = _module_of(rel, containers)
        m = mods.setdefault(name, {"name": name, "files": [], "langs": Counter()})
        m["files"].append(str(rel))
        m["langs"][LANG_BY_EXT.get(rel.suffix.lower(), rel.suffix)] += 1
    out = []
    for name in sorted(mods, key=lambda n: (n == ROOT_BUCKET, n)):
        m = mods[name]
        code_langs = [(l, c) for l, c in m["langs"].most_common() if l not in _DOC_LANGS]
        m["primary_langs"] = [l for l, _ in (code_langs or m["langs"].most_common())][:2]
        m["file_count"] = len(m["files"])
        out.append(m)
    return out


def detect_manifests(root: Path) -> list:
    root = Path(root)
    return [(name, MANIFESTS[name]) for name in MANIFESTS if (root / name).exists()]


# --------------------------------------------------------------------------- #
# Deterministic one-line descriptions (offline backend).
# --------------------------------------------------------------------------- #
_PY_DOC = re.compile(r'^\s*(?:#!.*\n)?(?:from __future__.*\n|\s*\n)*\s*[ru]?(["\']{3})(.*?)\1',
                     re.DOTALL)


def _first_sentence(text: str, limit: int = 160) -> str:
    line = " ".join(text.strip().split())
    if not line:
        return ""
    m = re.search(r"(.+?[.!?])(\s|$)", line)
    out = (m.group(1) if m else line)
    return out[:limit].rstrip()


def _lead_comment(text: str, ext: str) -> str:
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (lines[i].startswith("#!") or not lines[i].strip()):
        i += 1
    buf = []
    for ln in lines[i:]:
        s = ln.strip()
        if s.startswith(("#", "//")):
            buf.append(s.lstrip("#/ ").strip())
        elif s.startswith(("/*", "*", "*/")):
            buf.append(s.lstrip("/* ").rstrip("*/ ").strip())
        else:
            break
    return _first_sentence(" ".join(b for b in buf if b))


def _doc_of_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if path.suffix.lower() == ".py":
        m = _PY_DOC.match(text)
        if m and m.group(2).strip():
            return _first_sentence(m.group(2))
    return _lead_comment(text, path.suffix.lower())


def _readme_line(dir_path: Path) -> str:
    for name in ("README.md", "readme.md", "README.txt", "README"):
        f = dir_path / name
        if f.exists():
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for ln in text.splitlines():
                s = ln.strip().lstrip("#").strip()
                if s:
                    return _first_sentence(s)
    return ""


def _primary_file(root: Path, module: dict) -> Path | None:
    """Pick the most representative source file of a module."""
    files = [Path(f) for f in module["files"]]
    code = [f for f in files if LANG_BY_EXT.get(f.suffix.lower()) not in _DOC_LANGS]
    pool = code or files
    pref = ("__init__.py", "__main__.py", "main.py", "index.js", "index.ts", "mod.rs",
            "main.go", "main.rs", "app.py")
    pool.sort(key=lambda f: (f.name not in pref and module["name"] not in f.stem,
                             f.name not in pref, -len(f.parts)))
    return (root / pool[0]) if pool else None


def describe_offline(root: Path, module: dict) -> str:
    root = Path(root)
    dir_path = root if module["name"] == ROOT_BUCKET else root / module["name"]
    desc = _readme_line(dir_path)
    if not desc:
        pf = _primary_file(root, module)
        if pf is not None:
            desc = _doc_of_file(pf)
    if not desc:
        langs = ", ".join(module["primary_langs"]) or "mixed"
        desc = "%d file (%s)." % (module["file_count"], langs)
    return desc


_CTX_PROMPT = """\
You maintain a project's big-picture map. In ONE sentence (<= 22 words), say what
the module `%(name)s` does in this codebase. Output ONLY the sentence — no
preamble, no markdown, no file list.

Files: %(files)s

Heads of key files:
%(heads)s
"""


def describe_llm(root: Path, module: dict, model=None) -> str:
    """One-sentence module description via `claude -p` (your subscription).

    Minimal context: the file list + the first lines of a couple of key files.
    Falls back to the offline description on any LLM error.
    """
    from . import llm
    root = Path(root)
    files = ", ".join(module["files"][:20])
    heads = []
    for f in module["files"][:3]:
        try:
            text = (root / f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        heads.append("# %s\n%s" % (f, "\n".join(text.splitlines()[:15])))
    prompt = _CTX_PROMPT % {"name": module["name"], "files": files,
                            "heads": "\n\n".join(heads)[:6000]}
    try:
        out = llm.run_claude(prompt, model=model or llm.DEFAULT_MODEL)
        return _first_sentence(llm.strip_code_fence(out).strip()) or describe_offline(root, module)
    except Exception:
        return describe_offline(root, module)


# --------------------------------------------------------------------------- #
# Change detection over the code (per-file SHA-256).
# --------------------------------------------------------------------------- #
def code_hashes(root: Path, ignore: set | None = None) -> dict:
    out = {}
    for p, rel in iter_code_files(root, ignore):
        try:
            out[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def changed_modules(root: Path, prev: dict, ignore: set | None = None,
                    containers: set | None = None) -> set:
    """Top-level modules whose files were added/removed/modified vs `prev` hashes."""
    cur = code_hashes(root, ignore)
    changed_files = set()
    for f, h in cur.items():
        if prev.get(f) != h:
            changed_files.add(f)
    for f in prev:
        if f not in cur:
            changed_files.add(f)
    return {_module_of(Path(f), containers) for f in changed_files}


# --------------------------------------------------------------------------- #
# Render / parse the context.md map.
# --------------------------------------------------------------------------- #
_SECTION_RE = re.compile(r"^##\s+`?([^`\n—]+?)`?\s+—", re.MULTILINE)


def parse_descriptions(text: str) -> dict:
    """Recover {module: description} from an existing context.md (for reuse)."""
    out = {}
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = _SECTION_RE.match(ln)
        if m:
            name = m.group(1).strip().rstrip("/")
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    out[name] = nxt.strip()
                    break
    return out


_TITLE_RE = re.compile(r"^#\s+Context map\s+—\s+(.+?)\s*$", re.MULTILINE)


def parse_title(text: str) -> str | None:
    """Recover the project name from an existing context.md title, if any."""
    m = _TITLE_RE.search(text)
    return m.group(1).strip() if m else None


def render(root: Path, modules: list, descriptions: dict,
           updated: str | None = None, name: str | None = None) -> str:
    root = Path(root)
    updated = updated or date.today().isoformat()
    manifests = detect_manifests(root)
    all_langs = Counter()
    for m in modules:
        all_langs.update(m["langs"])
    top_langs = ", ".join(l for l, _ in all_langs.most_common(4)
                          if l not in _DOC_LANGS) or "mixed"
    stack = ", ".join("%s (%s)" % (n, t) for n, t in manifests) or "—"

    lines = [
        "# Context map — %s" % (name or root.name),
        "",
        "> Auto-derived from the code (deterministic core, LLM only on changed "
        "modules), change-driven. Updated %s." % updated,
        "> Source of truth is the **code** — edit the code, not this file.",
        "",
        "**Languages:** %s  ·  **Manifests:** %s  ·  **Modules:** %d"
        % (top_langs, stack, len(modules)),
        "",
    ]
    for m in modules:
        langs = ", ".join(m["primary_langs"]) or "mixed"
        label = m["name"] if m["name"] == ROOT_BUCKET else m["name"] + "/"
        lines.append("## `%s` — %s, %d file" % (label, langs, m["file_count"]))
        lines.append(descriptions.get(m["name"], "").strip()
                     or "(da descrivere)")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
