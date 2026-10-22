"""The models a protein-detergent build can choose between: a detergent's mappings joined to their fits.

The panel's picker used to offer mapping *files* -- a reader chose an opaque name and could not see that one candidate
carried a fitted parameterization while another would be built on terms derived from the Martini 3 references.
`/api/pdc/models` is that list instead: one entry per saved mapping of the chosen detergent that a build can reuse,
joined to the parameterization store by **content hash** (never by name: a record's `owners` list is inferred), and
labelled with what each model carries.

Everything here is the test's own. The mapping store and the parameterization store both redirect into the workspace
the `dashboard` fixture builds, the candidate is saved through the route the editor uses, and the revision goes
through `parameterization.save` -- the door a fit comes through.
"""
from __future__ import annotations

from dashboard.models.bonded import parameterization
from dashboard.models.mappings import context as mapping_context
from tests.dashboard.support import physical_mapping

#: What a fit writes: three atoms, one bond and one angle, so `terms` and `term_kinds` are both worth asserting. The
#: names are the export names a revision carries (`B01` is the first bead), which is how a term addresses a bead.
FITTED_TOPOLOGY = """; This file was generated using the following command:
; ff_inter -f ../2_mapping/mapped.xtc -s ../2_mapping/mapped.gro -i DDM_initial.itp

[ moleculetype ]
DDM 1

[ atoms ]
 1 C1  1 DDM B01  1 0.0 72.0
 2 C1  1 DDM B02  2 0.0 72.0
 3 SN6 1 DDM B03  3 0.0 54.0

[ bonds ]
 1  2 1 0.431 2690.007 ; B01_B02
 2  3 1 0.455 1250.000 ; B02_B03

[ angles ]
 1  2  3 2 2.350 25.000 ; B01_B02_B03
"""

REVISION = {
    'engine': 'fast-forward',
    'topology': FITTED_TOPOLOGY,
    'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                'torsion_model': 'legacy', 'torsion_scale': 1.0},
    'ensemble': {'frames': 20001, 'trajectory': '2_mapping/mapped.xtc',
                 'source': 'the mapped AA frames of the linked reference'},
    'aa_reference': {'run_id': 'dbc366ae772b', 'reference_sha256': 'ab' * 32,
                     'molecule_identity': 'cd' * 32, 'temperature_k': 303.15, 'production_ns': 200.0},
}


def save_mapping(dashboard, name, *, beads=None, retype=None) -> dict:
    """A saved DDM candidate, through the route the editor posts to.

    `beads` shortens the automatic assignment, which is how a mapping a build cannot reuse is made: the heavy atoms the
    missing beads would have carried are then unassigned, and that finding blocks `can_reuse` without blocking a save.

    `retype` changes the first bead's Martini type, which is how a *second* usable mapping is made: a content identity
    hashes beads, rings and connections and not the name, so saving the same assignment twice is refused as a
    duplicate -- two names for one model.
    """
    context = mapping_context.build_context(dashboard.paths.project_root / 'molecules', 'DDM')
    candidate = physical_mapping()
    candidate.update(name=name, molecule_id='DDM', molecule_snapshot=context['snapshot'])
    if beads is not None:
        candidate['beads'] = candidate['beads'][:beads]
    if retype is not None:
        candidate['beads'][0]['type'] = retype
    response = dashboard.client.post('/api/mappings/drafts', json=candidate)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def fitted(dashboard, name) -> dict:
    """A saved candidate with one recorded revision, the way the panel's fit leaves it."""
    record = save_mapping(dashboard, name)
    parameterization.save(record, REVISION)
    return record


def models(dashboard, molecule='DDM') -> dict:
    response = dashboard.client.get(f'/api/pdc/models?molecule_id={molecule}')
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_a_fitted_mapping_is_a_model_that_carries_its_revision_and_terms(dashboard):
    """The join is by content hash, and the entry says what the fit left: revision, terms, engine, when, unvalidated."""
    record = fitted(dashboard, 'DDM_CG_20261021')

    entries = models(dashboard)['models']

    assert len(entries) == 1, entries
    entry = entries[0]
    assert entry['file'] == record['file'] and entry['name'] == 'DDM_CG_20261021'
    assert entry['content_hash'] == parameterization.content_identity(record)
    assert entry['beads'] == len(record['beads'])
    assert entry['fitted']['revision'] == 1
    assert entry['fitted']['terms'] == 3
    assert entry['fitted']['term_kinds'] == {'bonds': 2, 'angles': 1}
    assert entry['fitted']['engine'] == 'fast-forward'
    assert entry['fitted']['scientifically_validated'] is False
    assert entry['fitted']['created_at'], 'a revision states when it was written'
    assert 'revision 1' in entry['label'] and '3 terms' in entry['label'], entry['label']
    assert f'{len(record["beads"])} beads' in entry['label'], entry['label']
    assert entry['label'].startswith('DDM_CG_20261021'), entry['label']


def test_the_label_names_the_mapping_and_never_its_file(dashboard):
    """What the reader sees is what the model carries; the file is the value the form submits, not the sentence."""
    record = fitted(dashboard, 'DDM_CG_20261021')

    entry = models(dashboard)['models'][0]

    assert record['file'] not in entry['label'], 'the mapping file is still what the picker shows'
    assert entry['label'].split(' · ')[0] == 'DDM_CG_20261021'


def test_the_molecule_is_named_and_fitted_models_come_before_derived_ones(dashboard):
    """A fit is what a run should consume, so the newest fitted model leads and the derived ones follow."""
    older = fitted(dashboard, 'DDM_CG_20261021')
    # Saved second, so a list ordered by when the mapping was saved would put it first.
    derived = save_mapping(dashboard, 'DDM draft from the automatic recogniser', retype='SN6')

    body = models(dashboard)

    assert body['molecule'] == 'DDM'
    assert [entry['file'] for entry in body['models']] == [older['file'], derived['file']], body['models']
    unfitted = body['models'][1]
    assert unfitted['fitted'] is None
    assert unfitted['content_hash'] == parameterization.content_identity(derived)
    assert unfitted['label'] == (f'{derived["name"]} · {len(derived["beads"])} beads · derived terms'), \
        unfitted['label']


def test_a_mapping_a_build_cannot_reuse_is_not_offered(dashboard):
    """`can_reuse` is the one rule: a mapping whose beads leave heavy atoms unassigned would be refused at prepare."""
    unusable = save_mapping(dashboard, 'DDM draft with unassigned atoms', beads=3)
    assert unusable['validation']['can_reuse'] is False, 'the fixture is meant to be unusable'

    body = models(dashboard)

    assert body['models'] == [], body['models']


def test_a_detergent_with_no_saved_mapping_offers_none(dashboard):
    """An empty list is an answer: the panel then offers the centres-only build and says so."""
    body = models(dashboard)

    assert body['molecule'] == 'DDM' and body['models'] == []


def test_an_unknown_molecule_is_refused_and_named(dashboard):
    """The list is one detergent's models, so a caller that names none, or one this panel cannot build, is refused."""
    missing = dashboard.client.get('/api/pdc/models')
    assert missing.status_code == 400
    assert 'molecule_id is required' in missing.get_json()['error']

    # A sugar in `molecules/` is not a detergent: the registry decides, and the refusal says which molecule it was.
    unknown = dashboard.client.get('/api/pdc/models?molecule_id=Sucrose')
    assert unknown.status_code == 400
    assert 'Sucrose' in unknown.get_json()['error'], unknown.get_json()['error']
