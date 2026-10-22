"""The preview route: one GET, its basis, and which refusals are answers rather than bad requests.

The route's job is to be honest about three things at once. The `basis` block travels with the picture, so a reader
never has to guess which question the thing on screen answered. A **refusal is an answer**: the template's own
validator and the placement's clearance gate come back as `200` with `valid: false` and the builder's own sentences,
because the panel renders those instead of inventing a message. And a *malformed* request -- an unknown protein, a
chain the file does not name, a seed that is not a whole number -- is a 400 with `{error}`, the spelling
`pdc_encapsulation` already uses.

The protein and the mapping are built here through the real import path and the real mapping store, so nothing reads
the developer's workspace. The one test that runs the real tools is skipped where martinize2 cannot be resolved, which
is this suite's own rule for a checkout without a vendor tree.
"""
from __future__ import annotations

import json
import math

import pytest

from dashboard.execution import tools
from dashboard.execution.adapters import pdc_view

# On the slow tier: a cold and a warm preview each pay a real coarse-graining run, which is what the marker renders.
pytestmark = pytest.mark.slow



def peptide(residues=6, *, chain='A', shift_nm=0.0) -> str:
    """A compact six-residue peptide, in the columns martinize2 reads: N, CA, C, O and CB per residue.

    Compact on purpose. The file states no membrane, so the placement is a **sphere whose radius is measured from the
    protein** -- the extent about the centroid plus the clearance plus the detergent's own length -- and a protein
    reaching past that shell puts its own atoms where the sites land, which is the clearance *refusal* rather than a
    picture. Every atom here is within 1.3 nm of the centre, so the shell clears the protein by more than a
    nanometre and the cold/warm test measures the cache instead of the gate. Six residues is the shortest fixture
    both secondary-structure sources answer (MDAnalysis' DSSP raises below five).

    `chain` and `shift_nm` place a second copy in its own chain, for the tests about a chain selection: a structure
    whose two halves are far apart measures a different shell for each.
    """
    records, serial = [], 0
    for residue in range(1, residues + 1):
        angle = 2.0 * math.pi * residue / residues
        centre = (0.8 * math.cos(angle) + shift_nm, 0.8 * math.sin(angle), 0.0)
        for name, offset, element in (('N', (0.0, 0.0, 0.25), 'N'), ('CA', (0.15, 0.0, 0.0), 'C'),
                                      ('C', (0.3, 0.1, -0.15), 'C'), ('O', (0.35, 0.2, -0.25), 'O'),
                                      ('CB', (0.2, -0.2, 0.1), 'C')):
            serial += 1
            xyz = [centre[axis] + offset[axis] for axis in range(3)]
            records.append(f'ATOM  {serial:5d} {name:^4s} ALA {chain}{residue:4d}    '
                           f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00          {element:>2s}')
    return '\n'.join(records) + '\nEND\n'


PEPTIDE = peptide()
#: Two copies of the peptide, the second in its own chain 8 nm away: selecting one chain halves the extent, which is
#: what the sphere's radius is measured from.
TWO_CHAINS = peptide() + peptide(chain='B', shift_nm=8.0)


def import_protein(dashboard, monkeypatch, text=PEPTIDE, pdbid='1qj8'):
    """Put a structure in the workspace through the real import path, and answer with its catalogue entry."""
    monkeypatch.setitem(dashboard.app.config, 'PDC_FETCHER', lambda url, body=text: body.encode())
    response = dashboard.client.post('/api/pdc/proteins/import', json={'pdbid': pdbid})
    assert response.status_code == 201, response.get_json()
    return next(entry for entry in dashboard.client.get('/api/pdc/catalog').get_json()['proteins']
                if entry['name'] == pdbid)


def write_mapping(dashboard, molecule_id='DDM', name='mapping_candidate_fixture.json', beads=None):
    """A saved candidate in the workspace's own mapping store, named the way the panel offers one."""
    directory = dashboard.paths.mapping_drafts
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps({
        'schema_version': 3, 'molecule_id': molecule_id, 'name': 'a test detergent mapping',
        'beads': beads if beads is not None else [
            {'name': 'TAIL1', 'type': 'C1', 'size': 'R', 'atoms': [1]},
            {'name': 'TAIL2', 'type': 'C1', 'size': 'R', 'atoms': [2]},
            {'name': 'S1A', 'type': 'SP1r', 'size': 'S', 'atoms': [3]},
            {'name': 'S1VS', 'type': 'TC4', 'size': 'T', 'atoms': [],
             'virtual_site': {'function': 1, 'parents': ['TAIL2', 'S1A']}}],
        'connections': [['TAIL1', 'TAIL2'], ['TAIL2', 'S1A']],
        'provenance': {'origin': 'manual', 'algorithm': None, 'references': []},
        'status': 'candidate-unvalidated', 'martini_version': '3'}))
    return name


TEMPLATE = 'molecules/DDM/micelle_template.json'


def get(dashboard, **query):
    """The route, with the panel's own spellings as the query."""
    return dashboard.client.get('/api/pdc/preview/placement?' +
                                '&'.join(f'{key}={value}' for key, value in query.items()))


def strict_loads(text):
    """`json.loads` at a browser's strictness: `NaN` and `Infinity` are not JSON, whatever Python's default accepts.

    Python's `json.loads` reads the bare token `NaN` without complaint, which is why a `nan` number can travel this
    whole path unnoticed by a Python test; a browser's `JSON.parse` throws on it, which is how the panel lost a
    refusal's own sentence. Every body this route answers with is put through this instead.
    """
    def reject(value):
        raise ValueError(f'{value} is not JSON: a browser refuses it')
    return json.loads(text, parse_constant=reject)


def test_a_coarse_grained_bead_with_no_position_refuses_with_a_reason_the_panel_can_read(dashboard, monkeypatch):
    """The user's 4iar through the real route: the answer must carry the gate's sentence *and* be JSON a browser reads.

    martinize2 leaves a CG bead at `nan` where the structure holds no coordinates for the residue it averages (4iar:
    20 of 928). The clearance the placement reported against such a bead was itself a `nan`, and Python's
    `json.dumps` writes that as the bare token `NaN` -- which a browser's `JSON.parse` refuses. The panel's
    `response.json().catch(() => ({}))` then carried on with an empty object, whose absent `valid` read as "the
    builder refuses these inputs" and whose absent `reasons` read as "the build gave no reason": a refusal the
    server never sent, for a picture the server had actually drawn. Both halves are pinned here -- the gate refuses
    with its own count, and what comes back is parseable.
    """
    from dashboard.execution import pdc_preview as preview_module

    beads = [{'residue_id': 1, 'residue': 'PRO', 'name': f'B{index:03d}', 'position': [float(index), 0.0, 0.0]}
             for index in range(1, 5)]
    beads[1]['position'] = [float('nan'), float('nan'), float('nan')]
    monkeypatch.setattr(preview_module, 'coarse_grained',
                        lambda *args, **kwargs: (beads, {'cached': False, 'seconds': 0.5, 'key': 'stub',
                                                         'path': '', 'beads_bytes': 0, 'dropped_residues': [],
                                                         'protein_input': 'protein.pdb', 'command': None,
                                                         'secondary_structure': None}))
    entry = import_protein(dashboard, monkeypatch)

    response = get(dashboard, template=TEMPLATE, protein=entry['name'], pdc_seed=20261013, aggregation_number=12)

    assert response.status_code == 200, 'a refusal is an answer, not a bad request'
    body = strict_loads(response.get_data(as_text=True))
    assert body['valid'] is False and body['pdb'] is None
    assert body['step'] == 'placement', body
    assert [reason for reason in body['reasons'] if 'without a position' in reason], body['reasons']
    assert body['basis']['clearance_nm'] is None, 'an unmeasurable clearance is not reported as a number'
    assert 'NaN' not in response.get_data(as_text=True), 'a body a browser refuses to parse is a body it cannot read'


def test_every_answer_this_route_sends_is_json_a_browser_can_parse(dashboard, monkeypatch):
    """No answer may carry `NaN`: the panel can only render what a browser is able to read.

    The valid path and the refusal path are both put through a strict parser, because the token travels as silently
    through Python as it does loudly through `JSON.parse`, and the panel is the thing that pays for it.
    """
    write_mapping(dashboard)
    empty_micelle = get(dashboard, template=TEMPLATE, molecule_id='DDM',
                        mapping_candidate='mapping_candidate_fixture.json', aggregation_number=40,
                        placement_mode='lattice', pdc_seed=20261013)
    assert empty_micelle.status_code == 200
    assert strict_loads(empty_micelle.get_data(as_text=True))['valid'] is True

    malformed = get(dashboard, template=TEMPLATE, pdc_seed=20261013, aggregation_number=0)
    assert malformed.status_code == 400
    assert strict_loads(malformed.get_data(as_text=True)).get('error')


def test_the_basis_is_the_question_that_was_asked_and_the_cost_says_what_was_paid(dashboard):
    """An empty micelle: no protein, so no coarse-graining at all -- and the cheapest preview the panel has."""
    write_mapping(dashboard)

    body = get(dashboard, template=TEMPLATE, molecule_id='DDM', mapping_candidate='mapping_candidate_fixture.json',
               aggregation_number=40, placement_mode='lattice', pdc_seed=20261013, box_margin_nm=2.0,
               initial_z_nm=6.0).get_json()

    assert body['valid'] is True, body['reasons']
    basis = body['basis']
    assert basis['protein'] is None and basis['chains'] == []
    assert basis['aggregation_number'] == 40 and basis['placement_mode'] == 'lattice' and basis['seed'] == 20261013
    assert basis['mapping'] == 'mapping_candidate_fixture.json'
    assert basis['detergent'] == 'DDM' and basis['residue'] == 'DDM' and basis['template'] == 'micelle_template.json'
    assert basis['beads'] == 160 and basis['protein_beads'] == 0
    assert basis['box_nm'] and len(basis['box_nm']) == 3 and basis['clearance_nm'] is None
    assert basis['detergent_representation'] == 'the mapping\u2019s beads'

    assert body['cost']['cg_cached'] is False and body['cost']['coarse_graining_seconds'] == 0
    assert body['cost']['cg_bytes'] == 0 and body['cost']['cg_key'] is None
    assert 'CONECT' in body['pdb'], 'the mapping bonds the beads, and the file carries those records'

    # And the same moleculetype is what colours them: every bead carries its own family's code in the file's
    # b-factor column, and the frame spans more than one family because the mapping's heads are polar (`SP1r`) and
    # its tails apolar (`C1`, `TC4`). A frame the writer was handed no moleculetype for writes the unstated zero for
    # every bead, which is the empty micelle's `family not stated` defect: this is that frame's acceptance, read off
    # the route's own answer.
    families = [int(round(float(line[60:66]))) for line in body['pdb'].splitlines() if line.startswith('HETATM')]
    assert families and 0 not in families, f'a bead states no family: {sorted(set(families))}'
    assert len(set(families)) >= 2, sorted(set(families))
    assert {pdc_view.bead_family_code('SP1r'), pdc_view.bead_family_code('C1')} <= set(families), sorted(set(families))

    # Nothing a run reads, and no run: a preview is not a job.
    assert list(dashboard.paths.runs.glob('*')) == [] if dashboard.paths.runs.exists() else True
    assert dashboard.client.get('/api/jobs').get_json()['total'] == 0
    assert not (dashboard.paths.workspace / 'preview').exists(), 'an empty micelle coarse-grains nothing'


def test_a_template_the_builder_refuses_is_an_answer_with_no_coordinates(dashboard, tmp_path):
    """`validate_template` stops the build before anything is placed; the panel gets that sentence and no picture."""
    refused = tmp_path / 'skeleton'
    refused.mkdir()
    (refused / 'beads.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (refused / 'beads.itp').write_text('[ moleculetype ]\nDDM 1\n')
    (refused / 'micelle_template.json').write_text(json.dumps(
        {'name': 'DDM', 'residue': 'DDM', 'coordinates': 'beads.pdb', 'topology': 'beads.itp', 'beads': []}))

    response = get(dashboard, template=str(refused / 'micelle_template.json'), pdc_seed=20261013, aggregation_number=12)

    assert response.status_code == 200, 'a refusal is an answer, not a bad request'
    body = response.get_json()
    assert body['valid'] is False and body['pdb'] is None
    assert body['reasons'] == ['template has no beads']
    assert body['basis']['beads'] is None and body['basis']['box_nm'] is None


def test_an_unknown_protein_is_a_404_and_a_chain_the_file_does_not_name_is_a_400(dashboard, monkeypatch):
    """Both are malformed questions rather than this build's refusals, and each says which."""
    entry = import_protein(dashboard, monkeypatch)

    missing = get(dashboard, template=TEMPLATE, protein='nosuchentry', pdc_seed=20261013, aggregation_number=12)
    assert missing.status_code == 404 and 'nosuchentry' in missing.get_json()['error']

    unknown_chain = get(dashboard, template=TEMPLATE, protein=entry['name'], chains='Z', pdc_seed=20261013,
                        aggregation_number=12)
    assert unknown_chain.status_code == 400
    error = unknown_chain.get_json()['error']
    assert 'names no chain' in error and 'A' in error, error


def test_the_malformed_questions_are_400s_before_anything_is_derived(dashboard, tmp_path):
    """A question that cannot be asked at all is refused with `{error}`, the spelling the estimate route uses."""
    cases = {
        'a missing seed': {'template': TEMPLATE, 'aggregation_number': 12},
        'a seed that is not a number': {'template': TEMPLATE, 'pdc_seed': 'yesterday', 'aggregation_number': 12},
        'a count below one': {'template': TEMPLATE, 'pdc_seed': 20261013, 'aggregation_number': 0},
        'an unknown style': {'template': TEMPLATE, 'pdc_seed': 20261013, 'aggregation_number': 12,
                             'placement_mode': 'shaken'},
        'no template at all': {'pdc_seed': 20261013, 'aggregation_number': 12},
        'a template that is not a file': {'template': 'molecules/DDM/nothing.json', 'pdc_seed': 20261013,
                                          'aggregation_number': 12},
        'a mapping that is not a file': {'template': TEMPLATE, 'pdc_seed': 20261013, 'aggregation_number': 12,
                                         'mapping_candidate': 'not_a_candidate.json'},
    }
    for name, query in cases.items():
        response = get(dashboard, **query)
        assert response.status_code == 400, f'{name} was not refused: {response.status_code} {response.get_json()}'
        assert response.get_json().get('error'), name

    assert not (dashboard.paths.workspace / 'preview').exists(), 'nothing is written for a question that cannot be asked'


def test_a_mapping_of_another_molecule_is_refused_rather_than_drawn(dashboard):
    """The picture is drawn from the mapping's own beads: pairing two molecules would draw the wrong one."""
    write_mapping(dashboard, molecule_id='Maltose', name='mapping_candidate_maltose.json')

    response = get(dashboard, template=TEMPLATE, molecule_id='DDM', mapping_candidate='mapping_candidate_maltose.json',
                   pdc_seed=20261013, aggregation_number=12)

    assert response.status_code == 400 and 'Maltose' in response.get_json()['error']


def test_a_real_cold_and_warm_preview_pay_the_coarse_graining_once(dashboard, monkeypatch):
    """The plan's decision 4, measured through the route: the expensive half is paid per selection, not per question.

    The real martinize2 runs here rather than a stub, because what is being asserted is the *cost the panel reports*
    -- and a report of a cost nobody paid is the kind of number this panel exists not to print. Skipped where the
    tool cannot be resolved, which is this suite's rule for a checkout without the vendored tools.
    """
    if tools.tool_path('martinize2') is None:
        pytest.skip('martinize2 is not resolvable in this workspace')
    entry = import_protein(dashboard, monkeypatch)
    write_mapping(dashboard)
    query = {'template': TEMPLATE, 'protein': entry['name'], 'molecule_id': 'DDM',
             'mapping_candidate': 'mapping_candidate_fixture.json', 'aggregation_number': 40, 'pdc_seed': 20261013}

    cold = get(dashboard, **query).get_json()
    warm = get(dashboard, **query).get_json()

    assert cold['valid'] and warm['valid'], cold['reasons']
    assert cold['cost']['cg_cached'] is False and cold['cost']['coarse_graining_seconds'] > 0
    assert warm['cost']['cg_cached'] is True
    assert warm['cost']['coarse_graining_seconds'] < cold['cost']['coarse_graining_seconds']
    assert cold['cost']['cg_key'] == warm['cost']['cg_key']
    assert cold['cost']['cg_bytes'] > 0, 'the cached coarse-grained protein has a size, so the panel can report it'
    assert cold['pdb'] == warm['pdb'], 'the cached beads must give the same frame as the ones the tool wrote'
    assert cold['basis']['protein_beads'] > 0 and cold['basis']['beads'] > cold['basis']['protein_beads']
    assert cold['basis']['clearance_nm'] is not None, 'the sphere placement reports how close it got'
    # The assignment survives the cache: `pdc_build.cg_protein` reports none for an entry it did not build, so the
    # warm derive reads the one kept beside the beads rather than losing the colours on the second ask.
    assignment = cold['basis']['secondary_structure']
    assert assignment['letters'] and assignment['summary'], assignment
    assert warm['basis']['secondary_structure'] == assignment

    # The cache is the workspace's own scratch area, and it is not a run: nothing appears in the runs list.
    assert (dashboard.paths.workspace / 'preview/cg').is_dir()
    assert dashboard.client.get('/api/jobs').get_json()['total'] == 0

def test_a_chain_selection_measures_its_own_shell(dashboard, monkeypatch):
    """Task 3 through the route: selecting one subunit gets the shell that subunit needs, not the complex's.

    The coarse-graining is stubbed with beads that follow the selection, because what is under test is the radius the
    route reports -- `basis.shell_radius_nm` and `basis.radius_source`, the two fields the panel's sentence reads.
    The structure states no membrane, so the placement is the sphere, and its radius is measured from the beads the
    selection coarse-grains to.
    """
    from dashboard.execution import pdc_preview as preview_module

    def stub(cache_root, protein_path, chains, **kwargs):
        selected = [chain for chain in ('A', 'B') if chain in (chains or [])] or ['A']
        beads = []
        for chain in selected:
            shift = 8.0 if chain == 'B' else 0.0
            beads += [{'residue_id': index + 1, 'residue': 'PRO', 'name': f'B{index:03d}',
                       'position': [0.8 * index + shift, 0.0, 0.0]} for index in range(1, 5)]
        return beads, {'cached': True, 'seconds': 0.0, 'key': 'stub', 'path': str(cache_root),
                       'beads_bytes': 0, 'dropped_residues': [], 'protein_input': 'protein.pdb',
                       'command': None, 'secondary_structure': None}

    monkeypatch.setattr(preview_module, 'coarse_grained', stub)
    entry = import_protein(dashboard, monkeypatch, text=TWO_CHAINS, pdbid='1abc')
    query = {'template': TEMPLATE, 'protein': entry['name'], 'pdc_seed': 20261013, 'aggregation_number': 20}

    whole = get(dashboard, **{**query, 'chains': 'A,B'})
    part = get(dashboard, **{**query, 'chains': 'A'})

    assert whole.status_code == 200 and part.status_code == 200
    both, one = whole.get_json(), part.get_json()
    assert both['valid'] and one['valid'], (both.get('reasons'), one.get('reasons'))
    assert one['basis']['chains'] == ['A'] and both['basis']['chains'] == ['A', 'B']
    part_basis = one['basis']
    assert part_basis['shell_radius_nm'] < both['basis']['shell_radius_nm'], \
        'one subunit of a two-chain complex is a smaller shell'
    assert part_basis['radius_source'] == 'measured' and both['basis']['radius_source'] == 'measured'
    assert part_basis['measured_extent_nm'] < both['basis']['measured_extent_nm']
    assert part_basis['radius_floor_nm'] == both['basis']['radius_floor_nm'], 'the setting is the same floor'
    # The density the panel prints comes from the same volume, and the count is still the user's 20.
    assert part_basis['aggregation_number'] == 20 and part_basis['estimated_density_per_nm3'] > 0
    assert part_basis['capacity_aggregation'] is None, 'the count fits, so there is nothing to report'


def test_the_route_reads_the_preparation_choice_and_refuses_a_value_that_is_not_one(dashboard, monkeypatch):
    """The plan's step 1 is a choice the panel states, so the route reads it -- and a non-answer is not one.

    Three answers, and each is a different claim: absent is the adapter's own default (off, so an existing caller's
    preview is unchanged), `true` reaches the service as the choice it is, and a value that is neither is a *malformed
    request* rather than a yes -- a route that read `maybe` as one of them would put a control on screen that means
    the opposite of what it says.
    """
    from dashboard.execution import pdc_preview as preview_module

    beads = [{'residue_id': 1, 'residue': 'PRO', 'name': f'B{index:03d}',
              'position': [0.3 * index, 0.0, 0.0]} for index in range(1, 5)]
    monkeypatch.setattr(preview_module, 'coarse_grained',
                        lambda *args, **kwargs: (beads, {'cached': False, 'seconds': 0.5, 'key': 'stub',
                                                         'path': '', 'beads_bytes': 0, 'dropped_residues': [],
                                                         'protein_input': 'protein.pdb',
                                                         'structure': str(kwargs.get('protein_path') or ''),
                                                         'command': None, 'secondary_structure': None,
                                                         'prepare': None, 'prepare_seconds': 0.0}))
    entry = import_protein(dashboard, monkeypatch)
    query = {'template': TEMPLATE, 'protein': entry['name'], 'pdc_seed': 20261013, 'aggregation_number': 12}

    default = get(dashboard, **query)
    assert default.status_code == 200 and default.get_json()['valid'] is True, default.get_data(as_text=True)
    assert default.get_json()['basis']['prepare_protein'] is False
    assert default.get_json()['cost']['prepare_seconds'] == 0.0

    asked = get(dashboard, **{**query, 'prepare_protein': 'true'})
    assert asked.status_code == 200 and asked.get_json()['valid'] is True, asked.get_data(as_text=True)
    assert asked.get_json()['basis']['prepare_protein'] is True

    malformed = get(dashboard, **{**query, 'prepare_protein': 'maybe'})
    assert malformed.status_code == 400
    assert 'prepare_protein' in malformed.get_json()['error']

    none = get(dashboard, template=TEMPLATE, pdc_seed=20261013, aggregation_number=12, prepare_protein='true')
    assert none.status_code == 400
    assert 'structure' in none.get_json()['error'], 'a step about a protein cannot be asked for with none'
