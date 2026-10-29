"""The box for one concentration of an osmotic-pressure series, and the arithmetic that sets it.

The paper's box and restraint are fixed, so they are constants here with the source beside each one:

- `BOX_NM`, `CONFINEMENT_NM` and `CONFINEMENT_KJ_MOL_NM2` are the paper's: a rectangular box of 10.08312 nm in z and
  5.04156 nm in x and y, solute confined within 2.52078 nm of the centre by a flat potential and 1000 kJ/mol/nm2
  beyond it. The confinement is exactly the quarter box (10.08312 / 4 = 2.52078), which is worth knowing because it
  means the walls sit where the periodic images begin.
- `WATER_BEAD_MASS` is **read from the topology, never recalled**: `martini_v3.0.0.itp`'s `[ atomtypes ]` line for `W`
  gives 72.0, so a Martini 3 water bead is four waters. Whether it is three or four decides the bead volume, the water
  count in a fixed box, and therefore every molality in the series -- and every internal check still passes if it is
  wrong, which is what makes it worth naming the file it came from. `RADII_NM` in `models/sugars/recognition.py` is
  the precedent.
- `WATER_TILE_*` describe the coordinate file the CG stage solvates with (`inputs/water.gro`, 400 beads in a 3.64428 nm
  cube). `gmx solvate -cs` tiles it, so the packing it implies is the density this series will actually run at -- 988
  kg/m3, about 0.6% below water at 308.15 K. That is the repository's convention rather than a physical density, and
  it is recorded here so the small difference is never mistaken for a mistake.

**Molality is moles of solute per kilogram of *water*, so the water count is what has to be right.** The box is fixed,
the solute displaces some water, and the count follows; the *achieved* molality is reported beside the requested one
so a series cannot quietly land at the wrong concentration with every internal check still passing.
"""
import math

BOX_NM = (5.04156, 5.04156, 10.08312)
CONFINEMENT_NM = 2.52078
CONFINEMENT_KJ_MOL_NM2 = 1000.0
WATER_BEAD_MASS = 72.0
WATER_TILE_BEADS = 400
WATER_TILE_NM = 3.64428
MOLALITY_RANGE = (0.0, 2.5)
AVOGADRO = 6.02214076e23
KILOGRAM = 1000.0


def box_volume_nm3():
    """The paper's box volume, in nm3, which every condition in the series shares."""
    return BOX_NM[0] * BOX_NM[1] * BOX_NM[2]


def dividing_area_nm2():
    """The xy area the osmotic force is divided by -- one number for the whole series, because the box is fixed."""
    return BOX_NM[0] * BOX_NM[1]


def solvent_density_beads_per_nm3():
    """The water bead density the repository's own solvation tile implies."""
    return WATER_TILE_BEADS / WATER_TILE_NM ** 3


def water_beads(*, displaced_nm3=0.0):
    """How many W beads fill the box, less what the solute displaces.

    `gmx solvate` tiles a coordinate file rather than computing a density, so this is a prediction of what it will
    place, and the manifest should carry the count it actually placed. A prediction is not a substitute for the count.
    """
    available = box_volume_nm3() - float(displaced_nm3)
    if available <= 0:
        raise ValueError(f'the solute displaces {displaced_nm3} nm3 of a {box_volume_nm3():.2f} nm3 box')
    return int(available * solvent_density_beads_per_nm3())


def water_kg(bead_count):
    """The mass of water a bead count represents, in kilograms -- `W` beads are four waters each."""
    return float(bead_count) * (WATER_BEAD_MASS / KILOGRAM) / AVOGADRO


def _molecules_for(molality, water_bead_count):
    """The solute count a molality implies for a known water count, rounded to a whole molecule.

    The range is checked **here**, so every path that reaches a count has been through it -- a validation that lives
    only in a caller is one refactor away from not happening.
    """
    molality = float(molality)
    low, high = MOLALITY_RANGE
    if not low <= molality <= high:
        raise ValueError(f'molality {molality} is outside the paper\'s {low}-{high} range')
    present = water_kg(water_bead_count)
    if molality == 0.0:
        return 0
    if molality < 1.0 / (AVOGADRO * present):
        raise ValueError(f'{water_bead_count} water beads cannot express {molality} molal: one molecule is already more')
    return int(round(molality * present * AVOGADRO))


def solute_molecules(molality, *, displaced_nm3=0.0):
    """The solute count for a molality, given how much of the box the solute itself takes up.

    One half of the relation, not the whole answer: the displaced volume depends on the count. Use `plan_condition`,
    which solves the two together.
    """
    return _molecules_for(molality, water_beads(displaced_nm3=displaced_nm3))


def solute_volume_nm3(bead_radii_nm):
    """The volume ONE solute molecule's mapped beads occupy, as spheres at their own radii.

    An estimate, and named as one: it only decides how much room to leave before the solvent is placed, and the
    placement's own success or failure is the real check. `RADII_NM` is where the radii come from.
    """
    return sum(4.0 / 3.0 * math.pi * float(radius) ** 3 for radius in bead_radii_nm)


def plan_condition(molality, *, bead_radii_nm=(), solute_beads_per_molecule=None):
    """Everything one concentration needs, with the requested and the achieved molality both stated.

    **The two counts are solved together, and in closed form.** Molality is per kilogram of water; the water occupies
    what the solute does not; and the solute's count follows from the water. Writing those as `m = molality * q * N_A
    * w` and `w = (V - k*m)/v` and eliminating `m` gives

        w = (V / v) / (1 + (k / v) * molality * q * N_A)

    exactly, so there is nothing to iterate. The first version subtracted the solute's volume *after* counting it
    from a box assumed full of water -- and an iterated version of the same thing oscillated, because each pass both
    removed volume and reduced the count that removed it.
    """
    volume_per_molecule = solute_volume_nm3(bead_radii_nm)
    volume_per_bead = 1.0 / solvent_density_beads_per_nm3()
    # (k / v) * molality * q * N_A: how much box one bead's worth of water gives up to the solute at this molality.
    slope = (volume_per_molecule / volume_per_bead) * (
        float(molality) * water_kg(1) * AVOGADRO)
    water_bead_count = int(box_volume_nm3() / volume_per_bead / (1.0 + slope))
    molecules = _molecules_for(float(molality), water_bead_count)
    present = water_kg(water_bead_count)
    return {
        'requested_molality': float(molality),
        'achieved_molality': (molecules / AVOGADRO) / present if present else 0.0,
        'box_nm': list(BOX_NM),
        'box_volume_nm3': box_volume_nm3(),
        'dividing_area_nm2': dividing_area_nm2(),
        'water_beads': water_bead_count,
        'water_kg': present,
        'water_bead_mass': WATER_BEAD_MASS,
        'solute_molecules': molecules,
        'solute_beads': (molecules * int(solute_beads_per_molecule)
                         if solute_beads_per_molecule else None),
        'solute_volume_nm3': volume_per_molecule,
        'solute_volume_total_nm3': volume_per_molecule * molecules,
        'solved': 'closed form: w = (V/v) / (1 + (k/v) * molality * q * N_A)',
        'confinement_nm': CONFINEMENT_NM,
        'confinement_kj_mol_nm2': CONFINEMENT_KJ_MOL_NM2,
        'temperature_source': 'the experimental dataset\'s own temperature; 308.15 K for maltose',
    }
