#!/bin/bash
# A composition's CG run has nothing to score, and this stage says so instead of printing a number.
#
# `ff_assess` scores a CG trajectory against atomistic reference distributions a fitted parameterization measured.
# A composition's parameterization is derived from the tail recipe and the head fragment's published Martini 3 terms,
# and no atomistic trajectory of this molecule was ever mapped, so there is no reference distribution to compare
# against. The contract's fourth outcome is `skipped` (exit 4 plus `skip.json`); a fabricated score or an all-zero
# matrix would read like a measurement.
set -euo pipefail

printf '%s\n' '{"stage":"CG assessment","reason":"no AA reference distribution to score against","executed":false,"skipped":true,"scientifically_validated":false}' > skip.json
exit 4
