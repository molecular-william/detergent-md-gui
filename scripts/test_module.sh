#!/usr/bin/env bash
# Run one distribution's tests. Usage: scripts/test_module.sh <core|validation|pdc|all> [fast|browser|slow]
#
# The module is the tree: `packages/<module>/tests`. `core` is the engine's own tests, `validation`/`pdc` the tests
# of the panels, analyses and pipelines each feature ships. The install still contains every feature -- these are
# selections, not isolated environments, and the `-m <module>` markers remain as the alias for the same selection.
set -euo pipefail
usage() { echo "usage: $0 <core|validation|pdc|all> [fast|browser|slow]" >&2; exit 2; }
[ $# -ge 1 ] || usage
module="$1"; tier="${2:-fast}"
case "$module" in core|validation|pdc|all) ;; *) usage ;; esac
case "$tier" in
  fast)    selection="not browser and not slow"; parallel=(-n 8 --dist loadfile) ;;
  browser) selection="browser";                 parallel=(-n 8 --dist worksteal) ;;
  slow)    selection="slow";                    parallel=(-n 0) ;;
  *) usage ;;
esac
expression="$selection"
if [ "$module" != all ]; then expression="$module and $selection"; fi
export MPLCONFIGDIR="${MPLCONFIGDIR:-$(mktemp -d)}"
target=()
if [ "$module" != all ]; then target=("packages/$module/tests"); fi
echo "pytest ${target[*]} -m '$expression' ${parallel[*]}" >&2
exec .venv/bin/python -m pytest "${target[@]}" -m "$expression" -q -p no:cacheprovider "${parallel[@]}"
