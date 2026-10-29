#!/bin/bash
# The screening stub for a composition run's CG assessment: it is handed the stage before it and writes only the
# declaration that no assessment was executed. Kept as a repository script, recorded in `stage_scripts`, so the run
# holds no code of its own.
set -euo pipefail

printf '{"status":"screened","executed":false,"execution_kind":"screening-stub","scientifically_validated":false}\n' > validation.json
