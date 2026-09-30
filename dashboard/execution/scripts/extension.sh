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

mkdir -p prod
for name in run.tpr run.cpt run.xtc run.gro; do
  cp "../2_assessment/prod/$name" "$name"
done

# The extension length is the run's own setting, written beside this stage by the adapter rather than restated
# here: it is picoseconds, because that is what convert-tpr -extend takes.
EXTENSION_PS="$(cat extension.ps)"

gmx convert-tpr -s run.tpr -extend "$EXTENSION_PS" -o prod/run.tpr
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm run -cpi run.cpt ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v

cp run.gro prod/run.gro
cp run.xtc prod/run.xtc
printf 'System\n' | gmx trjconv -f prod/run.xtc -s prod/run.tpr -pbc mol -center -o prod/whole.xtc

# The same series for the extension phase, judged by the same function: the two phases' frames are comparable
# because nothing about the sampling or the criterion changes between them.
python pdc_snapshot.py --settings ../1_system/pdc-settings.json --stage . --phase extension \
  --trajectory prod/whole.xtc --tpr prod/run.tpr
