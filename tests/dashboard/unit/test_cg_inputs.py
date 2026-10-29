"""What an AA-to-CG run reads in place, and what it still writes by value.

Phase 1 of `docs/plans/2026-10-27-run-lifecycle-refactor.md`: a run no longer copies an input that already existed when
`prepare` ran. The installed Martini set (force field, solvents, ions, and a ringed model's sugar reference), the water
box `gmx solvate` replicates, the radii convention and a consumed parameterization's reference histograms are named by
path and digest in the manifest's `inputs` record; the generated data (mapping export, topologies, MDPs,
`references.txt`, the model's own terms, the CG radii) stays written into `stages/` and is mirrored into `inputs/`.
Each generated topology names the installed set by a path relative to itself, so a relocated run still resolves it.

Phase 2 adds the other half: the code is not written into the run at all. Every stage executes the repository script
recorded in the manifest's `stage_scripts`, its helpers are repository modules recorded in `python_modules`, and the
executor re-hashes both before a stage starts.

These tests read the *prepared run* the run type actually writes -- `adapter_for('aa_cg').prepare(run, metadata)`, the
one entry the coordinator uses -- and then ask the record to verify itself, because a reference the resume path cannot
check is a reference the run does not really have. The AA reference resolution and the tool report are stubbed: neither
decides what is referenced.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dashboard import martini3
from dashboard.execution import run_inputs
from dashboard.execution.adapters import cg
from dashboard.execution.protocol import adapter_for
from dashboard.models import mappings
from dashboard.models.bonded import parameterization
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.molecules import aa as aa_molecules

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MOLECULES = PROJECT_ROOT / 'molecules'
REFERENCE = {'source_run_id': '111111111111', 'sha256': {}}
REVISION = {'engine': 'fast-forward', 'topology': '[ moleculetype ]\nDDM 1\n\n[ atoms ]\n',
            'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                        'torsion_model': 'circular-harmonic', 'torsion_scale': 1.0},
            'ensemble': {'frames': 20001, 'trajectory': '2_mapping/mapped.xtc',
                         'source': 'the mapped AA frames'},
            'aa_reference': {'run_id': 'a54ac8f64710', 'reference_sha256': 'ab' * 32,
                             'molecule_identity': 'cd' * 32, 'temperature_k': 300.0,
                             'production_ns': 10.0}}

#: What every prepared run must not hold, in either the stage tree or the `inputs/` mirror. Each used to be a copy.
NOT_COPIED = ('3_initial_CG/martini_v3.0.0.itp',
              '3_initial_CG/reference_sugars_v2.itp',
              '4_CG_sim/inputs/martini_v3.0.0.itp',
              '4_CG_sim/inputs/martini_v3.0.0_solvents_v1.itp',
              '4_CG_sim/inputs/martini_v3.0.0_ions_v1.itp',
              '4_CG_sim/inputs/water.gro',
              '6_SASA/AA/vdwradii.dat')


def ddm_mapping():
    context = build_context(MOLECULES, 'DDM')
    candidate = mappings.automatic_candidate(as_structure(context), 'DDM')
    candidate.update(schema_version=3, molecule_id='DDM', molecule_snapshot=copy.deepcopy(context['snapshot']))
    return candidate


def fitted(candidate, files=('1_B01_1_B02_distances_distr.dat', 'B01_B02_B05_angles_distr.dat',
                             'B01_B11_bonds_distr.dat')):
    """Save a revision the way a real fit does: with the AA reference's histograms in its working directory."""
    work = parameterization.work_root() / f'{parameterization.content_identity(candidate)}-{REFERENCE["source_run_id"]}'
    stage = work / '3_initial_CG'
    stage.mkdir(parents=True, exist_ok=True)
    for name in files:
        (stage / name).write_text('0.005 0.0\n0.015 1.0\n')
    return parameterization.save(candidate, REVISION, work=work)


def metadata(mapping_candidate):
    return {'detergent': 'DDM', 'profile': cg.AA_CG_PROFILE, 'settings': {'cg_production_ps': 20},
            'mapping_candidate': mapping_candidate, 'shared_reference': REFERENCE,
            'reference_root': Path('/runs'), 'molecule_snapshot': aa_molecules.selection(MOLECULES, 'DDM'),
            'molecule_root': MOLECULES, 'run_type': 'aa_cg', 'molecule_id': 'DDM'}


def prepare(run, monkeypatch, mapping_candidate):
    """The run type's own prepare, with the outside-world seams stubbed.

    The shared Martini set is installed once per test session by `tests/dashboard/conftest.py` under
    `DASHBOARD_MARTINI3`, outside the developer's workspace; every run here reads that install.
    """
    from dashboard.analysis.runs import references as aa_references
    monkeypatch.setattr(aa_references, 'resolve', lambda *args, **kwargs: REFERENCE)
    monkeypatch.setattr(cg, 'tool_metadata', lambda: {'gmx': {'path': '/usr/bin/gmx'}})
    run.mkdir()
    adapter_for('aa_cg').prepare(run, metadata(mapping_candidate))
    return run, json.loads((run / 'manifest.json').read_text())


@pytest.fixture
def fitted_run(tmp_path, monkeypatch):
    """A prepared run that fits its own bonded terms; a ringed mapping, so the sugar reference is named too."""
    candidate = ddm_mapping()
    candidate['rings'][0]['scale'] = 1.2
    return prepare(tmp_path / 'run', monkeypatch, candidate)


@pytest.fixture
def consuming_run(tmp_path, monkeypatch):
    """A prepared run that consumes its model's current parameterization, whose revision recorded histograms."""
    candidate = ddm_mapping()
    fitted(candidate)
    return prepare(tmp_path / 'run', monkeypatch, candidate)


def roles(manifest, kind=None):
    return {entry['role'] for entry in manifest['inputs'] if kind is None or entry['kind'] == kind}


def test_the_manifest_is_the_reference_record_and_the_run_has_no_copies(fitted_run):
    run, manifest = fitted_run

    assert manifest['layout_version'] == 3
    installed = {'martini_force_field', 'martini_solvents', 'martini_ions',
                 'sugar_reference', 'sugar_reference_provenance'}
    assert installed | {'martini_water', 'sasa_radii_aa'} <= roles(manifest, 'published')
    # The Martini files come from the workspace's install (or absolutely when a test points the install elsewhere);
    # the water box and the radii are repository fixtures and are still published from the checkout.
    assert all(entry['kind'] == 'published' and entry['root'] in ('workspace', 'absolute')
               for entry in manifest['inputs'] if entry['role'] in installed)
    assert all(entry['kind'] == 'published' and entry['root'] == 'repo'
               for entry in manifest['inputs'] if entry['role'] in ('martini_water', 'sasa_radii_aa'))
    for relative in NOT_COPIED:
        assert not (run / 'stages' / relative).exists(), f'staged a copy: {relative}'
        assert not (run / 'inputs' / relative).exists(), f'mirrored a copy: {relative}'
    assert not (run / 'stages' / cg.FORCE_FIELD.name).exists(), 'the atomistic force-field tree is not copied'
    assert not (run / 'inputs' / cg.FORCE_FIELD.name).exists()
    assert 'staged_path' not in manifest['force_field'], 'the record no longer claims the tree is in the run'
    # The generated data is still written by value, in both the stage tree and the mirror. No code is: the stages
    # run the repository scripts named in the manifest.
    for relative in ('3_initial_CG/topol.top', '3_initial_CG/DDM_initial.itp', '3_initial_CG/initial.mdp',
                     '4_CG_sim/system_EMPTY.top', '4_CG_sim/inputs/md.mdp', '6_SASA/CG/vdwradii.dat',
                     '2_mapping/mapping.map', '5_assessment/references.txt'):
        assert (run / 'stages' / relative).is_file(), relative
        assert (run / 'inputs' / relative).is_file(), relative
    for tree in (run / 'stages', run / 'inputs'):
        copied = sorted(path.relative_to(run).as_posix() for path in tree.rglob('*')
                        if path.suffix in ('.py', '.sh'))
        assert copied == [], f'{tree.name}/ holds code that belongs to the repository: {copied}'


def test_the_generated_topologies_name_the_installed_files_relative_to_themselves(fitted_run):
    run, _ = fitted_run
    stage_root = run / 'stages'

    topol = (stage_root / '3_initial_CG/topol.top').read_text()
    force_field = martini3.include(cg.MARTINI_FF, stage_root / '3_initial_CG')
    assert f'#include "{force_field}"' in topol
    assert not Path(force_field).is_absolute(), 'a run stays relocatable: the include resolves from its own directory'
    assert (stage_root / '3_initial_CG' / force_field).resolve() == martini3.path(cg.MARTINI_FF).resolve()
    simulation = stage_root / '4_CG_sim'
    system = (simulation / 'system_EMPTY.top').read_text()
    assert f'#include "{martini3.include(cg.MARTINI_FF, simulation)}"' in system
    assert f'#include "{martini3.include(cg.MARTINI_SOLVENTS, simulation)}"' in system
    # The model's own topology is beside this one (`cg_simulation.sh` copies it next to the system topology), so it
    # stays a bare name.
    assert '#include "DDM.itp"' in system
    # The water box is read where it lives: `cg_simulation.sh` names it through `$PROJECT_ROOT` and nothing is linked
    # into the stage.
    script = (PROJECT_ROOT / 'dashboard/execution/scripts/cg_simulation.sh').read_text()
    assert 'resources/templates/small_mols_fast_forward/4_CG_sim/inputs/water.gro' in script
    # `relative` keeps the stage's legacy entry-point name; the recorded `script` is the repository file the
    # executor runs.
    assert dict(manifest_stages(run))['CG simulation'] == '4_CG_sim/cg_simulation_run.sh'
    assert json.loads((run / 'manifest.json').read_text())['stage_scripts']['CG simulation']['path'] == \
        'dashboard/execution/scripts/cg_simulation.sh'


def test_the_run_records_the_script_and_modules_each_stage_executes(fitted_run):
    """The code is pinned by path and digest, and the executor re-hashes it before a stage starts.

    The command a stage runs is built from the recorded path, not from a file in the stage directory, so every stage
    names the repository script it actually executes.
    """
    from dashboard.execution import run_scripts, workflow

    run, manifest = fitted_run
    recorded = manifest['stage_scripts']
    assert set(recorded) == {name for name, _ in manifest['stage_plan']}
    for name, entry in recorded.items():
        verified = run_scripts.verify_one(name, entry, root=PROJECT_ROOT)
        assert verified == (PROJECT_ROOT / entry['path']).resolve()
        command = workflow.stage_command(name, verified)
        assert command[-1] == str(PROJECT_ROOT / entry['path'])
        assert 'dashboard/execution/scripts/' in command[-1], 'the stage runs the repository script, not a copy'
    assert recorded['CG parameterization']['path'] == 'dashboard/execution/scripts/fit_topology.sh'
    assert recorded['CG simulation']['path'] == 'dashboard/execution/scripts/cg_simulation.sh'

    modules = manifest['python_modules']
    assert set(modules) == set(cg.MODULES)
    for name, entry in modules.items():
        assert run_scripts.verify_one(name, entry, root=PROJECT_ROOT) == (PROJECT_ROOT / entry['path']).resolve()
    assert modules['dashboard.models.bonded']['path'] == 'dashboard/models/bonded/__init__.py'


def manifest_stages(run):
    return json.loads((run / 'manifest.json').read_text())['stage_plan']


def test_the_record_verifies_and_a_changed_installed_file_refuses_it(tmp_path, monkeypatch):
    """The digest is the seal: an installed file mutated after prepare is refused before a stage reads it.

    The install is pointed at a scratch directory for this one test -- mutating the shared set is exactly what the
    guard exists to detect, not something a test may do.
    """
    monkeypatch.setenv(martini3.ENVIRONMENT_VARIABLE, str(tmp_path / 'martini3'))
    candidate = ddm_mapping()
    candidate['rings'][0]['scale'] = 1.2
    run, manifest = prepare(tmp_path / 'run', monkeypatch, candidate)

    assert run_inputs.verify_manifest(run, manifest) is not None
    solvents = martini3.path(martini3.REQUIRED[1])
    assert solvents.parent == tmp_path / 'martini3', 'the mutated set is this test\'s own install'
    solvents.write_text('a different solvent set\n')
    with pytest.raises(ValueError, match='martini_solvents changed since this run was prepared'):
        run_inputs.verify_manifest(run, manifest)


def test_a_consuming_run_names_the_revisions_histograms_in_the_store(consuming_run):
    run, manifest = consuming_run

    histograms = [entry for entry in manifest['inputs'] if entry['role'] == 'reference_distribution']
    assert len(histograms) == 3
    assert all(entry['kind'] == 'store' and entry['root'] == 'workspace' for entry in histograms)
    assert [Path(entry['path']).name for entry in histograms] == ['1_B01_1_B02_distances_distr.dat',
                                                                  'B01_B02_B05_angles_distr.dat',
                                                                  'B01_B11_bonds_distr.dat']
    assert not list((run / 'stages/3_initial_CG').glob('*_distr.dat'))
    assert not list((run / 'inputs/3_initial_CG').glob('*_distr.dat'))
    inventory = json.loads((run / 'inputs/3_initial_CG/distributions.json').read_text())
    assert {Path(entry['name']).name for entry in inventory['files']} == {
        Path(entry['path']).name for entry in histograms}
    assert all(Path(entry['name']).is_absolute() and Path(entry['name']).is_file()
               for entry in inventory['files'])


def test_the_consuming_stage_finds_the_histograms_it_was_handed(consuming_run):
    run, _ = consuming_run
    stage = run / 'stages/5_assessment'
    assert not (stage / 'assess_parameterization.sh').exists()
    # The reference directory is data the run wrote, and the script it runs is the repository's own.
    recorded = parameterization.distributions(json.loads((run / 'manifest.json').read_text())['mapping_candidate'])
    declared = Path((stage / 'references.txt').read_text().strip())
    assert declared.resolve() == Path(recorded['directory']).resolve()
    assert sorted(path.name for path in declared.glob('*_distr.dat')) == [
        '1_B01_1_B02_distances_distr.dat', 'B01_B02_B05_angles_distr.dat', 'B01_B11_bonds_distr.dat']

    done = subprocess.run(['bash', str(cg.SCRIPTS / 'assess.sh')], cwd=stage, capture_output=True, text=True,
                          env={'PATH': f'{Path(sys.executable).parent}:/usr/bin:/bin',
                               'PYTHON': sys.executable, 'PYTHONPATH': str(PROJECT_ROOT)})

    assert done.returncode != 4, 'the pair family is present, so the stage does not skip'
    assert not (stage / 'skip.json').exists()
    assert not (stage / 'references').exists(), 'nothing is linked into the run: the store is read where it lives'


def test_a_changed_histogram_in_the_store_refuses_the_run(consuming_run):
    run, manifest = consuming_run
    directory = parameterization.distributions(manifest['mapping_candidate'])['directory']

    (directory / 'B01_B11_bonds_distr.dat').write_text('0.005 9.9\n')

    with pytest.raises(ValueError, match='reference_distribution changed since this run was prepared'):
        run_inputs.verify_manifest(run, manifest)


def test_every_prepared_mdp_is_its_recorded_profile_at_the_run_numbers(fitted_run):
    """Phase 3: the MDPs are rendered from reviewed profiles, and the manifest names each profile it used.

    The paths are the ones the stage scripts already read; the files are `render(profile, values)` for the settings
    the manifest records, in the stage tree and in the mirrored `inputs/`.
    """
    from dashboard.execution.mdp import render

    run, manifest = fitted_run
    assert manifest['mdp_profiles'] == {
        '3_initial_CG/initial.mdp': 'cg-initial-v1',
        '4_CG_sim/inputs/minimization.mdp': 'cg-minimization-v1',
        '4_CG_sim/inputs/eq.mdp': 'cg-equilibration-v1',
        '4_CG_sim/inputs/md.mdp': 'cg-production-v1'}
    for relative, profile in manifest['mdp_profiles'].items():
        values = (cg.mdp_values(manifest['settings'], profile)
                  if profile in ('cg-equilibration-v1', 'cg-production-v1') else None)
        expected = render(profile, values)
        assert (run / 'stages' / relative).read_text() == expected, relative
        assert (run / 'inputs' / relative).read_text() == expected, relative
