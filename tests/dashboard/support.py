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

__all__ = ['PROJECT_ROOT', 'FAST_FORWARD_ROOT', 'Dashboard', 'build', 'physical_mapping',
           'write_aa_fixture', 'cg_fixture_run', 'QuietHandler', 'fast_forward_source']


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
