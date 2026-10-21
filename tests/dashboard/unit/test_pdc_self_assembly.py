"""Self-assembly placement: detergents at random around the protein, and the seed that makes it reproducible.

T6 of the new-run panel plan (`2026-10-12-pdc-new-run-panel.md`). The properties worth pinning are the ones a
reader would otherwise have to trust: the count is exact, every placed detergent sits inside the box the protein is
inserted into and clear of the protein, the seed decides and a different seed does not, the build records which
mode built the system, and the lattice mode is untouched by the arrival of the second one.

The protein fixture is a hollow ellipsoid of beads -- a surface, which is what a real protein bead set is -- so a
random cloud has room to land in without being asked to thread between the atoms.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from dashboard.execution.adapters import pdc, pdc_box, pdc_placement
from micelle.packing import pack_micelle
from micelle.registry import load_template
from tests.dashboard.pdc_fixtures import candidate_file, write_cg_pdb

MARGIN_NM = 2.0
INITIAL_Z_NM = 6.0
MOLECULE_ROOT = Path(__file__).resolve().parents[3] / 'molecules'


def _template(tmp_path):
    (tmp_path / 'x.pdb').write_text('')
    (tmp_path / 'x.itp').write_text('')
    path = tmp_path / 'x.json'
    path.write_text(json.dumps({'name': 'X', 'residue': 'X', 'beads': [{'name': 'B1'}, {'name': 'B2'}],
                                'coordinates': 'x.pdb', 'topology': 'x.itp', 'tail_direction': [0, 0, -1]}))
    return load_template(path)


def _protein(axes=(2.0, 2.0, 1.0), rings=6, spokes=12):
    """A hollow ellipsoid of beads: the surface a membrane protein presents, with free volume inside and out."""
    points = []
    for ring in range(1, rings):
        theta = np.pi * ring / rings
        for spoke in range(spokes):
            phi = 2 * np.pi * spoke / spokes
            points.append([axes[0] * np.sin(theta) * np.cos(phi),
                           axes[1] * np.sin(theta) * np.sin(phi),
                           axes[2] * np.cos(theta)])
    return [[round(float(value), 6) for value in point] for point in points]


# The existing lattice test's three-point protein, kept small on purpose: this module pins that the *lattice* still
# means exactly what it meant, so it is checked against the builder's own generator rather than against numbers here.
TINY = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def test_self_assembly_places_exactly_n_inside_the_box_and_clear_of_the_protein(tmp_path):
    protein = _protein()
    placed = pdc_placement.place_detergents(protein, _template(tmp_path), 20, seed=11, mode='self-assembly',
                                            margin_nm=MARGIN_NM, initial_z_nm=INITIAL_Z_NM)

    assert placed['valid'], placed['issues']
    assert placed['mode'] == 'self-assembly'
    assert len(placed['centers']) == 20, 'the requested count is the count that is placed'

    points = np.asarray(protein)
    centres = np.asarray(placed['centers'])
    half = np.asarray(pdc_box.initial_box(protein, margin_nm=MARGIN_NM, initial_z_nm=INITIAL_Z_NM)) / 2
    middle = points.mean(0)
    for centre in centres:
        assert np.linalg.norm(centre - points, axis=1).min() >= pdc_placement.MIN_CLEARANCE_NM, \
            'a detergent overlapping the protein is not a placement'
        assert (np.abs(centre - middle) <= half + 1e-9).all(), 'every detergent is inside the box it was placed in'
    assert placed['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM
    # The builder's own overlap gate has to pass too, or the placement is one it would have refused.
    assert not any('overlap' in issue for issue in placed['issues']), placed['issues']


def test_the_seed_decides_a_self_assembled_placement(tmp_path):
    first = pdc_placement.place_detergents(_protein(), _template(tmp_path), 16, seed=5, mode='self-assembly')
    again = pdc_placement.place_detergents(_protein(), _template(tmp_path), 16, seed=5, mode='self-assembly')
    other = pdc_placement.place_detergents(_protein(), _template(tmp_path), 16, seed=6, mode='self-assembly')

    assert first['centers'] == again['centers'], 'the same seed rebuilds the same placement'
    assert first['centers'] != other['centers'], 'a different seed is a different build'


def test_an_empty_micelle_self_assembles_by_the_same_path(tmp_path):
    placed = pdc_placement.place_detergents(None, _template(tmp_path), 12, seed=3, mode='self-assembly')

    assert placed['valid'] and placed['protein_free']
    assert placed['mode'] == 'self-assembly'
    assert len(placed['centers']) == 12 and placed['protein_clearance_nm'] is None


def test_the_lattice_stays_the_default_and_still_means_the_lattice(tmp_path):
    default = pdc_placement.place_detergents(TINY, _template(tmp_path), 12, seed=7)
    named = pdc_placement.place_detergents(TINY, _template(tmp_path), 12, seed=7, mode='lattice')
    centres, _ = pack_micelle(np.asarray(TINY), None, 12, 7, radius=pdc_placement.DEFAULT_RADIUS_NM)

    assert default['mode'] == 'lattice', 'an unstated mode is the behaviour every existing run had'
    assert default['centers'] == named['centers'] == centres.tolist()


def test_an_unknown_mode_is_refused_rather_than_guessed(tmp_path):
    with pytest.raises(ValueError, match='mode'):
        pdc_placement.place_detergents(TINY, _template(tmp_path), 4, seed=1, mode='brownian')


# --- the build: which mode the system was built in, recorded where the run's readers look ---------------------------------

TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'},
                                                   {'name': 'HEAD', 'type': 'SN6', 'role': 'head'}],
}
PROTEIN_ITP = '[ moleculetype ]\nPROT 1\n\n[ atoms ]\n1 C1 1 PROT B01 1 0 72\n'


def _prepared_run(tmp_path: Path, *, placement_mode=None, aggregation_number=8):
    """A run prepared through the adapter, with the CG protein already in place so martinize2 never runs."""
    root = tmp_path / 'root'
    (root / 'molecules').mkdir(parents=True)
    shutil.copytree(MOLECULE_ROOT / 'DDM', root / 'molecules' / 'DDM')
    (root / 'molecules' / 'DDM' / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    (root / 'molecules' / 'DDM' / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    run = tmp_path / 'run'
    run.mkdir()
    settings = {'seed': 20260930, 'aggregation_number': aggregation_number}
    if placement_mode is not None:
        settings['placement_mode'] = placement_mode
    pdc.prepare(run, protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                settings=settings, project_root=root, mapping=candidate_file(tmp_path))
    stage = run / Path(pdc.stage_by_name('System preparation').relative).parent
    ellipsoid = _protein()
    write_cg_pdb(stage / 'cg' / 'protein_cg.pdb',
                 [(1, 'PRO', f'B{index:02d}', point) for index, point in enumerate(ellipsoid, 1)])
    (stage / 'cg' / 'protein_CG.itp').write_text(PROTEIN_ITP)
    return run, stage


def test_a_self_assembled_build_records_its_mode_in_the_report_and_the_manifest(tmp_path):
    """The mode is provenance: a reader has to be able to tell which build made the system, without re-deriving it."""
    from dashboard.execution.scripts import pdc_build

    run, stage = _prepared_run(tmp_path, placement_mode='self-assembly')

    code = pdc_build.build(stage)

    assert code == 0, 'the placement path with a mapping is the one that finishes'
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['placement_mode'] == 'self-assembly'
    assert report['placed_detergents'] == 8 and report['placement_issues'] == []
    assert report['protein_clearance_nm'] >= pdc_placement.MIN_CLEARANCE_NM
    settings = json.loads((stage / pdc.SETTINGS_NAME).read_text())
    assert settings['placement_mode'] == 'self-assembly'
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['settings']['placement_mode'] == 'self-assembly', 'the run manifest carries the mode'


def test_the_lattice_is_what_a_build_does_when_no_mode_is_stated(tmp_path):
    from dashboard.execution.scripts import pdc_build

    run, stage = _prepared_run(tmp_path)

    code = pdc_build.build(stage)

    assert code == 0
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['placement_mode'] == 'lattice'
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['settings']['placement_mode'] == 'lattice'


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / 'root'
    (root / 'molecules').mkdir(parents=True)
    shutil.copytree(MOLECULE_ROOT / 'DDM', root / 'molecules' / 'DDM')
    (root / 'molecules' / 'DDM' / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    return root


def test_the_panels_spelling_of_the_mode_reaches_the_builders_own(tmp_path):
    """The panel sends `pdc_placement_mode`; the settings file is spelled for the builder, as every other field is."""
    root = _minimal_root(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()

    pdc.prepare(run, template='molecules/DDM/micelle_template.json',
                settings={'seed': 20260930, 'aggregation_number': 4, 'pdc_placement_mode': 'self-assembly'},
                project_root=root)

    settings = json.loads((run / '1_system' / pdc.SETTINGS_NAME).read_text())
    assert settings['placement_mode'] == 'self-assembly'
    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['settings']['placement_mode'] == 'self-assembly'


def test_a_build_refuses_an_unknown_placement_mode_at_admission(tmp_path):
    root = _minimal_root(tmp_path)
    (tmp_path / 'run').mkdir()

    with pytest.raises(ValueError, match='mode'):
        pdc.prepare(tmp_path / 'run', template='molecules/DDM/micelle_template.json', project_root=root,
                    settings={'seed': 1, 'pdc_placement_mode': 'brownian'})
