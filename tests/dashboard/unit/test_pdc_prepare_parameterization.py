"""A pdc build simulates the mapping's own fitted bonded terms when the mapping carries them.

The run's detergent topology used to be derived every time: the mapping's current parameterization was never read, so
a fitted mapping simulated terms from the Martini 3 references and the geometry while the panel showed the fit. These
tests drive `pdc.prepare` with a revision saved through `bonded.parameterization` -- the door a fit comes through --
and read the prepared stage and the manifest back, because the record those two carry is what a later reader has.

The mapping here is the test's own and the revision's topology is this file's own two-bead ITP; the molecule is the
repository's tracked `molecules/DDM`, an asset like a template, so nothing reads the developer's saved candidates or
the live workspace (the `isolated_workspace` fixture points the parameterization store at the test's directory).
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.models.bonded import parameterization
from detergent_pdc.execution.adapters import pdc
from detergent_pdc.execution.scripts import pdc_build
from detergent_pdc.models.molecules import detergent_cg

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'

#: A mapping over the real DDM: one tail bead and one head bead, the shape the editor exports.
CANDIDATE = {
    'schema_version': 3, 'molecule_id': 'DDM', 'name': 'a two-bead fixture over the real DDM', 'martini_version': 3,
    'beads': [{'name': 'TAIL1', 'type': 'C1', 'atoms': [1, 2, 3, 4]},
              {'name': 'HEAD', 'type': 'SN6', 'atoms': [5, 6, 7, 8]}],
    'connections': [['TAIL1', 'HEAD']],
}

#: What a fit writes: the export names `B01`, `B02`, and one bond with the fit's own force constant. The value is
#: arbitrary on purpose -- the derived topology certainly does not carry it, so a build that wrote the derivation
#: anyway cannot pass this file.
FITTED_TOPOLOGY = """; This file was generated using the following command:
; ff_inter -f ../2_mapping/mapped.xtc -s ../2_mapping/mapped.gro -i DDM_initial.itp

[ moleculetype ]
DDM 1

[ atoms ]
 1 C1  1 DDM B01  1 0.0 72.0
 2 SN6 1 DDM B02  2 0.0 54.0

[ bonds ]
 1  2 1 0.431 2690.007 ; B01_B02

[ exclusions ]
 1  2
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


def fit(candidate: dict = CANDIDATE, revisions: int = 1):
    """Store the mapping's revisions the way the panel's fit does, the last one current."""
    for _ in range(revisions):
        parameterization.save(candidate, REVISION)
    return parameterization.current(candidate)


def candidate_file(tmp_path: Path, candidate: dict = CANDIDATE) -> Path:
    path = tmp_path / 'mapping_candidate_0123456789abcdef0123456789abcdef.json'
    path.write_text(json.dumps(candidate))
    return path


def prepared(tmp_path: Path, candidate: dict = CANDIDATE) -> Path:
    run = tmp_path / 'run'
    pdc.prepare(run, template=TEMPLATE_PATH, settings={'seed': 1}, project_root=ROOT,
                mapping=str(candidate_file(tmp_path, candidate)))
    return run


def system(run: Path) -> Path:
    """Where `prepare` wrote the detergent's generated model: the run's `inputs/`."""
    return run / pdc.INPUTS_DIRECTORY


def model(run: Path) -> dict:
    return json.loads((system(run) / pdc.SETTINGS_NAME).read_text())['detergent_model']


def limitations(run: Path) -> str:
    return ' '.join(json.loads((run / 'manifest.json').read_text())['limitations'])


def atom_rows(text: str) -> list[list[str]]:
    section, rows = '', []
    for line in text.splitlines():
        content = line.split(';', 1)[0].strip()
        if content.startswith('[') and content.endswith(']'):
            section = content[1:-1].strip().lower()
        elif content and section == 'atoms':
            rows.append(content.split())
    return rows


def test_a_fitted_mapping_is_simulated_on_its_own_terms(tmp_path):
    """The run's topology is the fit's, and its atoms are named the way the coordinates name them."""
    fit(revisions=2)
    run = prepared(tmp_path)

    topology = (system(run) / pdc.DETERGENT_TOPOLOGY).read_text()

    assert [row[4] for row in atom_rows(topology)] == ['TAIL1', 'HEAD'], \
        f'the atoms are not the mapping\'s bead names: {atom_rows(topology)}'
    assert [row[1] for row in atom_rows(topology)] == ['C1', 'SN6'], 'the types are the fit\'s'
    assert '0.431 2690.007' in topology, 'the fit\'s bond, not a reference or a geometry fallback'
    assert topology.startswith('; This file was generated using the following command:')
    assert pdc_build.molecule_name(topology) == 'DDM', 'the molecule `[ molecules ]` and the .gro residue both name'


def test_the_manifest_names_the_revision_the_terms_came_from(tmp_path):
    """A reader of the run's record can say which fit it simulated, and that the fit was never validated."""
    current = fit(revisions=2)
    run = prepared(tmp_path)

    recorded = model(run)['parameterization']

    assert recorded['revision'] == current['revision'] == 2
    assert recorded['content_hash'] == parameterization.content_identity(CANDIDATE)
    assert recorded['engine'] == 'fast-forward'
    assert recorded['created_at'] == current['created_at']
    assert recorded['scientifically_validated'] is False
    assert recorded['aa_reference'] == {'run_id': 'dbc366ae772b'}
    assert model(run)['source'] == "the mapping's current parameterization"
    assert model(run)['term_kinds'] == parameterization.term_counts(current)
    assert model(run)['terms'] == parameterization.total_terms(current) == 1


def test_a_fitted_build_says_so_in_its_limitations(tmp_path):
    fit(revisions=2)
    run = prepared(tmp_path)

    said = limitations(run)

    assert 'revision 2' in said and 'content hash' in said, said
    assert 'dbc366ae772b' in said, 'the AA reference the fit was measured against is named'
    assert 'not scientifically validated' in said, said
    assert 'reference terms' not in said, f'a fitted build has no reference terms: {said}'


def test_the_placement_is_still_the_mappings_geometry(tmp_path):
    """The fit decides the terms; the mapping decides where the beads are, so the geometry file is the draft's."""
    fit()
    run = prepared(tmp_path)

    geometry = json.loads((system(run) / pdc.DETERGENT_GEOMETRY).read_text())

    assert [bead['name'] for bead in geometry['beads']] == ['TAIL1', 'HEAD']
    assert all(len(bead['position']) == 3 for bead in geometry['beads'])
    assert geometry['residue'] == 'DDM'


def test_a_mapping_with_no_parameterization_keeps_the_derived_topology(tmp_path):
    """Nothing was fitted, so nothing is adopted -- and the record says which of the two this build is."""
    run = prepared(tmp_path)
    draft = detergent_cg.derive(candidate_file(tmp_path), ROOT / 'molecules', ROOT)

    topology = (system(run) / pdc.DETERGENT_TOPOLOGY).read_text()
    recorded = model(run)

    assert topology == draft['topology'], 'a build with no fit writes the derivation it always wrote'
    assert 'parameterization' not in recorded
    assert recorded['source'] == (f"the mapping's derived topology: {draft['reference_terms']} reference terms, "
                                  f"{draft['fallback_terms']} fallbacks")
    assert recorded['terms'] == recorded['reference_terms'] + recorded['fallback_terms'] == draft['terms']
    said = limitations(run)
    assert 'derived from' in said and 'reference terms' in said, said
    assert 'parameterization' not in said, f'a derived build must not claim a fit: {said}'

