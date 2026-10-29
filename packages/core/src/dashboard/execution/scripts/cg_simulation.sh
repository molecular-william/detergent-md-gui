#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
set -euxo pipefail
# The interpreter the application runs under, and the checkout it imports from; the water box below is a published
# file read where it lives, so nothing has to be linked or copied into the stage.
PYTHON="${PYTHON:-python}"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
WATER_BOX="$PROJECT_ROOT/resources/templates/small_mols_fast_forward/4_CG_sim/inputs/water.gro"
# The mdrun budget, the device and the scheme choices arrive as environment, because these stages are scripts
# rather than commands the adapter generates: MDRUN_LAUNCHER is an mpirun prefix or empty, MDRUN_FLAGS the
# flags. The default below is the case with no executor and no device named -- threads only -- because the
# device is decided in one place (`aa.mdrun_command_flags`, from `mdrun_gpu`) and a second copy here would be a
# second opinion about which GPU this run used.
# No -ntmpi anywhere: /usr/local/gromacs/2026.3/bin/gmx is a symlink to gmx_mpi, an MPI build with no
# thread-MPI, where that flag aborts mdrun before the first step. -ntomp is valid for both builds.
# Fitted output is copied forward; the seed topology and reference stay immutable.
cp ../3_initial_CG/$FINAL_ITP $FINAL_ITP
# ff_inter can fit numerically extreme bond force constants that make the
# short draft system unstable. Cap only pathological fitted bonds before the
# exploratory CG run; the original fitted topology remains preserved upstream.
"$PYTHON" - "$FINAL_ITP" <<'PY'
from pathlib import Path
import sys
if Path('../2_mapping/ring_targets.json').is_file():
    raise SystemExit(0)  # paper topology retains fitted link constants; no silent capping
p = Path(sys.argv[1])
lines = p.read_text().splitlines()
in_bonds = False
for i, line in enumerate(lines):
    s = line.split(';', 1)[0].split()
    if line.strip().startswith('['):
        in_bonds = line.strip().lower() == '[ bonds ]'
    elif in_bonds and len(s) >= 5 and s[0].isdigit() and s[1].isdigit():
        try:
            if float(s[4]) > 50000:
                s[4] = '50000'
                comment = (' ;' + line.split(';', 1)[1]) if ';' in line else ''
                lines[i] = ' '.join(s) + comment
        except ValueError:
            pass
p.write_text('\n'.join(lines) + '\n')
PY
cp system_EMPTY.top system.top
CG_START=../2_mapping/mapped.gro
if [ -f ../2_mapping/mapped_scaled.gro ]; then CG_START=../2_mapping/mapped_scaled.gro; fi
gmx editconf -f "$CG_START" -c -d 1.5 -bt dodecahedron -o boxed.gro
gmx solvate -cp boxed.gro -cs "$WATER_BOX" -p system.top -radius 0.21 -o solvated.gro
gmx grompp -f inputs/minimization.mdp -p system.top -c solvated.gro -o min.tpr
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm min ${MDRUN_FLAGS:--ntomp 8} -v
gmx grompp -f inputs/eq.mdp -p system.top -c min.gro -o eq.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm eq ${MDRUN_FLAGS:--ntomp 8} -v
gmx grompp -f inputs/md.mdp -p system.top -c eq.gro -t eq.cpt -o md.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm md ${MDRUN_FLAGS:--ntomp 8} -v
mkdir prod
printf "$MOLECULE_TYPE\n$MOLECULE_TYPE\n" | gmx trjconv -f md.xtc -s md.tpr -pbc mol -center -o prod/lig_CG.xtc
printf "$MOLECULE_TYPE\n" | gmx convert-tpr -s md.tpr -o prod/lig_CG.tpr
printf 'System\n' | gmx trjconv -f prod/lig_CG.xtc -s prod/lig_CG.tpr -dump 0 -o prod/lig_CG.gro
