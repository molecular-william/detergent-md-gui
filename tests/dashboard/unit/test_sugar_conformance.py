"""Does a generated candidate reproduce the reference entry, and how far are the numbers?

Conformance covers the mapping: residues, bead letters and types, each ring's virtual site, and the
inter-residue links. The parameter delta covers the equilibrium numbers, which are derived here by the
paper's own method (mean heavy-atom COG distances scaled 1.15) from a different atomistic source, so they
are reported rather than copied.
"""
import copy
from pathlib import Path

import pytest

from dashboard import paths
from dashboard.models.mappings import context as mapping_context
from dashboard.models.sugars import candidate, reference
from dashboard.models.sugars.topology import topology

MOLECULES = Path(paths.DEFAULT.project_root) / 'molecules'


@pytest.fixture(scope='module')
def sucrose():
    return mapping_context.as_structure(mapping_context.build_context(MOLECULES, 'Sucrose'))


@pytest.fixture(scope='module')
def candidate_data(sucrose):
    return candidate(sucrose, 'Sucrose')


def test_the_sucrose_candidate_conforms_to_the_reference_entry(candidate_data):
    assert reference.conform(candidate_data, 'SUCR') == []


def test_a_removed_bead_is_reported_by_letter_and_residue(candidate_data):
    broken = copy.deepcopy(candidate_data)
    broken['beads'] = [bead for bead in broken['beads'] if bead['name'] != 'S2C']
    issues = reference.conform(broken, 'SUCR')
    assert issues and 'residue 2' in issues[0]


def test_a_changed_type_is_reported(candidate_data):
    broken = copy.deepcopy(candidate_data)
    next(bead for bead in broken['beads'] if bead['name'] == 'S2A')['type'] = 'SP4r'
    issues = reference.conform(broken, 'SUCR')
    assert any('SN6' in issue and 'SP4r' in issue for issue in issues), issues


def test_a_moved_linkage_is_reported(candidate_data):
    broken = copy.deepcopy(candidate_data)
    broken['connections'] = [[edge[0], edge[1]] for edge in broken['connections']
                             if {edge[0], edge[1]} != {'S1A', 'S2A'}]
    broken['connections'].append(['S1B', 'S2A'])
    issues = reference.conform(broken, 'SUCR')
    assert any('link' in issue for issue in issues), issues


def test_a_site_built_from_the_wrong_beads_is_reported(candidate_data):
    broken = copy.deepcopy(candidate_data)
    site = next(bead for bead in broken['beads'] if bead['name'] == 'S2VS')
    site['virtual_site'] = {'parents': ['S1A', 'S1B', 'S1C'], 'function': 1}
    issues = reference.conform(broken, 'SUCR')
    assert any('ring site' in issue for issue in issues), issues


def test_the_parameter_delta_reports_every_reference_constraint(candidate_data, sucrose):
    rows = reference.parameter_delta(topology(candidate_data, sucrose, residue_name='SUCR'), 'SUCR')
    assert [(row['residue'], row['pair']) for row in rows] == [
        (1, ['A', 'B']), (1, ['A', 'C']), (1, ['B', 'C']),
        (2, ['A', 'B']), (2, ['A', 'C']), (2, ['B', 'C']),
        ('link', ['A', 'A'])]
    assert all(row['generated'] is not None for row in rows)


def test_the_generated_constraints_agree_with_the_published_ones_to_about_a_fifth(candidate_data, sucrose):
    """Measured: the same method from a different atomistic source lands within about 15% here."""
    rows = reference.parameter_delta(topology(candidate_data, sucrose, residue_name='SUCR'), 'SUCR')
    assert max(abs(row['relative']) for row in rows) < 0.20
    assert min(row['generated'] for row in rows) > 0.25, \
        'a factor-of-ten unit error looks like this: see test_sugar_reference_units.py'
