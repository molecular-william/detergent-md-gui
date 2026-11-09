"""Surface generation: reviewed GROMACS knobs, bounded parallel variants, and per-variant progress.

These fake the trajectory work and the gmx runner. No simulation or production trajectory is read: what is under
test is the command construction, the variant set, the join order and failure attribution.
"""
import json
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest
from dashboard.analysis.runs.radii import PROBE
from detergent_validation.analysis.runs import surfaces

BEADS = [{'export_name': 'R1', 'size': 'R', 'virtual_site': False},
         {'export_name': 'R2', 'size': 'R', 'virtual_site': False}]


class _Atoms:
    def __init__(self, names):
        self.names = names

    def __len__(self):
        return len(self.names)


class _Trajectory:
    def close(self):
        pass


class _Universe:
    def __init__(self, names):
        self.atoms = _Atoms(names)
        self.trajectory = _Trajectory()


def _fake_mda():
    aa_names, cg_names = ['C1', 'C2'], [bead['export_name'] for bead in BEADS]

    def Universe(path, trajectory):
        return _Universe(cg_names if 'lig_CG' in str(path) else aa_names)

    return types.SimpleNamespace(Universe=Universe)


def _run(tmp_path, rings=True):
    """The five sources `generate` reads, in the layout it reads them from; contents are never parsed."""
    root = tmp_path / 'run'
    for relative in ('1_AA-reference/prod/lig.gro', '1_AA-reference/prod/lig.xtc',
                     '4_CG_sim/prod/lig_CG.gro', '4_CG_sim/prod/lig_CG.xtc'):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('placeholder')
    model = {'rings': rings, 'beads': BEADS}
    (root / '2_mapping').mkdir(parents=True)
    (root / '2_mapping/model.json').write_text(json.dumps(model))
    return root


def _fake_generate(monkeypatch):
    """Fake the stateful extraction; keep the real orchestration and post-processing."""
    monkeypatch.setitem(sys.modules, 'MDAnalysis', _fake_mda())
    monkeypatch.setattr(surfaces, '_write_variant',
                        lambda label, universe, reader, radii, model, work: np.zeros((4, 3)) + _variant_offset(label))
    monkeypatch.setattr(surfaces, 'align', lambda points, target, physical: points)
    monkeypatch.setattr(surfaces, 'envelope',
                        lambda points, radii: (np.zeros((4, 3)), np.array([[0, 1, 2], [0, 1, 3]])))


def _variant_offset(label):
    return {'AA': (0, 0, 0), 'Mapped raw': (1, 0, 0), 'Mapped ring-scaled': (2, 0, 0),
            'Simulated CG': (3, 0, 0)}[label]


def test_sasa_commands_pin_the_reviewed_knobs():
    full, snapshot = surfaces._sasa_commands('/opt/gmx')

    assert full == ['/opt/gmx', 'sasa', '-s', 'surface.gro', '-f', 'surface.xtc', '-o', 'sasa.xvg',
                    '-probe', str(PROBE), '-ndots', '240', '-surface', 'all', '-output', 'all']
    assert snapshot == ['/opt/gmx', 'sasa', '-s', 'surface.gro', '-f', 'surface.gro',
                        '-o', 'snapshot-sasa.xvg', '-q', 'connolly.pdb', '-probe', str(PROBE),
                        '-ndots', '240', '-surface', 'all', '-output', 'all']


@pytest.mark.parametrize('rings, expected', [
    (True, ['AA', 'Mapped raw', 'Mapped ring-scaled', 'Simulated CG']),
    (False, ['AA', 'Mapped raw', 'Simulated CG']),
])
def test_variant_set_keeps_every_published_surface(tmp_path, monkeypatch, rings, expected):
    _fake_generate(monkeypatch)
    monkeypatch.setattr(surfaces, '_gmx_variant', lambda label, work, gmx: (
        [{'cwd': str(work.relative_to(work.parents[2])), 'command': [label], 'exit_code': 0}],
        {'frames': 2, 'start_ps': 0.0, 'end_ps': 10.0, 'mean_nm2': 1.0, 'std_nm2': 0.0, 'xvg': 'sasa.xvg'}))

    metadata = surfaces.generate(_run(tmp_path, rings))

    assert list(metadata['statistics']) == expected
    assert [command['command'][0] for command in metadata['commands']] == expected
    found = sorted(path.name for path in (tmp_path / 'run/analysis/surfaces').iterdir() if path.is_dir())
    assert found == sorted(label.lower().replace(' ', '-') for label in expected)


def test_metadata_commands_stay_in_variant_order_when_completions_interleave(tmp_path, monkeypatch):
    _fake_generate(monkeypatch)
    delays = {'AA': 0.08, 'Mapped raw': 0.0, 'Mapped ring-scaled': 0.04, 'Simulated CG': 0.0}

    def fake_gmx(label, work, gmx):
        time.sleep(delays[label])
        return ([{'cwd': 'x', 'command': [label], 'exit_code': 0}],
                {'frames': 2, 'start_ps': 0.0, 'end_ps': 10.0, 'mean_nm2': 1.0, 'std_nm2': 0.0, 'xvg': 'sasa.xvg'})

    monkeypatch.setattr(surfaces, '_gmx_variant', fake_gmx)

    metadata = surfaces.generate(_run(tmp_path))

    assert [command['command'][0] for command in metadata['commands']] == \
        ['AA', 'Mapped raw', 'Mapped ring-scaled', 'Simulated CG']


def test_one_failed_variant_is_named_and_the_others_are_still_attempted(tmp_path, monkeypatch):
    _fake_generate(monkeypatch)
    attempted = []

    def fake_run(command, cwd, text, capture_output, timeout):
        label = Path(cwd).name
        attempted.append(label)
        if label == 'mapped-raw' and 'surface.xtc' in command:
            return types.SimpleNamespace(returncode=1, stdout='', stderr='connolly exploded: bad solvent')
        if 'surface.xtc' in command:
            (Path(cwd) / 'sasa.xvg').write_text('# comment\n0.0 12.5\n10.0 12.7\n')
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(surfaces.subprocess, 'run', fake_run)

    with pytest.raises(RuntimeError) as joined:
        surfaces.generate(_run(tmp_path))

    message = str(joined.value)
    assert message.startswith('surface variants failed:')
    assert 'Mapped raw' in message and 'connolly exploded: bad solvent' in message
    # All four variants were attempted despite the first failure; the join happens after every future settles.
    assert set(attempted) == {'aa', 'mapped-raw', 'mapped-ring-scaled', 'simulated-cg'}


def test_phases_say_which_variant_is_running(tmp_path, monkeypatch):
    _fake_generate(monkeypatch)
    phases = []
    monkeypatch.setattr(surfaces.progress, 'report', phases.append)
    monkeypatch.setattr(surfaces, '_gmx_variant', lambda label, work, gmx: (
        [{'cwd': 'x', 'command': [label], 'exit_code': 0}],
        {'frames': 2, 'start_ps': 0.0, 'end_ps': 10.0, 'mean_nm2': 1.0, 'std_nm2': 0.0, 'xvg': 'sasa.xvg'}))

    surfaces.generate(_run(tmp_path))

    for label in ('AA', 'Mapped raw', 'Mapped ring-scaled', 'Simulated CG'):
        extracting = phases.index(f'Surfaces: extracting {label}')
        submitted = phases.index(f'Surfaces: {label} · gmx sasa')
        done = phases.index(f'Surfaces: {label} done')
        assert extracting < submitted < done, (label, phases)
    assert phases[-1] == 'Surfaces: envelopes and figure'
