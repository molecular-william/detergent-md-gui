"""The catalogue the Osmotic Series panel builds its sugar list from.

The panel recomputes nothing: readiness is the server's answer, and the two facts that decide it are the
molecule's saved CG mapping and its prepared solute files. Both are built here through the routes the editor and
the runner use, so the test says what the route does with them rather than what this machine happens to hold --
`paths.current()` redirects the mapping store, the runs directory and the solute directory into the fixture.

The failure-policy half is the same shape: the route reports which of the two choices can act, so a control the
panel shows is a control the server can honour. Both act now, and the half that acts on the choice is the series
run's own driver -- so the answer no longer rests on anything outside the run type.
"""
import dataclasses

from dashboard.execution.adapters import osmotic
from dashboard.models.mappings import context as mapping_context

CATALOGUE = '/api/osmotic/catalogue'
# The solute bundle's own files: the Martini solvents file is the workspace install's now, not a bundle file.
SOLUTE_FILES = osmotic.SOLUTE_FILES


def _catalogue(dashboard):
    with dashboard.client as c:
        response = c.get(CATALOGUE)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _sugar(body, molecule_id):
    return next(item for item in body['sugars'] if item['molecule_id'] == molecule_id)


def _solute_files(dashboard, molecule='maltose'):
    """The directory `prepare` copies out of, under the fixture's own workspace rather than the developer's."""
    root = dashboard.coordinator.RUNS.parent / 'osmotic' / molecule
    root.mkdir(parents=True, exist_ok=True)
    for name in SOLUTE_FILES:
        (root / name).write_text('fixture\n')
    return root


def _save_mapping(dashboard, molecule_id):
    """Save a candidate through the route the assignment editor posts to."""
    context = mapping_context.build_context(dashboard.coordinator.ROOT / 'molecules', molecule_id)
    with dashboard.client as c:
        preview = c.post('/api/mappings/automatic/preview',
                         json={'molecule_id': molecule_id, 'molecule_snapshot': context['snapshot']}).get_json()
        assert preview['available'] is True, preview.get('reasons')
        candidate = dict(preview['candidate'], molecule_id=molecule_id, molecule_snapshot=context['snapshot'])
        saved = c.post('/api/mappings/drafts', json=candidate)
    assert saved.status_code == 201, saved.get_data(as_text=True)
    return saved.get_json()


def test_the_catalogue_names_the_repositorys_carbohydrates_in_the_order_it_carries_them(dashboard):
    """The registry names four; a folder exists for three. Nothing is invented and nothing is silently dropped."""
    body = _catalogue(dashboard)
    assert [item['molecule_id'] for item in body['sugars']] == ['Maltose', 'Sucrose', 'Trehalose', 'Glucose']
    assert [item['molecule_folder'] for item in body['sugars']] == [True, True, True, False]
    assert [item['ready'] for item in body['sugars']] == [False, False, False, False]
    assert body['solute_files'] == list(SOLUTE_FILES)
    assert body['molality_range'] == [0.0, 2.5]


def test_a_carbohydrate_with_no_molecule_folder_is_refused_and_the_blocker_names_the_missing_mapping(dashboard):
    """Glucose carries a measured target and no molecule: the reason says which of the two is missing."""
    glucose = _sugar(_catalogue(dashboard), 'Glucose')
    assert glucose['mappings'] == []
    assert any('No saved CG mapping' in blocker for blocker in glucose['blockers']), glucose['blockers']
    assert any('molecules/' in blocker for blocker in glucose['blockers']), glucose['blockers']


def test_a_missing_solute_file_is_named_and_the_sugar_is_not_ready(dashboard):
    """The blocker names the file, so a run that would die in `prepare` is refused here where the name is known."""
    trehalose = _sugar(_catalogue(dashboard), 'Trehalose')
    assert trehalose['solute_files_missing'] == list(SOLUTE_FILES)
    assert any('missing solute.gro' in blocker for blocker in trehalose['blockers']), trehalose['blockers']
    # Only some of the files: the count says how many, and the missing list names the one that is not there.
    root = _solute_files(dashboard, 'trehalose')
    (root / 'water.gro').unlink()
    trehalose = _sugar(_catalogue(dashboard), 'Trehalose')
    assert trehalose['solute_files_present'] == len(SOLUTE_FILES) - 1
    assert trehalose['solute_files_missing'] == ['water.gro']
    assert trehalose['ready'] is False


def test_the_solute_root_sits_beside_the_runs_in_the_selected_workspace(dashboard):
    """Resolved by the server and never typed: the fixture's own workspace, not the developer's."""
    maltose = _sugar(_catalogue(dashboard), 'Maltose')
    assert maltose['solute_root'] == str(dashboard.coordinator.RUNS.parent / 'osmotic' / 'maltose')
    assert 'workspace/osmotic/maltose' in maltose['solute_root'].replace('\\', '/')


def test_sucroses_blocker_carries_the_provisional_mapping_note(dashboard):
    """The repository's own standing decision, said where Sucrose's blocker is shown rather than in a footnote.

    It is attached to the *mapping*: with no saved candidate there is nothing to call provisional, and the note
    arrives with the candidate it describes.
    """
    assert _sugar(_catalogue(dashboard), 'Sucrose')['provisional'] is True
    assert not any('provisional' in blocker for blocker in _sugar(_catalogue(dashboard), 'Sucrose')['blockers'])
    _save_mapping(dashboard, 'Sucrose')
    sucrose = _sugar(_catalogue(dashboard), 'Sucrose')
    assert any('provisional' in blocker for blocker in sucrose['blockers']), sucrose['blockers']
    assert _sugar(_catalogue(dashboard), 'Maltose')['provisional'] is False


def test_a_sugar_with_a_mapping_and_its_solute_files_is_ready(dashboard):
    """Both halves present is the only state that is ready, and the mapping is listed with its own name."""
    _solute_files(dashboard, 'maltose')
    assert _sugar(_catalogue(dashboard), 'Maltose')['ready'] is False, 'no mapping yet'
    saved = _save_mapping(dashboard, 'Maltose')
    maltose = _sugar(_catalogue(dashboard), 'Maltose')
    assert maltose['ready'] is True
    assert [item['file'] for item in maltose['mappings']] == [saved['file']]
    assert maltose['mappings'][0]['name'] == saved['name']


def test_the_failure_policy_reports_both_choices_as_they_are_acted_on(dashboard):
    """Both choices act, and the acting half is the run type's own driver rather than something outside it."""
    policy = _catalogue(dashboard)['failure_policy']
    assert policy['key'] == 'series_on_failure'
    assert policy['default'] == 'carry_on'
    assert policy['attempts_max'] == 3, 'the run type\'s own default: a condition is retried three times'
    assert policy['driver'] == 'osmotic_simulation.sh', 'the half that acts on the choice, named where it lives'
    carry_on, stop = policy['options']
    assert carry_on['value'] == 'carry_on' and carry_on['available'] is True and carry_on['reason'] is None
    assert stop['value'] == 'stop' and stop['available'] is True, 'the series run honours it itself'
    assert stop['reason'] is None
    assert policy['advertised'] is True, 'the run type names the key, so the route keeps it'


def test_a_choice_the_run_type_did_not_carry_is_offered_disabled_with_its_reason(dashboard, monkeypatch):
    """The choice is still *listed* -- with the reason -- rather than hidden or, worse, inert.

    Both options stand on one fact now: the key has to be in the run type's vocabulary, or the queue routes drop it
    before the job exists and nothing downstream can act on it. This pins what the answer looks like when that fact
    is false, which is the state a panel has to be able to render rather than the state it is in.
    """
    from dashboard.execution import protocol
    from dashboard.web.routes import osmotic as route

    real = protocol.adapter_for

    def without_the_policy(name):
        adapter = real(name)
        if name != 'osmotic':
            return adapter
        return dataclasses.replace(adapter, choice_specs=lambda: {key: spec for key, spec in
                                                                  osmotic.CHOICE_SPECS.items()
                                                                  if key != route.FAILURE_KEY})

    monkeypatch.setattr(protocol, 'adapter_for', without_the_policy)
    policy = _catalogue(dashboard)['failure_policy']
    assert policy['advertised'] is False
    for option in policy['options']:
        assert option['available'] is False
        assert route.FAILURE_KEY in option['reason'] and 'dropped' in option['reason'], option['reason']


def test_the_standing_setup_is_the_pipelines_own_numbers(dashboard):
    """Shown, never offered: every value is read from the module that decides it."""
    from dashboard.execution.adapters import osmotic, osmotic_box, osmotic_mdp

    setup = _catalogue(dashboard)['setup']
    assert setup['box_nm'] == list(osmotic_box.BOX_NM)
    assert setup['dividing_area_nm2'] == osmotic_box.dividing_area_nm2()
    assert setup['confinement_nm'] == osmotic_box.CONFINEMENT_NM
    assert setup['confinement_kj_mol_nm2'] == osmotic_box.CONFINEMENT_KJ_MOL_NM2
    assert setup['kappa'] == osmotic_mdp.DEFAULT_CONFINEMENT_KJ_MOL_NM2 / 2, 'PLUMED writes V = KAPPA*(x-AT)^2'
    assert setup['restraint_kj_mol_nm2'] == osmotic.REFERENCE_RESTRAINT
    assert setup['mdrun_ntomp'] == osmotic.DEFAULTS['mdrun_ntomp']
    assert setup['mdrun_ranks'] == osmotic.DEFAULTS['mdrun_ranks']


def test_the_defaults_are_the_panels_own_and_the_production_bar_is_the_papers(dashboard):
    """500 ns is what every measured condition in the completed series ran; 500000 ps is the wire value."""
    defaults = _catalogue(dashboard)['defaults']
    assert defaults['duration_ns'] == 500
    assert defaults['production_ps'] == 500000.0
    assert defaults['temperature_k'] == 308.15
    assert defaults['equilibration_ps'] == 10000.0
    assert defaults['output_interval_ps'] == 10.0
