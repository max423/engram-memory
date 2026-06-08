#!/usr/bin/env bash
# install.sh — plug-and-play setup.
#
#   ./install.sh                  # put `mem` on your PATH (~/.local/bin)
#   ./install.sh /path/to/repo    # also: init .memory/ + install merge hook there
#
# Zero runtime dependencies (Python 3.9+ stdlib only). Idempotent.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINDIR="${MEM_BINDIR:-$HOME/.local/bin}"

echo "==> Making scripts executable"
chmod +x "$SRC/bin/mem" "$SRC/core/mem.py" "$SRC/core/change_detect.py" \
         "$SRC/core/reconcile.py" "$SRC/hooks/post-merge" 2>/dev/null || true

echo "==> Linking 'mem' into $BINDIR"
mkdir -p "$BINDIR"
ln -sf "$SRC/bin/mem" "$BINDIR/mem"

if ! echo ":$PATH:" | grep -q ":$BINDIR:"; then
  echo "    NOTE: $BINDIR is not on your PATH. Add this to your shell profile:"
  echo "      export PATH=\"$BINDIR:\$PATH\""
fi

echo "==> Smoke test"
python3 "$SRC/core/mem.py" --help >/dev/null && echo "    mem CLI OK"
python3 "$SRC/tests/run.py" >/dev/null 2>&1 && echo "    test suite OK" \
  || echo "    test suite reported failures — run: python3 $SRC/tests/run.py"

TARGET="${1:-}"
if [ -n "$TARGET" ]; then
  echo "==> Initializing memory in $TARGET"
  python3 "$SRC/core/mem.py" init "$TARGET"
  if [ -d "$TARGET/.git" ]; then
    python3 "$SRC/core/mem.py" install-hooks "$TARGET"
  else
    echo "    ($TARGET is not a git repo — skip hook; run 'git init' then"
    echo "     'mem install-hooks $TARGET')"
  fi
fi

cat <<'EOF'

Done. Quick start:
  mem init .                 # create .memory/ in the current repo
  # drop a decision into .memory/raw/, e.g. 2026-06-08-my-choice.md
  mem ingest                 # compile new sources into draft pages (offline)
  mem index && mem lint      # rebuild indexes, check health
  mem search "your terms"    # BM25 search
  mem detect                 # what changed since last snapshot (0 tokens)
EOF
