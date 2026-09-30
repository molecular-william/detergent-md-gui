#!/bin/bash
# CG assessment phase for a protein-detergent complex: solvent, ions, then the sampling the micelle criterion is
# judged on.
#
# The mdrun budget and the scheme choices arrive as environment -- MDRUN_LAUNCHER is an mpirun prefix or empty,
# MDRUN_FLAGS the flags -- because these stages are scripts rather than generated commands. The defaults below are
# this host's: an 8-thread MPI-only GROMACS with one GPU.
#
# No -ntmpi anywhere: /usr/local/gromacs/2026.3/bin/gmx is a symlink to gmx_mpi, an MPI build with no thread-MPI,
# where that flag aborts mdrun before the first step. -ntomp is valid for both builds.
#
# Solvation is not restated here: pdc_solvate.py calls pdc_solvation, which is the tested place that decides the
# water bead radius, the ion names and the group genion may replace.
set -euxo pipefail

python pdc_solvate.py --topology system.top --structure ../1_system/system.gro

gmx grompp -f minimization.mdp -p system.top -c system.gro -o min.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm min ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v

gmx grompp -f equilibration.mdp -p system.top -c min.gro -o eq.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm eq ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v

mkdir -p prod
gmx grompp -f assessment.mdp -p system.top -c eq.gro -t eq.cpt -o prod/run.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm prod/run ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v

# The trajectory is written molecule-whole below, because the criterion and the viewer both need molecules that
# have not been broken at periodic boundaries, and reading them back whole is what makes a snapshot reproducible.
printf 'System\n' | gmx trjconv -f prod/run.xtc -s prod/run.tpr -pbc mol -center -o prod/whole.xtc
printf 'System\n' | gmx trjconv -f prod/whole.xtc -s prod/run.tpr -dump 0 -o prod/start.gro

# The series through the phase: the frames and, with each one, the numbers the criterion gives at that moment.
python pdc_snapshot.py --settings ../1_system/pdc-settings.json --stage . --phase assessment \
  --trajectory prod/whole.xtc --tpr prod/run.tpr
