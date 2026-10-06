"""The build for one osmotic-pressure condition: the mdps, the groups, the reference bead, and the numbers.

The runner (a stage script, like every other CG stage here) does the GROMACS work. This module decides *what* it works
on, and writes the three things the paper's method needs that no other stage here has:

1. **The mdps** from `osmotic_mdp`, which carry the z-only coupling, the flat-bottomed restraint and the durations.
2. **An index file** naming the two pull groups. `grompp` refuses a `direction` geometry with one group, and the
   groups must be named rather than inferred, so the builder owns the file it will be read from.
3. **The reference bead.** The pull's second group must have its centre of mass *at the box centre*, so it is a single
   bead placed there, frozen, with a **zero-size, zero-charge type**: `sigma = 0` and `epsilon = 0` means no van der
   Waals, no charge means no Coulomb, and frozen means it cannot move off the centre it defines. It is given a real
   mass because GROMACS will not integrate a massless bead, and it is excluded from nothing because it interacts with
   nothing -- which is the whole point of giving it that type.

**And the manifest carries the numbers the analysis divides with.** The dividing area, the water and solute counts,
the requested *and* achieved molality, the confinement and its constant, and the temperature with where it came from.
An analysis that recomputed the area from a trajectory would be dividing a force by a number the build never agreed
to; recording it at build time means the two are the same number by construction.
"""
import json
from pathlib import Path

from . import osmotic_box, osmotic_mdp

REFERENCE_TYPE = 'REF'
REFERENCE_MASS = 72.0          # a real mass, because a massless bead has no defined force; it is frozen anyway
REFERENCE_MOLECULE = 'REFC'
MANIFEST = 'osmotic_condition.json'


def reference_bead_itp(*, residue='REFC'):
    """The one-bead molecule the pull measures against: zero size, zero charge, and therefore no interaction."""
    return (
        f'[ moleculetype ]\n{REFERENCE_MOLECULE}  1\n\n'
        f'; a frozen, non-interacting bead at the box centre, for the pull to measure against\n'
        f'[ atoms ]\n'
        f';id  type  resnr  residu  atom  cgnr  charge  mass\n'
        f' 1   {REFERENCE_TYPE}   1  {residue}  {REFERENCE_TYPE}   1   0.0   {REFERENCE_MASS:g}\n\n'
        f'[ atomtypes ]\n'
        f'; the zero-size type: no van der Waals, and the zero charge above means no Coulomb either\n'
        f'{REFERENCE_TYPE}  {REFERENCE_MASS:g}  0.0  A  0.0  0.0\n'
    )


def index_groups(*, solute_atoms, reference_atom, solvent_atoms=()):
    """The `.ndx` naming the pull's two groups, plus the solvent for anything that wants it.

    Indices are 1-based, as GROMACS writes them. A group that is empty or that shares an atom with another is refused
    here: `grompp` would take the file happily and the run would measure something other than what was intended.
    """
    solute = [int(index) for index in solute_atoms]
    solvent = [int(index) for index in solvent_atoms]
    reference = int(reference_atom)
    if not solute:
        raise ValueError('the solute group is empty, so there is nothing to confine or to measure')
    if reference <= 0:
        raise ValueError(f'the reference atom index {reference} is not 1-based')
    overlap = set(solute) & set(solvent)
    if overlap:
        raise ValueError(f'atom {sorted(overlap)[0]} is in both the solute and the solvent group')
    if reference in set(solute) | set(solvent):
        raise ValueError(f'the reference atom {reference} is also in the solute or solvent group')
    lines = ['[ SOLUTE ]', *[str(index) for index in solute], '', '[ REFERENCE ]', str(reference), '']
    if solvent:
        lines += ['[ SOLVENT ]', *[str(index) for index in solvent], '']
    return '\n'.join(lines)


def build(destination, *, plan, temperature, production_ps=osmotic_mdp.DEFAULT_PRODUCTION_PS,
          equilibration_ps=osmotic_mdp.DEFAULT_EQUILIBRATION_PS,
          output_interval_ps=osmotic_mdp.DEFAULT_OUTPUT_INTERVAL_PS,
          solute_atoms=(), reference_atom=None, solvent_atoms=()):
    """Write one condition's mdp set, reference bead and index file, and return the record to manifest.

    `plan` is `osmotic_box.plan_condition`'s result -- the counts this build is for. The record returned is what the
    manifest and the analysis both read, so the area a force is divided by is the area this build made.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    mdps = osmotic_mdp.osmotic_mdps(temperature=temperature, production_ps=production_ps,
                                    equilibration_ps=equilibration_ps,
                                    output_interval_ps=output_interval_ps)
    written = {}
    for stage, text in mdps.items():
        name = {'minimization': 'minimization.mdp', 'equilibration': 'eq.mdp', 'production': 'md.mdp'}[stage]
        (destination / name).write_text(text)
        written[stage] = name
    (destination / 'reference.itp').write_text(reference_bead_itp())
    index = index_groups(solute_atoms=solute_atoms, reference_atom=reference_atom, solvent_atoms=solvent_atoms)
    (destination / 'index.ndx').write_text(index)

    record = {
        'molality_requested': plan['requested_molality'],
        'molality_achieved': plan['achieved_molality'],
        'box_nm': plan['box_nm'],
        'box_volume_nm3': plan['box_volume_nm3'],
        'dividing_area_nm2': plan['dividing_area_nm2'],
        'water_beads': plan['water_beads'],
        'solute_molecules': plan['solute_molecules'],
        'solute_beads': plan.get('solute_beads'),
        'confinement_nm': plan['confinement_nm'],
        'confinement_kj_mol_nm2': plan['confinement_kj_mol_nm2'],
        'temperature': float(temperature),
        'temperature_source': plan.get('temperature_source'),
        'production_ps': float(production_ps),
        'equilibration_ps': float(equilibration_ps),
        'output_interval_ps': float(output_interval_ps),
        'restraint': {'mechanism': 'pull, flat-bottom, direction z',
                      'reference_type': REFERENCE_TYPE,
                      'reference_atom': int(reference_atom) if reference_atom is not None else None},
        'groups': {'solute': len(list(solute_atoms)), 'solvent': len(list(solvent_atoms))},
        'files': written,
        'note': 'the analysis recomputes the force from the trajectory and divides by dividing_area_nm2 above; it '
                'must not recompute that area, or the two would be different numbers',
    }
    (destination / MANIFEST).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def plan_and_build(destination, *, molality, temperature, bead_radii_nm=(), solute_beads_per_molecule=None,
                   solute_atoms=(), reference_atom=None, solvent_atoms=(), **durations):
    """`plan_condition` then `build`, so a caller cannot pass a plan that does not match what was written."""
    plan = osmotic_box.plan_condition(molality, bead_radii_nm=bead_radii_nm,
                                      solute_beads_per_molecule=solute_beads_per_molecule)
    return build(destination, plan=plan, temperature=temperature, solute_atoms=solute_atoms,
                 reference_atom=reference_atom, solvent_atoms=solvent_atoms, **durations)
