"""The trajectory overview: one sampled segment, four measured questions, and its own record.

The fixture writes a real `.gro` + `.xtc` with MDAnalysis: three DDM molecules, two of them touching and one far
away, so the aggregate count is a visible number rather than a tolerance. No GROMACS is needed -- the energy panel
says what is missing instead of inventing a curve.
"""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import matplotlib.figure
import MDAnalysis as mda
import numpy as np
import pytest
from dashboard.analysis.runs import trajectory_overview

#: The keys `series_summary` promises, which every rich series in the record must carry.
SUMMARY_KEYS = {'n', 'mean', 'std', 'sem', 'block_sem', 'blocks', 'median', 'p05', 'p95', 'min', 'max',
                'first_half_mean', 'second_half_mean', 'slope_per_ns', 'slope_stderr', 'r2', 'rms_from_fit',
                'autocorr_time_samples', 'effective_samples'}


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


def fake_gmx_energy(monkeypatch, series, *, menu=True, times_ps=None, legends=None):
    """Replace `gmx energy` with its two calls: discovery, then one XVG holding every term.

    `series` maps a term name to its values, one per row, and its insertion order is the menu's order. The XVG's
    columns are written in the file's own (reversed) order, so a reader that trusted its request order fails. No
    `-o` prints the numbered menu on stderr, as the real tool does; `menu=False` emulates a version whose output
    cannot be parsed. `legends` overrides an XVG legend, for GROMACS' spelling (`Proper-Dih.` becomes `Proper Dih.`).
    """
    order = list(series)
    rows = len(next(iter(series.values())))
    times = list(times_ps) if times_ps is not None else [1000.0 * index for index in range(rows)]
    columns = list(reversed(order))
    legends = {name: (legends or {}).get(name, name) for name in order}

    def run(command, **kwargs):
        if '-o' not in command:
            if not menu:
                return SimpleNamespace(returncode=1, stdout='', stderr='no term menu here')
            assert kwargs.get('input') == '0\n', 'discovery runs with the one input the menu needs'
            listed = ''.join(f'{index + 1}  {name}\n' for index, name in enumerate(order))
            stderr = ('Select the terms you want from the following list by\n'
                      'selecting either (comma) separated numbers or using ranges.\n\n'
                      f'{listed}---  ---\n')
            return SimpleNamespace(returncode=1, stdout='', stderr=stderr)
        selected = [line for line in kwargs.get('input', '').splitlines() if line.strip()]
        if menu:
            assert selected[:len(order)] == [str(index + 1) for index in range(len(order))], selected
            assert selected[len(order)] == '0', 'a zero ends the selection'
        output = Path(command[command.index('-o') + 1])
        lines = ['# a fake gmx energy XVG']
        lines += [f'@ s{index} legend "{legends[name]}"' for index, name in enumerate(columns)]
        for row in range(rows):
            values = ' '.join(str(series[name][row]) for name in columns)
            lines.append(f'{times[row]} {values}')
        output.write_text('\n'.join(lines) + '\n')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(trajectory_overview.subprocess, 'run', run)
    monkeypatch.setattr(trajectory_overview.tools, 'tool_path', lambda *args, **kwargs: 'gmx')


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

    fake_gmx_energy(monkeypatch, {'Potential': [-190000, -191000],
                                  'Temperature': [299.5, 300.5],
                                  'Pressure': [0.5, 1.5]})

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

    fake_gmx_energy(monkeypatch, {'Temperature': [300.0, 301.0]})

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
    """The three plotted terms, with the XVG columns in a different order than requested."""
    fake_gmx_energy(monkeypatch, {'Potential': [-190000, -191000],
                                  'Temperature': [temperature, temperature + 1],
                                  'Pressure': [0.5, 1.5]})


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


def test_the_shape_series_carry_the_full_statistics(tmp_path):
    """RMSD and Rg are not just means: the record states spread, drift, distribution and effective samples."""
    write_run(tmp_path)

    trajectory_overview.run(tmp_path)

    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    for name in ('rmsd_nm', 'gyration_nm'):
        entry = record[name]
        assert set(entry) == SUMMARY_KEYS | {'se'}, name
        assert entry['se'] == entry['block_sem'], 'the compatibility key is the honest block standard error'
        assert all(math.isfinite(value) for value in entry.values() if isinstance(value, (int, float))), name


def test_the_shape_descriptors_are_summarised(tmp_path):
    """The gyration tensor gives three non-increasing eigenvalues and three finite scalar shape metrics."""
    write_run(tmp_path)

    trajectory_overview.run(tmp_path)

    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    shape = record['shape']
    eigenvalues = shape['rg_eigenvalues_nm']
    assert set(eigenvalues) == {'mean', 'std', 'first_half', 'second_half'}
    for key in ('mean', 'std', 'first_half', 'second_half'):
        assert len(eigenvalues[key]) == 3, key
    assert eigenvalues['mean'][0] >= eigenvalues['mean'][1] >= eigenvalues['mean'][2] >= 0
    for name in ('asphericity', 'acylindricity', 'shape_anisotropy'):
        entry = shape[name]
        assert set(entry) == SUMMARY_KEYS, name
        assert math.isfinite(entry['mean']), name


def test_rmsf_and_end_to_end_are_measured_for_the_subject(tmp_path):
    """The four-atom subject gets a per-atom RMSF and a pairwise end-to-end series; both are finite."""
    write_run(tmp_path)

    trajectory_overview.run(tmp_path)

    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    rmsf = record['rmsf_nm']
    assert rmsf['atoms'] == 4
    assert len(rmsf['per_atom']) == 4
    assert 0.0 <= rmsf['mean'] <= rmsf['max']
    end_to_end = record['end_to_end_nm']
    assert set(end_to_end) == SUMMARY_KEYS
    assert end_to_end['n'] == 5
    assert end_to_end['mean'] == pytest.approx(0.044721, abs=1e-5)
    assert 'end_to_end_absent' not in record


def test_the_energy_record_summarises_every_term_and_the_drift(tmp_path, monkeypatch):
    """Discovery opens the whole EDR; only the plotted terms keep their samples, and the drift is arithmetic."""
    stage = write_run(tmp_path)
    (stage / 'run.edr').write_text('not really an edr; the reader is replaced below')
    fake_gmx_energy(monkeypatch, {
        'Potential': [0.0, -100.0, -200.0, -300.0, -400.0],
        'Total-Energy': [0.0, 25.0, 50.0, 75.0, 100.0],
        'Kinetic-En.': [0.0, 0.0, 0.0, 0.0, 0.0],
        'Bond': [10.0, 11.0, 12.0, 13.0, 14.0],
        'Angle': [20.0, 21.0, 22.0, 23.0, 24.0],
        'LJ-SR:non-Water-Water': [-1.0, -2.0, -3.0, -4.0, -5.0],
        'Coul-SR:non-Water-Water': [-6.0, -7.0, -8.0, -9.0, -10.0],
        'Pres-XX': [1.0, 2.0, 3.0, 4.0, 5.0],
        'Vir-XX': [10.0, 20.0, 30.0, 40.0, 50.0],
        '#Surf*SurfTen': [0.5, 0.6, 0.7, 0.8, 0.9],
        'Temperature': [300.0, 301.0, 302.0, 303.0, 304.0],
        'Pressure': [1.0, 1.1, 1.2, 1.3, 1.4],
    })

    trajectory_overview.run(tmp_path)

    energy = json.loads((tmp_path / 'trajectory-overview.json').read_text())['energy']
    assert set(energy['components']) == {'Potential', 'Bond', 'Angle'}
    assert energy['components']['Bond']['mean'] == 12.0
    assert set(energy['interactions']) == {'LJ-SR:non-Water-Water', 'Coul-SR:non-Water-Water'}
    assert set(energy['pressure_tensor']) == {'Pres-XX', 'Vir-XX', '#Surf*SurfTen'}
    assert energy['terms']['Bond']['mean'] == 12.0
    assert 'values' not in energy['terms']['Bond'], 'a statistics-only term keeps the JSON bounded'
    assert 'time_ps' not in energy['terms']['Bond']
    assert energy['terms']['Temperature']['values'] == [300.0, 301.0, 302.0, 303.0, 304.0]
    drift = energy['drift']
    assert drift['total_energy_slope_per_ns'] == pytest.approx(25.0)
    assert drift['potential_slope_per_ns'] == pytest.approx(-100.0)
    assert drift['kinetic_energy_slope_per_ns'] == pytest.approx(0.0)
    assert drift['ratio'] == pytest.approx(0.25), '|25| / |-100|'
    assert drift['nve'] is False, 'a pdc leg is not an NVE AA production leg'
    assert 'energy balance' in drift['basis']


def test_drift_nve_follows_the_aa_manifest_couplings(tmp_path, monkeypatch):
    """Both coupling keys 'no' is NVE; a recorded thermostat makes it false; a missing record is unknown."""
    write_aa_run(tmp_path)
    manifest_path = tmp_path / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['settings'].update({'aa_production_tcoupl': 'no', 'aa_production_pcoupl': 'no'})
    manifest_path.write_text(json.dumps(manifest))
    fake_gmx_energy(monkeypatch, {'Total-Energy': [0.0, 10.0], 'Potential': [0.0, -20.0],
                                  'Temperature': [300.0, 301.0]})

    trajectory_overview.run(tmp_path)
    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    assert record['energy']['drift']['nve'] is True

    manifest['settings']['aa_production_tcoupl'] = 'V-rescale'
    manifest_path.write_text(json.dumps(manifest))
    trajectory_overview.run(tmp_path)
    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    assert record['energy']['drift']['nve'] is False
    assert 'V-rescale' in record['energy']['drift']['basis']

    del manifest['settings']['aa_production_tcoupl']
    del manifest['settings']['aa_production_pcoupl']
    manifest_path.write_text(json.dumps(manifest))
    trajectory_overview.run(tmp_path)
    record = json.loads((tmp_path / 'trajectory-overview.json').read_text())
    assert record['energy']['drift']['nve'] is None, 'an unrecorded coupling is unknown, not conservation'


def test_a_missing_energy_menu_falls_back_to_the_three_plotted_terms(tmp_path, monkeypatch):
    """When discovery prints nothing parseable, the old three-term request still renders the figure."""
    stage = write_run(tmp_path)
    (stage / 'run.edr').write_text('not really an edr; the reader is replaced below')
    fake_gmx_energy(monkeypatch, {'Temperature': [300.0, 301.0],
                                  'Pressure': [1.0, 1.5],
                                  'Potential': [-190000.0, -191000.0]}, menu=False)

    trajectory_overview.run(tmp_path)

    energy = json.loads((tmp_path / 'trajectory-overview.json').read_text())['energy']
    assert set(energy['terms']) == {'Temperature', 'Pressure', 'Potential'}
    assert energy['terms']['Temperature']['mean'] == 300.5
    assert energy['terms']['Temperature']['values'] == [300.0, 301.0]


def test_the_menu_is_parsed_with_the_indices_gromacs_prints():
    """A real 2026.3 menu numbers terms from 1, several per row, with its dashed rule before the rows."""
    menu = ('Select the terms you want from the following list by\n'
            'selecting either (part of) the name or the number or a combination.\n'
            'End your selection with an empty line or a zero.\n'
            '-------------------------------------------------------------------\n'
            '  1  Angle            2  Proper-Dih.      3  LJ-14            4  Coulomb-14    \n'
            '  5  LJ-(SR)          6  Coulomb-(SR)     7  Coul.-recip.     8  Potential     \n'
            '  9  Kinetic-En.     10  Total-Energy    11  Conserved-En.   12  Temperature   \n'
            '\n')
    assert trajectory_overview._energy_menu(menu) == [
        (1, 'Angle'), (2, 'Proper-Dih.'), (3, 'LJ-14'), (4, 'Coulomb-14'),
        (5, 'LJ-(SR)'), (6, 'Coulomb-(SR)'), (7, 'Coul.-recip.'), (8, 'Potential'),
        (9, 'Kinetic-En.'), (10, 'Total-Energy'), (11, 'Conserved-En.'), (12, 'Temperature')]


def test_xvg_legends_are_folded_to_the_canonical_term_names(tmp_path, monkeypatch):
    """GROMACS writes `Total-Energy` as `Total Energy` in the XVG; the drift and components still find it."""
    stage = write_run(tmp_path)
    (stage / 'run.edr').write_text('not really an edr; the reader is replaced below')
    fake_gmx_energy(monkeypatch, {
        'Total-Energy': [0.0, 10.0, 20.0, 30.0, 40.0],
        'Kinetic-En.': [0.0, 1.0, 2.0, 3.0, 4.0],
        'Proper-Dih.': [5.0, 6.0, 7.0, 8.0, 9.0],
        'Potential': [0.0, -10.0, -20.0, -30.0, -40.0],
        'Temperature': [300.0, 300.0, 300.0, 300.0, 300.0],
    }, legends={'Total-Energy': 'Total Energy', 'Kinetic-En.': 'Kinetic En.',
                'Proper-Dih.': 'Proper Dih.'})

    trajectory_overview.run(tmp_path)

    energy = json.loads((tmp_path / 'trajectory-overview.json').read_text())['energy']
    assert 'Proper Dih.' in energy['terms'], 'terms keep the legend the XVG actually printed'
    assert energy['components']['Proper-Dih.']['mean'] == 7.0
    assert energy['drift']['total_energy_slope_per_ns'] == pytest.approx(10.0)
    assert energy['drift']['kinetic_energy_slope_per_ns'] == pytest.approx(1.0)
    assert energy['drift']['ratio'] == pytest.approx(1.0)
    assert energy['terms']['Temperature']['values'] == [300.0] * 5
