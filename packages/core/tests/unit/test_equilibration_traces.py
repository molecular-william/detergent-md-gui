"""The equilibration-traces producer: one bounded trace per leg, from that leg's own fake .edr.

No GROMACS is needed. The harness is the trajectory overview's own: it replaces `gmx energy`'s two calls (the term
menu, then the XVG) for each EDR and writes a fake XVG, so the producer is exercised through the shared reader it
imports rather than through a second parser of this file's invention.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from dashboard.analysis.runs import equilibration_traces, trajectory_overview

TERMS = ('Potential', 'Temperature', 'Pressure')


def write_stage_edrs(root):
    """The three equilibration EDRs, in the root and `stages/` spellings the run layouts use."""
    paths = {}
    for relative in ('03_minimization/run.edr', 'stages/04_nvt/run.edr', '05_npt/system.edr'):
        path = Path(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('not really an edr; the reader is replaced in the tests')
        paths[relative] = path
    return paths


def table(times_ps, **columns):
    return {'terms': {name: [float(value) for value in values] for name, values in columns.items()},
            'times_ps': [float(value) for value in times_ps]}


def three_tables(paths, rows=4):
    """One row-per-sample table per equilibration EDR, keyed by full path so equal file names cannot collide."""
    times = [1000.0 * index for index in range(rows)]
    steps = [float(index) for index in range(rows)]
    values = lambda base, step=1.0: [base + step * index for index in range(rows)]
    return {
        str(paths['03_minimization/run.edr']): table(steps, Potential=values(-190000.0),
                                                     Temperature=values(300.0), Pressure=values(1.0)),
        str(paths['stages/04_nvt/run.edr']): table(times, Potential=values(-189000.0),
                                                    Temperature=values(300.0), Pressure=values(1.0)),
        str(paths['05_npt/system.edr']): table(times, Potential=values(-188000.0),
                                                Temperature=values(300.0), Pressure=values(1.0)),
    }


def write_manifest(root, settings=None, tools=None):
    (Path(root) / 'manifest.json').write_text(json.dumps({
        'run_type': 'pdc', 'settings': settings or {}, 'tools': tools or {}, 'stages': []}))


def fake_gmx_energy(monkeypatch, series=None, *, menu=True, times_ps=None, legends=None, edrs=None):
    """Replace `gmx energy` with its two calls: discovery, then one XVG holding the requested terms.

    Copied from `test_run_trajectory_overview.py` -- `edrs` maps an EDR's full path (or bare file name) to its own
    terms, times and legends, so each leg can carry a different menu and x column. The XVG's columns are written in
    the file's own (reversed) order, so a reader that trusted its request order fails.
    """
    edrs = edrs or {}

    def resolve(edr):
        key = str(edr) if str(edr) in edrs else Path(edr).name
        spec = edrs.get(key) or ({} if series is None else {'terms': series})
        table = spec.get('terms') or {}
        order = list(table)
        rows = len(next(iter(table.values()))) if table else 0
        times = spec.get('times_ps', times_ps)
        times = list(times) if times is not None else [1000.0 * index for index in range(rows)]
        return table, order, rows, times, spec.get('legends', legends)

    def run(command, **kwargs):
        edr = command[command.index('-f') + 1]
        table, order, rows, times, overrides = resolve(edr)
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
        assert selected and selected[-1] == '0', 'a zero ends the selection'
        if menu:
            chosen = []
            for line in selected[:-1]:
                assert line.isdigit() and 1 <= int(line) <= len(order), line
                chosen.append(int(line))
            assert len(set(chosen)) == len(chosen), 'a term is selected once'
            names = [order[index - 1] for index in chosen]
        else:
            names = [name for name in selected[:-1] if name in order]
        columns = list(reversed(names))
        legends_for = {name: (overrides or {}).get(name, name) for name in names}
        output = Path(command[command.index('-o') + 1])
        lines = ['# a fake gmx energy XVG']
        lines += [f'@ s{index} legend "{legends_for[name]}"' for index, name in enumerate(columns)]
        for row in range(rows):
            values = ' '.join(str(table[name][row]) for name in columns)
            lines.append(f'{times[row]} {values}')
        output.write_text('\n'.join(lines) + '\n')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(trajectory_overview.subprocess, 'run', run)
    monkeypatch.setattr(trajectory_overview.tools, 'tool_path', lambda *args, **kwargs: 'gmx')


def read_record(root):
    return json.loads((Path(root) / 'equilibration-traces.json').read_text())


def test_each_leg_keeps_its_own_traces_and_the_three_terms(tmp_path, monkeypatch):
    paths = write_stage_edrs(tmp_path)
    write_manifest(tmp_path, settings={'temperature_k': 300, 'pressure_bar': 1})
    fake_gmx_energy(monkeypatch, edrs=three_tables(paths))

    result = equilibration_traces.run(tmp_path)

    record = read_record(tmp_path)
    assert result['legs'] == ['minimisation', 'nvt', 'npt']
    assert set(record['legs']) == {'minimisation', 'nvt', 'npt'}
    assert record['terms'] == list(TERMS)
    for leg, entry in record['legs'].items():
        assert set(entry['terms']) == set(TERMS), leg
        assert len(entry['x']) == len(entry['terms']['Potential']['values']) <= trajectory_overview.ENERGY_POINTS
    minimisation = record['legs']['minimisation']
    assert minimisation['x_unit'] == 'step'
    assert minimisation['x'] == [0, 1, 2, 3], 'the x column is the step count'
    assert all(isinstance(value, int) for value in minimisation['x'])
    assert minimisation['duration_ps'] is None, 'a minimisation has no simulated span'
    assert minimisation['source'] == '03_minimization/run.edr'
    nvt = record['legs']['nvt']
    assert nvt['x_unit'] == 'time_ps'
    assert nvt['x'] == [0.0, 1000.0, 2000.0, 3000.0]
    assert nvt['duration_ps'] == 3000.0
    assert nvt['source'] == 'stages/04_nvt/run.edr'
    assert nvt['terms']['Temperature']['mean'] == pytest.approx(301.5)
    assert nvt['terms']['Temperature']['values'] == [300.0, 301.0, 302.0, 303.0]
    assert nvt['terms']['Potential']['values'] == [-189000.0, -188999.0, -188998.0, -188997.0]


def test_a_term_the_edr_does_not_carry_is_absent_from_that_leg(tmp_path, monkeypatch):
    paths = write_stage_edrs(tmp_path)
    edrs = three_tables(paths)
    edrs[str(paths['05_npt/system.edr'])] = table([0.0, 1000.0], Pressure=[1.0, 2.0])
    fake_gmx_energy(monkeypatch, edrs=edrs)

    equilibration_traces.run(tmp_path)

    npt = read_record(tmp_path)['legs']['npt']
    assert set(npt['terms']) == {'Pressure'}
    assert 'Temperature' not in npt['terms']
    assert 'Potential' not in npt['terms']


def test_a_leg_with_no_energy_file_is_absent(tmp_path, monkeypatch):
    paths = write_stage_edrs(tmp_path)
    paths['05_npt/system.edr'].unlink()
    fake_gmx_energy(monkeypatch, edrs=three_tables(paths))

    equilibration_traces.run(tmp_path)

    assert set(read_record(tmp_path)['legs']) == {'minimisation', 'nvt'}


def test_one_file_answering_two_legs_is_recorded_once(tmp_path, monkeypatch):
    """A CG run's `4_CG_sim/eq.edr` answers the nvt and npt keys; it is one equilibration leg, not two."""
    for relative in ('4_CG_sim/min.edr', '4_CG_sim/eq.edr'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('not really an edr')
    write_manifest(tmp_path)
    edrs = {
        str(tmp_path / '4_CG_sim/min.edr'): table([0.0, 1.0], Potential=[-190000.0, -189999.0]),
        str(tmp_path / '4_CG_sim/eq.edr'): table([0.0, 1000.0], Potential=[-189000.0, -188999.0],
                                                   Temperature=[300.0, 301.0], Pressure=[1.0, 1.5]),
    }
    fake_gmx_energy(monkeypatch, edrs=edrs)

    equilibration_traces.run(tmp_path)

    legs = read_record(tmp_path)['legs']
    assert set(legs) == {'minimisation', 'npt'}, 'the shared equilibration file was claimed as one leg'
    assert set(legs['npt']['terms']) == set(TERMS)
    assert legs['npt']['source'] == '4_CG_sim/eq.edr'


def test_the_targets_and_build_come_from_the_run_manifest(tmp_path, monkeypatch):
    paths = write_stage_edrs(tmp_path)
    write_manifest(tmp_path, settings={'temperature_k': 310, 'cg_equil_ref_p': 2.5},
                   tools={'gmx': {'version_output': 'GROMACS version: 2026.3\nPrecision: mixed\n'}})
    fake_gmx_energy(monkeypatch, edrs=three_tables(paths))

    equilibration_traces.run(tmp_path)

    record = read_record(tmp_path)
    assert record['targets'] == {'Temperature': 310.0, 'Pressure': 2.5}
    # The version, not the banner line the tool prints first, and not the word GROMACS twice: the panel's own caption
    # already names the tool.
    assert record['gmx_version'] == '2026.3'


def test_the_kind_row_names_the_leg_energy_files_and_records_the_build():
    """The row a run's queue and the panel read: explicit .edr paths, on demand only, with the resolved build."""
    from dashboard.analysis import kinds

    row = kinds.TABLE['equilibration-traces']
    assert row.run is equilibration_traces.run
    assert row.title == 'Equilibration traces'
    assert row.records_gmx_version is True
    assert row.default_for_run_types == ()
    assert all(source.endswith('.edr') for source in row.sources), 'the record reads only energy files'
    assert '4_CG_sim/eq.edr' in row.sources
    assert len(row.sources) == len(set(row.sources)), 'a shared leg file is named once'


def test_an_unrecorded_target_and_build_are_absent_not_defaulted(tmp_path, monkeypatch):
    paths = write_stage_edrs(tmp_path)
    write_manifest(tmp_path)
    fake_gmx_energy(monkeypatch, edrs=three_tables(paths))

    equilibration_traces.run(tmp_path)

    record = read_record(tmp_path)
    assert record['targets'] == {}
    assert record['gmx_version'] is None
