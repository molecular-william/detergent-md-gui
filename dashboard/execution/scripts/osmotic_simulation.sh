#!/bin/bash
# One osmotic-pressure condition, end to end: place the solute in the slab, put a frozen reference bead at the box
# centre, solvate, and run the three stages the adapter wrote mdps for.
#
# The method is the paper's: the solute is confined to the middle of a fixed box by a flat-bottomed potential
# (2.52078 nm from the centre, 1000 kJ/mol/nm2 beyond it), pressure is coupled only in z, and the osmotic pressure
# comes from the force the solute exerts on those walls divided by the xy area. The force is NOT read from this run's
# pull machinery -- the analysis recomputes it from the trajectory -- so what this has to get right is the geometry:
# the box, the slab, and a reference whose centre of mass IS the box centre.
#
# Three substitutions or choices from the paper, recorded rather than hidden:
#   * the paper builds the initial configuration with polyply; this samples positions inside the slab itself, which is
#     the tool this repository already has, and it reports the minimum separation it actually achieved.
#   * the paper's systems are binary sugar-water. No ions are added, because the osmometry it compares against
#     measured salt-free solutions.
#   * the index file is written HERE and not by the adapter: the pull's groups are atom indices, and the indices are
#     not known until the molecules have been placed.
#
# Inputs, in the working directory:
#   minimization.mdp eq.mdp md.mdp   from dashboard.execution.adapters.osmotic
#   reference.itp osmotic_condition.json
#   solute/                          ONE solute molecule: solute.gro, solute.itp, and the includes it needs
# Environment:
#   SOLUTE_DIR, MDRUN_LAUNCHER, MDRUN_FLAGS, GROMACS -- as cg_simulation.sh
GROMACS="${GROMACS:-/usr/local/gromacs/2026.3/bin/gmx}"
SOLUTE_DIR="${SOLUTE_DIR:-solute}"
export PATH="$(dirname "$GROMACS"):$PATH"
set -euxo pipefail

# 1. The box the paper states, and the molecules placed in the slab it implies. The manifest's counts are used as
#    written: the analysis divides by the area in that file, so a second derivation here would be a second opinion.
python - "$SOLUTE_DIR" "$PWD" <<'PY'
import json
import random
import sys
from pathlib import Path

solute_dir, workdir = Path(sys.argv[1]), Path(sys.argv[2])
manifest = json.loads((workdir / 'osmotic_condition.json').read_text())
box = manifest['box_nm']
count = int(manifest['solute_molecules'])
half = manifest['confinement_nm'] - 0.5          # a margin, so no bead is asked to sit in a wall

molecule = (solute_dir / 'solute.gro').read_text().splitlines()
header, atoms = molecule[0], [line for line in molecule[2:-1] if line.strip()]
if not atoms:
    raise SystemExit(f'{solute_dir / "solute.gro"} has no atoms')

rng = random.Random(20261006)
# Rejection sampling with a floor on the separation: the paper's polyply does this properly, and this reports what it
# actually managed rather than assuming it succeeded.
floor = 0.7
placed, closest = [], 0.0
for _ in range(count):
    for _attempt in range(200):
        position = [rng.uniform(1.0, box[0] - 1.0), rng.uniform(1.0, box[1] - 1.0),
                    box[2] / 2 + rng.uniform(-half, half)]
        if all(sum((a - b) ** 2 for a, b in zip(position, other)) > floor ** 2 for other in placed):
            break
    else:
        position = [rng.uniform(1.0, box[0] - 1.0), rng.uniform(1.0, box[1] - 1.0),
                    box[2] / 2 + rng.uniform(-half, half)]
    placed.append(position)

for other in placed:
    distances = [sum((a - b) ** 2 for a, b in zip(other, point)) ** 0.5 for point in placed if point is not other]
    if distances:
        closest = min(closest, min(distances)) if closest else min(distances)

lines = ['placed solute and reference', f'{len(atoms) * count + 1:5d}']
serial = 0
for position in placed:
    for atom in atoms:
        serial += 1
        # The .gro atom line is a 15-character prefix (residue 5, atom 5, serial 5) and then three coordinates.
        # The input line's own prefix is copied verbatim, which keeps its residue and atom names.
        lines.append(f'{atom[:15]:<15}{position[0]:8.3f}{position[1]:8.3f}{position[2]:8.3f}')
# the reference bead, at the exact centre
serial += 1
lines.append(f'{"    1REFC":<10}{"REF":<5}{serial:5d}{box[0] / 2:8.3f}{box[1] / 2:8.3f}{box[2] / 2:8.3f}')
lines.append(f'{box[0]:10.5f}{box[1]:10.5f}{box[2]:10.5f}')
(workdir / 'system.gro').write_text('\n'.join(lines) + '\n')

record = {'solute_molecules_placed': count, 'solute_atoms_in_system': len(atoms) * count,
          'reference_atom': len(atoms) * count + 1, 'water_atoms': 0,
          'min_separation_achieved_nm': round(closest, 4),
          'min_separation_target_nm': floor,
          'box_nm': box, 'gate_met': closest >= floor}
(workdir / 'placement.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
print('placement:', record['solute_molecules_placed'], 'molecules, closest', record['min_separation_achieved_nm'],
      'nm against a', floor, 'nm target')
PY

# 2. The index file, now that the indices exist. Written with the adapter's own function rather than by hand, so the
#    groups the pull reads are the groups it validates. REPO_ROOT is where `dashboard` can be imported from; the
#    adapter that runs this script passes it, and the default assumes the executor's working directory is the repo.
REPO_ROOT="${REPO_ROOT:-.}"
# Exported once, for every `python` block below: the executor runs a stage with the *stage directory* as its working
# directory, so `import dashboard` from `.` fails unless the root is on the path for all of them, not just the first.
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
python - "$PWD" <<'PY'
import json
import sys
from pathlib import Path

from dashboard.execution.adapters import osmotic

workdir = Path(sys.argv[1])
placement = json.loads((workdir / 'placement.json').read_text())
solute = range(1, placement['solute_atoms_in_system'] + 1)
(workdir / 'index.ndx').write_text(osmotic.index_groups(
    solute_atoms=solute, reference_atom=placement['reference_atom']))
print('index: SOLUTE 1-%d, REFERENCE %d' % (placement['solute_atoms_in_system'], placement['reference_atom']))
PY

# 3. The topology: the force field, the solute, the reference and the water, with the counts between them. `solvate`
#    fills the water count in [ molecules ] itself, which is why that line starts at zero.
cat > system.top <<TOP
#include "martini_v3.0.0.itp"
#include "$SOLUTE_DIR/solute.itp"
#include "reference.itp"
#include "$SOLUTE_DIR/martini_v3.0.0_solvents_v1.itp"

[ system ]
osmotic condition

[ molecules ]
SOL   $(python -c "import json;print(json.load(open('placement.json'))['solute_molecules_placed'])")
REFC  1
W     0
TOP

# 4. Solvent fills what the solute and the reference do not. The water count that follows is the one the molality is
#    actually made of, so it is recorded and compared with what the box predicted.
gmx solvate -cp system.gro -cs "$SOLUTE_DIR/water.gro" -p system.top -radius 0.21 -o solvated.gro

# 5. The stages. -n names the groups for freezegrps and for the pull alike.
gmx grompp -f minimization.mdp -p system.top -c solvated.gro -n index.ndx -o min.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm min ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v
gmx grompp -f eq.mdp -p system.top -c min.gro -n index.ndx -t min.cpt -o eq.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm eq ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v
gmx grompp -f md.mdp -p system.top -c eq.gro -n index.ndx -t eq.cpt -o md.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm md ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v

# 6. The trajectory the analysis reads, and the counts it should be told were actually built. The build predicted
#    them; a prediction is not a substitute for the number, and the difference is the whole reason molality is
#    reported as achieved rather than requested.
mkdir -p prod
printf 'System\n' | gmx trjconv -f md.xtc -s md.tpr -pbc mol -o prod/md_whole.xtc
python - <<'PY'
import json
import re
from pathlib import Path

condition = json.loads(Path('osmotic_condition.json').read_text())
placement = json.loads(Path('placement.json').read_text())
topology = Path('system.top').read_text()
water = re.search(r'^W\s+(\d+)\s*$', topology, re.M)
built = {'water_beads_solvated': int(water.group(1)) if water else None,
         **{key: placement[key] for key in ('solute_molecules_placed', 'min_separation_achieved_nm', 'gate_met')}}
if built['water_beads_solvated']:
    grams = built['water_beads_solvated'] * (condition['water_bead_mass'] / 1000.0) / 6.02214076e23
    built['molality_from_what_was_built'] = built['solute_molecules_placed'] / 6.02214076e23 / grams
Path('built.json').write_text(json.dumps(
    {'predicted': {'water_beads': condition['water_beads'],
                   'solute_molecules': condition['solute_molecules'],
                   'molality_achieved': condition['molality_achieved'],
                   'dividing_area_nm2': condition['dividing_area_nm2']},
     'actual': built}, indent=2, sort_keys=True) + '\n')
PY
