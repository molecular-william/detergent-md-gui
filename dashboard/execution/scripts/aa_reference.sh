#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
# Run-local SwissParam/CHARMM reference; retain all logs and full-system outputs.
# No -ntmpi in the mdrun lines below: /usr/local/gromacs/2026.3/bin/gmx is a symlink to gmx_mpi, an MPI build
# with no thread-MPI, where -ntmpi aborts mdrun before the first step. -ntomp is valid for both builds; extra
# MPI ranks need mpirun, which the adapter's mdrun_launch arranges -- this legacy launcher runs a single rank.
set -euxo pipefail
cp system_EMPTY.top system.top
gmx editconf -f molecule.pdb -d 1.5 -c -bt dodecahedron -o boxed.gro
gmx grompp -f em.mdp -c boxed.gro -p system.top -o vacuum.tpr
gmx mdrun -deffnm vacuum -ntomp 8 -gpu_id 0 -nb gpu -pin on -v
gmx solvate -cp vacuum.gro -cs spc216.gro -p system.top -o solvated.gro
gmx grompp -f em.mdp -c solvated.gro -p system.top -o 1-em.tpr
gmx mdrun -deffnm 1-em -ntomp 8 -gpu_id 0 -nb gpu -pin on -v
gmx grompp -f eq.mdp -c 1-em.gro -p system.top -o 2-eq.tpr
gmx mdrun -deffnm 2-eq -ntomp 8 -gpu_id 0 -nb gpu -pme gpu -pmefft gpu -pin on -v
gmx grompp -f run.mdp -c 2-eq.gro -t 2-eq.cpt -p system.top -o 3-run.tpr
gmx mdrun -deffnm 3-run -ntomp 8 -gpu_id 0 -nb gpu -pme gpu -pmefft gpu -pin on -v
mkdir prod
printf 'LIG1\nLIG1\n' | gmx trjconv -f 3-run.xtc -s 3-run.tpr -pbc mol -center -o prod/lig.xtc
printf 'LIG1\n' | gmx convert-tpr -s 3-run.tpr -o prod/lig.tpr
printf 'System\n' | gmx trjconv -f prod/lig.xtc -s prod/lig.tpr -dump 0 -o prod/lig.gro
