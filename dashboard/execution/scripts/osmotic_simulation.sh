#!/bin/bash
# The osmotic series, end to end: one concentration at a time, in its own directory.
#
# The method is the paper's: the solute is confined to the middle of a fixed box by a flat-bottomed potential
# (2.52078 nm from the centre, 1000 kJ/mol/nm2 beyond it), pressure is coupled only in z, and the osmotic pressure
# comes from the force the solute exerts on those walls divided by the xy area. The force is NOT read from this run's
# pull machinery -- the analysis recomputes it from the trajectory -- so what this has to get right is the geometry:
# the box, the slab, and a reference whose centre of mass IS the box centre.
#
# **The series is one stage and N concentrations, and the two halves of that are this file's structure.** Invoked
# with no `OSMOTIC_CONDITION`, this script is the driver: it reads `conditions.json`, and for each concentration in
# the caller's order it runs one condition to the end before starting the next -- that is what "one at a time"
# means here, and it is the stage's own loop rather than anything the queue has to enforce. Invoked with
# `OSMOTIC_CONDITION=<directory>`, it runs that one condition with the condition's own directory as its working
# directory. The process boundary is deliberate: a condition's exit code is its own outcome, so the driver can
# record it and honour the series' policy on it.
#
# **A condition that already finished is not entered again, and a condition that died resumes.** Each condition's
# `min/eq/md.cpt`, its `attempts.json` and a terminal `condition.json` live in its own directory. The driver skips a
# condition whose record says `complete`, so a second entry into the series -- which is what resuming the run does
# -- runs only what did not finish, and the retry inside a condition continues from that condition's own
# checkpoint rather than restarting it.
#
# Three substitutions or choices from the paper, recorded rather than hidden:
#   * the paper builds the initial configuration with polyply; this samples positions inside the slab itself, which is
#     the tool this repository already has, and it reports the minimum separation it actually achieved.
#   * the paper's systems are binary sugar-water. No ions are added, because the osmometry it compares against
#     measured salt-free solutions.
#   * the index file is written HERE and not by the adapter: the pull's groups are atom indices, and the indices are
#     not known until the molecules have been placed.
#
# Inputs, in the stage directory:
#   run.sh conditions.json        this driver, and the series it drives
#   conditions/<n>_<m>molal/      one per concentration: minimization.mdp eq.mdp md.mdp reference.itp
#                                 osmotic_condition.json, solute/ (one molecule + its includes),
#                                 martini_v3.0.0.itp
# Environment:
#   SOLUTE_DIR, MDRUN_LAUNCHER, MDRUN_FLAGS, GROMACS, OSMOTIC_CONDITION -- as cg_simulation.sh, plus the last,
#   which the driver sets to the condition directory it is entering.
GROMACS="${GROMACS:-/usr/local/gromacs/2026.3/bin/gmx}"
SOLUTE_DIR="${SOLUTE_DIR:-solute}"
CONDITIONS_MANIFEST="${CONDITIONS_MANIFEST:-conditions.json}"
CONDITIONS_DIRECTORY="${CONDITIONS_DIRECTORY:-conditions}"
export PATH="$(dirname "$GROMACS"):$PATH"
set -euxo pipefail

# One attempt's record, appended per attempt rather than written at the end, so it survives the condition being
# killed. Read back with `python -c "import json;print(json.load(open('attempts.json')))"`.
record_attempt() {
    python - "$1" "$2" "$3" "$4" <<'PY'
import json
import os
import sys
from pathlib import Path

stage, attempt, resumed, outcome = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
path = Path('attempts.json')
data = json.loads(path.read_text()) if path.is_file() else {'attempts': []}
data.setdefault('attempts', []).append({
    'attempt': attempt,
    'stage': stage,
    'checkpoint': f'{stage}.cpt',
    'resumed': resumed == 'yes',
    'attempts_max': int(os.environ.get('OSMOTIC_ATTEMPTS_MAX', '3')),
    'outcome': outcome,
})
path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
PY
}

run_stage() {
    local stage="$1" attempt=1 resumed outcome
    while [ "$attempt" -le "$OSMOTIC_ATTEMPTS_MAX" ]; do
        if [ -f "$stage.cpt" ]; then resumed=yes; else resumed=no; fi
        if [ "$resumed" = no ]; then
            # Nothing to continue from: drop this stage's own partial output first, so the fresh run does not append
            # to a failed attempt's truncated trajectory and splice two runs into one file. Only the failed stage's
            # files are touched -- never another stage's, and never the tpr the grompp above just wrote.
            rm -f "$stage.trr" "$stage.xtc" "$stage.edr" "$stage.log" "$stage.gro"
        fi
        outcome=ok
        ${MDRUN_LAUNCHER:-}gmx mdrun -deffnm "$stage" -cpi "$stage.cpt" \
            ${PLUMED} ${MDRUN_FLAGS:--ntomp 4 -gpu_id 0 -nb gpu -pin on} -v || outcome=failed
        record_attempt "$stage" "$attempt" "$resumed" "$outcome"
        if [ "$outcome" = ok ]; then return 0; fi
        echo "### $stage failed on attempt $attempt of $OSMOTIC_ATTEMPTS_MAX" >&2
        attempt=$((attempt + 1))
    done
    echo "### $stage failed after $OSMOTIC_ATTEMPTS_MAX attempts: the condition ends failed" >&2
    return 1
}

# The retry ceiling reaches this script the way `REPO_ROOT` does: a stage script is a file read at prepare time, so
# a per-run value is written into it there. The default is for a script run by hand, and it is the house ceiling
# (`attempts_max = 3` in `pdc.DEFAULTS` and the loop bound in `pdc_extension.py`).
OSMOTIC_ATTEMPTS_MAX="${OSMOTIC_ATTEMPTS_MAX:-3}"

# -----------------------------------------------------------------------------------------------------------------
# One condition, or the series.
# -----------------------------------------------------------------------------------------------------------------
if [ -n "${OSMOTIC_CONDITION:-}" ]; then
cd "$OSMOTIC_CONDITION"

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
    reference = placement['reference_atom']
    (workdir / 'plumed.dat').write_text(osmotic_mdp.plumed_walls(
        solute_molecules=molecules, solute_atoms=range(1, reference),
        box_centre_nm=float((workdir / 'solvated.gro').read_text().splitlines()[-1].split()[2]) / 2.0))
print('plumed: %d molecules confined, each by its own wall pair' % molecules)
PY

#     The pure-solvent control has nothing to confine, so it writes no file and passes no option: `plumed_walls`
#     refuses a zero molecule count rather than writing a wall on nothing, and PLUMED handed an empty file stops
#     mdrun. An `if` rather than `[ -f ... ] &&`, because a false test is a non-zero status and this script is
#     expected to reach the next line either way.
if [ -f plumed.dat ]; then PLUMED="-plumed plumed.dat"; else PLUMED=""; fi

#     **The kernel is loaded at run time, and GROMACS does not carry it.** This build is compiled *with* PLUMED
#     support but not against it: with no kernel on the machine, mdrun stops with "You are trying to use plumed, but
#     it is not available. Check your PLUMED_KERNEL environment variable." `config/tools.json` declares the entry
#     point, and `tools.plumed_environment` turns that into the two variables the load needs -- the kernel's path and
#     its library directory, appended after whatever is inherited. It contributes nothing when nothing is declared,
#     which is this repository's rule everywhere: the run then fails in mdrun saying exactly what is missing.
#     Written to a file and sourced rather than `eval`-ed from a command substitution, because a heredoc nested in
#     `$(...)` is precisely the construct that ran `LIG1` as a command two commits ago.
python - <<'PY'
import shlex
from pathlib import Path

from dashboard.execution import tools

Path('plumed_env.sh').write_text(''.join(
    f'export {name}={shlex.quote(value)}\n'
    for name, value in tools.plumed_environment().items()))
print('plumed: ' + (Path('plumed_env.sh').read_text().strip() or 'no declaration, so no kernel is loaded'))
PY
. ./plumed_env.sh

# 5. The stages. `-n` names the one group the mdps refer to by name: `System`, for the thermostat and the barostat.
#    **Concurrency is what the pinning question was really about, and the answer is that it does not pay here.**
#    Four conditions at once measured, from PLUMED's own clock: ~291 ns/day each when all four shared cores 0-7,
#    ~130 spread across all 72, ~105 each on its own block of eight -- against **~2400 ns/day for one condition run
#    alone with `-pin on`**, which is what the 0.5 molal run measured over its whole 500 ns. So the aggregate falls
#    by roughly 4.6x when four run together, and no thread placement recovers it: a 2502-bead system pays a per-run
#    overhead that more runs cannot amortise. The machine's own numbers: 32 cores fully busy, the GPU at 13%, I/O
#    negligible -- the limit is neither cycles nor the accelerator.
#    `-pin on` is therefore restored, because serial with it is the only placement this machine has *measured* at
#    2400 ns/day. That measurement is also why **the conditions run one at a time inside this one run**: the same
#    number, read as an instruction rather than as an observation. See
#    `docs/superpowers/plans/2026-10-06-osmotic-concentration-series.md` for the three-way comparison.
#    **The mdrun flags, measured rather than assumed.** Eight configurations on this system's own `md.tpr`, 0.5 ns
#    each: `-nb gpu` beat `-nb cpu` by 1.6x to 7x, and `-ntomp 4` beat every other thread count -- so `-nb gpu` was
#    right and the GPU is not idle because the flags are wrong. Then the same comparison with the confinement
#    PLUMED actually runs: **PLUMED costs a factor of three** (14255 -> 4782 ns/day at `-ntomp 4 -nb gpu`), which
#    is where the 500 ns conditions spend most of their wall clock, and `-ntomp 4` is still the best of the four
#    thread counts once it is loaded. `-ntomp 8` was the only flag worth changing, and it is worth ~1.5%: the bare
#    benchmark made it look like 6.7%.
#    Absolute rates from a 0.1-0.5 ns window are optimistic -- a short window is startup-dominated, and the same
#    system's 0.2 ns probe read 4577 against 2400 measured over a real 500 ns. The matrix ranks the options; only a
#    long run prices them.
#    **The index still carries MOL<i> and REFERENCE, but nothing names them any more** -- the confinement is PLUMED's,
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
#    **A failed mdrun is resumed from its own checkpoint, bounded at OSMOTIC_ATTEMPTS_MAX (default 3).** The
#    condition is one stage made of three mdrun calls, so the ceiling bounds *this condition's* attempts: one stage is
#    launched at most OSMOTIC_ATTEMPTS_MAX times, and the last failure ends the condition `failed`. The resume is
#    `-cpi`, the same flag the pdc extension stage continues with (`pdc_extension.py`: `mdrun -deffnm run -cpi
#    run.cpt`), and the two cases are not the same work:
#
#      * **a checkpoint exists** (`eq.cpt`, `md.cpt` -- mdrun writes one at its own interval) -- the stage died
#        mid-run, so the retry continues from the state it left rather than repeating what it had already
#        integrated. That is the case the retry exists for: a 500 ns production can die at 171 ns, and its sibling
#        condition of the same series survived the identical 500 ns, so the failure is stochastic rather than a
#        property of the inputs. **And it is the case a second entry into the series relies on**: the driver skips
#        the conditions that finished and re-enters the one that did not, whose `md.cpt` is still here.
#      * **no checkpoint exists** -- the stage died before mdrun wrote its first one, or before it ran at all. There
#        is nothing to continue *from*, so the stage restarts cleanly from its own tpr. GROMACS is explicit that a
#        missing checkpoint is not an error -- `gmx mdrun -h`: "if no checkpoint file is found, GROMACS just assumes a
#        normal run and starts from the first step of the .tpr file" -- and the retry must not fail on a file that
#        was never written. Minimization is always this case: `integrator = steep` writes no checkpoint, because a
#        minimization has no velocities to carry.
#    Every attempt is recorded in `attempts.json` -- the stage, the attempt number, the checkpoint, whether it
#    resumed and the outcome -- the shape `pdc_extension.py` writes.
gmx grompp -f minimization.mdp -p system.top -c solvated.gro -r solvated.gro -n index.ndx -o min.tpr -maxwarn 1
run_stage min
gmx grompp -f eq.mdp -p system.top -c min.gro -r min.gro -n index.ndx -o eq.tpr -maxwarn 1
run_stage eq
gmx grompp -f md.mdp -p system.top -c eq.gro -r eq.gro -n index.ndx -t eq.cpt -o md.tpr -maxwarn 1
run_stage md

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

exit 0
fi

# -----------------------------------------------------------------------------------------------------------------
# The driver: every condition in the order `conditions.json` gives them.
# -----------------------------------------------------------------------------------------------------------------

# A condition's terminal record. Written for every condition the driver enters, so a second entry can tell a
# finished condition from one that never ran -- and so the reader has the outcome beside the condition's own files
# rather than only in this run's manifest.
record_condition() {
    python - "$1" "$2" <<'PY'
import datetime
import json
import sys
from pathlib import Path

directory, status = Path(sys.argv[1]), sys.argv[2]
condition = json.loads((directory / 'osmotic_condition.json').read_text())
attempts = directory / 'attempts.json'
records = json.loads(attempts.read_text())['attempts'] if attempts.is_file() else []
(directory / 'condition.json').write_text(json.dumps({
    'directory': directory.name,
    'molality': condition['molality_requested'],
    'molality_achieved': condition['molality_achieved'],
    'solute_molecules': condition['solute_molecules'],
    'dividing_area_nm2': condition['dividing_area_nm2'],
    'status': status,
    'attempts': len(records),
    'ended_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, indent=2, sort_keys=True) + '\n')
PY
}

condition_status() {
    python - "$1" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1]) / 'condition.json'
try:
    print(json.loads(path.read_text()).get('status') or '')
except (OSError, ValueError):
    print('')
PY
}

SERIES_POLICY="$(python -c "
import json
print(json.load(open('$CONDITIONS_MANIFEST')).get('series_on_failure') or 'carry_on')")"
echo "series: policy on a failed condition is $SERIES_POLICY, ceiling $OSMOTIC_ATTEMPTS_MAX attempts per condition"

failed=0
CONDITIONS="$(python -c "
import json
print(' '.join(condition['directory'] for condition in
               json.load(open('$CONDITIONS_MANIFEST'))['conditions']))")"
# A manifest that names nothing is refused rather than reported as a series that ran: the loop below would never
# execute, and `failed` would stay zero -- a green exit for a series that does not exist.
if [ -z "$CONDITIONS" ]; then
    echo "### $CONDITIONS_MANIFEST names no condition, so there is no series to run" >&2
    exit 1
fi
for directory in $CONDITIONS; do
    if [ ! -d "$CONDITIONS_DIRECTORY/$directory" ]; then
        echo "### $CONDITIONS_MANIFEST names $directory, which is not a directory in this stage" >&2
        exit 1
    fi
    if [ "$(condition_status "$CONDITIONS_DIRECTORY/$directory")" = complete ]; then
        # Already finished, in this entry into the stage or in an earlier one: it is not run again. This is what
        # makes a second entry into the series a resume -- the conditions that survived are exactly the ones the
        # retry does not repeat.
        echo "condition $directory already complete: not run again"
        continue
    fi
    echo "condition $directory: entering"
    outcome=failed
    if OSMOTIC_CONDITION="$CONDITIONS_DIRECTORY/$directory" bash "$0"; then
        outcome=complete
    fi
    record_condition "$CONDITIONS_DIRECTORY/$directory" "$outcome"
    if [ "$outcome" = complete ]; then
        continue
    fi
    failed=$((failed + 1))
    if [ "$SERIES_POLICY" = stop ]; then
        echo "### the series stops here: the $directory condition ended failed" >&2
        exit 1
    fi
    echo "### the $directory condition ended failed; the series carries on and this is its gap" >&2
done

if [ "$failed" -gt 0 ]; then
    echo "### the series ran to its end with $failed condition(s) failed: see each one's condition.json" >&2
    exit 1
fi
echo "### the series completed: every condition ended complete"
