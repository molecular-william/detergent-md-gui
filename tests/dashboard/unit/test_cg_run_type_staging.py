"""What an AA-to-CG run stages by itself, and what it can no longer be asked to do.

Phase A of the New Run panel refactor. Fitting is a property of the run type rather than a per-run choice (D1),
so the mapping-staging block is no longer gated on an execution profile (D2a), the run contract carries no
bonded state and no intent, and stage 3 is named for what it does (D3).

These tests read the *prepared run directory* rather than the branch that used to decide it: a branch that must
disappear is proved absent by the run it leaves behind, and by the profile it used to skip. Two outside-world
seams are stubbed -- the AA reference resolution and the tool report -- because neither decides what is staged.
"""
import copy
import inspect
import json

import pytest
from dashboard.execution import run_scripts
from dashboard.execution.adapters import cg
from dashboard.models import mappings
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.molecules import aa as aa_molecules

from tests.harness.support import PROJECT_ROOT

MOLECULES = PROJECT_ROOT / 'molecules'
REFERENCE = {'source_run_id': '111111111111', 'sha256': {}}

#: What every AA-to-CG run stages, whichever profile it was handed: the mapping export, the generated data stage 3
#: reads, and the MDP the CG simulation runs. The helpers are repository modules now, so no `.py` is staged for a
#: mapping with rings or without one.
STAGED = ('2_mapping/model.json', '2_mapping/mapping.map', '2_mapping/mapping.ndx', '2_mapping/README.txt',
          '2_mapping/draft-source.json',
          '3_initial_CG/DDM_initial.itp', '3_initial_CG/topol.top', '3_initial_CG/initial.mdp',
          '4_CG_sim/inputs/md.mdp', '6_SASA/CG/vdwradii.dat')

#: The stage scripts' executable lines: the comments above a line name the old value and why it went, so a
#: presence check over the executable lines is the one that cannot be fooled by the explanation.
EXECUTABLE = tuple(line for line in (cg.SCRIPTS / 'fit_topology.sh').read_text().splitlines()
                   if not line.lstrip().startswith('#'))


def ddm_mapping():
    """The saved-candidate shape the queue builds: the molecule's current snapshot, exported by one mapper."""
    context = build_context(MOLECULES, 'DDM')
    candidate = mappings.automatic_candidate(as_structure(context), 'DDM')
    candidate.update(schema_version=3, molecule_id='DDM', molecule_snapshot=copy.deepcopy(context['snapshot']))
    return candidate


def prepared_run(tmp_path, monkeypatch, **prepare_arguments):
    """One real `prepare()` into a scratch run directory, with the two outside-world seams stubbed."""
    from dashboard.analysis.runs import references as aa_references
    monkeypatch.setattr(aa_references, 'resolve', lambda *args, **kwargs: REFERENCE)
    monkeypatch.setattr(cg, 'tool_metadata', lambda: {'gmx': {'path': '/usr/bin/gmx'}})
    run = tmp_path / 'run'
    run.mkdir()
    cg.prepare(run, molecule_snapshot=aa_molecules.selection(MOLECULES, 'DDM'),
               mapping_candidate=ddm_mapping(), shared_reference=REFERENCE, molecule_root=MOLECULES,
               **prepare_arguments)
    return run


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """A prepared run with no profile passed at all: the panel no longer offers one (D2)."""
    return prepared_run(tmp_path, monkeypatch)


@pytest.fixture
def prepared_standard(tmp_path, monkeypatch):
    """A prepared run at the profile that used to stage no mapping: the branch this phase deletes."""
    return prepared_run(tmp_path, monkeypatch, profile='standard')


def test_the_mapping_and_every_script_it_needs_are_staged_with_no_profile_passed(prepared):
    missing = [relative for relative in STAGED if not (prepared / relative).is_file()]
    assert missing == [], 'an AA-to-CG run stages its own mapping: ' + '; '.join(missing)


def test_the_profile_that_used_to_stage_nothing_stages_the_same_run(prepared_standard):
    """`standard` used to hold no mapping block at all.

    The gate was `if profile in ('draft-smoke', 'draft-smoke-reference')`, so this profile produced a run with no
    `2_mapping/`, no topology and no fit -- and the panel offered it for an AA-to-CG run. What it stages now is the
    same shape as every other AA-to-CG run, and the profile it was handed is still what the manifest records.
    """
    missing = [relative for relative in STAGED if not (prepared_standard / relative).is_file()]
    assert missing == [] and json.loads((prepared_standard / 'manifest.json').read_text())['profile'] == 'standard'


def test_the_run_type_stamps_its_own_profile_when_no_profile_is_handed_to_it(prepared):
    """D2: the route stamps it; this is the same answer for a caller that reaches the run type directly."""
    assert cg.AA_CG_PROFILE == 'draft-smoke-reference'
    assert json.loads((prepared / 'manifest.json').read_text())['profile'] == cg.AA_CG_PROFILE


def test_no_run_can_be_handed_a_pre_fitted_bonded_state(prepared):
    """D1: the `reuse_state` branch staged `BOND_STATE.itp` and copied a state's distributions; both are gone.

    The arguments that fed it are gone from the signature too, so a stale record cannot reach the branch by
    compiling against it.
    """
    assert not (prepared / '3_initial_CG/BOND_STATE.itp').exists()
    assert not list((prepared / '3_initial_CG').glob('*_distr.dat'))
    for retired in ('bonded_state_snapshot', 'bonded_intent'):
        assert retired not in inspect.signature(cg.prepare).parameters


def test_the_stage_script_calls_both_helpers_as_repository_modules():
    """D4: both helpers are always run, and now they are repository modules rather than files staged beside a script.

    The pre-fitted path is gone with the profile gate: no executable line reads `BOND_STATE.itp` any more, because
    no run can be handed one.
    """
    assert '"$PYTHON" -m dashboard.execution.scripts.prepare_ring_constraints' in EXECUTABLE
    assert '"$PYTHON" -m dashboard.execution.scripts.refine_bonded' in EXECUTABLE
    assert [line for line in EXECUTABLE if '[ -f' in line] == []
    assert [line for line in EXECUTABLE if 'BOND_STATE' in line] == []


def test_a_prepared_run_holds_no_code_of_its_own(prepared):
    """The phase's rule: a run names the repository script it executes, it does not carry a copy of one.

    Both the stage tree and the `inputs/` mirror are checked, because a script in either is a second copy of code
    the manifest is supposed to pin by digest.
    """
    for tree in ('stages', 'inputs'):
        copied = sorted(path.relative_to(prepared).as_posix()
                        for path in (prepared / tree).rglob('*')
                        if path.suffix in ('.py', '.sh'))
        assert copied == [], f'{tree}/ holds code that belongs to the repository: {copied}'


def test_every_stage_declares_the_repository_script_it_runs():
    """One declaration per stage, both shapes of stage 3 included, each naming a file in this checkout."""
    scripts = {stage.name: stage.script for stage in cg.stage_definitions(parameterized=True)}

    assert all(script.startswith('dashboard/execution/scripts/') for script in scripts.values())
    assert [name for name, script in scripts.items() if not run_scripts.code_path(script, root=PROJECT_ROOT).is_file()] == []
    assert scripts['CG parameterization'] == 'dashboard/execution/scripts/use_parameterization.sh'
    assert {stage.name: stage.script for stage in cg.stage_definitions()}['CG parameterization'] == \
        'dashboard/execution/scripts/fit_topology.sh'


def test_stage_three_is_named_for_what_it_does():
    """D3: rings, fit, refine, record -- not one tool's stage."""
    stages = dict(cg.STAGES)
    assert stages['CG parameterization'] == '3_initial_CG/fit_topology.sh'
    assert 'CG topology (ff_inter)' not in stages
