"""The osmotic run type: that it is reachable, that it refuses what it must, and that it prepares a run.

The last one is the substance. `prepare` is what the executor runs before a single GROMACS command, so a test that
only checked the dataclass would pass while the run was unbuildable.
"""

import pytest

from dashboard.execution import protocol
from dashboard.execution.adapters import osmotic

MAPPING = {'beads': [{'name': 'S1A', 'type': 'SP1r', 'atoms': [1, 2, 3]},
                     {'name': 'S1B', 'type': 'SP4r', 'atoms': [4, 5, 6]},
                     {'name': 'S1C', 'type': 'SP1r', 'atoms': [7, 8, 9]},
                     {'name': 'VS1', 'type': 'TC4', 'atoms': []}]}


def solute_root(tmp_path, *, complete=True):
    root = tmp_path / 'solute'
    root.mkdir(exist_ok=True)
    names = osmotic.SOLUTE_FILES if complete else ('solute.gro',)
    for name in names:
        (root / name).write_text('placeholder\n')
    return root


def test_the_run_type_is_reachable_by_name():
    """Without this an osmotic job cannot be created at all: `adapter_for` is how the executor finds a run type."""
    entry = protocol.adapter_for('osmotic')

    assert entry is osmotic.PROTOCOL
    assert entry.name == 'osmotic'
    assert [name for name, _ in osmotic.STAGES] == ['Osmotic condition']


def test_the_defaults_are_the_papers_durations_and_a_temperature_that_says_where_it_came_from():
    values = osmotic.stage_defaults()['values']

    assert values['osmotic_production_ps'] == pytest.approx(500000.0)      # 500 ns
    assert values['osmotic_equilibration_ps'] == pytest.approx(10000.0)    # 10 ns
    assert values['temperature_k'] == pytest.approx(308.15)                # Ebrahimi & Sadeghi 2016
    assert 'osmotic' in osmotic.stage_defaults()['sources']


def test_settings_are_range_checked_and_a_ragged_duration_is_refused():
    assert osmotic.normalize_settings({'osmotic_molality': 2.5})['osmotic_molality'] == pytest.approx(2.5)
    assert isinstance(osmotic.normalize_settings({})['mdrun_ntomp'], int)

    with pytest.raises(ValueError, match='between 0.0 and 2.5'):
        osmotic.normalize_settings({'osmotic_molality': 3.0})
    with pytest.raises(ValueError, match='whole number of output intervals'):
        osmotic.normalize_settings({'osmotic_production_ps': 5005.0})
    with pytest.raises(ValueError, match='Unknown osmotic setting'):
        osmotic.normalize_settings({'nope': 1})
    with pytest.raises(ValueError, match='must be numeric'):
        osmotic.normalize_settings({'osmotic_molality': 'a lot'})


def test_readiness_names_the_blocker_rather_than_saying_no(tmp_path):
    """A blocker with the file name in it is what a caller can act on."""
    bare = osmotic.readiness({'molecule_id': 'Maltose'})
    assert bare['ready'] is False
    assert any('solute_root is required' in blocker for blocker in bare['blockers'])
    assert any(check['label'] == 'GROMACS' for check in bare['checks'])

    partial = osmotic.readiness({'molecule_id': 'Maltose', 'solute_root': str(solute_root(tmp_path, complete=False))})
    assert any('solute.itp' in blocker for blocker in partial['blockers'])

    named = osmotic.readiness({'solute_root': str(solute_root(tmp_path))})
    assert any('molecule_id is required' in blocker for blocker in named['blockers'])


def test_the_types_radii_come_from_the_repositorys_own_table():
    """A bead with no atoms is a massless virtual site and leaves no room; the others are spheres at our own radii."""
    from dashboard.models.sugars import recognition

    radii = osmotic.solute_bead_radii(MAPPING)

    assert len(radii) == 3
    assert radii[0] == pytest.approx(recognition.RADII_NM['S'])
    assert osmotic.solute_bead_radii({}) == []


def test_prepare_builds_a_run_the_executor_could_start(tmp_path):
    """The substance: the inputs exist, the stage has its script and its own copy, and the manifest is written."""
    record = osmotic.prepare(tmp_path, {'molecule_id': 'Maltose', 'solute_root': str(solute_root(tmp_path)),
                                        'mapping_snapshot': MAPPING,
                                        'settings': {'osmotic_molality': 1.0}, 'profile': 'standard'})

    assert record['molality_achieved'] == pytest.approx(1.0, rel=0.01)
    for name in ('minimization.mdp', 'eq.mdp', 'md.mdp', 'reference.itp', 'osmotic_condition.json'):
        assert (tmp_path / 'inputs' / name).is_file(), name
    assert (tmp_path / '01_simulate' / 'run.sh').is_file()
    # The runner's own documented layout: the molecule in `solute/` beside it, the build's files in its directory.
    assert (tmp_path / '01_simulate' / 'md.mdp').is_file()
    assert (tmp_path / '01_simulate' / 'solute' / 'solute.gro').is_file()
    assert 'REF' in (tmp_path / 'inputs' / 'reference.itp').read_text()
    # The manifest every prepared run type carries, wherever the shared writer puts it: what matters is that this
    # run type has one and that it names itself, because the resume path verifies runs against it.
    manifests = list(tmp_path.rglob('manifest.json'))
    assert manifests, 'a prepared run carries a manifest'
    document = manifests[0].read_text()
    assert 'osmotic' in document and 'input_snapshot_sha256' in document


def test_a_zero_molality_condition_says_it_is_a_control(tmp_path):
    """A run that measures the floor should not look like a run whose solute count went missing."""
    osmotic.prepare(tmp_path, {'molecule_id': 'Maltose', 'solute_root': str(solute_root(tmp_path)),
                               'mapping_snapshot': MAPPING, 'settings': {'osmotic_molality': 0.0}})

    control = (tmp_path / 'inputs' / 'control.json').read_text()
    assert 'pure solvent' in control and 'zero by construction' in control


def test_the_stage_contract_is_the_shared_shape():
    """`stage_tables` returns the stages as named entries and the inputs and outputs keyed by stage name, and the
    executor walks the three together."""
    stages, inputs, outputs = osmotic.PROTOCOL.stage_contract({'molecule_id': 'Maltose'})

    assert stages == osmotic.STAGES
    assert len(stages) == 1
    name = stages[0][0]                    # stage_tables yields (name, script) pairs
    assert inputs[name] == osmotic.STAGE_DEFS[0].inputs
    assert outputs[name] == osmotic.STAGE_DEFS[0].outputs
    assert 'prod/md_whole.xtc' in outputs[name]
