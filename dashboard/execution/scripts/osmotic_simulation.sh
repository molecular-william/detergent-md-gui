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

# The molecule's own shape, as offsets from its centroid. A .gro atom line is a 15-character (residue, residue name,
# atom name) prefix, the 5-character atom serial, then x, y and z at 8.3 each -- so the coordinates start at column 20.
# Placement chooses a *point* per molecule, so the molecule keeps its geometry only if each atom is written as that
# point plus its own offset. A first version wrote every bead of a molecule at the same coordinates: the file was five
# characters short per line for want of the serial, and even with that fixed each maltose would have been eight beads
# stacked on one another.
shape = [(line[:15], float(line[20:28]), float(line[28:36]), float(line[36:44])) for line in atoms]
centre = [sum(atom[i] for atom in shape) / len(shape) for i in (1, 2, 3)]
relative = [(prefix, x - centre[0], y - centre[1], z - centre[2]) for prefix, x, y, z in shape]

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
    for prefix, dx, dy, dz in relative:
        serial += 1
        # prefix(15) + serial(5) + x, y, z (8.3 each) = 44 characters, which is what fixed format means.
        lines.append(f'{prefix}{serial:5d}'
                     f'{position[0] + dx:8.3f}{position[1] + dy:8.3f}{position[2] + dz:8.3f}')
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
python - "$PWD" "$SOLUTE_DIR" <<'PY'
import json
import sys
from pathlib import Path

from dashboard.execution.adapters import osmotic

workdir, solute_dir = Path(sys.argv[1]), sys.argv[2]
placement = json.loads((workdir / 'placement.json').read_text())

# The moleculetype the topology declares, which is what `[ molecules ]` has to name it by. It is the molecule's own
# name -- LIG1 for the maltose mapping -- and not something this pipeline chooses: writing `SOL` there is what
# grompp answers with "No such moleculetype SOL".
lines = (workdir / solute_dir / 'solute.itp').read_text().splitlines()
header = next(n for n, line in enumerate(lines) if line.strip().startswith('[ moleculetype'))
name = lines[header + 1].split()[0]
(workdir / 'solute_molecule.txt').write_text(name + '\n')

print('solute: moleculetype %s, %d molecules confined individually'
      % (name, placement['solute_molecules_placed']))
PY

# 3. The topology: the force field, the solute, the reference and the water, with the counts between them.
#
#    **Written from Python, not a heredoc, and that is not style.** This was a `cat` heredoc with the molecule's own
#    name substituted into it by `$(python -c "...")`. A command substitution *inside* an unquoted heredoc is
#    expanded as the heredoc is read, and when it goes wrong bash executes the substituted text: the run that first
#    carried the PLUMED step reported "line 135: LIG1: command not found" and the script then stopped before
#    plumed.dat was ever written. A writer that cannot be re-parsed removes the class, not the instance.
python - "$PWD" "$SOLUTE_DIR" <<'PY'
import json
import sys
from pathlib import Path

workdir, solute_dir = Path(sys.argv[1]), sys.argv[2]
count = json.loads((workdir / 'placement.json').read_text())['solute_molecules_placed']
name = (workdir / 'solute_molecule.txt').read_text().strip()
# **A zero count is not written, and this is not tidiness.** `LIG1  0` in [ molecules ] makes grompp *segfault* --
# not refuse, crash -- because a moleculetype with bonded interactions and no copies has no edges to build. The
# pure-solvent control is exactly that case, so the entry is omitted and the file says why it is absent. The water
# count is appended after the solvent is placed; it cannot be known here.
entries = [f'{name}  {count}'] if count else ['; no solute in this condition: the pure-solvent control']
entries.append('REFC  1')
(workdir / 'system.top').write_text('\n'.join([
    '#include "martini_v3.0.0.itp"',
    '#include "reference.itp"',
    f'#include "{solute_dir}/solute.itp"',
    f'#include "{solute_dir}/martini_v3.0.0_solvents_v1.itp"',
    '',
    '[ system ]',
    'osmotic condition',
    '',
    '[ molecules ]',
    *entries,
]) + '\n')
print('topology: %s' % (entries[0] if count else 'no solute in this condition'))
PY

# 4. Solvent fills what the solute and the reference do not. **The paper's polyply fills the solvent in the entire
#    box; filling it the other way costs the run.** `gmx solvate` tiles its 3.64428 nm configuration and discards the
#    molecules that clash with their own periodic images, arriving 7.2% light even for pure solvent and 18% light with
#    solute (its -radius also strips a shell around 560 beads). At 1 bar the box then contracts to correct that --
#    measured: 10.08 -> 8.17 nm -- until half the box is barely wider than the confined slab, and mdrun's half-box
#    check aborts the run.
#    `insert-molecules` packs to a target instead, rejecting overlaps, so it fills the free volume at the tile's own
#    density and reports how many it managed. The target is the box's own capacity from the condition record; the
#    overlap rejection is what keeps it from over-filling around the solute.
python - "$SOLUTE_DIR" <<'PY'
import pathlib, sys
# One bead, from the tile: insert-molecules inserts the whole configuration it is given, and the tile is 400 beads.
lines = (pathlib.Path(sys.argv[1]) / 'water.gro').read_text().splitlines()
pathlib.Path('water_one.gro').write_text(
    '\n'.join([lines[0], '    1', lines[2], '   1.00000   1.00000   1.00000']) + '\n')
PY
WATER_TARGET="$(python -c "import json;print(json.load(open('osmotic_condition.json'))['water_beads'])")"
gmx insert-molecules -f system.gro -ci water_one.gro -nmol "$WATER_TARGET" -radius 0.05 -try 200 \
    -o solvated.gro > insert.log 2>&1 || { cat insert.log; exit 1; }
grep -E "Added|Could only" insert.log
WATER_ADDED="$(python -c "
import json, pathlib
total = int(pathlib.Path('solvated.gro').read_text().splitlines()[1])
placement = json.loads(pathlib.Path('placement.json').read_text())
print(total - placement['solute_atoms_in_system'] - 1)
")"
printf 'W  %s\n' "$WATER_ADDED" >> system.top
echo "water: $WATER_ADDED beads inserted, target $WATER_TARGET"

# 4b. The index, now that the system is complete. **`System` must cover the solvated atoms**, and passing `-n` replaces
#     GROMACS's own group list rather than adding to it -- so an index written before solvation leaves every water
#     bead outside the thermostat and the first dynamics step fails with "1537 atoms are not part of any of the
#     T-Coupling groups". The pull's groups are the same indices either way: solvate appends.
#     **One group per solute molecule**, named MOL<i> to match the per-molecule coordinates the adapter wrote into the
#     mdps. The adapter used the *planned* count and this uses the *placed* count; if those ever diverge the index
#     cannot name a group the mdp asks for, and grompp says so rather than the run confining something unintended.
python - "$PWD" "$SOLUTE_DIR" <<'PY'
import json
import sys
from pathlib import Path

from dashboard.execution.adapters import osmotic

workdir = Path(sys.argv[1])
placement = json.loads((workdir / 'placement.json').read_text())
total = int((workdir / 'solvated.gro').read_text().splitlines()[1])
reference = placement['reference_atom']
(workdir / 'index.ndx').write_text(osmotic.index_groups(
    solute_atoms=range(1, reference), reference_atom=reference,
    solute_molecules=placement['solute_molecules_placed'],
    solvent_atoms=range(reference + 1, total + 1)))
print('index: System 1-%d, %d MOL groups, REFERENCE %d'
      % (total, placement['solute_molecules_placed'], reference))
PY

# 4c. The confinement, as PLUMED. The paper's potential is *external* -- a flat-bottom at 2.52078 nm from the box
#     centre, k = 1000 kJ/mol/nm2, per solute molecule -- and GROMACS's `pull` is not: it is a spring between two
#     groups, so its coordinate is what it measures and its origin is what it pulls against. Both failed visibly.
#     The coordinate is the *unwrapped* z-difference: it grew to 4.91 nm, nearly half the box, and mdrun's half-box
#     check aborted the run while the trajectory still showed the solute 1.64 nm from the origin, inside the wall.
#     And a coordinate free to pass half the box is a potential free to act on the wrong side of it: once the minimum
#     image flips, a flat-bottom pushes *away*. PLUMED evaluates each wall on an absolute coordinate, referenced to
#     the solvent's centre of mass -- which is the box centre by symmetry, follows the box, and being ~2000 beads
#     absorbs the wall's reaction force as 1/2000 of itself per bead. The pull's origin was a single atom.
python - "$PWD" "$SOLUTE_DIR" <<'PY'
import json
import sys
from pathlib import Path

from dashboard.execution.adapters import osmotic_mdp

workdir = Path(sys.argv[1])
placement = json.loads((workdir / 'placement.json').read_text())
molecules = placement['solute_molecules_placed']
if molecules:
    total = int((workdir / 'solvated.gro').read_text().splitlines()[1])
    reference = placement['reference_atom']
    (workdir / 'plumed.dat').write_text(osmotic_mdp.plumed_walls(
        solute_molecules=molecules, solute_atoms=range(1, reference),
        solvent_atoms=range(reference + 1, total + 1)))
print('plumed: %d molecules confined, each by its own wall pair' % molecules)
PY

#     The pure-solvent control has nothing to confine, so it writes no file and passes no option: `plumed_walls`
#     refuses a zero molecule count rather than writing a wall on nothing, and PLUMED handed an empty file stops
#     mdrun. An `if` rather than `[ -f ... ] &&`, because a false test is a non-zero status and this script is
#     expected to reach the next line either way.
if [ -f plumed.dat ]; then PLUMED="-plumed plumed.dat"; else PLUMED=""; fi

# 5. The stages. `-n` names the one group the mdps refer to by name: `System`, for the thermostat and the barostat.
#    The index still carries MOL<i> and REFERENCE, but nothing names them any more -- the confinement is PLUMED's,
#    and it takes its atoms from plumed.dat rather than from an index group. The equilibration takes no `-t`: a steep
#    minimization writes no checkpoint -- it has no velocities to carry -- and passing min.cpt is "No such file or
#    directory" one step after the first mdrun this pipeline ever completed. Production *does* continue from the
#    equilibration's checkpoint, because that is where gen_vel went.
#    `-r` names the file the position restraints' reference coordinates come from: the same coordinates the stage
#    starts from, which is where the reference bead sits at the box centre. With the confinement in PLUMED nothing
#    depends on that bead any more -- the walls are referenced to the solvent -- so it and its restraint are left
#    where they are rather than removed mid-flight. `-maxwarn 1` is for the Berendsen barostat the paper's method
#    names -- GROMACS warns it is not a strictly correct ensemble, and here that warning is the method rather than a
#    mistake. More than one warning means something else is wrong, so the count stays at one.
gmx grompp -f minimization.mdp -p system.top -c solvated.gro -r solvated.gro -n index.ndx -o min.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm min ${PLUMED} ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v
gmx grompp -f eq.mdp -p system.top -c min.gro -r min.gro -n index.ndx -o eq.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm eq ${PLUMED} ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v
gmx grompp -f md.mdp -p system.top -c eq.gro -r eq.gro -n index.ndx -t eq.cpt -o md.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm md ${PLUMED} ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v

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
