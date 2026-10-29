"""The ring distance scale: the number a mapping states, and the constraint it produces.

A coarse-grained run's ring constraint is the mapped trajectory's own mean distance times the ring's scale --
measured on run `1322f9e0782e`, 0.31020506722186164 x 1.15 = 0.35673582730514086. Until now the scale was 1.15
and nothing else: `mappings/schema.py` refused any other number, so the two arms of the ring experiment could not
be built from the same mapping. What changes here is only who decides: a mapping states the scale its own rings
were built with, the paper's 1.15 stays what the recogniser writes and what everything defaults to, and a value
outside the admissible range is still refused.
"""
import json
from pathlib import Path

import pytest

from dashboard.models import mappings
from dashboard.models.mappings import schema
from dashboard.models.molecules import detergent_cg
from dashboard.models.sugars import validation

MOLECULE_ROOT = Path(__file__).resolve().parents[3] / 'molecules'

BEADS = [{'name': 'A', 'type': 'SP1r', 'size': 'S', 'atoms': [1, 2, 3, 4]},
         {'name': 'B', 'type': 'SP1r', 'size': 'S', 'atoms': [5, 6, 7, 8]},
         {'name': 'C', 'type': 'SP1r', 'size': 'S', 'atoms': [9, 10, 11, 12]},
         {'name': 'VS', 'type': 'TC4', 'size': 'T', 'atoms': [],
          'virtual_site': {'function': 1, 'parents': ['A', 'B', 'C']}}]


def document(scale):
    """One ring of three beads, at a stated scale."""
    return {'schema_version': 3, 'molecule_id': 'DDM', 'name': 'ring scale',
            'beads': BEADS, 'connections': [['A', 'B'], ['A', 'C'], ['B', 'C']],
            'rings': [{'beads': ['A', 'B', 'C'], 'virtual_site': 'VS', 'scale': scale}]}


def constraint_lengths(topology):
    """The `[ constraints ]` rows of a generated topology, keyed by the bead pair."""
    rows, section = {}, ''
    for line in topology.splitlines():
        raw = line.split(';')[0].strip()
        if raw.startswith('['):
            section = raw.strip('[] ')
        elif raw and section == 'constraints':
            fields = raw.split()
            rows[tuple(sorted((int(fields[0]), int(fields[1]))))] = float(fields[3])
    return rows


@pytest.mark.parametrize('scale', [0.0, 0.2, 2.5, -1.0, 'wide', None])
def test_a_scale_outside_the_admissible_range_is_refused_with_the_range(scale):
    with pytest.raises(ValueError, match='scale'):
        schema.check_schema(document(scale))


def test_the_constraint_is_the_mappings_own_measured_distance_times_its_scale(tmp_path):
    """The load-bearing one: the scale in the mapping is the constraint the run will simulate with.

    1.0 holds the geometry the atoms have; 1.15 holds it 15% wider. That is the only difference between the
    two arms, so it has to be the only difference in the generated topology too.
    """
    generated = {}
    for scale in (1.0, 1.15):
        path = tmp_path / f'candidate_{scale}.json'
        path.write_text(json.dumps(document(scale)))
        generated[scale] = constraint_lengths(detergent_cg.derive(path, MOLECULE_ROOT, MOLECULE_ROOT.parent)['topology'])

    assert set(generated[1.0]) == set(generated[1.15]) == {(1, 2), (1, 3), (2, 3)}, 'three ring pairs, both arms'
    for pair, measured in generated[1.0].items():
        assert measured > 0
        assert generated[1.15][pair] == pytest.approx(measured * 1.15, rel=1e-9), pair


def test_the_validation_representation_accepts_the_stated_scale():
    """`sugars/validation.py` guards the same rule for the carbohydrate-validation route; one rule, not two."""
    validation.validate_representation(document(1.0), validation.TC4)
    validation.validate_representation(document(1.15), validation.TC4)
    with pytest.raises(ValueError, match='scale'):
        validation.validate_representation(document(3.0), validation.TC4)


def test_the_recogniser_still_writes_the_paper_scale():
    """Nothing about the default moves: a candidate the recogniser builds is still a 1.15 candidate."""
    candidate = mappings.automatic_candidate(mappings.molecule(), 'DDM')

    assert candidate['rings'], 'this molecule has rings to check'
    assert {ring['scale'] for ring in candidate['rings']} == {1.15}
