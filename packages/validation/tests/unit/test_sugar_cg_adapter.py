"""The CG-only sugar run: the published reference is the topology, the AA geometry is only the start.

The tests are about construction, not simulation. `prepare` is what the executor runs before a single GROMACS command,
so the substance is: the published terms are written verbatim, a nonconforming mapping is refused, the run carries no
AA stage, and its provenance says where every number came from.
"""
import json

import pytest
from dashboard.execution import protocol
from dashboard.models.molecules import aa as aa_molecules
from dashboard.models.sugars import reference
from detergent_validation.execution.adapters import sugar_cg

from tests.harness.support import PROJECT_ROOT

MOLECULES = PROJECT_ROOT / 'molecules'


@pytest.fixture(autouse=True)
def no_tool_probe(monkeypatch):
    """`prepare` records the resolved gmx; this suite is about the files, not the host's GROMACS."""
    monkeypatch.setattr(sugar_cg, 'tool_metadata', lambda: {})


def _prepare(run, *, molecule_id='Sucrose', entry='SUCR'):
    snapshot = aa_molecules.selection(MOLECULES, molecule_id)
    return sugar_cg.prepare(run, {'molecule_id': molecule_id, 'molecule_snapshot': snapshot,
                                  'settings': {'sugar_entry': entry},
                                  'profile': 'sugar-cg-v1', 'molecule_root': MOLECULES})


def test_the_run_type_is_reachable_and_has_one_cg_stage():
    entry = protocol.adapter_for('sugar_cg')

    assert entry is sugar_cg.PROTOCOL
    assert entry.name == 'sugar_cg'
    assert [stage.name for stage in sugar_cg.STAGE_DEFS] == ['CG simulation']
    assert 'AA reference' not in [stage.name for stage in sugar_cg.STAGE_DEFS]
    # The stage's plan is the engine's existing CG spellings, so the run view's trajectory readers need no new code.
    assert sugar_cg.STAGES[0][1] == '4_CG_sim/cg_simulation.sh'


def test_the_preset_is_the_lead_decided_five_and_ten_nanoseconds():
    values = sugar_cg.stage_defaults()['values']

    assert values['cg_equil_ps'] == pytest.approx(5000.0)
    assert values['cg_production_ps'] == pytest.approx(10000.0)
    assert sugar_cg.stage_defaults()['profile'] == 'sugar-cg-v1'
    assert protocol.profile_for_run_type('sugar_cg') == 'sugar-cg-v1'
    # The reviewed MDP files are unchanged; the preset changes only the duration the renderer passes them.
    assert sugar_cg.MDP_PROFILES == {'inputs/minimization.mdp': 'cg-minimization-v1',
                                     'inputs/eq.mdp': 'cg-equilibration-v1',
                                     'inputs/md.mdp': 'cg-production-v1'}


def test_sucrose_conforms_and_trehalose_is_blocked_by_the_published_residue_column():
    sucrose = sugar_cg.preview('Sucrose', 'SUCR', molecule_root=MOLECULES)
    assert sucrose['ready'] is True
    assert sucrose['conforms'] is True
    assert len(sucrose['beads']) == 8
    assert [bead['type'] for bead in sucrose['beads']] == ['SP1r', 'SP4r', 'SP1r', 'TC4',
                                                           'SN6', 'SP4r', 'SP1r', 'TC4']

    trehalose = sugar_cg.preview('Trehalose', 'TREH', molecule_root=MOLECULES)
    assert trehalose['ready'] is False
    assert trehalose['conforms'] is False
    assert any("do not match the reference ['A', 'B', 'C', 'VS', 'VS']" in blocker
               for blocker in trehalose['blockers']), trehalose['blockers']


def test_an_entry_mismatch_is_a_blocker_not_a_silent_swap():
    answer = sugar_cg.preview('Sucrose', 'TREH', molecule_root=MOLECULES)

    assert answer['ready'] is False
    assert any('identifies SUCR' in blocker for blocker in answer['blockers'])


def test_prepare_writes_a_cg_only_run_with_the_published_terms(tmp_path):
    run = tmp_path / 'run'
    document = _prepare(run)

    assert document['run_type'] == 'sugar_cg'
    assert document['workflow_version'] == 'sugar-cg-v1'
    assert document['topology_source'] == 'published-reference'
    assert document['scientifically_validated'] is False
    assert document['starting_structure'] == {'source': 'mapped-AA', 'scaled': True, 'ring_scale': 1.15}
    assert (run / 'stages/4_CG_sim').is_dir()
    assert not (run / 'stages/1_AA-reference').exists()
    assert not (run / 'stages/2_mapping').exists()

    manifest = json.loads((run / 'manifest.json').read_text())
    assert manifest['stage_plan'] == ['CG simulation']
    assert manifest['stage_scripts']['CG simulation']['path'] == sugar_cg.SCRIPT
    assert manifest['cg_names'] == {'residue_name': 'SUCR', 'initial_itp': 'SUCR.itp', 'final_itp': 'SUCR.itp'}
    roles = {entry['role'] for entry in manifest['inputs']}
    assert {'martini_force_field', 'martini_solvents', 'martini_ions', 'sugar_reference',
            'sugar_reference_provenance', 'martini_water', 'molecule_topology',
            'molecule_coordinates'} <= roles
    assert manifest['sugar']['entry'] == 'SUCR'
    assert manifest['sugar']['reference']['sha256'] == '4d29956a77d936cfdad10e8bbdf201cebdaa24a2f5f50688988a1c7bb9ebfc50'
    assert manifest['sugar']['reference']['commit'] == 'e11f1d31923ba8090779f8601847dbde84e559e4'

    topology = (run / 'inputs/SUCR.itp').read_text()
    sections = reference._sections(topology)
    assert [row[4] for row in sections['atoms']] == [f'B{index:02d}' for index in range(1, 9)]
    # T2: the published lengths are written, not the mapped geometry's.
    assert [row[3] for row in sections['constraints']] == ['0.305', '0.385', '0.336', '0.376', '0.468', '0.359']
    assert [row[3] for row in sections['bonds']] == ['0.369']
    assert [row[4] for row in sections['bonds']] == ['6200']
    assert (run / 'inputs/sugar.gro').read_text().splitlines()[1] == '8'
    system = (run / 'inputs/system.top').read_text()
    assert '#include "SUCR.itp"' in system
    assert '[ molecules ]\nSUCR 1' in system

    conformance = json.loads((run / 'inputs/conformance.json').read_text())
    assert conformance['topology_source'] == 'published-reference'
    assert conformance['issues'] == []
    # The published-vs-mapped delta is recorded, and the run layout translation makes it readable.
    assert conformance['parameter_delta']
    assert all(row['generated'] is not None for row in conformance['parameter_delta'])
    assert conformance['parameter_delta'][0]['generated'] == pytest.approx(0.305)


def test_prepare_refuses_a_nonconforming_entry(tmp_path):
    with pytest.raises(ValueError, match='do not match the reference'):
        _prepare(tmp_path / 'run', molecule_id='Trehalose', entry='TREH')


def test_parameter_delta_reads_the_run_layout(tmp_path):
    topology = reference.run_topology('SUCR')
    delta = reference.parameter_delta(topology, 'SUCR', layout='run')

    assert [row['pair'] for row in delta[:-1]] == [['A', 'B'], ['A', 'C'], ['B', 'C'],
                                                   ['A', 'B'], ['A', 'C'], ['B', 'C']]
    assert all(row['difference'] == pytest.approx(0.0) for row in delta)
    assert delta[-1]['residue'] == 'link'
    assert delta[-1]['reference_force'] == 6200


def test_settings_refuse_a_field_this_run_does_not_use():
    values = sugar_cg.normalize_settings({'sugar_entry': 'SUCR', 'cg_production_ps': 10000})
    assert values['sugar_entry'] == 'SUCR'
    assert values['cg_seed'] == 20260911

    with pytest.raises(ValueError, match='Unknown sugar CG setting'):
        sugar_cg.normalize_settings({'aa_nvt_ps': 100})
    with pytest.raises(ValueError, match='must be one of SUCR, TREH'):
        sugar_cg.normalize_settings({'sugar_entry': 'LAC'})
    with pytest.raises(ValueError, match='Trajectory interval'):
        sugar_cg.normalize_settings({'cg_production_ps': 10, 'output_interval_ps': 11})


def test_the_stage_contract_names_the_selected_entry():
    plan, inputs, outputs = sugar_cg.stage_contract({'settings': {'sugar_entry': 'TREH'}})

    assert plan == (('CG simulation', '4_CG_sim/cg_simulation.sh'),)
    assert '../../inputs/TREH.itp' in inputs['CG simulation']
    assert outputs['CG simulation'] == ('prod/lig_CG.gro', 'prod/lig_CG.tpr', 'prod/lig_CG.xtc')
