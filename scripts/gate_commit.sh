#!/usr/bin/env bash
# The local gate this repo's docs name: run the fast tier and ruff over the paths you name,
# stage only those paths, and commit only when every status is zero.
#
#   scripts/gate_commit.sh <message-file> <path> [<path> ...]
#
# This repository carried no copy of the gate until 2026-10-15 (`c6ec468`). The script the docs meant is Hermes's
# own (its skill directory: `~/.hermes/profiles/moldym/skills/software-development/detergent-md-dashboard/scripts/
# gate_commit.sh`, documented in that skill's `references/verification-and-commit-gates.md`), and the docs' "no CI"
# row described it -- including the browser tier being reported rather than gating. This copy is for working inside
# the repo: it resolves the repository from its own location so it needs no environment, and it keeps that
# behaviour. Two copies exist; change the behaviour in both or they will disagree.
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
PY="$ROOT/.venv/bin/python"
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
FRONT_END=0
for p in "${PATHS[@]}"; do
  case "$p" in
    *.py)
      if [ -f "$p" ]; then PY_PATHS+=("$p"); else SKIPPED+=("$p"); fi
      ;;
    *.js|*.css|*.html|*.jinja|packages/*/tests/browser/*) FRONT_END=1 ;;
  esac
done

echo "gate: fast tier"
"$PY" -m pytest -m 'not browser and not slow' -q -p no:cacheprovider > "$OUT/gate-pytest.txt" 2>&1
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

# The browser tier is *reported*, never gating: it was red against the old vertical rail and the decision to
# promote it is the user's, not this script's. When it is promoted, add its status to the condition below. On
# front-end paths it runs at -n 6 -- 173 tests in ~85 s on this 72-core box, measured 2026-10-15 -- not at -n 2,
# which left the machine idle and made one load-sensitive test look like a code failure.
BROWSER_LOG="$OUT/gate-browser.txt"
BROWSER_REPORT='not run (no front-end path named)'
if [ "$FRONT_END" -eq 1 ]; then
  "$PY" -m pytest -m browser -q -n 16 --dist worksteal -p no:cacheprovider > "$BROWSER_LOG" 2>&1
  BROWSER_REPORT="exit $? -- $(tail -n 1 "$BROWSER_LOG")"
fi
echo "gate: browser tier (reported, not gating): $BROWSER_REPORT"

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
