#!/bin/bash
# CG extension phase for a protein-detergent complex: continue the assessment phase's trajectory for the second
# duration, so the whole sampling is the stated 1 us rather than 100 ns.
#
# The assessment phase's own outputs are immutable, so they are copied in under the names mdrun needs for a
# continue: `convert-tpr -extend` writes the new end time into a copy of the phase's tpr, and `-cpi` continues from
# the phase's checkpoint. This stage's trajectory holds the extension's frames; the assessment phase's frames stay
# in 2_assessment, and a series across both phases is the snapshot work's job, not this script's.
#
# The mdrun budget arrives as environment, as in the assessment phase, and no -ntmpi appears in the executed lines:
# gmx here is an mpi-only build where that flag aborts mdrun before the first step.
set -euxo pipefail

# Both paths -- continue from the assessment's checkpoint, or delete what the criterion left outside the micelle and
# restart from the kept system with new velocities -- are the helper's, because the difference is a decision rather
# than a command: it reads the assessment's own removal record and the run's settings and does the one they imply.
python pdc_extension.py --settings ../1_system/pdc-settings.json --stage . \
  --assessment ../3_assessment --assessment-stage ../2_assessment
# `-center` asks twice: the group to centre on, then the group to write. One answer reads EOF on the second.
printf 'System\nSystem\n' | gmx trjconv -f prod/run.xtc -s prod/run.tpr -pbc mol -center -o prod/whole.xtc

# The same series for the extension phase, judged by the same function: the two phases' frames are comparable
# because nothing about the sampling or the criterion changes between them.
# `--start` names the structure this phase began from: the restart path rebuilds the system and never writes the
# `prod/start.gro` the assessment path leaves behind, so without it a phase shorter than the cadence records nothing.
python pdc_snapshot.py --settings ../1_system/pdc-settings.json --stage . --phase extension \
  --trajectory prod/whole.xtc --tpr prod/run.tpr --start system.gro
