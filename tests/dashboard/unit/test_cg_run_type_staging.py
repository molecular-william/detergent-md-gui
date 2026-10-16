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
from pathlib import Path

import pytest

from dashboard.execution.adapters import cg
from dashboard.models import mappings
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.molecules import aa as aa_molecules

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MOLECULES = PROJECT_ROOT / 'molecules'
REFERENCE = {'source_run_id': '111111111111', 'sha256': {}}

#: What every AA-to-CG run stages, whichever profile it was handed: the mapping export, the one mapper, and the
#: three scripts stage 3 drives. `prepare_ring_constraints.py` is staged for a mapping with no rings too -- the
#: stage script calls it unconditionally, so it has to be there and inert rather than absent.
STAGED = ('2_mapping/model.json', '2_mapping/mapping.map', '2_mapping/mapping.ndx', '2_mapping/README.txt',
          '2_mapping/draft-source.json', '2_mapping/sugar_mapping.py',
          '3_initial_CG/bonded.py', '3_initial_CG/refine_bonded.py', '3_initial_CG/prepare_ring_constraints.py',
          '3_initial_CG/DDM_initial.itp', '3_initial_CG/topol.top', '3_initial_CG/initial.mdp',
          '4_CG_sim/inputs/md.mdp', '6_SASA/CG/vdwradii.dat')

#: The stage script's executable lines: the comments above a line name the old value and why it went, so a
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


def test_the_stage_script_calls_both_helpers_without_probing_for_them():
    """D4: both scripts are staged always, so `[ -f ... ]` has nothing left to decide.

    The pre-fitted path is gone with the profile gate: no executable line reads `BOND_STATE.itp` any more, because
    no run can be handed one.
    """
    assert 'python prepare_ring_constraints.py' in EXECUTABLE
    assert 'python refine_bonded.py' in EXECUTABLE
    assert [line for line in EXECUTABLE if '[ -f' in line] == []
    assert [line for line in EXECUTABLE if 'BOND_STATE' in line] == []


def test_stage_three_is_named_for_what_it_does():
    """D3: rings, fit, refine, record -- not one tool's stage."""
    stages = dict(cg.STAGES)
    assert stages['CG parameterization'] == '3_initial_CG/fit_topology.sh'
    assert 'CG topology (ff_inter)' not in stages
