#!/bin/bash
# CG production for a protein-detergent complex: the sampling the micelle criterion is judged on.
#
# Production only. The three legs in front of this stage -- `03_minimisation`, `04_nvt`, `05_npt` -- solvate, minimise
# and equilibrate the built system, and this stage samples the system the NPT leg left. It used to do all of that
# itself from `02_system/system.gro`, so a run equilibrated twice and the legs' own output fed nothing.
#
# The system is copied in here from the phase before it, which stays immutable. Only the writable working copy moves:
# the topology names the detergent's, the protein's `cg/` tree and the installed Martini 3 set where they already are,
# by paths relative to this stage, so this stage copies none of them.
#
# The mdrun budget, the device and the scheme choices arrive as environment -- MDRUN_LAUNCHER is an mpirun
# prefix or empty, MDRUN_FLAGS the flags -- because this stage is a script rather than a generated command. The
# default below is the case with no executor and no device named, threads only: the device is decided in one
# place (`aa.mdrun_command_flags`, from `mdrun_gpu`), so this file states no second opinion about it.
#
# No -ntmpi anywhere: /usr/local/gromacs/2026.3/bin/gmx is a symlink to gmx_mpi, an MPI build with no thread-MPI,
# where that flag aborts mdrun before the first step. -ntomp is valid for both builds.
set -euxo pipefail

# The interpreter the application runs under, and the repository it imports from. `python` on the stage PATH is this
# workspace's virtualenv (`tools.search_path` puts it first); a caller that exports PYTHON/PROJECT_ROOT wins.
PYTHON="${PYTHON:-python}"
REPO_ROOT="${PROJECT_ROOT:-$("$PYTHON" -c 'from dashboard import paths; print(paths.PROJECT_ROOT)')}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# The NPT leg's system is the one this stage samples; it is copied in rather than read where it lies, because the
# phase before this one is immutable.
cp -f ../05_npt/system.gro ../05_npt/system.top .
mkdir -p prod
cp -f ../../inputs/assessment.mdp .

# The velocities the NPT leg equilibrated are in its checkpoint, and a leg the run asked none of leaves none: the
# file is read when it is there rather than declared as an input no skip path could satisfy.
if [ -f ../05_npt/system.cpt ]; then CHECKPOINT="-t ../05_npt/system.cpt"; else CHECKPOINT=""; fi
gmx grompp -f assessment.mdp -p system.top -c system.gro $CHECKPOINT -o prod/run.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm prod/run ${MDRUN_FLAGS:--ntomp 8} -v

# The trajectory is written molecule-whole below, because the run view's segments need molecules that have not
# been broken at periodic boundaries.
# Two answers, not one: `-center` asks which group to centre on and then which group to write, and a single answer
# leaves the second prompt reading EOF -- "Fatal error: Cannot read from input" -- after the MD has already run.
printf 'System\nSystem\n' | gmx trjconv -f prod/run.xtc -s prod/run.tpr -pbc mol -center -o prod/whole.xtc
