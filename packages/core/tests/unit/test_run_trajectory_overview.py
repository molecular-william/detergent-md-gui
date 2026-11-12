"""The trajectory overview: one sampled segment, four measured questions, and its own record.

The fixture writes a real `.gro` + `.xtc` with MDAnalysis: three DDM molecules, two of them touching and one far
away, so the aggregate count is a visible number rather than a tolerance. No GROMACS is needed -- the energy panel
says what is missing instead of inventing a curve.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import matplotlib.figure
import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.analysis.runs import trajectory_overview


def write_run(root, *, frames=5, contact_nm=0.6, positions=None):
    stage = Path(root) / 'stages' / '08_extension' / 'prod'
    stage.mkdir(parents=True)
    universe = mda.Universe.empty(6, n_residues=3, atom_resindex=[0, 0, 1, 1, 2, 2], trajectory=True)
    universe.add_TopologyAttr('names', ['B01', 'B02'] * 3)
    universe.add_TopologyAttr('resnames', ['DDM', 'DDM', 'DDM'])
    universe.add_TopologyAttr('resids', [1, 2, 3])
    positions = np.array(positions if positions is not None else
                         [[0, 0, 0], [0.3, 0, 0], [0.1, 0.2, 0], [0.4, 0.2, 0], [50, 50, 50], [50.3, 50, 50]])
    with mda.Writer(str(stage / 'run.xtc'), n_atoms=6) as writer:
        for frame in range(frames):
            universe.atoms.positions = positions + frame * 0.01
            universe.dimensions = [100, 100, 100, 90, 90, 90]
            universe.trajectory.ts.time = frame * 1000
            if frame == 0:
                universe.atoms.write(str(stage / 'run.gro'))
            writer.write(universe.atoms)
    (Path(root) / 'manifest.json').write_text(json.dumps({
        'run_type': 'pdc', 'detergent': 'DDM', 'settings': {'contact_nm': contact_nm},
        'stages': [{'name': 'CG extension MD', 'status': 'completed'}]}))
    return stage


def write_aa_run(root, *, frames=5):
    """One AA-only molecule published under `07_reference/`, with its production leg's energy above it.

    That is the live layout the overview was missing: the reference stage extracts `lig.xtc` from
    `06_production/run.xtc`, so the leg's `run.edr` is not beside the trajectory the overview reads.
    """
    reference = Path(root) / 'stages' / '07_reference'
    reference.mkdir(parents=True)
    universe = mda.Universe.empty(2, n_residues=1, atom_resindex=[0, 0], trajectory=True)
    universe.add_TopologyAttr('names', ['C1', 'C2'])
    universe.add_TopologyAttr('resnames', ['DDM'])
    universe.add_TopologyAttr('resids', [1])
    with mda.Writer(str(reference / 'lig.xtc'), n_atoms=2) as writer:
        for frame in range(frames):
            universe.atoms.positions = np.array([[0, 0, 0], [0.3, 0, 0]]) + frame * 0.01
            universe.dimensions = [100, 100, 100, 90, 90, 90]
            universe.trajectory.ts.time = frame * 1000
            if frame == 0:
                universe.atoms.write(str(reference / 'lig.gro'))
            writer.write(universe.atoms)
    production = Path(root) / 'stages' / '06_production'
    production.mkdir()
    (production / 'run.edr').write_text('not really an edr; the reader is replaced in the tests')
    (Path(root) / 'manifest.json').write_text(json.dumps({
        'run_type': 'aa_only', 'detergent': 'DDM', 'settings': {'contact_nm': 0.6},
        'stages': [{'name': 'AA reference publication', 'status': 'completed'}]}))
    return reference


def test_the_overview_measures_the_segment_and_records_its_own_limits(tmp_path):
    write_run(tmp_path)

    result = trajectory_overview.run(tmp_path)

    assert result['frames'] == 5
    assert result['molecules'] == 3
    assert result['largest_aggregate'] == 2, 'the two touching molecules are one aggregate'
    assert (tmp_path / 'trajectory-overview.png').is_file()
    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    assert record['subject'] == 'largest detergent aggregate'
    assert record['frames_in_file'] == 5 and record['stride'] == 1
    assert record['aggregates']['largest_mean'] == 2
    assert record['aggregates']['count_mean'] == 2, 'two aggregates: the touching pair and the distant molecule'
    assert record['rmsd_nm']['mean'] < 1e-3, 'a rigid translation was not fitted away'
    assert record['energy'] is None
    assert 'no .edr' in record['energy_absent']
    assert record['smoothing']['frames'] == trajectory_overview._window(5) == 2
    assert record['scientifically_validated'] is False
    assert set(record['series']) == {'times_ns', 'rmsd_nm', 'gyration_nm', 'aggregate_largest',
                                     'aggregates', 'aggregate_free'}


def test_the_contact_distance_is_read_from_the_run_settings(tmp_path):
    write_run(tmp_path, contact_nm=0.01)

    trajectory_overview.run(tmp_path)

    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    assert record["contact_nm"] == 0.01
    assert record['aggregates']['largest_mean'] == 1, 'at 0.01 nm no pair is within contact'


def test_energy_columns_are_mapped_by_their_legend(tmp_path, monkeypatch):
    """`gmx energy` writes its columns in the EDR's term order, not the selection order: the legend decides."""
    stage = write_run(tmp_path)
    (stage / 'run.edr').write_text('not really an edr; the reader is replaced below')

    def fake_energy(command, **kwargs):
        output = Path(command[command.index('-o') + 1])
        output.write_text('# a fake gmx energy XVG\n'
                          '@ s0 legend "Potential"\n@ s1 legend "Temperature"\n@ s2 legend "Pressure"\n'
                          '0 -190000 299.5 0.5\n1000 -191000 300.5 1.5\n')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(trajectory_overview.subprocess, 'run', fake_energy)
    monkeypatch.setattr(trajectory_overview.tools, 'tool_path', lambda *args, **kwargs: 'gmx')

    trajectory_overview.run(tmp_path)

    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    terms = record['energy']['terms']
    assert terms['Temperature']['mean'] == 300.0
    assert terms['Pressure']['mean'] == 1.0
    assert terms['Potential']['mean'] == pytest.approx(-190500.0)
    assert terms['Temperature']['values'] == [299.5, 300.5], 'the legend, not the first data column'


def test_the_energy_of_an_extracted_solute_is_found_one_stage_up(tmp_path):
    """The AA-CG pipeline writes `prod/lig_CG.xtc` while the leg's `md.edr` stays in `4_CG_sim/`. A sibling-only
    reader says there is no energy for a run that has one; the explicit names keep `eq.edr`/`min.edr` out."""
    prod = tmp_path / '4_CG_sim' / 'prod'
    prod.mkdir(parents=True)
    trajectory = prod / 'lig_CG.xtc'
    trajectory.write_text('')
    edr = tmp_path / '4_CG_sim' / 'md.edr'
    edr.write_text('')

    assert trajectory_overview._energy_beside(trajectory) == edr


def test_sources_stages_the_energy_file_one_stage_up(tmp_path):
    stage = write_run(tmp_path)  # .../stages/08_extension/prod
    (stage.parent / 'md.edr').write_text('not really an edr')

    entries = trajectory_overview.sources(tmp_path)

    assert entries['stages/08_extension/md.edr'] == stage.parent / 'md.edr'


def test_the_overview_reads_the_energy_file_one_stage_up(tmp_path, monkeypatch):
    """The same run the user saw: the trajectory is under `prod/`, the energy one stage above it."""
    stage = write_run(tmp_path)
    (stage.parent / 'md.edr').write_text('not really an edr; the reader is replaced below')

    def fake_energy(command, **kwargs):
        output = Path(command[command.index('-o') + 1])
        output.write_text('# a fake gmx energy XVG\n@ s0 legend "Temperature"\n'
                          '0 300.0\n1000 301.0\n')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(trajectory_overview.subprocess, 'run', fake_energy)
    monkeypatch.setattr(trajectory_overview.tools, 'tool_path', lambda *args, **kwargs: 'gmx')

    trajectory_overview.run(tmp_path)

    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    assert record['energy']['source'] == 'md.edr'
    assert record['energy']['terms']['Temperature']['mean'] == 300.5


def test_the_moving_average_uses_only_the_points_it_has_at_the_ends():
    """A centred window at an edge averages the points that exist, never padding the ends with zero."""
    assert list(trajectory_overview._moving_average([2, 2, 2, 2], 3)) == pytest.approx([2, 2, 2, 2])
    averaged = trajectory_overview._moving_average([0, 10, 0, 10], 3)
    assert averaged[0] == pytest.approx(5)
    assert averaged[1] == pytest.approx(10 / 3)
    assert averaged[3] == pytest.approx(5)


def test_a_micelle_across_the_box_face_is_one_aggregate(tmp_path):
    """The same two touching molecules, with one of them on the far face of a 10 nm box, are still one aggregate."""
    write_run(tmp_path, positions=[[1, 2, 0], [3, 2, 0], [99, 2, 0], [97, 2, 0], [50, 90, 50], [50.3, 90, 50]])

    trajectory_overview.run(tmp_path)

    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    assert record['pbc']['treatment'].startswith('minimum image')
    assert record['aggregates']['largest_mean'] == 2, 'the raw distance across the face is ~9.8 nm'
    assert record['aggregates']['free_mean'] == 1
    assert record['gyration_nm']['mean'] < 0.5, 'the aggregate is compact once its two halves are one image'


def spy_figures(monkeypatch):
    """Record every Figure `_draw` makes, so a test reads the titles a reader sees."""
    recorded = []

    class Spy(matplotlib.figure.Figure):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            recorded.append(self)

    monkeypatch.setattr(matplotlib.figure, 'Figure', Spy)
    return recorded


def fake_energy(monkeypatch, *, temperature=300.0):
    """Replace `gmx energy` with one that writes the three terms in a different column order than requested."""
    def run(command, **kwargs):
        output = Path(command[command.index('-o') + 1])
        output.write_text('# a fake gmx energy XVG\n'
                          '@ s0 legend "Potential"\n@ s1 legend "Temperature"\n@ s2 legend "Pressure"\n'
                          f'0 -190000 {temperature} 0.5\n1000 -191000 {temperature + 1} 1.5\n')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(trajectory_overview.subprocess, 'run', run)
    monkeypatch.setattr(trajectory_overview.tools, 'tool_path', lambda *args, **kwargs: 'gmx')


def test_an_aa_reference_stages_and_reads_its_production_energy(tmp_path, monkeypatch):
    """An AA-only run's energy is the leg the reference was extracted from, not a sibling of `lig.xtc`."""
    reference = write_aa_run(tmp_path)

    entries = trajectory_overview.sources(tmp_path)

    edr = tmp_path / 'stages/06_production/run.edr'
    assert entries['stages/06_production/run.edr'] == edr
    assert trajectory_overview._energy_beside(reference / 'lig.xtc') is None

    fake_energy(monkeypatch)
    trajectory_overview.run(tmp_path)

    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    assert record['energy']['terms']['Temperature']['mean'] == 300.5
    assert record['energy_absent'] is None
    assert record['subject'] == 'molecule', 'one molecule is not an aggregate'


def test_a_single_molecule_figure_has_no_aggregate_panel(tmp_path, monkeypatch):
    """A molecule cannot aggregate: the panel would be a flat line at 1, and its title would be wrong anyway."""
    write_aa_run(tmp_path)
    recorded = spy_figures(monkeypatch)
    fake_energy(monkeypatch)

    trajectory_overview.run(tmp_path)

    axes = recorded[0].axes
    titles = [axis.get_title() for axis in axes]
    assert len(axes) == 5, 'RMSD, Rg and the three energy terms; no aggregate cell'
    assert titles[:2] == ['RMSD', 'Radius of gyration']
    assert titles[2].startswith('Temperature · mean')
    assert not any('aggregate' in title.lower() for title in titles)


def test_a_multi_molecule_figure_keeps_the_generic_aggregate_panel(tmp_path, monkeypatch):
    """A micelle's aggregate curve stays; only its detergent-specific title goes."""
    write_run(tmp_path)
    recorded = spy_figures(monkeypatch)

    trajectory_overview.run(tmp_path)

    titles = [axis.get_title() for axis in recorded[0].axes]
    assert titles[:3] == ['RMSD', 'Radius of gyration', 'Largest aggregate'], titles
