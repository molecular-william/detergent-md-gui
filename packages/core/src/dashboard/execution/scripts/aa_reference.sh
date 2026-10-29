#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
# Run-local SwissParam/CHARMM reference; retain all logs and full-system outputs.
#
# The mdrun budget, the device and the scheme choices arrive as environment, from the one builder that reads
# `mdrun_gpu` (`aa.mdrun_command_flags`): MDRUN_LAUNCHER is an mpirun prefix or empty, MDRUN_FLAGS the minimisation
# bracket, MDRUN_FLAGS_PME the dynamics bracket (PME on the GPU, which this launcher has always asked for). The
# defaults are the case with no executor and no device named -- threads only -- because a device written here
# would be a second opinion about which GPU the run used.
#
# No -ntmpi anywhere: /usr/local/gromacs/2026.3/bin/gmx is a symlink to gmx_mpi, an MPI build with no
# thread-MPI, where that flag aborts mdrun before the first step. -ntomp is valid for both builds; extra ranks
# need mpirun, which MDRUN_LAUNCHER supplies.
set -euxo pipefail
cp system_EMPTY.top system.top
gmx editconf -f molecule.pdb -d 1.5 -c -bt dodecahedron -o boxed.gro
gmx grompp -f em.mdp -c boxed.gro -p system.top -o vacuum.tpr
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm vacuum ${MDRUN_FLAGS:--ntomp 8} -v
gmx solvate -cp vacuum.gro -cs spc216.gro -p system.top -o solvated.gro
gmx grompp -f em.mdp -c solvated.gro -p system.top -o 1-em.tpr
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm 1-em ${MDRUN_FLAGS:--ntomp 8} -v
gmx grompp -f eq.mdp -c 1-em.gro -p system.top -o 2-eq.tpr
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm 2-eq ${MDRUN_FLAGS_PME:--ntomp 8} -v
gmx grompp -f run.mdp -c 2-eq.gro -t 2-eq.cpt -p system.top -o 3-run.tpr
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm 3-run ${MDRUN_FLAGS_PME:--ntomp 8} -v
mkdir prod
printf 'LIG1\nLIG1\n' | gmx trjconv -f 3-run.xtc -s 3-run.tpr -pbc mol -center -o prod/lig.xtc
printf 'LIG1\n' | gmx convert-tpr -s 3-run.tpr -o prod/lig.tpr
printf 'System\n' | gmx trjconv -f prod/lig.xtc -s prod/lig.tpr -dump 0 -o prod/lig.gro
