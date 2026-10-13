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


def test_the_retry_ceiling_and_the_series_policy_are_advertised_where_the_routes_read_them():
    """`runs.py:queue` and the series route both keep a setting only when the run type advertises it, so the keys
    the panel posts have to be in the route's own union or they are silently dropped."""
    advertised = set(osmotic.SETTING_SPECS) | set(osmotic.CHOICE_SPECS)

    assert {'osmotic_attempts_max', 'series_on_failure'} <= advertised
    # And both carry a default, because a default is what makes the retry a capability rather than a claim.
    values = osmotic.stage_defaults()['values']
    assert values['osmotic_attempts_max'] == 3
    assert values['series_on_failure'] == 'carry_on'
    assert osmotic.DEFAULTS['osmotic_attempts_max'] == 3
    assert osmotic.DEFAULTS['series_on_failure'] == 'carry_on'


def test_the_retry_ceiling_is_bounded_and_a_fractional_attempt_is_refused():
    """Three is the house ceiling (`pdc.DEFAULTS`), and an attempt count is a count: 2.5 attempts is not one."""
    assert osmotic.normalize_settings({'osmotic_attempts_max': 5})['osmotic_attempts_max'] == 5
    assert isinstance(osmotic.normalize_settings({})['osmotic_attempts_max'], int)

    with pytest.raises(ValueError, match='between 1 and 10'):
        osmotic.normalize_settings({'osmotic_attempts_max': 0})
    with pytest.raises(ValueError, match='whole number'):
        osmotic.normalize_settings({'osmotic_attempts_max': 2.5})


def test_a_series_carries_on_by_default_and_may_be_told_to_stop():
    """`carry_on` is the existing route's contract; `stop` is the other choice, and anything else is refused."""
    assert osmotic.normalize_settings({})['series_on_failure'] == 'carry_on'
    assert osmotic.normalize_settings({'series_on_failure': 'stop'})['series_on_failure'] == 'stop'

    with pytest.raises(ValueError, match='must be one of'):
        osmotic.normalize_settings({'series_on_failure': 'abandon'})


def test_prepare_bakes_the_retry_ceiling_into_the_runner(tmp_path):
    """The runner is a shell script and gets the ceiling the way it gets `REPO_ROOT` -- written in at prepare time.

    A default in `DEFAULTS` alone would be advertised and then never reach the process that retries.
    """
    osmotic.prepare(tmp_path, {'molecule_id': 'Maltose', 'solute_root': str(solute_root(tmp_path)),
                               'mapping_snapshot': MAPPING,
                               'settings': {'osmotic_molality': 1.0, 'osmotic_attempts_max': 5}})

    runner = (tmp_path / '01_simulate' / 'run.sh').read_text()
    assert 'OSMOTIC_ATTEMPTS_MAX="5"' in runner
    assert 'OSMOTIC_ATTEMPTS_MAX="${OSMOTIC_ATTEMPTS_MAX:-3}"' not in runner


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
    # **Every input the stage declares must resolve from the stage directory.** The executor checks exactly this, and
    # a declaration that does not resolve stops the run before GROMACS is reached. Asserting the files exist is not
    # the same test: the first two versions of this declaration passed the assertions above and failed this one.
    for declared in osmotic.STAGE_DEFS[0].inputs:
        assert (tmp_path / '01_simulate' / declared).resolve().is_file(), declared
    # `[ atomtypes ]` must come before the moleculetype that uses it, or GROMACS reports "Atomtype REF not found" with
    # the type visible in the same file. Asserting the file *contains* REF passes either way -- which is what the
    # first version of this assertion did, while the run was failing on grompp.
    reference = (tmp_path / 'inputs' / 'reference.itp').read_text()
    assert reference.index('[ atomtypes ]') < reference.index('[ moleculetype ]')
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


def test_the_paper_scale_production_writes_the_frames_it_was_asked_for():
    """The trap this test exists for: `nstxtcout` is a *step* count, so an interval of 10 ps at dt 0.02 is 500 steps.
    The first version of the mdp divided the 500 ns *duration* by the interval and passed 50,000, which is 1 ns per
    frame -- a hundred times sparser than asked, and the same cost."""
    from dashboard.execution.adapters import osmotic_mdp

    mdps = osmotic_mdp.osmotic_mdps(temperature=308.15, solute_molecules=2, production_ps=500000.0,
                                    equilibration_ps=10000.0, output_interval_ps=10.0)

    def settings(text):
        out = {}
        for line in text.splitlines():
            if '=' in line:
                key, _, value = line.partition('=')
                out[key.strip()] = value.strip()
        return out

    md = settings(mdps['production'])
    assert float(md['dt']) == 0.02
    assert int(md['nsteps']) == 25_000_000                 # 500 ns at 20 fs
    assert int(md['nstxtcout']) == 500                     # 500 steps x 0.02 ps = 10 ps
    assert int(md['nsteps']) / int(md['nstxtcout']) == 50_000
    # The engine's own measurement of the confinement is PLUMED's now -- `plumed_walls` writes the wall's bias at
    # its own stride -- so the mdp declares no pull output interval, and asserting that it does not is what would
    # catch a stale `pull-*` line coming back with it.
    assert 'pull-nstfout' not in md
    assert 'pull' not in md
    # The confinement is PLUMED's, switched on at the mdrun call rather than from the mdp: `gmx grompp -h` mentions
    # PLUMED nowhere, and an mdp entry named `plumed` is two warnings against `-maxwarn 1`.
    assert not [key for key in md if key.startswith('plumed')]

    eq = settings(mdps['equilibration'])
    assert float(eq['dt']) == 0.005
    assert int(eq['nstxtcout']) == 2000                    # 2000 steps x 0.005 ps = 10 ps
    assert int(eq['nsteps']) / int(eq['nstxtcout']) == 1000


def test_an_output_interval_that_is_not_a_whole_number_of_steps_is_refused():
    """Silently flooring it would write frames at an interval nobody chose, and two conditions in a series would then
    have different windows -- which is what makes their averages incomparable."""
    import pytest

    from dashboard.execution.adapters import osmotic_mdp

    with pytest.raises(ValueError, match='whole number of'):
        osmotic_mdp.osmotic_mdps(temperature=308.15, solute_molecules=2, production_ps=1000.0,
                                 equilibration_ps=1000.0, output_interval_ps=0.017)


def test_the_placement_writes_a_gro_file_gromacs_can_read(tmp_path):
    """The script's placement half, run for real. It writes what `gmx solvate` reads first, and .gro is fixed format.

    **Nothing ran this script before this test, which is why two defects reached GROMACS**: an atom line five
    characters short because the 5-character serial field was missing, and every bead of a molecule written at the
    same coordinates because the molecule was placed but its atoms were never translated. Both are invisible to a
    test that only checks the files exist -- so this runs the script, with `gmx` stubbed out, and reads what it wrote.
    """
    import os
    import subprocess

    solute = tmp_path / 'solute'
    solute.mkdir()
    # Two beads 0.26 nm apart, in the fixed-format layout a real mapping produces.
    (solute / 'solute.gro').write_text('a written molecule\n    2\n'
                                       '    1LIG1   B01    1   1.000   1.000   1.000\n'
                                       '    1LIG1   B02    2   1.260   1.000   1.000\n'
                                       '   4.00000   4.00000   4.00000\n')
    for name in ('solute.itp', 'water.gro', 'martini_v3.0.0_solvents_v1.itp'):
        (solute / name).write_text('placeholder\n')
    # A real moleculetype, because `[ molecules ]` is written by reading this name: a placeholder here would stop the
    # script before it wrote the topology at all.
    (solute / 'solute.itp').write_text('[ moleculetype ]\nLIG1 1\n\n[ atoms ]\n'
                                       '1  SP1r  1  LIG1  B01  1  0.0  36.0\n'
                                       '2  SP1r  1  LIG1  B02  1  0.0  36.0\n')

    record = osmotic.prepare(tmp_path, {'molecule_id': 'Maltose', 'solute_root': str(solute),
                                        'mapping_snapshot': MAPPING, 'settings': {'osmotic_molality': 1.0}})
    stage = tmp_path / '01_simulate'
    stub = tmp_path / 'gmx'
    stub.write_text('#!/bin/sh\nexit 0\n')
    stub.chmod(0o755)
    # A stubbed `gmx` that produces nothing stops the script at the step after the placement; the placement is step 1,
    # so its outputs are on disk. The return code is not what this test is about, the file it wrote is.
    subprocess.run(['bash', str(stage / 'run.sh')], cwd=stage, capture_output=True, check=False,
                   env={**os.environ, 'GROMACS': str(stub)})

    lines = (stage / 'system.gro').read_text().splitlines()
    molecules = record['solute_molecules']
    assert lines[1].strip() == str(2 * molecules + 1)              # two beads each, plus the reference

    atoms = lines[2:2 + 2 * molecules]
    assert all(len(line) == 44 for line in atoms), sorted({len(line) for line in atoms})
    # The molecule keeps its shape: its two beads stay 0.26 nm apart rather than being written on top of each other.
    assert float(atoms[1][20:28]) - float(atoms[0][20:28]) == pytest.approx(0.26, abs=1e-3)
    # And the reference bead sits at the box centre, last before the box line. `.gro` coordinates carry three decimals,
    # so "the centre" is 2.52078 written as 2.521: a 0.2 pm rounding, which at 1000 kJ/mol/nm2 is a force of order
    # 1e-7 kJ/mol/nm. The assertion is at the format's precision, not at the intent's.
    reference = lines[2 + 2 * molecules]
    assert [float(reference[20:28]), float(reference[28:36]), float(reference[36:44])] == pytest.approx(
        [2.521, 2.521, 5.042], abs=1e-3)
    # And the topology's includes are ordered by what the parser needs, not by what reads well: the force field, then
    # the reference -- whose first section is `[ atomtypes ]` -- and only then the moleculetypes that use those types.
    # Including the reference after the solute put a type after a moleculetype, and grompp answered "Atomtype REF not
    # found" with the type eleven lines away in the same file.
    top = (stage / 'system.top').read_text()
    includes = [line for line in top.splitlines() if line.startswith('#include')]
    assert includes[0].endswith('martini_v3.0.0.itp"')
    assert 'reference.itp' in includes[1]
    assert 'solute.itp' in includes[2]
    # And `[ molecules ]` names the solute by the moleculetype its own topology declares, not by a name this pipeline
    # picks: `SOL` there is what grompp answers with "No such moleculetype SOL".
    assert top.split('[ molecules ]')[1].strip().splitlines()[0].split()[0] == 'LIG1'
