"""The pressure a condition's own trajectory implies, recomputed rather than read out of an engine.

The paper is explicit that this is the method: "the force was recomputed from the trajectory". The walls are the
instrument and the trajectory is the record, so the pressure is arithmetic over frames -- not a number an engine
printed. `plumed_bias.dat` is used for one thing only: to *check* this module's force against the engine's own energy
for the same molecule on the same frame. That check is why the walls' `KAPPA` and the paper's force constant have to
agree, and it is what makes the two independent.

**Three facts the geometry fixes, all asserted rather than assumed.**

  * **The two walls carry equal forces.** The slab is symmetric and each wall bounds it, so a *difference* between
    them is a net force on the slab that no measurement of an osmotic pressure should absorb. `symmetry` is reported
    on every measurement, because a broken symmetry is exactly the failure this arithmetic would otherwise hide.
  * **The pressure is one wall's force per unit area, not both walls'.** Both walls bound the same slab and each
    carries it, so the force on one wall is `pi * area`; summing them would report twice the pressure. The *measured*
    per-wall forces are both returned so the reader can see the symmetry rather than take the halving on trust.
  * **A molecule inside the flat region contributes nothing.** The mean is therefore an average over the rare
    excursions that reach a wall, which is what gives it a sample size rather than a constant.

The molecule grouping is not re-derived here: it is **read out of the run's own `plumed.dat`**, the same file the
walls were built from. A second definition of "molecule" is a second thing to keep in step, and the analysis and the
simulation disagreeing about that would be invisible in the output.
"""
import json
import math
import re
from pathlib import Path

AVOGADRO = 6.02214076e23
#: kJ/mol/nm2 -> bar. A pressure of 1 kJ/mol/nm3 is 1e30 J/mol/m3, and per molecule that is 1e30/N_A = 1.6605e6 Pa.
#: Written out because the number 16.605 is the only place a factor of 1e5 or of N_A can hide in this module.
KJ_MOL_NM2_TO_BAR = 1.0e30 / AVOGADRO / 1.0e5

MANIFEST = 'osmotic_condition.json'
WALLS = 'plumed.dat'
BIAS = 'plumed_bias.dat'
TRAJECTORY = ('prod/md_whole.xtc', 'md.xtc')
STRUCTURE = ('solvated.gro', 'system.gro')

_MOLECULE = re.compile(r'^m(\d+):\s+COM\s+ATOMS=([\d,]+)\s*$', re.M)
_CENTRE = re.compile(r'^#\s*The box centre is z = (\S+) nm', re.M)
_KAPPA = re.compile(r'^upper\d+:\s+UPPER_WALLS\s+ARG=m\d+\.z\s+AT=(\S+)\s+KAPPA=(\S+)', re.M)


def read_walls(path):
    """The run's own confinement, as its grouping, its wall positions and its constant.

    Raises rather than returning a partial answer: a trajectory analysed against a guessed wall is a number with no
    provenance, and this module exists to produce numbers with one.
    """
    text = Path(path).read_text()
    molecules = [[int(index) for index in atoms.split(',')] for _, atoms in _MOLECULE.findall(text)]
    if not molecules:
        raise ValueError(f'{path}: no solute molecule is confined, so there is no wall force to measure')
    centre = _CENTRE.search(text)
    upper = _KAPPA.search(text)
    if centre is None or upper is None:
        raise ValueError(f'{path}: the box centre and the walls are not both named in it')
    return {'molecules': molecules,
            'centre_nm': float(centre.group(1)),
            'upper_nm': float(upper.group(1)),
            'kappa_kj_mol_nm2': float(upper.group(2))}


def wall_force_kj_nm(dz_nm, *, centre_nm, half_width_nm, force_constant_kj_mol_nm2):
    """One molecule's outward push on each wall, from its z relative to the box centre.

    The paper's flat bottom: nothing while the molecule is within `half_width_nm` of the centre, and beyond it a
    restoring force proportional to the excursion. Returned as `(upper, lower)`, each a magnitude, because they are
    the two walls' separate loads and their equality is a fact worth seeing rather than assuming.
    """
    offset = float(dz_nm) - float(centre_nm)
    beyond = abs(offset) - float(half_width_nm)
    if beyond <= 0.0:
        return 0.0, 0.0
    return ((beyond * float(force_constant_kj_mol_nm2), 0.0) if offset > 0 else
            (0.0, beyond * float(force_constant_kj_mol_nm2)))


def pressure_bar(force_kj_nm, area_nm2):
    """One wall's force per unit dividing area, as a pressure in bar."""
    force = float(force_kj_nm)
    area = float(area_nm2)
    if not math.isfinite(force):
        raise ValueError('Force must be finite')
    if not math.isfinite(area) or area <= 0:
        raise ValueError('area must be finite and greater than zero')
    return force / area * KJ_MOL_NM2_TO_BAR


def divide(force_kj_nm, area_nm2, *, force_run_id, area_run_id):
    """A pressure, refusing a force and an area that did not come from the same run.

    Both are properties of one condition -- the force is its trajectory's, the area its own record's -- and a
    quotient of the two from different runs is a number that looks like a measurement and is not one. Both ids are
    named in the refusal so the mistake is visible rather than inferred.
    """
    if str(force_run_id) != str(area_run_id):
        raise ValueError(f'Force is from run {force_run_id} and the area from run {area_run_id}; '
                         'an osmotic pressure needs both from the same condition')
    return pressure_bar(force_kj_nm, area_nm2)


def _structure_and_trajectory(run_dir):
    for name in TRAJECTORY:
        if (run_dir / name).is_file():
            trajectory = run_dir / name
            break
    else:
        raise FileNotFoundError(f'{run_dir}: no trajectory ({", ".join(TRAJECTORY)})')
    for name in STRUCTURE:
        if (run_dir / name).is_file():
            return run_dir / name, trajectory
    raise FileNotFoundError(f'{run_dir}: no structure ({", ".join(STRUCTURE)})')


def measure(run_dir, *, force_constant_kj_mol_nm2=None, frames=None):
    """The mean wall force and the pressure it implies, over a completed condition's own trajectory.

    `force_kj_nm` is the **total over the condition's molecules**, averaged over the frames: each frame contributes
    every molecule's push on a wall, and the mean of those sums is what the dividing area turns into a pressure;
    `upper_force_kj_nm` and `lower_force_kj_nm` are the two walls' separate means, so the symmetry is visible.

    `force_constant_kj_mol_nm2` defaults to the one the run's walls were built with, doubled: PLUMED's `KAPPA` is a
    potential constant and the force it applies is `2*kappa*(x-AT)`, so the force constant is `2*kappa`. This docstring
    said "halved" until the arithmetic in the tests disagreed with it.
    """
    import MDAnalysis as mda

    run_dir = Path(run_dir)
    walls = read_walls(run_dir / WALLS)
    condition = json.loads((run_dir / MANIFEST).read_text())
    area = float(condition['dividing_area_nm2'])
    half = float(condition['confinement_nm'])
    force_constant = (float(force_constant_kj_mol_nm2) if force_constant_kj_mol_nm2 is not None
                      else 2.0 * walls['kappa_kj_mol_nm2'])
    structure, trajectory = _structure_and_trajectory(run_dir)

    universe = mda.Universe(str(structure), str(trajectory))
    if len(universe.atoms) < max(max(group) for group in walls['molecules']):
        raise ValueError(f'{run_dir}: the trajectory has {len(universe.atoms)} atoms and the walls name atom '
                         f'{max(max(group) for group in walls["molecules"])}')
    step = int(frames or 1)
    upper, lower, counted = [], [], 0
    for number, _ in enumerate(universe.trajectory):
        if number % step:
            continue
        counted += 1
        for group in walls['molecules']:
            # MDAnalysis reports positions in Angstrom; the walls are in nm, and this line multiplied where it
            # should have divided. The comment said "Angstrom -> nm" the whole time: a comment is not a check, and
            # the only thing that caught it was the force coming out a hundred times too large.
            z = universe.atoms[[index - 1 for index in group]].center_of_mass()[2] / 10.0
            up, down = wall_force_kj_nm(z, centre_nm=walls['centre_nm'], half_width_nm=half,
                                        force_constant_kj_mol_nm2=force_constant)
            upper.append(up)
            lower.append(down)
    if not counted:
        raise ValueError(f'{run_dir}: the trajectory has no frames')

    upper_mean = sum(upper) / counted
    lower_mean = sum(lower) / counted
    return {'run_id': run_dir.parent.name if run_dir.name == '01_simulate' else run_dir.name,
            'molecules': len(walls['molecules']), 'frames': counted,
            'force_constant_kj_mol_nm2': force_constant,
            'upper_force_kj_nm': upper_mean, 'lower_force_kj_nm': lower_mean,
            'force_kj_nm': (upper_mean + lower_mean) / 2.0,
            'symmetry': (min(upper_mean, lower_mean) / max(upper_mean, lower_mean)
                         if max(upper_mean, lower_mean) else None),
            'area_nm2': area,
            'pressure_bar': pressure_bar((upper_mean + lower_mean) / 2.0, area)}
