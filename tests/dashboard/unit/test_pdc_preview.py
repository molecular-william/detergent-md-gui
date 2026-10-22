"""The system preview: the frame a protein-detergent build would write, and what it says when it cannot.

The claims this file pins are the plan's, and none of them is a claim about a drawing:

* the preview is the build's own placement step and not an illustration of one -- the functions the stage calls, in
  the order it calls them;
* the expensive half is martinize2, and it is *cached*, so a re-derive of the count, the style or the seed is
  milliseconds and does not pay it again;
* the frame is deterministic in the seed, which is what lets the panel say "this is the frame the run will build"
  rather than "this is roughly what it might look like";
* a refusal is the builder's own sentence with no coordinates at all -- never a picture of a system the build would
  refuse, and never a blank;
* the protein's **secondary structure**, which martinize2 was coarse-grained with, travels in the basis keyed by the
  residue number the frame gives each residue -- the letters, the three classes they sort into and their counts -- and
  a residue the frame cannot give one class to is left unstated rather than guessed into one.

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
from dashboard.execution.adapters import pdc_box, pdc_placement, pdc_preparation, pdc_view
from dashboard.execution.scripts import pdc_build
from dashboard.models.bonded import parameterization
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


def stubbed_cg(beads, secondary=None):
    """A `coarse_grained` that answers with `beads`, so a test can hand the placement the protein it needs.

    `secondary` is the assignment that step would report (`pdc_build.secondary_structure`'s own record), because the
    basis now carries it: a stub that says nothing about it is a build on which no secondary structure was assigned.
    """
    return lambda *args, **kwargs: (beads, {'cached': False, 'seconds': 0.5, 'key': 'stub',
                                            'path': str(kwargs.get('entry') or ''), 'beads_bytes': 0,
                                            'dropped_residues': [], 'protein_input': 'protein.pdb',
                                            'command': None, 'secondary_structure': secondary})


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


# --- the terms the picture's bonds are -------------------------------------------------------------------------
#
# A fitted mapping is simulated on its fit's bonded terms, and `pdc.prepare` adopted that topology while this preview
# still drew `detergent_cg.derive`'s -- so the card, which says the bonds are the model's own, showed a bond set the
# run would never simulate. Positions are identical either way (the fit decides the terms, the mapping decides where
# the beads are), which is why nothing else in the frame moves and only the bonds can disagree. What these two tests
# pin is that the frame's CONECT records are the fit's own when the mapping carries one, that they are the
# derivation's when it does not, and that the basis says which of the two the reader is looking at.

#: What a fit of the fixture mapping writes: `ff_inter`'s export names (`B01`..`B04`), one bond the derivation does
#: not carry -- `TAIL1`-`S1A`, where the derivation bonds `TAIL1`-`TAIL2` and `TAIL2`-`S1A` -- and a ring constraint to
#: the virtual site the derivation bonds nothing to. Same term count as the derivation, different pairs, so a frame
#: that merely counted its bonds could not pass.
FITTED = """; This file was generated using the following command:
; ff_inter -f ../2_mapping/mapped.xtc -s ../2_mapping/mapped.gro -i DDM_initial.itp

[ moleculetype ]
DDM 1

[ atoms ]
 1 C1   1 DDM B01 1 0.0 72.0
 2 C1   1 DDM B02 2 0.0 72.0
 3 SP1r 1 DDM B03 3 0.0 54.0
 4 TC4  1 DDM B04 4 0.0  0.0

[ bonds ]
 1  3 1 0.9 100.0 ; B01_B03

[ constraints ]
 3  4 1 0.32

[ virtual_sitesn ]
 4 1 2 3
"""

#: A revision as the fit records one: the engine, its ITP, the options it fitted under and the AA reference.
FIT_REVISION = {'engine': 'fast-forward', 'topology': FITTED,
                'options': {'constraints_threshold': 10000.0, 'temperature_k': 300.0,
                            'torsion_model': 'legacy', 'torsion_scale': 1.0},
                'ensemble': {'frames': 20001, 'trajectory': '2_mapping/mapped.xtc',
                             'source': 'the mapped AA frames of the linked reference'},
                'aa_reference': {'run_id': 'dbc366ae772b'}}


def fit(mapping_path):
    """Store the fixture mapping's fit the way the panel's own fit does, and answer what a preview may read back."""
    return parameterization.save(json.loads(Path(mapping_path).read_text()), FIT_REVISION)


def conect_pairs(pdb):
    """The `CONECT` pairs a frame declares, as the bead serials the file itself writes."""
    return [(int(line[6:11]), int(line[11:16])) for line in pdb.splitlines() if line.startswith('CONECT')]


def molecule_pairs(pdb, beads=len(BEADS)):
    """Those pairs by position within the molecule, so every copy of the detergent reads the same."""
    return [((first - 1) % beads + 1, (second - 1) % beads + 1) for first, second in conect_pairs(pdb)]


def test_a_fitted_mapping_is_drawn_with_the_fits_bonds(tmp_path):
    """The frame draws the fit's bond set, under the mapping's bead names, and the basis names the parameterization.

    The fit's topology is deliberately different from the derivation's: `TAIL1`-`S1A` is not a pair the derivation
    bonds, and `TAIL2`-`S1A` is not a pair the fit carries. A frame that drew the derivation here would show the
    card's "bonds are the model's own" saying something false about the run behind it.
    """
    mapping_path = mapping(tmp_path)
    revision = fit(mapping_path)

    answer = preview(tmp_path, mapping=str(mapping_path), molecule_id='DDM', aggregation_number=40)

    assert answer['valid'], answer['reasons']
    per_molecule = molecule_pairs(answer['pdb'])
    assert set(per_molecule) == {(1, 3), (3, 4)}, 'the fit bond and its ring constraint, not the derivation pairs'
    assert len(per_molecule) == 40 * 2, 'one bond and one constraint per detergent molecule'
    # The derivation's own pairs are the ones a preview that still derived would have drawn.
    assert (1, 2) not in set(per_molecule) and (2, 3) not in set(per_molecule)
    # And the atoms are the mapping's names, adopted from `ff_inter`'s export names -- what `grompp` matches the
    # stamped coordinates by, and what makes these bonds this molecule's. The name column is four characters, so the
    # two tail beads both read `TAIL` here; what the rows show is that the fit's `B01`..`B04` are not what got drawn.
    names = [line[12:16].strip() for line in answer['pdb'].splitlines()
             if line.startswith('HETATM') and line[17:20].strip() == 'DET']
    assert names[:len(BEADS)] == [str(bead['name'])[:4] for bead in BEADS], names[:len(BEADS)]
    assert "BONDS ARE THE MODEL'S OWN, NOT GUESSED: 1 [ bonds ] + 1 [ constraints ]" in answer['pdb']
    assert answer['basis']['detergent_terms'] == {'source': "the mapping's current parameterization", 'terms': 2,
                                                  'revision': revision['revision']}


def test_a_mapping_with_no_parameterization_is_drawn_from_its_derivation_and_says_so(tmp_path):
    """Nothing was fitted, so the derivation's bonds are the run's -- and the basis says which terms they are."""
    mapping_path = mapping(tmp_path)

    answer = preview(tmp_path, mapping=str(mapping_path), molecule_id='DDM', aggregation_number=40)

    draft = detergent_cg.derive(mapping_path, MOLECULES, PROJECT_ROOT)
    model = pdc_view.read_moleculetype_text(draft['topology'])
    drawn = set(molecule_pairs(answer['pdb']))
    assert drawn == {tuple(pair) for pair in (*model['bonds'], *model['constraints'])}, 'the derivation pairs'
    assert answer['basis']['detergent_terms'] == {
        'source': (f"the mapping's derived topology: {draft['reference_terms']} reference terms, "
                   f"{draft['fallback_terms']} fallbacks"),
        'terms': draft['terms'], 'revision': None}


def test_a_centres_only_build_attributes_no_bonds_to_any_model(tmp_path):
    """One centre per molecule draws nothing to attribute, so the basis states no term source at all."""
    answer = preview(tmp_path, mapping=None, aggregation_number=40)

    assert answer['valid'] and answer['basis']['detergent_terms'] is None


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


# --- the secondary structure the assignment carries ------------------------------------------------------------
#
# The assignment was computed and then dropped: `pdc_build.secondary_structure` hands martinize2 the letters, the CG
# beads are built from them, and every protein bead came back `family not stated` on the card. What these tests pin is
# that the letters reach the basis *keyed by the residue number the frame itself gives each residue* -- the number a
# viewer selects on -- together with the three classes they sort into and their counts, and that a residue the frame
# cannot give one class to is left unstated rather than guessed into one.

#: Eight residues as martinize2 writes them: a backbone bead and one side-chain bead each, in bead order. The
#: residue names are the amino acids of the tool's own file -- the frame below renames them all `PRO`, so they are
#: here to make the fixture the shape a real coarse-grained protein has, not to be read back.
RESIDUES = ['ALA', 'GLY', 'SER', 'THR', 'VAL', 'LEU', 'ILE', 'PHE']


def cg_residues(names, *, ids=None, backbone='BB') -> list[dict]:
    """A coarse-grained protein's beads, one residue group after another: a backbone bead, then one side chain."""
    beads = []
    for index, name in enumerate(names, 1):
        residue_id = index if ids is None else ids[index - 1]
        beads.append({'residue_id': residue_id, 'residue': name, 'name': backbone,
                      'position': [0.4 * index, 0.0, 0.0]})
        beads.append({'residue_id': residue_id, 'residue': name, 'name': 'SC1',
                      'position': [0.4 * index, 0.35, 0.0]})
    return beads


def assignment(letters, *, source=pdc_build.SS_SOURCE):
    """`pdc_build.secondary_structure`'s record, for letters a test plants."""
    return {'source': source, 'route': '-dssp', 'residues': len(letters), 'letters': letters,
            **pdc_build.martini_classes(letters)}


def assigned_preview(tmp_path, monkeypatch, record, beads=None):
    """A preview whose coarse-graining is stubbed with `beads` and the assignment `record`."""
    beads = cg_residues(RESIDUES) if beads is None else beads
    monkeypatch.setattr(pdc_preview, 'coarse_grained', stubbed_cg(beads, record))
    return preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=12)


def test_the_basis_carries_the_assignment_keyed_the_way_the_frame_names_its_residues(tmp_path, monkeypatch):
    """The letters, the classes and the counts travel with the frame -- keyed by its own residue numbers.

    The letters are planted (`H H G I E B C S`, so every class is in play), and the keys are read back out of the
    frame the service returns rather than taken on trust: the backbone beads the file holds at residue 1..8 are the
    residues the assignment is keyed for, which is what makes the payload usable as a selection.
    """
    answer = assigned_preview(tmp_path, monkeypatch, assignment('HHGIEBCS'))

    assert answer['valid'], answer['reasons']
    secondary = answer['basis']['secondary_structure']
    assert secondary['source'] == pdc_build.SS_SOURCE and secondary['route'] == '-dssp'
    assert secondary['detail'] is None
    assert secondary['residues'] == 8 and secondary['protein_residues'] == 8

    # The frame's own residue numbers, read from the file: every backbone bead is a `PRO` residue's `BB` atom, one
    # per residue, and there are exactly as many as the assignment has letters.
    frame = [line for line in answer['pdb'].splitlines() if line.startswith('HETATM')]
    backbone = {int(line[22:26]): line[12:16].strip() for line in frame if line[17:20].strip() == 'PRO'
                and line[12:16].strip() == 'BB'}
    assert sorted(backbone) == list(range(1, 9)), backbone
    assert sorted(secondary['classes']) == [str(number) for number in range(1, 9)]

    assert secondary['letters'] == {str(number): letter for number, letter in enumerate('HHGIEBCS', 1)}
    # One table, applied: `H G I` helix, `E B` sheet, everything else -- `C` and `S` here -- coil.
    assert secondary['classes'] == {'1': 'helix', '2': 'helix', '3': 'helix', '4': 'helix',
                                    '5': 'sheet', '6': 'sheet', '7': 'coil', '8': 'coil'}
    # Counted from the letters, so the three add up to the assignment rather than to what could be drawn.
    assert secondary['summary'] == {'helix': 4, 'sheet': 2, 'coil': 2}
    assert sum(secondary['summary'].values()) == 8


def test_a_residue_number_two_chains_share_is_left_unstated_when_their_classes_differ(tmp_path, monkeypatch):
    """The one case this writer makes: `(name, residue_id)` names a residue, so two chains' `LEU 19` collide.

    A frame residue number that holds a helix and a coil cannot be coloured: one colour there would claim a structure
    one of the two beads does not have. The number is `null` in both the letters and the classes -- drawn in its
    family colour by the panel -- while the summary still counts both letters, because it is a statement about the
    protein's assignment rather than about what could be drawn.
    """
    beads = cg_residues(['LEU', 'ALA', 'LEU'], ids=[19, 20, 19])
    answer = assigned_preview(tmp_path, monkeypatch, assignment('HHC'), beads=beads)

    assert answer['valid'], answer['reasons']
    secondary = answer['basis']['secondary_structure']
    assert secondary['protein_residues'] == 3, 'each residue group is its own occurrence, collisions included'
    assert secondary['classes'] == {'1': None, '2': 'helix'}, secondary['classes']
    assert secondary['letters'] == {'1': None, '2': 'H'}, secondary['letters']
    assert secondary['summary'] == {'helix': 2, 'sheet': 0, 'coil': 1}

    # And the frame agrees: both `LEU 19` groups really do carry residue number 1, which is why they share one.
    numbers = [int(line[22:26]) for line in answer['pdb'].splitlines()
               if line.startswith('HETATM') and line[12:16].strip() == 'BB']
    assert numbers == [1, 2, 1], numbers


def test_an_assignment_that_does_not_match_the_frame_is_refused_rather_than_shifted(tmp_path, monkeypatch):
    """Letters for a different number of residues cannot be keyed, and a guess is not an answer."""
    answer = assigned_preview(tmp_path, monkeypatch, assignment('HHEE'))

    assert answer['valid'], answer['reasons']
    secondary = answer['basis']['secondary_structure']
    assert secondary['classes'] == {} and secondary['letters'] == {} and secondary['summary'] is None
    assert '4 letters' in secondary['detail'] and '8 residues' in secondary['detail'], secondary['detail']


def test_a_protein_with_no_assignment_says_so_and_names_the_reason(tmp_path, monkeypatch):
    """martinize2's documented no-assignment case: the card is told why, rather than being handed empty keys."""
    record = {'source': None, 'detail': 'mdtraj is not importable: no module named mdtraj'}
    answer = assigned_preview(tmp_path, monkeypatch, record)

    assert answer['valid'], answer['reasons']
    secondary = answer['basis']['secondary_structure']
    assert secondary['source'] is None and secondary['classes'] == {} and secondary['summary'] is None
    assert secondary['detail'] == 'mdtraj is not importable: no module named mdtraj'


def test_a_refusal_carries_no_assignment_because_it_carries_no_frame(tmp_path, monkeypatch):
    """A refusal draws nothing, so it has no residues to give a class to -- and says that rather than naming one."""
    monkeypatch.setattr(pdc_preview, 'coarse_grained', stubbed_cg(shell(3.2), assignment('HH')))
    answer = preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=60)

    assert answer['valid'] is False and answer['pdb'] is None
    assert answer['basis']['secondary_structure'] is None


def test_a_build_with_no_protein_has_no_assignment_to_carry(tmp_path):
    """An empty micelle coarse-grains nothing, so there is no protein whose structure could be stated."""
    answer = preview(tmp_path, aggregation_number=40, mapping=None)

    assert answer['valid'] and answer['basis']['secondary_structure'] is None


def test_the_three_classes_are_martinize2s_own_partition():
    """The table cannot disagree with the tool's: vermouth's `SS_CG` sorts the same letters the same three ways.

    `pdc_build.martini_classes` counts with `SS_CG` -- what martinize2 runs over the letters before it builds
    anything -- so this is the one place the two spellings are compared: helix for `H G I`, `sheet` here for its
    `extended` (`E B`), and coil for the rest.
    """
    martini = {'helix': 'helix', 'extended': 'sheet', 'coil': 'coil'}
    for letter in sorted(pdc_build.DSSP_LETTERS):
        counts = pdc_build.martini_classes(letter)
        expected = next(martini[name] for name, count in counts.items() if count)
        assert pdc_preview.secondary_class(letter) == expected, letter
    # A letter outside either alphabet is a coil, not an exception: the table states a rule, not a lookup that fails.
    assert pdc_preview.secondary_class('-') == 'coil' and pdc_preview.secondary_class('') == 'coil'


def test_a_reused_cache_entry_keeps_the_assignment_martinize2_was_built_with(tmp_path, monkeypatch):
    """A warm derive must not lose the letters, and must not pay for them twice.

    `pdc_build.cg_protein` reports the assignment only when it *ran* martinize2: a re-used entry answers that the file
    was already there, which says nothing about the structure. The preview therefore assigns a re-used entry the same
    way it was assigned the first time and keeps the answer beside the beads -- so the second derive of the same
    protein answers with the same letters, from the entry's own record, without a second assignment.
    """
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_martinize2(calls))
    planted = assignment('H')

    def assign(structure, *args, **kwargs):
        calls.append(('assign', str(structure)))
        return planted

    monkeypatch.setattr(pdc_build, 'secondary_structure', assign)
    query = {'protein': str(protein(tmp_path)), 'chains': ['A'], 'mapping': None, 'aggregation_number': 12}

    cold = preview(tmp_path, **query)
    warm = preview(tmp_path, **query)

    assert cold['cost']['cg_cached'] is False and warm['cost']['cg_cached'] is True
    assignments = [call for call in calls if isinstance(call, tuple) and call[0] == 'assign']
    assert len(assignments) == 1, f'the assignment was paid for {len(assignments)} times'
    for answer in (cold, warm):
        secondary = answer['basis']['secondary_structure']
        assert secondary['letters'] == {'1': 'H'} and secondary['summary'] == {'helix': 1, 'sheet': 0, 'coil': 0}
    assert cold['basis']['secondary_structure'] == warm['basis']['secondary_structure']
    entry = tmp_path / 'cache' / cold['cost']['cg_key']
    assert (entry / pdc_preview.SECONDARY_RECORD).is_file(), 'the assignment is kept beside the beads it was made for'


# --- the all-atom structure the frame is a coarse-graining of --------------------------------------------------
#
# The picture had beads and no protein under them. What these tests pin is the *name* of the structure, not a
# drawing: the basis carries the cache entry the beads came from and the route that serves it -- and carries neither
# for a build with no protein -- and the route serves that entry's file, refuses a key that is not an entry name, and
# answers 404 for an entry the cache does not hold. The file itself is never inlined in the placement answer.

def test_a_protein_build_names_the_structure_its_beads_were_coarse_grained_from(tmp_path, monkeypatch):
    """The key is the entry the beads are in, and the URL is the route that serves it -- named, never built here.

    Read back out of the answer: `basis.protein_structure.key` is `cost.cg_key`, and the file the URL resolves to on
    this workspace's disk is the chain selection `pdc_build.select_protein` wrote for martinize2. That is the file the
    ribbon is drawn from, so it must be the one martinize2 was handed rather than the source the reader picked.
    """
    calls = []
    monkeypatch.setattr(pdc_build.subprocess, 'run', stubbed_martinize2(calls))

    answer = preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=12)

    assert answer['valid'], answer['reasons']
    structure = answer['basis']['protein_structure']
    assert structure['key'] == answer['cost']['cg_key'], structure
    assert structure['url'] == f'/api/pdc/preview/protein?key={answer["cost"]["cg_key"]}', structure
    assert answer['cost']['cg_key'] in structure['url']
    entry = tmp_path / 'cache' / structure['key']
    assert pdc_preview.protein_structure_path(entry) == entry / pdc_build.SELECTED_PROTEIN
    # The frame's own beads are not the all-atom structure: the answer carries a name for it, and no coordinates.
    assert 'CA ' in (entry / pdc_build.SELECTED_PROTEIN).read_text()
    assert ' CA ' not in answer['pdb'], 'the all-atom structure was inlined in the placement answer'


def test_an_empty_micelle_names_no_structure_because_it_coarse_grained_none(tmp_path):
    """No protein, no coarse-graining, no entry -- so nothing for a ribbon to be drawn from."""
    answer = preview(tmp_path, aggregation_number=40, mapping=None)

    assert answer['valid'] and answer['basis']['protein_beads'] == 0
    assert answer['basis']['protein_structure'] is None
    assert answer['cost']['cg_key'] is None


def test_a_refusal_names_no_structure_because_it_draws_nothing(tmp_path, monkeypatch):
    """A refusal is a sentence and no picture: it has no ribbon to put under coordinates it did not produce."""
    monkeypatch.setattr(pdc_preview, 'coarse_grained', stubbed_cg(shell(3.2), assignment('HH')))
    answer = preview(tmp_path, protein=str(protein(tmp_path)), chains=['A'], mapping=None, aggregation_number=60)

    assert answer['valid'] is False and answer['pdb'] is None
    assert answer['basis']['protein_structure'] is None


def test_a_prepared_entry_serves_the_prepared_structure_martinize2_read(tmp_path):
    """One rule for which file is the one the beads came from, and the prepared one wins when the entry holds it.

    `coarse_grained` hands martinize2 the prepared structure for a prepared derive, so that is the file the beads are
    in; the chain selection is the file for every other derive. A directory holding neither answers `None` rather
    than reading whatever the caller would have tried next.
    """
    entry = tmp_path / 'entry'
    entry.mkdir()
    assert pdc_preview.protein_structure_path(entry) is None

    (entry / pdc_build.SELECTED_PROTEIN).write_text('ATOM\n')
    assert pdc_preview.protein_structure_path(entry) == entry / pdc_build.SELECTED_PROTEIN
    assert pdc_preview.protein_structure_basis('0123456789abcdef', entry) is not None

    prepared = entry / pdc_preparation.PREPARED_NAME
    prepared.write_text('ATOM\n')
    assert pdc_preview.protein_structure_path(entry) == prepared
    # A key that is not an entry name names nothing, even when the directory is real: the function is the one the
    # route leans on for that, so it refuses it here too.
    for malformed in ('../../etc', '0123456789abcde', 'ABCDEF0123456789', '', None):
        assert pdc_preview.protein_structure_basis(malformed, entry) is None, malformed


# --- the route that serves it ----------------------------------------------------------------------------------
#
# The route is asked through the application, with the entry written into the test workspace's own preview cache --
# the same directory `pdc_preview.preview` writes to, so a key the placement named is a key this route answers for.

ENTRY_KEY = '0123456789abcdef'
ATOM_TEXT = ('ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n'
             'ATOM      2  CA  ALA A   1       0.145   0.000   0.000  1.00  0.00           C\nEND\n')


def planted_entry(dashboard, key=ENTRY_KEY, text=ATOM_TEXT, name=pdc_build.SELECTED_PROTEIN):
    """A cache entry in the test workspace holding `text` as `name`, and the key to ask for it with."""
    entry = dashboard.paths.workspace / pdc_preview.CACHE_DIRECTORY / key
    entry.mkdir(parents=True, exist_ok=True)
    (entry / name).write_text(text)
    return key


def test_the_protein_route_serves_the_cached_structure_it_was_asked_for(dashboard):
    """A valid key reads the entry's all-atom file, unchanged, as the text a viewer loads."""
    key = planted_entry(dashboard)

    response = dashboard.client.get(f'/api/pdc/preview/protein?key={key}')

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_data(as_text=True) == ATOM_TEXT
    assert response.mimetype == 'text/plain'


def test_the_protein_route_refuses_a_key_that_is_not_an_entry_name(dashboard):
    """Hex of the key's own length and nothing else -- which is also what keeps a key inside the cache root."""
    planted_entry(dashboard)
    outside = dashboard.paths.workspace / 'outside_the_cache.pdb'
    outside.write_text(ATOM_TEXT)

    for malformed in ('../../outside_the_cache.pdb', '..%2F..%2Foutside_the_cache.pdb', '/etc/passwd',
                      '0123456789abcde', '0123456789abcdef0', 'ABCDEF0123456789', '0123456789abcdeZ', '', ' '):
        response = dashboard.client.get('/api/pdc/preview/protein', query_string={'key': malformed})
        assert response.status_code == 400, f'{malformed!r} was not refused: {response.status_code}'
        assert 'key' in response.get_json()['error'], malformed
    # Nothing was served for any of them: the file outside the cache root is still outside it, unread.
    assert outside.is_file()


def test_the_protein_route_says_404_for_an_entry_the_cache_does_not_hold(dashboard):
    """A well-formed key with nothing behind it is a missing file, and the sentence names which."""
    dashboard.paths.workspace.mkdir(parents=True, exist_ok=True)
    missing = 'ffffffffffffffff'

    response = dashboard.client.get(f'/api/pdc/preview/protein?key={missing}')

    assert response.status_code == 404
    assert missing in response.get_json()['error'], response.get_json()


def test_the_protein_route_answers_404_for_an_entry_holding_no_structure(dashboard):
    """An entry exists and holds no all-atom file (it was pruned, or the derive wrote neither): still no picture."""
    entry = dashboard.paths.workspace / pdc_preview.CACHE_DIRECTORY / ENTRY_KEY
    entry.mkdir(parents=True)

    response = dashboard.client.get(f'/api/pdc/preview/protein?key={ENTRY_KEY}')

    assert response.status_code == 404
    assert ENTRY_KEY in response.get_json()['error']
