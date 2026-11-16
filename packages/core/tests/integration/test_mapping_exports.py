"""Checks against CGbuilder/FF formats, RDKit chemistry, and real grompp."""
import importlib.util

import numpy as np
import pytest
from dashboard.models import mappings

from tests.harness.support import fast_forward_source, physical_mapping


def test_fast_forward_parser_reads_names_and_order():
    data = physical_mapping()
    path = fast_forward_source('map_file_parers.py')
    if path is None:
        pytest.skip('Fast_Forward source is not provisioned in this checkout')
    spec = importlib.util.spec_from_file_location('ff_mapping_reader', path)
    reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)
    files = mappings.export_files(data)
    parsed = reader.read_mapping(files['mapping.map'].splitlines())[-1]['LIG1']
    assert parsed.to_resname == 'DDM'
    assert parsed.beads == [f'B{i+1:02d}' for i in range(len(data['beads']))]
    atoms = {a['id']: a for a in mappings.molecule()['atoms']}
    for alias, bead in zip(parsed.beads, data['beads']):
        assert parsed.bead_to_atom[alias] == [atoms[i]['name'] for i in sorted(bead['atoms'])]
        assert all(weight == 1 for weight in parsed.atom_weights[alias])


def test_index_and_coordinates_match_same_assignments():
    data = physical_mapping()
    files = mappings.export_files(data)
    sections = files['mapping.ndx'].strip().split('\n\n')
    xyz = {a['id']: a['xyz'] for a in mappings.molecule()['atoms']}
    lines = files['mapped.gro'].splitlines()
    assert int(lines[1]) == len(data['beads'])
    for i, bead in enumerate(data['beads']):
        assert list(map(int, sections[i].splitlines()[1].split())) == sorted(bead['atoms'])
        assert lines[i+2][10:15].strip() == f'B{i+1:02d}'
        expected = np.mean([xyz[a] for a in bead['atoms']], axis=0)/10
        actual = [float(lines[i+2][start:start+8]) for start in (20, 28, 36)]
        np.testing.assert_allclose(actual, expected, atol=.00051)


def test_export_rejects_missing_or_duplicate_atoms():
    data = physical_mapping()
    data['beads'][0]['atoms'].pop()
    with pytest.raises(ValueError, match='Missing heavy atoms'):
        mappings.export_files(data)
    data['beads'][0]['atoms'].append(data['beads'][1]['atoms'][0])
    with pytest.raises(ValueError, match='Repeated atom'):
        mappings.export_files(data)
