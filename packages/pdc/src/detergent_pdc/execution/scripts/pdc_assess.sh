#!/bin/bash
# Micelle assessment for a protein-detergent complex phase: `07_micelle_assessment` and `09_final_assessment`.
#
# The criterion, the tail beads and the aggregation number are not restated here: pdc_assess reads the run's own
# settings and calls pdc_assessment, which is the one implementation of the design spec's §7. This stage writes
# assessment.json (the numbers behind the verdict), kept.gro (what stays if the rest is removed) and removed.json
# (what a removal decision would act on).
#
# The structure it judges is copied in from the phase before it: the production leg's when the micelle is judged, and
# the extension's when the final assessment is. A run with out-of-micelle removal off has neither stage.
set -euxo pipefail

# The interpreter the application runs under, and the repository it imports from. `python` on the stage PATH is this
# workspace's virtualenv (`tools.search_path` puts it first); a caller that exports PYTHON/PROJECT_ROOT wins.
PYTHON="${PYTHON:-python}"
REPO_ROOT="${PROJECT_ROOT:-$("$PYTHON" -c 'from dashboard import paths; print(paths.PROJECT_ROOT)')}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

SOURCE=../06_assessment
if [ -f ../08_extension/prod/run.gro ]; then
  SOURCE=../08_extension
fi
mkdir -p prod
cp -f "$SOURCE/prod/run.gro" prod/run.gro

"$PYTHON" -m detergent_pdc.execution.scripts.pdc_assess --settings ../../inputs/pdc-settings.json --structure prod/run.gro
