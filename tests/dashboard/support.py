"""What the tests share: the repository root, mapping fixtures, a quiet handler, and the factory.

This was three modules with a helper or two each -- fixtures.py (PROJECT_ROOT, physical_mapping,
QuietHandler), mapping_fixtures.py (write_aa_fixture), and tool_paths.py, which imported its
PROJECT_ROOT back out of fixtures and carried fast_forward_source. One module now, so a test has
one import to reach for.

The old names are re-exported for one commit while the importing files move over, then they go.
"""
from pathlib import Path

from werkzeug.serving import WSGIRequestHandler

from tests.dashboard.factory import Dashboard, build

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: The vendored Fast_Forward tree; not part of every checkout, which is why lookups may return None.
FAST_FORWARD_ROOT = PROJECT_ROOT / 'resources/parameterizers/fast_forward/fast_forward'

#: One DDM molecule as a run's own `detergent_CG.itp` declares it: eleven beads, and the ten bonded terms that
#: hold them together -- four `[ bonds ]` and the six `[ constraints ]` the head's ring is pinned by. The numbers
#: are the run's (so a reader can check them against a stage's file), and the bead types are the ones the saved DDM
#: mapping carries (`SP1r`, `SN6`, `SP4r`, `TC4`, `C1`), because the type's first letter is where a moleculetype
#: states a bead's Martini 3 size class and three tests now read that column.
DDM_BEADS = ('S1A', 'S1B', 'S1C', 'S1VS', 'S2A', 'S2B', 'S2C', 'S2VS', 'TAIL1', 'TAIL2', 'TAIL3')
DDM_BONDS = ((1, 11), (2, 5), (9, 10), (10, 11))
DDM_CONSTRAINTS = ((1, 2), (1, 3), (2, 3), (5, 6), (5, 7), (6, 7))
#: Each bead's own size class, as the DDM mapping states it in its beads' `size` fields: the sugar ring's beads are
#: small, its two ring virtual sites are tiny, and the three tail beads are regular. Martini 3 spells the class in a
#: bead type's first letter (`S`mall, `T`iny) and leaves the regular class unmarked.
DDM_CLASSES = {'S1A': 'S', 'S1B': 'S', 'S1C': 'S', 'S1VS': 'T', 'S2A': 'S', 'S2B': 'S', 'S2C': 'S', 'S2VS': 'T',
               'TAIL1': 'R', 'TAIL2': 'R', 'TAIL3': 'R'}
#: The bead type each class is written with, and the mass that class' beads carry -- `bonded/generation.py` writes
#: both from a mapping bead's `size`, so a fixture that states a class states it the way a run's file does.
DDM_TYPES = {'R': 'C1', 'S': 'SP1r', 'T': 'TC4'}
DDM_MASSES = {'R': 72, 'S': 54, 'T': 36}

__all__ = ['PROJECT_ROOT', 'FAST_FORWARD_ROOT', 'Dashboard', 'build', 'physical_mapping',
           'write_aa_fixture', 'cg_fixture_run', 'QuietHandler', 'fast_forward_source',
           'DDM_BEADS', 'DDM_BONDS', 'DDM_CONSTRAINTS', 'DDM_CLASSES', 'DDM_TYPES', 'DDM_MASSES',
           'DDM_PLACEMENT', 'ddm_moleculetype', 'ddm_system_gro', 'gro_atom_line']


#: One DDM molecule's eleven beads, in nanometres, in the order the moleculetype lists them. These are the
#: coordinates a run's placement frame held -- the distances a viewer's distance-based bond guess was measured on.
DDM_PLACEMENT = ((-1.302, -1.022, 2.508), (-1.286, -1.023, 2.481), (-1.276, -1.046, 2.496),
                 (-1.288, -1.030, 2.495), (-1.277, -1.022, 2.456), (-1.264, -1.040, 2.439),
                 (-1.246, -1.043, 2.461), (-1.262, -1.035, 2.452), (-1.331, -1.099, 2.601),
                 (-1.330, -1.077, 2.567), (-1.313, -1.043, 2.544))


def gro_atom_line(residue_id, residue, name, serial, xyz) -> str:
    """One .gro atom line, in the format's fixed-width fields: 5, 5, 5, 5, then three 8.3f values."""
    return (f'{residue_id:5d}{str(residue)[:5]:<5}{str(name)[:5]:>5}{serial:5d}'
            + ''.join(f'{value:8.3f}' for value in xyz))


def ddm_system_gro(molecules, *, protein_beads=0, spacing_nm=3.0) -> str:
    """A built system's .gro text: `protein_beads` protein beads, then `molecules` DDM molecules.

    One place for the coordinates the panel's assertion and the route's share, so both describe the same system.
    Each molecule sits `spacing_nm` from the next, so no bead of one is near enough for a viewer's distance-based
    guess to join it to another -- which is what makes a drawn bond count a statement about the model.
    """
    lines = ['protein-detergent complex (DDM)', str(protein_beads + len(DDM_PLACEMENT) * molecules)]
    serial = 0
    for _ in range(protein_beads):
        serial += 1
        lines.append(gro_atom_line(1, 'PRO', 'BB', serial, (0.0, 0.0, 0.0)))
    for molecule in range(molecules):
        for name, xyz in zip(DDM_BEADS, DDM_PLACEMENT):
            serial += 1
            lines.append(gro_atom_line(2 + molecule, 'DDM', name, serial,
                                       (xyz[0] + molecule * spacing_nm, xyz[1], xyz[2])))
    lines.append('   30.00000   10.00000   10.00000')
    return '\n'.join(lines) + '\n'


def ddm_moleculetype() -> str:
    """The detergent moleculetype, in the shape a run's file has -- including the sections a viewer ignores.

    One place for it, because three tests need the same model: the reader that parses it, the writer that puts its
    bonds into a PDB, and the panel that draws them all have to agree about what the molecule is. Each bead carries
    its own class, in the type's first letter and in the mass `bonded/generation.py` derives from that class, so the
    file states the three sizes a picture is drawn at.
    """
    atoms = '\n'.join(f'{index} {DDM_TYPES[DDM_CLASSES[name]]} 1 DDM {name} {index} 0 '
                      f'{DDM_MASSES[DDM_CLASSES[name]]}'
                      for index, name in enumerate(DDM_BEADS, 1))
    constraints = '\n'.join(f'{first} {second} 1 0.361013007037' for first, second in DDM_CONSTRAINTS)
    bonds = '\n'.join(f'{first} {second} 1 0.429374836245 5000' for first, second in DDM_BONDS)
    return ('; Automatic bonded draft\n[ moleculetype ]\nDDM 1\n\n'
            f'[ atoms ]\n{atoms}\n\n'
            f'[ constraints ]\n{constraints}\n\n'
            f'[ bonds ]\n{bonds}\n\n'
            '[ angles ]\n2 1 3 1 49.887304076 25\n2 1 11 1 146.614164146 25\n\n'
            '[ dihedrals ]\n2 5 7 6 1 5 10 1\n\n'
            '[ virtual_sitesn ]\n4 1 1 2 3\n\n'
            '[ exclusions ]\n4 1 2 3\n')


def physical_mapping():
    """COG format fixture without virtual sites, for the basic FF mapper tests."""
    from dashboard.models import mappings
    generated = mappings.automatic_candidate(mappings.molecule(), 'DDM')
    return {'name': 'Physical COG format fixture',
            'beads': [b for b in generated['beads'] if not b.get('virtual_site')]}


def write_aa_fixture(root, molecule_id='Fixture'):
    """A minimal atomistic molecule directory: molecule.itp, molecule.gro and metadata.json."""
    import json
    folder = root / molecule_id; folder.mkdir(parents=True)
    rows = ['[ moleculetype ]', 'LIG 1', '[ atoms ]',
            '1 CT 1 LIG C1 1 0 12.011', '2 CT 1 LIG C2 2 0 12.011',
            '3 CT 1 LIG C3 3 0 12.011', '4 CT 1 LIG C4 4 0 12.011',
            '5 HC 1 LIG H1 5 0 1.008', '[ bonds ]',
            '1 2 1 0.15 1000', '2 3 1 0.15 1000', '3 4 1 0.15 1000', '1 5 1 0.10 1000']
    (folder / 'molecule.itp').write_text('\n'.join(rows) + '\n')
    gro = ['Fixture', '5']
    for i, name in enumerate(('C1', 'C2', 'C3', 'C4', 'H1'), 1):
        gro.append(f'{1:5d}{"LIG":<5}{name:>5}{i:5d}{i * .1:8.3f}{0.:8.3f}{0.:8.3f}')
    (folder / 'molecule.gro').write_text('\n'.join(gro + ['1 1 1', '']))
    (folder / 'metadata.json').write_text(json.dumps({'name': molecule_id, 'molecule_type': 'LIG',
                                                      'net_charge': 0,
                                                      'force_field': 'charmm36-jul2022.ff',
                                                      'water_model': 'tip3p'}))
    return folder


def cg_fixture_run(root, positions, names=('B01', 'B02', 'B03', 'B04'), frames=3, residue='SUCR',
                   topology=None, run_dir=None):
    """A minimal CG consumer: its topology, its structure, and a trajectory at the given coordinates.

    `positions` are nanometres, the way a GROMACS trajectory carries them. MDAnalysis holds ångström, so the
    trajectory is written at ten times that: a reader that forgets the conversion is caught by the tests
    instead of passing on a round-tripped number that never changed unit. The structure is written by hand
    because a GRO line's fixed columns are part of what a reader has to parse.

    Returns `(run directory, trajectory path, structure path, topology path)`.
    """
    import MDAnalysis as mda
    import numpy as np
    run_dir = run_dir or root
    topology_dir = run_dir / 'stages/3_initial_CG'
    topology_dir.mkdir(parents=True, exist_ok=True)
    topology_path = topology_dir / f'{residue}_initial.itp'
    rows = [f'{index} {"TC4" if name == "VS" else "SP1r"} 1 {residue} {name} {index} 0 '
            f'{"0" if name == "VS" else "54"}' for index, name in enumerate(names, 1)]
    topology_path.write_text(topology or '[ moleculetype ]\n' + residue + ' 1\n\n[ atoms ]\n'
                             + '\n'.join(rows) + '\n')
    production = run_dir / 'stages/4_CG_sim/prod'
    production.mkdir(parents=True, exist_ok=True)
    structure = production / 'lig_CG.gro'
    lines = ['coarse-grained fixture', f'{len(names):5d}']
    for index, (name, xyz) in enumerate(zip(names, positions), 1):
        lines.append(f"{1:5d}{residue:<5}{name:>5}{index:5d}"
                     + ''.join(f'{value:8.3f}' for value in xyz))
    lines.append('   1.00000   1.00000   1.00000')
    structure.write_text('\n'.join(lines) + '\n')
    trajectory = production / 'lig_CG.xtc'
    universe = mda.Universe.empty(len(names), trajectory=True)
    universe.atoms.positions = np.asarray(positions, dtype=float) * 10.0
    with mda.Writer(str(trajectory), n_atoms=len(names)) as writer:
        for _ in range(frames):
            writer.write(universe)
    return run_dir, trajectory, structure, topology_path


class QuietHandler(WSGIRequestHandler):
    """Suppress routine loopback HTTP request logging in browser tests."""
    def log_request(self, *args):
        pass


def fast_forward_source(*parts):
    """Return a Fast_Forward Python source file, or None when the vendor tree is unprovisioned."""
    candidate = FAST_FORWARD_ROOT.joinpath(*parts)
    return candidate if candidate.is_file() else None
