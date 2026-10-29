#!/bin/bash
# The screening stub for a composition run's SASA stage: no surface was computed, and the file says so. A repository
# script now, recorded in `stage_scripts`, rather than code written into the run at prepare time.
set -euo pipefail

printf '{"stage":"CG SASA","executed":false,"execution_kind":"screening-stub"}\n' > sasa.json
