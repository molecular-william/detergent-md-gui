"""The detergent's beads in place, and the topology that names them: stage 1's last two pieces.

The stamping is checked against arithmetic a reader can do by hand (a two-bead molecule, a stated centre and a
direction), and the topology against the invariant `grompp` enforces: every `[ molecules ]` count times its
molecule's bead count must equal the atoms the structure holds. The end-to-end case runs the real stage on the
repository's own DDM with a mapping the test writes, which is the first time that stage can complete.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.execution.adapters import pdc
from dashboard.execution.scripts import pdc_build

MOLECULE_ROOT = Path(__file__).resolve().parents[3] / 'molecules'
TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'},
                                                   {'name': 'HEAD', 'type': 'SN6', 'role': 'head'}],
}
PROTEIN_ITP = '[ moleculetype ]\nPROT 1\n\n[ atoms ]\n1 C1 1 PROT B01 1 0 72\n'
DRAFT = {'molecule_id': 'DDM', 'residue': 'DDM', 'terms': 2, 'reference_terms': 0, 'fallback_terms': 2,
         'beads': [{'name': 'TAIL1', 'type': 'C1', 'residue': 'DDM', 'position': [0.5, 0.0, 0.0]},
                   {'name': 'HEAD', 'type': 'SN6', 'residue': 'DDM', 'position': [0.0, 0.0, 0.0]}]}


def gro_line(residue_id, residue, name, serial, xyz) -> str:
    return (f'{residue_id:5d}{residue[:5]:<5}{name[:5]:>5}{serial:5d}'
            f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}')


def write_gro(path: Path, atoms, box=(8.0, 8.0, 8.0)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['system', str(len(atoms))]
    lines += [gro_line(residue_id, residue, name, index, xyz)
              for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    lines.append(''.join(f'{value:10.5f}' for value in box))
    path.write_text('\n'.join(lines) + '\n')
    return path


def write_cg_pdb(path: Path, atoms) -> Path:
    """The CG structure as martinize2 writes it (`-x`): `ATOM` records in Angstroms, the stage reads them back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'ATOM  {index:5d} {name:^4s} {residue:>3s} A{residue_id:4d}    '
             f'{xyz[0] * 10.0:8.3f}{xyz[1] * 10.0:8.3f}{xyz[2] * 10.0:8.3f}  1.00  0.00'
             for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    path.write_text('\n'.join(lines) + '\nEND\n')
    return path


def test_a_detergent_is_placed_with_its_head_end_at_the_site_it_was_given():
    """Heads to the water, tails to the core -- and the *head end* is what the site names.

    The placement's sites are the head ends of the belt's detergents (the tube's outer surface), so `stamp`
    translates each copy until its head-most bead sits at the site and its body hangs back toward the centre-line.
    Measured before this: the molecule's *mean* was put at the site, which left every head bead 0.25 nm past the
    site it was supposed to stand on. The direction the placement hands over is the way out of the tube, so the
    molecule's head-ward axis is the one that takes it.
    """
    along = pdc_build.stamp(DRAFT, [[3.0, 0.0, 0.0]], [[1.0, 0.0, 0.0]], first_residue=10)
    against = pdc_build.stamp(DRAFT, [[3.0, 0.0, 0.0]], [[-1.0, 0.0, 0.0]], first_residue=10)

    beads = {atom['name']: atom['position'] for atom in along}
    assert beads['HEAD'] == [3.0, 0.0, 0.0], 'the head end is the site, not the molecule\'s middle'
    assert beads['TAIL1'] == [2.5, 0.0, 0.0], 'and the tail hangs back toward the centre-line'
    flipped = {atom['name']: atom['position'] for atom in against}
    assert flipped['HEAD'] == [3.0, 0.0, 0.0], 'the anchor holds whichever way the head faces'
    assert flipped['TAIL1'] == [3.5, 0.0, 0.0], 'and the body follows the direction it was given'


def test_a_stamped_micelle_has_its_heads_toward_the_water_and_its_tails_in_the_core():
    """The property the frames are judged by: per detergent, the head is further from the micelle's centre than
    the tail -- heads to the water, tails in the core.

    This is the end-to-end shape of the defect a reader saw -- the head bead pointing into the micelle -- measured
    the way the draft's frames were measured, over a real lattice placement of the pipeline's own code.
    """
    import numpy as np

    from dashboard.execution.adapters import pdc_placement

    placed = pdc_placement.place_detergents(None, None, 24, seed=20261013, mode='lattice')
    atoms = pdc_build.stamp(DRAFT, placed['centers'], placed['directions'], first_residue=10)
    centre = np.mean([atom['position'] for atom in atoms], axis=0)

    molecules: dict[int, list[dict]] = {}
    for atom in atoms:
        molecules.setdefault(atom['residue_id'], []).append(atom)
    assert len(molecules) == 24
    centres = set()
    for residue_id, beads in molecules.items():
        head = np.mean([atom['position'] for atom in beads if atom['name'] == 'HEAD'], axis=0)
        tail = np.mean([atom['position'] for atom in beads if atom['name'] == 'TAIL1'], axis=0)
        assert np.linalg.norm(head - centre) > np.linalg.norm(tail - centre), \
            f'detergent {residue_id} has its head facing the micelle and its tail facing the water'
        centres.add(tuple(np.round(np.mean([atom['position'] for atom in beads], axis=0), 4)))
    assert len(centres) == 24, 'sanity: every detergent sits at its own placement site'


def test_every_copy_keeps_the_topologys_bead_names_and_gets_its_own_residue():
    atoms = pdc_build.stamp(DRAFT, [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                            first_residue=7)

    assert [atom['name'] for atom in atoms] == ['TAIL1', 'HEAD', 'TAIL1', 'HEAD']
    assert [atom['residue'] for atom in atoms] == ['DDM'] * 4
    assert [atom['residue_id'] for atom in atoms] == [8, 8, 9, 9], 'one residue per molecule, after the protein'


def test_a_mapping_that_marks_no_hydrophobic_core_is_refused():
    undifferentiated = {'residue': 'DDM', 'beads': [{'name': 'A', 'type': 'SN6', 'position': [0.0, 0.0, 0.0]},
                                                    {'name': 'B', 'type': 'SP1r', 'position': [0.5, 0.0, 0.0]}]}

    with pytest.raises(SystemExit, match='no hydrophobic core'):
        pdc_build.stamp(undifferentiated, [[0.0, 0.0, 0.0]], [[1.0, 0.0, 0.0]])


def test_the_topology_names_its_molecules_exactly_as_the_itps_do(tmp_path):
    protein = tmp_path / 'protein_CG.itp'
    protein.write_text(PROTEIN_ITP)
    detergent = tmp_path / 'detergent_CG.itp'
    detergent.write_text('[ moleculetype ]\nDDM 1\n\n[ atoms ]\n1 C1 1 DDM TAIL1 1 0 72\n')

    written = pdc_build.write_topologies(tmp_path, protein, detergent, 3)

    whole = (tmp_path / 'system.top').read_text()
    assert written == {'protein_molecule': 'PROT', 'detergent_molecule': 'DDM', 'detergents': 3}
    assert '#include "protein_CG.itp"' in whole and '#include "detergent_CG.itp"' in whole
    assert 'PROT\t1' in whole and 'DDM\t3' in whole
    assert 'DDM\t' not in (tmp_path / 'system_EMPTY.top').read_text(), 'the empty topology is the protein alone'


def test_a_topology_without_a_molecule_name_is_refused_rather_than_guessed():
    with pytest.raises(SystemExit, match='moleculetype'):
        pdc_build.molecule_name('; a topology with nothing to name\n')


def candidate_file(tmp_path: Path) -> Path:
    path = tmp_path / 'ddm_mapping.json'
    path.write_text(json.dumps({
        'schema_version': 3, 'molecule_id': 'DDM', 'name': 'two beads over the real DDM', 'martini_version': 3,
        'beads': [{'name': 'TAIL1', 'type': 'C1', 'atoms': [1, 2, 3, 4]},
                  {'name': 'HEAD', 'type': 'SN6', 'atoms': [5, 6, 7, 8]}],
        'connections': [['TAIL1', 'HEAD']]}))
    return path


def test_the_stage_completes_when_the_run_was_prepared_with_a_detergent_mapping(tmp_path):
    """The whole of stage 1: a placed system, a topology whose counts match its atoms, and exit 0."""
    import shutil

    # The real molecule, copied into the test's own tree, so nothing writes near the repository's files.
    root = tmp_path / 'root'
    (root / 'molecules').mkdir(parents=True)
    shutil.copytree(MOLECULE_ROOT / 'DDM', root / 'molecules' / 'DDM')
    (root / 'molecules' / 'DDM' / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    (root / 'molecules' / 'DDM' / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                settings={'seed': 20260930, 'aggregation_number': 2}, project_root=root,
                mapping=candidate_file(tmp_path))
    stage = run / Path(pdc.stage_by_name('System preparation').relative).parent
    write_cg_pdb(stage / 'cg' / 'protein_cg.pdb', [(1, 'PRO', 'B01', (0.0, 0.0, 0.0)),
                                                  (1, 'PRO', 'B02', (1.0, 0.0, 0.0)),
                                                  (1, 'PRO', 'B03', (0.0, 1.0, 0.0))])
    (stage / 'cg' / 'protein_CG.itp').write_text(PROTEIN_ITP)

    code = pdc_build.build(stage)

    assert code == 0, 'the first time this stage has anything to finish with'
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['system_top'] == 'system.top' and report['molecules']['detergent_molecule'] == 'DDM'
    system = (stage / 'system.gro').read_text().splitlines()
    beads = int(system[1])
    protein = 3
    per_detergent = len(json.loads((stage / pdc.DETERGENT_GEOMETRY).read_text())['beads'])
    assert per_detergent == 2
    assert beads == protein + 2 * per_detergent, 'the atoms present are what [ molecules ] claims'
    topology = (stage / 'system.top').read_text()
    assert 'DDM\t2' in topology and 'PROT\t1' in topology
    assert (stage / 'snapshots' / 'placement.pdb').is_file()
