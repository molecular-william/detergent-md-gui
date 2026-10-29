#!/bin/bash
# CG extension phase for a protein-detergent complex: continue the assessment phase's trajectory for the second
# duration, so the whole sampling is the stated 1 us rather than 100 ns.
#
# The assessment phase's own outputs are immutable, so they are copied in under the names mdrun needs for a
# continue: `convert-tpr -extend` writes the new end time into a copy of the phase's tpr, and `-cpi` continues from
# the phase's checkpoint. This stage's trajectory holds the extension's frames; the production phase's frames stay
# in `06_assessment`, and the run view reads both legs as segments (`GET /api/jobs/<id>/trajectory`).
#
# The mdrun budget arrives as environment, as in the assessment phase, and no -ntmpi appears in the executed lines:
# gmx here is an mpi-only build where that flag aborts mdrun before the first step.
set -euxo pipefail

# The interpreter the application runs under, and the repository it imports from. `python` on the stage PATH is this
# workspace's virtualenv (`tools.search_path` puts it first); a caller that exports PYTHON/PROJECT_ROOT wins.
PYTHON="${PYTHON:-python}"
REPO_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# The system this phase extends is the production phase's, and the decision about what to remove is the micelle
# assessment's. Both phases are immutable, so the files this stage edits are copies. Only the writable working copy
# moves: the topology it carries names the detergent's, the protein's `cg/` tree and the Martini 3 set where they
# already are, by a path relative to this stage -- so this stage copies none of them.
cp -f ../06_assessment/system.gro ../06_assessment/system.top .
mkdir -p prod inputs
cp -f ../../inputs/extension.mdp ../../inputs/extension.ps ../../inputs/minimization.mdp \
      ../../inputs/equilibration.mdp ../../inputs/ions.mdp .
cp -f ../../inputs/water.gro inputs/water.gro

# Both paths -- continue from the assessment's checkpoint, or delete what the criterion left outside the micelle and
# restart from the kept system with new velocities -- are the helper's, because the difference is a decision rather
# than a command: it reads the assessment's own removal record and the run's settings and does the one they imply.
"$PYTHON" -m dashboard.execution.scripts.pdc_extension --settings ../../inputs/pdc-settings.json --stage . \
  --assessment ../07_micelle_assessment --assessment-stage ../06_assessment
# `-center` asks twice: the group to centre on, then the group to write. One answer reads EOF on the second.
printf 'System\nSystem\n' | gmx trjconv -f prod/run.xtc -s prod/run.tpr -pbc mol -center -o prod/whole.xtc
