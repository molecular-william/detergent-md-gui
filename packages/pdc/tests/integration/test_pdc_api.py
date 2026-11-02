"""The catalogue endpoint the complex panel builds its setup from, and the conformation-library wiring around it.

The catalogue endpoint's job is not to look impressive but to be honest: it lists what the repository actually holds,
including the state of the files a template names, because the shipped DDM template is a skeleton and the panel
must not offer it as a fitted detergent model.

The second half is the run's side of the conformation library: `prepare` records the resolved library as a verified
input and writes the `conformations_*` keys the build stage reads, a later run may name the same stored library by
key after its source runs are gone, and the two routes the shape card reads list what the workspace really holds.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from dashboard import files
from dashboard.execution import run_inputs
from detergent_pdc import conformations
from detergent_pdc.execution.adapters import pdc
from detergent_pdc.execution.scripts import pdc_build

from tests.harness import conformation_fixtures
from tests.harness.pdc_fixtures import settings_of, system_stage
from tests.harness.support import DDM_BONDS, DDM_CLASSES, PROJECT_ROOT


def test_the_catalogue_lists_the_shipped_template_and_says_what_it_is(dashboard):
    response = dashboard.client.get('/api/pdc/catalog')
    assert response.status_code == 200

    body = response.get_json()
    assert body['templates'], body
    ddm = next(entry for entry in body['templates'] if entry['molecule'] == 'DDM')
    assert ddm['residue'] == 'DDM'
    assert ddm['registered_type'] == 'registered-template'   # not a fitted model, and the panel says so
    assert ddm['limitations'], 'a template must carry its limitation rather than look ready'
    assert isinstance(ddm['files_present'], bool)
    assert ddm['missing_files'] == [] or ddm['files_present'] is False


def test_the_catalogue_carries_the_decided_defaults(dashboard):
    """The numbers the protocol was agreed with, in one place, so a panel field cannot invent its own."""
    defaults = dashboard.client.get('/api/pdc/catalog').get_json()['defaults']
    assert defaults['salt_molar'] == 0.15
    assert defaults['assessment_ns'] == 100 and defaults['extension_ns'] == 900
    assert defaults['selection_threshold_fraction'] == 0.10 and defaults['attempts_max'] == 3
    assert defaults['box_margin_nm'] == 2.0 and defaults['initial_z_nm'] == 6.0 and defaults['contact_nm'] == 0.6


def test_the_protein_list_is_what_the_repository_holds(dashboard):
    proteins = dashboard.client.get('/api/pdc/catalog').get_json()['proteins']
    assert isinstance(proteins, list)
    for entry in proteins:
        assert entry['path'].endswith('.pdb') and entry['name'] and entry['id']


# The head of a real OPM download (1qj8, OmpX), and a fetch that counts itself, so a test can assert the network was
# touched once or not at all.
STRUCTURE = ('REMARK      1/2 of bilayer thickness:   11.8                                    \n'
             'ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N\n')


def _counted_fetcher(monkeypatch, dashboard, payload=STRUCTURE.encode()):
    calls = []

    def fetch(url):
        calls.append(url)
        return payload

    monkeypatch.setitem(dashboard.app.config, 'PDC_FETCHER', fetch)
    return calls


def test_importing_a_structure_puts_it_in_the_catalogue_with_what_the_file_states(dashboard, monkeypatch):
    """The point of the import: the panel can then name this protein the way it names a packaged one."""
    calls = _counted_fetcher(monkeypatch, dashboard)

    response = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': '1qj8'})

    assert response.status_code == 201
    record = response.get_json()
    assert record['pdbid'] == '1qj8' and record['half_thickness_nm'] == 1.18
    assert calls == ['https://biomembhub.org/shared/opm-assets/pdb/1qj8.pdb']
    assert (dashboard.paths.proteins / '1qj8.pdb').read_bytes() == STRUCTURE.encode()

    catalogue = dashboard.client.get('/api/pdc/catalog').get_json()['proteins']
    entry = next(item for item in catalogue if item['name'] == '1qj8')
    assert entry['source'] == 'imported' and entry['half_thickness_nm'] == 1.18


def test_an_id_that_is_already_here_answers_without_fetching_again(dashboard, monkeypatch):
    """A second import is a question about a file, not a reason to reach the network."""
    calls = _counted_fetcher(monkeypatch, dashboard)

    first = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': '1qj8'})
    second = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': '1qj8'})

    assert (first.status_code, second.status_code) == (201, 200)
    assert len(calls) == 1
    assert second.get_json()['already_present'] is True


def test_an_id_that_is_not_a_pdb_id_is_refused_before_anything_is_fetched(dashboard, monkeypatch):
    """The id becomes a file name, so this is the trust boundary -- and a refusal must not reach the network.

    What is refused is the *form*: `nope` is four letters and therefore a well-formed id, and whether a well-formed
    id names a structure is the fetch's question to answer, not this gate's.
    """
    calls = _counted_fetcher(monkeypatch, dashboard)

    for bad in ('../../etc/passwd', '1qj8.pdb', '1qj', '1qj88', '1q;8', ''):
        assert dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': bad}).status_code == 400, bad

    assert calls == []
    assert not dashboard.paths.proteins.exists() or list(dashboard.paths.proteins.iterdir()) == []


def test_a_body_with_no_id_at_all_is_refused_rather_than_fetching_anything(dashboard, monkeypatch):
    calls = _counted_fetcher(monkeypatch, dashboard)

    assert dashboard.client.post('/api/pdc/proteins/import', json={}).status_code == 400
    assert calls == []


def test_a_fetch_that_failed_is_reported_and_leaves_the_catalogue_as_it_was(dashboard, monkeypatch):
    """A failure upstream is not the caller's bad request, and it must not leave a half-made import behind."""
    def broken(url):
        raise OSError('connection reset by peer')

    monkeypatch.setitem(dashboard.app.config, 'PDC_FETCHER', broken)

    response = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': '1qj8'})

    assert response.status_code == 502
    assert '1qj8' in response.get_json()['error']
    catalogue = dashboard.client.get('/api/pdc/catalog').get_json()['proteins']
    assert '1qj8' not in [item['name'] for item in catalogue]


# --- the conformation library a run names -------------------------------------------------------------

SOURCE_RUN = 'b920391735dd'
TEMPLATE = 'molecules/DDM/micelle_template.json'
LIBRARY_MAPPING = 'mapping_candidate_library.json'


def library_mapping():
    """The fixture source run's own eleven beads, as the mapping editor exports a saved mapping.

    The library is matched bead for bead against the mapping's derived model, so a run that uses the fixture's
    library must derive the same bead names in the same order. The virtual sites and the connectivity are the
    fixture's own, which is what makes the derivation and the trajectory the same molecule.
    """
    parents = dict(conformation_fixtures.VIRTUAL_SITES)
    beads = []
    for index, (name, kind, _position) in enumerate(conformation_fixtures.BEADS, start=1):
        bead = {'name': name, 'type': kind, 'size': DDM_CLASSES[name],
                'atoms': [] if index in parents else [index]}
        if index in parents:
            bead['virtual_site'] = {'function': 1, 'parents': [conformation_fixtures.BEADS[parent - 1][0]
                                                               for parent in parents[index]]}
        beads.append(bead)
    names = [name for name, _kind, _position in conformation_fixtures.BEADS]
    return {'schema_version': 3, 'molecule_id': 'DDM', 'name': "the fixture run's own eleven beads",
            'martini_version': 3, 'beads': beads,
            'connections': [[names[first - 1], names[second - 1]] for first, second in DDM_BONDS]}


def store_mapping(workspace):
    """The saved mapping put where a run resolves one by name, and its file (for the digest a source run records)."""
    directory = Path(workspace) / 'mapping_drafts'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LIBRARY_MAPPING
    path.write_text(json.dumps(library_mapping()))
    return path


def source_run(dashboard, run_id=SOURCE_RUN, **kwargs):
    """A completed, protein-free pdc run with a tiny real trajectory, built by the shared harness fixtures."""
    mapping = store_mapping(dashboard.paths.workspace)
    return conformation_fixtures.run_tree(dashboard.paths.workspace, run_id=run_id,
                                          mapping_sha256=files.sha256(mapping), **kwargs)


def library_settings(source, **extra):
    return {'seed': 20261013, 'aggregation_number': 6,
            'conformation_library': {'runs': [source['run_id']], 'size': 2, 'seed': 0}, **extra}


def prepare_run(run, settings, *, mapping=LIBRARY_MAPPING):
    pdc.prepare(run, template=TEMPLATE, settings=settings, project_root=PROJECT_ROOT, mapping=mapping)
    return run


def manifest_of(run):
    return json.loads((Path(run) / 'manifest.json').read_text())


def insert_job(dashboard, job_id, *, status='completed', run_type='pdc', created, label=''):
    dashboard.coordinator.database().insert({'id': job_id, 'run_type': run_type, 'status': status,
                                             'label': label, 'created': created})


def test_prepare_records_the_resolved_library_as_a_verified_input(dashboard, tmp_path):
    """The library is an input like any other: path, digest and label in `inputs.json`, and the pin the build reads.

    The digest is what makes a changed file visible instead of silent: `pdc_build` re-verifies the file against the
    settings, and `run_inputs` verifies the record before any stage runs -- so an edited library is caught twice, and
    neither check is a second write path.
    """
    mapping = store_mapping(dashboard.paths.workspace)
    source = source_run(dashboard)
    run = prepare_run(tmp_path / 'run', library_settings(source))

    settings = settings_of(run)
    key = settings['conformations_key']
    library_path = Path(settings['conformations_library'])
    assert settings['conformations_mode'] == 'build'
    assert settings['conformations_runs'] == [SOURCE_RUN]
    assert settings['conformations_size'] == 2
    assert len(key) == 16 and int(key, 16) >= 0
    assert library_path.is_file()
    assert library_path == Path(dashboard.paths.workspace) / 'conformations' / 'DDM' / key / 'library.json'
    assert settings['conformations_sha256'] == files.sha256(library_path)
    assert settings['conformations_mapping_sha256'] == files.sha256(mapping)
    assert set(settings['conformations_producer']) == {'numpy', 'mdanalysis'}

    # The manifest's settings are the same record, and `inputs.json` names the library by workspace path and digest.
    manifest = manifest_of(run)
    assert manifest['settings']['conformations_key'] == key
    entry = next(record for record in manifest['inputs'] if record['role'] == 'detergent_conformations')
    assert entry['kind'] == 'store' and entry['root'] == 'workspace'
    assert entry['sha256'] == settings['conformations_sha256']
    assert entry['label'] == f'DDM-{key}'
    assert Path(dashboard.paths.workspace, entry['path']).resolve() == library_path.resolve()
    run_inputs.verify_manifest(run, manifest)

    # Editing the file it pinned makes the input verification fail, naming the role.
    library_path.write_text(library_path.read_text() + ' \n')
    with pytest.raises(ValueError, match='detergent_conformations'):
        run_inputs.verify_manifest(run, manifest)


def test_a_later_run_selects_the_library_by_key_after_its_source_runs_are_gone(dashboard, tmp_path):
    """A reference library is self-contained: its source runs need not exist in this workspace.

    The second run must record the same key and digest as the first, under mode `reference`, because that digest is
    the run's pin -- and losing the stored directory is a refusal that says to copy the original back, never a
    rebuild that quietly produces different bytes.
    """
    source = source_run(dashboard)
    built = prepare_run(tmp_path / 'built', library_settings(source))
    recorded = settings_of(built)

    shutil.rmtree(dashboard.paths.workspace / 'runs' / SOURCE_RUN)
    referenced = prepare_run(tmp_path / 'referenced', {
        'seed': 20261013, 'aggregation_number': 6,
        'conformation_library': {'key': recorded['conformations_key'],
                                 'sha256': recorded['conformations_sha256']}})

    settings = settings_of(referenced)
    assert settings['conformations_mode'] == 'reference'
    assert settings['conformations_key'] == recorded['conformations_key']
    assert settings['conformations_sha256'] == recorded['conformations_sha256']
    assert settings['conformations_library'] == recorded['conformations_library']
    assert settings['conformations_runs'] == [SOURCE_RUN], 'a reference records the runs its library names'


def test_a_run_that_names_a_library_without_a_mapping_is_refused(dashboard, tmp_path):
    """A library is matched against the mapping's own beads, so a build with no mapping has nothing to match."""
    source = source_run(dashboard)

    with pytest.raises(ValueError, match='mapping'):
        pdc.prepare(tmp_path / 'run', template=TEMPLATE, settings=library_settings(source),
                    project_root=PROJECT_ROOT)


def test_a_library_for_another_detergent_is_refused_before_the_build(dashboard, tmp_path):
    """A library built from a different detergent cannot shape this run's beads, and the refusal names both."""
    source = source_run(dashboard, residue='OCT')

    with pytest.raises(ValueError, match='residue'):
        pdc.prepare(tmp_path / 'run', template=TEMPLATE, settings=library_settings(source),
                    project_root=PROJECT_ROOT, mapping=LIBRARY_MAPPING)


def test_a_prepared_library_reaches_the_build_stage_and_is_stamped(dashboard, tmp_path):
    """The end of the real flow: prepare writes the settings, and the build draws and stamps the stored bodies.

    This is the wiring the lanes meet at. The run is prepared through the adapter, its `pdc-settings.json` is what
    the stage would copy, and the build stage reads the `conformations_*` keys, loads and re-verifies the library,
    draws one entry and one azimuth per site, and stamps exactly that many bodies -- no template repeated.
    """
    source = source_run(dashboard)
    assert source['run_id'] == SOURCE_RUN
    run = prepare_run(tmp_path / 'run', library_settings(source))
    settings = settings_of(run)

    stage = system_stage(run)
    assert pdc_build.build(stage) == 0
    report = json.loads((stage / pdc.REPORT_NAME).read_text())

    assert report['valid'] is True, report.get('reasons')
    drawn = report['conformations']
    assert drawn['key'] == settings['conformations_key']
    assert drawn['mode'] == 'build' and drawn['sources'] == [SOURCE_RUN]
    assert len(drawn['entries']) == len(drawn['twists']) == settings['aggregation_number']
    assert all(0 <= index < settings['conformations_size'] for index in drawn['entries'])
    assert all(0.0 <= twist < 2.0 * 3.141592653589793 for twist in drawn['twists'])

    lines = (stage / 'system.gro').read_text().splitlines()
    assert int(lines[1]) == settings['aggregation_number'] * len(conformation_fixtures.BEADS), \
        'each site carries a whole drawn body, not one centre or one repeated template bead'


def test_the_conformation_runs_route_lists_every_completed_pdc_run_and_its_verdict(dashboard):
    """The shape card's run list: eligible runs first-class, ineligible ones still listed with their sentence.

    Hiding an ineligible run would read as "this workspace has no such run"; the reader choosing source runs needs
    to see the protein-bearing micelle and be told why it cannot be a source. Runs that are not completed pdc runs
    are not this list's subject at all.
    """
    source = source_run(dashboard)
    manifest = json.loads((source['run'] / 'manifest.json').read_text())
    manifest['settings'] = {'assessment_ns': 40, 'extension_ns': 60}
    (source['run'] / 'manifest.json').write_text(json.dumps(manifest))
    insert_job(dashboard, SOURCE_RUN, created='2026-11-01T00:00:00+00:00', label='empty micelle')

    source_run(dashboard, run_id='aabbccddeeff', protein='molecules/DDM/protein.pdb')
    insert_job(dashboard, 'aabbccddeeff', created='2026-11-02T00:00:00+00:00', label='with protein')
    insert_job(dashboard, 'failedrun0001', status='failed', created='2026-11-03T00:00:00+00:00')
    insert_job(dashboard, 'cgonlyrun0001', run_type='aa_cg', created='2026-11-04T00:00:00+00:00')

    body = dashboard.client.get('/api/pdc/conformations/runs').get_json()

    assert [run['id'] for run in body['runs']] == ['aabbccddeeff', SOURCE_RUN]
    eligible, ineligible = body['runs'][1], body['runs'][0]
    assert eligible == {'id': SOURCE_RUN, 'label': 'empty micelle', 'residue': 'DDM', 'protein': False,
                        'completed': True, 'duration_ns': 100.0, 'eligible': True, 'reason': None}
    assert ineligible['protein'] is True and ineligible['completed'] is True
    assert ineligible['eligible'] is False and 'carries a protein' in ineligible['reason']
    assert ineligible['residue'] == 'DDM', 'an ineligible run still says which detergent it is'


def test_the_libraries_route_lists_only_directories_it_can_verify(dashboard):
    """A stored library the panel may select is one `resolve` would accept; a broken directory is not offered."""
    source = source_run(dashboard)
    library = conformations.resolve(dashboard.paths.workspace, library_settings(source)['conformation_library'],
                                    build=True)
    broken = dashboard.paths.workspace / 'conformations' / 'DDM' / ('0' * 16)
    broken.mkdir(parents=True)
    (broken / 'library.json').write_text('{"format": "detergent-conformations-v1"}\n')

    body = dashboard.client.get('/api/pdc/conformations/libraries').get_json()
    assert body['libraries'] == [{'key': library.key, 'residue': 'DDM', 'size': 2, 'sha256': library.sha256,
                                  'sources': [SOURCE_RUN], 'path': str(library.path)}]

    narrowed = dashboard.client.get('/api/pdc/conformations/libraries?residue=OCT').get_json()
    assert narrowed['libraries'] == []
