#!/bin/bash
# One CG-only sugar run: the published Martini topology, the AA-mapped start, one molecule in Martini water.
#
# The build and the two equilibration legs are the same command sequence `cg_simulation.sh` runs for the CG half of
# an AA-to-CG run; the difference is only where the inputs come from. This run type has no `2_mapping/` or
# `3_initial_CG/`: `prepare` wrote the mapped coordinates, the published topology, the system and the reviewed MDPs
# into the run's shared `inputs/` record, and this script reads them there.
set -euxo pipefail
PROJECT_ROOT="${PROJECT_ROOT:?PROJECT_ROOT must name the checkout}"
WATER_BOX="$PROJECT_ROOT/resources/templates/small_mols_fast_forward/4_CG_sim/inputs/water.gro"
# MDRUN_FLAGS is the equilibration/production bracket; MDRUN_FLAGS_AUTO is the minimisation one.

# A resumed stage names production's own checkpoint; the build, the solvation and the two equilibration legs already
# happened in this directory, so only the production leg re-runs, appending to the trajectory it was writing.
if [ -n "${MDRUN_CONTINUE:-}" ]; then
  gmx mdrun -deffnm md -cpi "$MDRUN_CONTINUE" -append ${MDRUN_FLAGS:--ntomp 8} -v
  exit 0
fi

gmx editconf -f ../../inputs/sugar.gro -c -d 1.5 -bt dodecahedron -o boxed.gro
gmx solvate -cp boxed.gro -cs "$WATER_BOX" -p ../../inputs/system.top -radius 0.21 -o solvated.gro
gmx grompp -f ../../inputs/minimization.mdp -p ../../inputs/system.top -c solvated.gro -o min.tpr
gmx mdrun -deffnm min ${MDRUN_FLAGS_AUTO:--ntomp 8} -v
gmx grompp -f ../../inputs/eq.mdp -p ../../inputs/system.top -c min.gro -o eq.tpr -maxwarn 1
gmx mdrun -deffnm eq ${MDRUN_FLAGS:--ntomp 8} -v
gmx grompp -f ../../inputs/md.mdp -p ../../inputs/system.top -c eq.gro -t eq.cpt -o md.tpr -maxwarn 1
gmx mdrun -deffnm md ${MDRUN_FLAGS:--ntomp 8} -v

mkdir -p prod
printf '%s\n%s\n' "${MOLECULE_TYPE:-SUCR}" "${MOLECULE_TYPE:-SUCR}" | \
  gmx trjconv -f md.xtc -s md.tpr -pbc mol -center -o prod/lig_CG.xtc
printf '%s\n' "${MOLECULE_TYPE:-SUCR}" | gmx convert-tpr -s md.tpr -o prod/lig_CG.tpr
printf 'System\n' | gmx trjconv -f prod/lig_CG.xtc -s prod/lig_CG.tpr -dump 0 -o prod/lig_CG.gro
