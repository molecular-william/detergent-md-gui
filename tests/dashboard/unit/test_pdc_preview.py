"""The system preview: the frame a protein-detergent build would write, and what it says when it cannot.

The claims this file pins are the plan's, and none of them is a claim about a drawing:

* the preview is the build's own placement step and not an illustration of one -- the functions the stage calls, in
  the order it calls them;
* the expensive half is martinize2, and it is *cached*, so a re-derive of the count, the style or the seed is
  milliseconds and does not pay it again;
* the frame is deterministic in the seed, which is what lets the panel say "this is the frame the run will build"
  rather than "this is roughly what it might look like";
* a refusal is the builder's own sentence with no coordinates at all -- never a picture of a system the build would
  refuse, and never a blank.

Fixtures are built here, and nothing reads the developer's workspace. Two read-only *inputs* do come from the
checkout: `molecules/DDM`, which a fixture mapping is derived against, and the published Martini 3 set the derivation
takes its bonded terms from -- inputs rather than state someone is editing. The CG step is stubbed wherever a test is
about the cache, the placement or the writer, because a test that spent seven seconds running martinize2 would buy
nothing the stub does not: `coarse_grained`'s own call path (select the chains, gate on the file the command names,
read those beads back) is exercised exactly as the stage exercises it.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dashboard.execution import pdc_preview
from dashboard.execution.adapters import pdc_box, pdc_placement, pdc_view
from dashboard.execution.scripts import pdc_build
from dashboard.models.molecules import detergent_cg
from micelle.registry import load_template
from tests.dashboard.support import PROJECT_ROOT

MOLECULES = PROJECT_ROOT / 'molecules'


# --- fixtures --------------------------------------------------------------------------------------------------

#: A detergent template with the two things a placement and a picture need: a hydrophobic core and a head. The files
#: it names are written beside it, because `registry.load_template` and `validate_template` read them.
TEMPLATE = {'name': 'DDM', 'residue': 'DDM', 'coordinates': 'beads.pdb', 'topology': 'beads.itp',
            'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'},
                      {'name': 'TAIL2', 'type': 'C1', 'role': 'tail'},
                      {'name': 'HEAD', 'type': 'SN6', 'role': 'head'}]}


def template(tmp_path, **changes) -> Path:
    """A template the builder's own loader and validator accept, with the files it names present."""
    directory = tmp_path / 'template'
    directory.mkdir(exist_ok=True)
    (directory / 'beads.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (directory / 'beads.itp').write_text('[ moleculetype ]\nDDM 1\n')
    path = directory / 'micelle_template.json'
    path.write_text(json.dumps({**TEMPLATE, **changes}))
    return path


#: Four beads of DDM, the shape a saved candidate carries: three real atoms and one ring virtual site built from its
#: parents. Derived against the checkout's own `molecules/DDM`, so the bead types are ones the published reference set
#: actually covers.
BEADS = [{'name': 'TAIL1', 'type': 'C1', 'size': 'R', 'atoms': [1]},
         {'name': 'TAIL2', 'type': 'C1', 'size': 'R', 'atoms': [2]},
         {'name': 'S1A', 'type': 'SP1r', 'size': 'S', 'atoms': [3]},
         {'name': 'S1VS', 'type': 'TC4', 'size': 'T', 'atoms': [],
          'virtual_site': {'function': 1, 'parents': ['TAIL2', 'S1A']}}]


def mapping(tmp_path, molecule_id='DDM', name='mapping_candidate_fixture.json', beads=None) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({'schema_version': 3, 'molecule_id': molecule_id, 'name': 'a test detergent mapping',
                                'beads': BEADS if beads is None else beads,
                                'connections': [['TAIL1', 'TAIL2'], ['TAIL2', 'S1A']],
                                'provenance': {'origin': 'manual', 'algorithm': None, 'references': []},
                                'status': 'candidate-unvalidated', 'martini_version': '3'}))
    return path


def protein(tmp_path, chains=('A', 'B'), name='protein.pdb') -> Path:
    """A protein file with the two chains a selection test needs and no membrane statement of its own.

    No `REMARK 1/2 of bilayer thickness`, so the placement is the sphere -- the path that keeps this file's numbers a
    function of the placement code rather than of a remembered frame.
    """
    lines = []
    serial = 0
    for index, chain in enumerate(chains):
        for residue in range(1, 4):
            serial += 1
            lines.append(f'ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    '
                         f'{float(residue + 3 * index):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C')
    path = tmp_path / name
    path.write_text('\n'.join(lines) + '\nEND\n')
    return path


def cg_pdb(beads) -> str:
    """A CG structure as martinize2 writes one: `ATOM` records, one bead per line, in the columns the reader wants.

    The positions handed in are nanometres, which is what the builders work in; the tool writes Angstroms, so they are
    scaled here the way it would and the stage's own reader scales them back.
    """
    records = [f'ATOM  {index:5d} {name:^4s} {residue:>3s} A{residue_id:4d}    '
               f'{xyz[0] * 10.0:8.3f}{xyz[1] * 10.0:8.3f}{xyz[2] * 10.0:8.3f}  1.00  0.00'
               for index, (residue_id, residue, name, xyz) in enumerate(beads, 1)]
    return '\n'.join(records) + '\nEND\n'


def line_of_beads(count=4, spacing=1.0):
    """`count` beads along x, one every `spacing` nanometres, as `(residue_id, residue, name, xyz)`."""
    return [(1, 'PRO', f'B{index:03d}', (float(index) * spacing, 0.0, 0.0)) for index in range(1, count + 1)]


def stubbed_martinize2(calls, beads=None):
    """A martinize2 that writes exactly what its own command names, and records how it was called."""
    def run(command, **kwargs):
        calls.append({'command': list(command), **kwargs})
        structure = Path(command[command.index('-x') + 1])
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(cg_pdb(line_of_beads() if beads is None else beads))
        return subprocess.CompletedProcess(command, 0)
    return run


def shell(radius, count=400):
    """~`count` points on a sphere of `radius`, dense enough that no lattice site can clear it.

    This is the protein the sphere placement cannot satisfy: a shell of 3.0 nm about the centroid, with the protein's
    own beads 3.2 nm out, puts every site inside the clearance gate -- measured on 1AT9 at 0.174 nm against a 0.5 nm
    gate, which is the refusal the plan records.
    """
    index = np.arange(count) + 0.5
    z = 1.0 - 2.0 * index / count
    angle = np.pi * (3.0 - np.sqrt(5.0)) * index
    points = np.c_[np.sqrt(1.0 - z * z) * np.cos(angle), np.sqrt(1.0 - z * z) * np.sin(angle), z]
    return [{'residue_id': 1, 'residue': 'PRO', 'name': f'B{position + 1:04d}',
             'position': list(radius * point)} for position, point in enumerate(points)]


def preview(tmp_path, **kwargs):
    """The service, with the checkout as the project root: `template`, `molecules/` and the reference set all resolve.

    A template is built only when the caller names none: the fixture writes the file, so building a default here as
    well would overwrite the very template a test handed in.
    """
    arguments = {'project_root': PROJECT_ROOT, 'cache_root': tmp_path / 'cache', 'seed': 20261013,
                 'aggregation_number': 24, 'template': str(kwargs.pop('template', None) or template(tmp_path))}
    arguments.update(kwargs)
    return pdc_preview.preview(**arguments)


# --- no coarse-graining at all ---------------------------------------------------------------------------------

def test_an_empty_micelle_preview_needs_no_coarse_graining_at_all(tmp_path):
    """The cheapest case the panel has, and a first-class one: nothing is coarse-grained, so nothing is cached."""
    answer = preview(tmp_path, aggregation_number=40, mapping=str(mapping(tmp_path)), molecule_id='DDM')

    assert answer['valid'], answer['reasons']
    cost = answer['cost']
    assert cost['coarse_graining_seconds'] == 0.0 and cost['cg_cached'] is False
    assert cost['cg_bytes'] == 0 and cost['cg_key'] is None
    assert not (tmp_path / 'cache').exists(), 'an empty micelle has nothing to coarse-grain, so nothing is written'
    assert answer['basis']['protein'] is None and answer['basis']['protein_beads'] == 0
    assert answer['basis']['beads'] == 40 * len(BEADS)
    assert answer['basis']['detergent_representation'] == 'the mapping\u2019s beads'


def test_the_cached_step_is_not_run_again_and_a_different_selection_is_a_different_entry(tmp_path, monkeypatch):
    """The plan's decision 4, measured: the coarse-graining is the expensive half, and it is paid once per selection."""
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_martinize2(calls))
    protein_path = protein(tmp_path)

    cold = preview(tmp_path, protein=str(protein_path), chains=['A'], mapping=None, aggregation_number=12)
    warm = preview(tmp_path, protein=str(protein_path), chains=['A'], mapping=None, aggregation_number=12)
    other = preview(tmp_path, protein=str(protein_path), chains=['A', 'B'], mapping=None, aggregation_number=12)

    assert len(calls) == 2, 'the second derive of the same selection must not run the tool again'
    assert cold['cost']['cg_cached'] is False and warm['cost']['cg_cached'] is True
    assert cold['cost']['coarse_graining_seconds'] > 0 and warm['cost']['coarse_graining_seconds'] >= 0
    assert other['cost']['cg_cached'] is False, 'a different selection is a different entry'
    assert warm['cost']['cg_key'] == cold['cost']['cg_key'] != other['cost']['cg_key']
    assert cold['pdb'] == warm['pdb'], 'the same question, asked twice, is the same frame'


def test_the_cache_key_is_the_protein_the_selection_and_the_tool(tmp_path):
    """What invalidates an entry, one input at a time: the file's bytes, the chains, and the tool that built it."""
    protein_path = protein(tmp_path)
    copy = tmp_path / 'reimported.pdb'
    copy.write_text(protein_path.read_text())
    changed = tmp_path / 'changed.pdb'
    changed.write_text(protein_path.read_text().replace('3.000', '4.000'))
    tool = tmp_path / 'martinize2'
    tool.write_text('#!/bin/sh\n')
    other_tool = tmp_path / 'martinize2-other'
    other_tool.write_text('#!/bin/sh\n# another build\n')

    assert pdc_preview.cache_key(protein_path, ['A'], tool) == pdc_preview.cache_key(copy, ['A'], tool), \
        'the same structure under another name is the same entry'
    assert pdc_preview.cache_key(protein_path, ['A'], tool) != pdc_preview.cache_key(changed, ['A'], tool)
    assert pdc_preview.cache_key(protein_path, ['A'], tool) != pdc_preview.cache_key(protein_path, ['A', 'B'], tool)
    assert pdc_preview.cache_key(protein_path, ['A'], tool) != pdc_preview.cache_key(protein_path, ['A'], other_tool)
    assert pdc_preview.cache_key(protein_path, ['A'], tool) != pdc_preview.cache_key(protein_path, ['A'], None)


def test_a_coarse_graining_step_that_fails_is_a_refusal_rather_than_a_traceback(tmp_path, monkeypatch):
    """A tool that cannot run is the builder's problem to report, and the panel renders the sentence it gets back."""
    def broken(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(pdc_build.subprocess, 'run', broken)

    answer = preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=12)

    assert answer['valid'] is False and answer['pdb'] is None
    assert answer['reasons'] and 'coarse-graining step could not build this protein' in answer['reasons'][0]
    assert answer['basis']['beads'] is None, 'a refusal carries no coordinates and no bead count to read as one'


# --- the builder's refusals ------------------------------------------------------------------------------------

def strict_loads(text):
    """`json.loads` at a browser's strictness: `NaN` and `Infinity` are not JSON, whatever Python's default accepts.

    A browser's `JSON.parse` refuses the literal `NaN` that Python's `json.dumps` writes for a float `nan`, so an
    answer carrying one is an answer no panel can read. The route's own answer is put through this in the integration
    suite; here it holds the unit that produces it to the same rule.
    """
    def reject(value):
        raise ValueError(f'{value} is not JSON: a browser refuses it')
    return json.loads(text, parse_constant=reject)


def stubbed_cg(beads):
    """A `coarse_grained` that answers with `beads`, so a test can hand the placement the protein it needs."""
    return lambda *args, **kwargs: (beads, {'cached': False, 'seconds': 0.5, 'key': 'stub',
                                            'path': str(kwargs.get('entry') or ''), 'beads_bytes': 0,
                                            'dropped_residues': [], 'protein_input': 'protein.pdb',
                                            'command': None, 'secondary_structure': None})


def refuses_at_template_load(tmp_path, monkeypatch):
    """The loader's own `missing template topology` -- a template the build cannot read at all."""
    return preview(tmp_path, template=template(tmp_path, topology='absent.itp'), mapping=None, aggregation_number=12)


def refuses_at_template_validation(tmp_path, monkeypatch):
    """`validate_template`'s own sentence, before anything is placed."""
    return preview(tmp_path, template=template(tmp_path, beads=[]), mapping=None, aggregation_number=12)


def refuses_at_coarse_graining(tmp_path, monkeypatch):
    """A martinize2 that cannot run at all."""
    def broken(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(pdc_build.subprocess, 'run', broken)
    return preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=12)


def refuses_at_placement(tmp_path, monkeypatch):
    """The clearance gate's own sentence: a 3.2 nm shell no 3.0 nm sphere can clear."""
    monkeypatch.setattr(pdc_preview, 'coarse_grained', stubbed_cg(shell(3.2)))
    return preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=60)


def refuses_at_detergent_model(tmp_path, monkeypatch):
    """`stamp`'s own sentence: a mapping whose beads state no hydrophobic core cannot be oriented."""
    path = tmp_path / 'heads_only.json'
    path.write_text(json.dumps({'schema_version': 3, 'molecule_id': 'DDM', 'name': 'heads only',
                                'beads': [{'name': 'S1A', 'type': 'SP1r', 'size': 'S', 'atoms': [1]},
                                          {'name': 'S1B', 'type': 'SP1r', 'size': 'S', 'atoms': [2]}],
                                'connections': [['S1A', 'S1B']],
                                'provenance': {'origin': 'manual', 'algorithm': None, 'references': []},
                                'status': 'candidate-unvalidated', 'martini_version': '3'}))
    return preview(tmp_path, mapping=str(path), molecule_id='DDM', aggregation_number=12)


@pytest.mark.parametrize('at, expected_step', [(refuses_at_template_load, 'template'),
                                               (refuses_at_template_validation, 'template'),
                                               (refuses_at_coarse_graining, 'coarse-graining'),
                                               (refuses_at_placement, 'placement'),
                                               (refuses_at_detergent_model, 'detergent model')])
def test_a_refusal_carries_a_reason_and_names_the_step_that_refused(tmp_path, monkeypatch, at, expected_step):
    """Every gate a preview can be stopped by answers with a sentence and the step it belongs to.

    The sentence is the builder's own -- never one this service wrote for it -- and the step is what lets the panel
    say *where* the refusal came from when the sentence is all a reader gets. A refusal with neither is the state
    this file exists to make unreachable.
    """
    answer = at(tmp_path, monkeypatch)

    assert answer['valid'] is False and answer['pdb'] is None
    assert answer['step'] == expected_step, answer
    assert answer['reasons'] and all(str(reason).strip() for reason in answer['reasons']), answer['reasons']
    assert answer['basis']['beads'] is None, 'a refusal carries no coordinates and no bead count to read as one'


def test_a_gate_that_refuses_with_no_sentence_still_gets_one_naming_the_step(tmp_path, monkeypatch):
    """A sentence can come back empty -- an exception with no message, a gate with nothing to add.

    The panel's fallback for that used to be "the build gave no reason", which names nothing at all. The service
    answers with the step and the file it was working on instead, so the reader is told what refused even when the
    refuser said nothing.
    """
    beads = [{'residue_id': 1, 'residue': 'PRO', 'name': f'B{index:03d}', 'position': [float(index), 0.0, 0.0]}
             for index in range(1, 5)]
    monkeypatch.setattr(pdc_preview, 'coarse_grained', stubbed_cg(beads))
    monkeypatch.setattr(pdc_preview.pdc_placement, 'place_detergents',
                        lambda *args, **kwargs: {'centers': [], 'directions': [], 'mode': 'lattice',
                                                 'placement_shape': None, 'band': None, 'belt_reason': None,
                                                 'frame': None, 'aggregation_number': 12, 'radius_nm': 3.0,
                                                 'seed': 7, 'protein_free': False, 'protein_clearance_nm': None,
                                                 'issues': ['', None], 'valid': False})
    protein_path = protein(tmp_path)

    answer = preview(tmp_path, protein=str(protein_path), chains=['A'], mapping=None, aggregation_number=12)

    assert answer['valid'] is False and answer['step'] == 'placement'
    assert answer['reasons'] == [f'the placement step refused these inputs and named no reason '
                                 f'while working on {protein_path}']


def test_a_coarse_grained_protein_whose_beads_have_no_position_refuses_and_stays_readable(tmp_path, monkeypatch):
    """The user's own 4iar, as a fixture: a CG bead at `nan` must refuse, and the answer must still be JSON.

    martinize2 leaves a bead at `nan` where the structure holds no coordinates for the residue it averages; 4iar has
    20 of them. The placement cannot measure a clearance against such a bead, so it refuses with that count -- and
    the answer it hands the panel carries no `nan` number, which a browser's `JSON.parse` refuses outright (Python's
    `json.dumps` writes it by default, which is how this reached the panel as "the build gave no reason").
    """
    beads = [{'residue_id': 1, 'residue': 'PRO', 'name': f'B{index:03d}', 'position': [float(index), 0.0, 0.0]}
             for index in range(1, 5)]
    beads[1]['position'] = [float('nan'), float('nan'), float('nan')]
    monkeypatch.setattr(pdc_preview, 'coarse_grained', stubbed_cg(beads))

    answer = preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=12)

    assert answer['valid'] is False and answer['pdb'] is None and answer['step'] == 'placement'
    assert any('without a position' in reason for reason in answer['reasons']), answer['reasons']
    assert answer['basis']['clearance_nm'] is None and answer['basis']['box_nm'] is None
    assert strict_loads(json.dumps(answer))['step'] == 'placement', 'the answer a panel must be able to read'


def test_a_refusal_the_route_answers_with_is_always_json_a_browser_can_read(tmp_path, monkeypatch):
    """Every answer this service returns is JSON at a browser's strictness, refusal or picture.

    `json.dumps` writes a float `nan` as the bare token `NaN`, which `JSON.parse` rejects -- so an answer carrying
    one arrives at the panel as a parse failure, which is how a real refusal's own sentence was lost. No answer may
    carry one.
    """
    for answer in (preview(tmp_path, mapping=str(mapping(tmp_path)), molecule_id='DDM', aggregation_number=12),
                   refuses_at_coarse_graining(tmp_path, monkeypatch),
                   refuses_at_detergent_model(tmp_path, monkeypatch)):
        assert strict_loads(json.dumps(answer)) == json.loads(json.dumps(answer)), answer


def test_a_template_the_builders_validator_refuses_comes_back_as_its_own_reasons(tmp_path):
    """`registry.validate_template` stops the build before anything is placed; its sentence is the panel's sentence."""
    answer = preview(tmp_path, template=template(tmp_path, beads=[]), mapping=None, aggregation_number=12)

    assert answer['valid'] is False
    assert answer['pdb'] is None
    assert answer['reasons'] == ['template has no beads']
    assert not (tmp_path / 'cache').exists(), 'nothing is placed from a template that cannot build'
    assert answer['basis']['beads'] is None and answer['basis']['box_nm'] is None


def test_a_template_whose_file_is_missing_is_refused_with_the_loaders_sentence(tmp_path):
    """A template naming a file that is not there is the build's exit-2 case, not a crash and not a picture."""
    answer = preview(tmp_path, template=template(tmp_path, topology='absent.itp'), mapping=None,
                     aggregation_number=12)

    assert answer['valid'] is False and answer['pdb'] is None
    assert answer['reasons'] == ['missing template topology'], answer['reasons']


def test_a_placement_the_clearance_gate_refuses_returns_the_gates_own_sentence(tmp_path, monkeypatch):
    """The one refusal that reaches the panel with a real protein: the builder's clearance sentence, and no picture.

    The CG step is stubbed, because what is under test is the gate and what the service does with its answer. The
    protein is a 3.2 nm shell and the file states no membrane, so the placement is the sphere of the fixed 3.0 nm
    radius about the centroid -- the geometry that makes 1AT9's own file refuse at 0.174 nm when it carries no frame.
    """
    monkeypatch.setattr(pdc_preview, 'coarse_grained',
                        lambda *args, **kwargs: (shell(3.2), {'cached': False, 'seconds': 0.5, 'key': 'stub',
                                                              'path': str(tmp_path / 'entry'), 'beads_bytes': 0,
                                                              'dropped_residues': [], 'protein_input': 'protein.pdb',
                                                              'command': None, 'secondary_structure': None}))

    answer = preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=60)

    assert answer['valid'] is False and answer['pdb'] is None
    sentence = answer['reasons'][0]
    assert sentence.startswith('detergent too close to the protein:'), sentence
    assert sentence.endswith(f'< {pdc_placement.MIN_CLEARANCE_NM} nm'), sentence
    assert answer['basis']['clearance_nm'] is not None, 'the refusal carries the number it was refused for'
    assert answer['basis']['box_nm'] is None


def test_a_chain_the_protein_does_not_name_is_refused_before_anything_is_coarse_grained(tmp_path, monkeypatch):
    """A chain the file does not have is the adapter's own refusal, with the file's own list -- and no CG step."""
    calls = []

    def never(*args, **kwargs):
        calls.append(args)
        raise AssertionError('the CG step ran for a selection the file does not name')

    monkeypatch.setattr(pdc_preview, 'coarse_grained', never)

    with pytest.raises(ValueError, match='names no chain'):
        preview(tmp_path, protein=str(protein(tmp_path)), chains=['Z'], mapping=None, aggregation_number=12)
    assert calls == []


def test_a_mapping_of_another_molecule_is_refused_rather_than_drawn(tmp_path):
    """The picture is drawn from the mapping's own beads, so a form that pairs two molecules is a malformed question."""
    with pytest.raises(ValueError, match='is of Maltose, not of DDM'):
        preview(tmp_path, mapping=str(mapping(tmp_path, molecule_id='Maltose', name='maltose.json')),
                molecule_id='DDM', aggregation_number=12)


# --- the frame -------------------------------------------------------------------------------------------------

def test_the_same_seed_is_the_same_frame_and_a_different_seed_is_not(tmp_path):
    """Determinism is what the panel's sentence rests on: "this is the frame the run will build"."""
    common = {'mapping': str(mapping(tmp_path)), 'molecule_id': 'DDM', 'aggregation_number': 40}

    first = preview(tmp_path, seed=20261013, **common)
    again = preview(tmp_path, seed=20261013, **common)
    other = preview(tmp_path, seed=20261014, **common)

    assert first['pdb'] == again['pdb'], 'the same seed must rebuild the same coordinates, byte for byte'
    assert first['pdb'] != other['pdb'], 'a different seed must place differently'
    assert first['basis']['seed'] == 20261013 and other['basis']['seed'] == 20261014


def test_a_frame_with_a_mapping_carries_the_models_own_bonds_as_conect_records(tmp_path):
    """The bond guard's other half: the file states the bonds, so a viewer draws them and invents none."""
    mapping_path = mapping(tmp_path)
    answer = preview(tmp_path, mapping=str(mapping_path), molecule_id='DDM', aggregation_number=40)

    draft = detergent_cg.derive(mapping_path, MOLECULES, PROJECT_ROOT)
    model = pdc_view.read_moleculetype_text(draft['topology'])
    per_molecule = len(model['bonds']) + len(model['constraints'])
    assert per_molecule, 'the fixture mapping must have bonded terms for this test to say anything'

    assert answer['pdb'].count('\nCONECT') == 40 * per_molecule
    assert "BONDS ARE THE MODEL'S OWN, NOT GUESSED" in answer['pdb']
    assert 'NO BONDS RECORDED' not in answer['pdb']


def test_a_centres_only_build_says_so_and_carries_no_bonds(tmp_path):
    """No mapping is a real build (`pdc_build` writes one centre per molecule), and a dot has no bonds to draw."""
    answer = preview(tmp_path, mapping=None, aggregation_number=40)

    assert answer['valid'] and answer['basis']['detergent_representation'] == 'one centre per molecule'
    assert 'CONECT' not in answer['pdb']
    assert 'NO BONDS RECORDED' in answer['pdb'], 'the file says why there are none rather than leaving a viewer to guess'
    assert answer['basis']['beads'] == 40, 'one centre per molecule: the count is the molecule count'


def test_the_box_is_the_one_the_build_measures(tmp_path):
    """`pdc_box`'s own rule over the placed centres -- restated nowhere, or the two would drift apart."""
    answer = preview(tmp_path, mapping=None, aggregation_number=40, box_margin_nm=1.5, initial_z_nm=7.0)

    placement = pdc_placement.place_detergents(None, load_template(str(template(tmp_path))), 40, 20261013,
                                               radius_nm=pdc_placement.DEFAULT_RADIUS_NM, mode='lattice',
                                               margin_nm=1.5, initial_z_nm=7.0)
    initial = pdc_box.initial_box(placement['centers'], margin_nm=1.5, initial_z_nm=7.0)
    expected = pdc_box.extended_box(initial[:2], placement['centers'], margin_nm=1.5)

    assert answer['basis']['box_nm'] == expected
    assert answer['basis']['box_nm'][1] < answer['basis']['box_nm'][2], 'the box is not a cube by accident'


def test_the_preview_says_which_tool_it_would_have_to_run(tmp_path, monkeypatch):
    """Nothing is coarse-grained without a resolved tool: the service is handed one, and the cache key carries it."""
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_martinize2(calls))
    executable = tmp_path / 'martinize2'
    executable.write_text('#!/bin/sh\n')

    answer = preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=12,
                     executable=str(executable))

    assert calls and calls[0]['command'][0] == str(executable), (
        'the resolved tool is the command, not the bare name a stage relies on its own PATH for')
    assert answer['basis']['protein'] == 'protein', 'a resolution the caller made does not change what is drawn'
