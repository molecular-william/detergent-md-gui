#!/bin/bash
# CG production for a protein-detergent complex: the sampling the micelle criterion is judged on.
#
# Production only. The three legs in front of this stage -- `2_minimisation`, `3_nvt`, `4_npt` -- solvate, minimise
# and equilibrate the built system, and this stage samples the system the NPT leg left. It used to do all of that
# itself from `1_system/system.gro`, so a run equilibrated twice and the legs' own output fed nothing.
#
# The system is copied in by the prelude the pdc adapter emits from this stage's own declaration, which is why the
# grompp below names `system.gro` and `system.top` rather than a path into `4_npt`.
#
# The mdrun budget and the scheme choices arrive as environment -- MDRUN_LAUNCHER is an mpirun prefix or empty,
# MDRUN_FLAGS the flags -- because these stages are scripts rather than generated commands. The defaults below are
# this host's: an 8-thread MPI-only GROMACS with one GPU.
#
# No -ntmpi anywhere: /usr/local/gromacs/2026.3/bin/gmx is a symlink to gmx_mpi, an MPI build with no thread-MPI,
# where that flag aborts mdrun before the first step. -ntomp is valid for both builds.
set -euxo pipefail

mkdir -p prod
# The velocities the NPT leg equilibrated are in its checkpoint, and a leg the run asked none of leaves none: the
# file is read when it is there rather than declared as an input no skip path could satisfy.
if [ -f ../4_npt/system.cpt ]; then CHECKPOINT="-t ../4_npt/system.cpt"; else CHECKPOINT=""; fi
gmx grompp -f assessment.mdp -p system.top -c system.gro $CHECKPOINT -o prod/run.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm prod/run ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v

# The trajectory is written molecule-whole below, because the criterion and the viewer both need molecules that
# have not been broken at periodic boundaries, and reading them back whole is what makes a snapshot reproducible.
# Two answers, not one: `-center` asks which group to centre on and then which group to write, and a single answer
# leaves the second prompt reading EOF -- "Fatal error: Cannot read from input" -- after the MD has already run.
printf 'System\nSystem\n' | gmx trjconv -f prod/run.xtc -s prod/run.tpr -pbc mol -center -o prod/whole.xtc
printf 'System\n' | gmx trjconv -f prod/whole.xtc -s prod/run.tpr -dump 0 -o prod/start.gro

# The series through the phase: the frames and, with each one, the numbers the criterion gives at that moment.
python pdc_snapshot.py --settings ../1_system/pdc-settings.json --stage . --phase assessment \
  --trajectory prod/whole.xtc --tpr prod/run.tpr
