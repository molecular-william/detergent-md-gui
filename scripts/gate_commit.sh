#!/usr/bin/env bash
# The local gate this repo's docs name: run the fast tier and ruff over the paths you name,
# stage only those paths, and commit only when every status is zero.
#
#   scripts/gate_commit.sh <message-file> <path> [<path> ...]
#
# Why it is a shell script and not a chain of `&&`s: a pipeline reports its own status, not the
# status of the step inside it, so `pytest ... | tail && git commit` lands a failing suite inside
# a commit whose message claims the gate passed. Every status here is captured into a variable
# from the command itself, printed, and the commit happens only when all of them are zero.
#
# ruff is handed only the .py paths that still exist: passed a template or a stylesheet it parses
# it as Python and reports thousands of syntax errors, and a path deleted by the commit reaches it
# as E902. A docs-only commit therefore passes with ruff skipped, which is the case the docs name.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
PY="$ROOT/dashboard/.venv/bin/python"
OUT="${TMPDIR:-/tmp}"

if [ $# -lt 2 ]; then
  echo "usage: scripts/gate_commit.sh <message-file> <path> [<path> ...]" >&2
  exit 2
fi

MSG="$1"; shift
if [ ! -f "$MSG" ]; then
  echo "gate: no message file at $MSG" >&2
  exit 2
fi
PATHS=("$@")

PY_PATHS=()
SKIPPED=()
for p in "${PATHS[@]}"; do
  case "$p" in
    *.py)
      if [ -f "$p" ]; then PY_PATHS+=("$p"); else SKIPPED+=("$p"); fi
      ;;
  esac
done

echo "gate: fast tier"
"$PY" -m pytest -m 'not browser and not slow' -q > "$OUT/gate-pytest.txt" 2>&1
PYTEST_STATUS=$?
tail -n 3 "$OUT/gate-pytest.txt"
echo "gate: pytest exit $PYTEST_STATUS (full output $OUT/gate-pytest.txt)"

RUFF_STATUS=0
if [ ${#PY_PATHS[@]} -eq 0 ]; then
  echo "gate: ruff skipped (no Python path named)"
else
  "$PY" -m ruff check "${PY_PATHS[@]}" > "$OUT/gate-ruff.txt" 2>&1
  RUFF_STATUS=$?
  tail -n 5 "$OUT/gate-ruff.txt"
  echo "gate: ruff exit $RUFF_STATUS over ${PY_PATHS[*]} (full output $OUT/gate-ruff.txt)"
fi
if [ ${#SKIPPED[@]} -gt 0 ]; then
  echo "gate: ruff not given (deleted or absent): ${SKIPPED[*]}"
fi

if [ "$PYTEST_STATUS" -ne 0 ] || [ "$RUFF_STATUS" -ne 0 ]; then
  echo "gate: NOT committing (pytest $PYTEST_STATUS, ruff $RUFF_STATUS)"
  exit 1
fi

git add -A -- "${PATHS[@]}"
STAGE_STATUS=$?
if [ "$STAGE_STATUS" -ne 0 ]; then
  echo "gate: staging failed (git add exit $STAGE_STATUS)"
  exit 1
fi
echo "gate: staged"
git diff --cached --stat

git commit -F "$MSG"
COMMIT_STATUS=$?
if [ "$COMMIT_STATUS" -ne 0 ]; then
  echo "gate: commit failed (exit $COMMIT_STATUS)"
  exit 1
fi
echo "gate: committed"
git show --stat --oneline HEAD | head -n 20
