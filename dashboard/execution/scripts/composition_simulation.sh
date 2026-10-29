#!/bin/bash
# The screening stub for a composition run's CG simulation.
#
# **It integrates nothing, and it says so.** The file this used to be a generated copy of copied `composition.gro`
# into `cg.gro` and wrote a `screening.json` declaring the stage did not execute -- which is the whole contract of a
# screening run. It is a repository script now, recorded in the manifest's `stage_scripts`, and it reads the artifact's
# recorded path from the run's own `inputs/inputs.json` rather than from a path stamped into it at prepare time: the
# artifact is referenced, never copied into the run.
set -euo pipefail

PYTHON="${PYTHON:-python}"
REPO_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

COMPOSITION_GRO="$("$PYTHON" -c "
import json
from pathlib import Path

from dashboard.execution import run_inputs

record = json.loads(Path('../../inputs/inputs.json').read_text())
entry = next(item for item in record['inputs'] if item['label'] == 'composition.gro')
print(run_inputs.resolve(entry))
")"
cp "$COMPOSITION_GRO" cg.gro
printf '{"stage":"CG simulation","executed":false,"execution_kind":"screening-stub"}\n' > screening.json
