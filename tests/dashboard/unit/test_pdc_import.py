"""Importing an OPM structure: the file, what it says about itself, and what the import records beside it.

Every fetch below is injected. A test that reaches the network tests the network, and this repository's rule is
that a run records what it used and works again offline -- so the one real download lives in the plan's last phase,
done by hand, not here.
"""
import hashlib
import json

import pytest

from dashboard.execution.adapters import pdc_import

# The head of a real OPM download (1qj8, OmpX). The statement travels with the coordinates, which is why the import
# reads the file and not the entry page.
OPM_HEADER = ('REMARK      1/2 of bilayer thickness:   11.8                                    \n'
              'ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N\n')


def test_the_half_thickness_is_read_out_of_the_files_own_remark():
    assert pdc_import.membrane_statement(OPM_HEADER) == {'half_thickness_nm': 1.18}


def test_a_structure_that_states_nothing_returns_nothing_rather_than_a_default():
    """The defect this replaces was a silent 1.0 nm: an unstated membrane must stay unstated."""
    assert pdc_import.membrane_statement('ATOM      1  N   ALA A   1       1.000   2.000   3.000\n') is None


def test_another_remark_is_not_mistaken_for_a_membrane_statement():
    """Our own system PDBs carry `REMARK 950`; a reader that matched any REMARK would invent a membrane."""
    assert pdc_import.membrane_statement('REMARK 950 COARSE-GRAINED SYSTEM AS SET UP\n') is None


def test_the_import_writes_the_structure_and_a_sidecar_that_says_where_it_came_from(tmp_path):
    calls = []

    def fetcher(url):
        calls.append(url)
        return OPM_HEADER.encode()

    record = pdc_import.import_structure('1qj8', tmp_path, fetcher=fetcher,
                                         fetched_at='2026-10-05T18:00:00+00:00')

    # The asset host, not the site: opm.phar.umich.edu answers every path with its React shell.
    assert calls == ['https://biomembhub.org/shared/opm-assets/pdb/1qj8.pdb']
    written = (tmp_path / '1qj8.pdb').read_bytes()
    assert written == OPM_HEADER.encode()
    assert record['pdbid'] == '1qj8'
    assert record['half_thickness_nm'] == 1.18
    assert record['sha256'] == hashlib.sha256(written).hexdigest()
    assert record['bytes'] == len(written)
    assert record['fetched_at'] == '2026-10-05T18:00:00+00:00'
    assert json.loads((tmp_path / '1qj8.json').read_text()) == record


def test_the_id_becomes_a_file_name_so_it_is_validated_before_anything_is_written(tmp_path):
    for bad in ('../../etc/passwd', '1qj8.pdb', '1qj', '1qj88', ''):
        with pytest.raises(ValueError, match='four'):
            pdc_import.import_structure(bad, tmp_path, fetcher=lambda url: b'')
    assert list(tmp_path.iterdir()) == []


def test_a_fetch_that_failed_leaves_no_structure_and_no_sidecar(tmp_path):
    """A sidecar is a claim that a file is there, so it is written only after the file is."""
    def broken(url):
        raise OSError('connection reset by peer')

    with pytest.raises(OSError):
        pdc_import.import_structure('1qj8', tmp_path, fetcher=broken)
    assert list(tmp_path.iterdir()) == []


# The chain list is read where the half-thickness is: the file's own text. An assembly deposits its subunits in
# named chains, so the ids travel with the coordinates and the import records them beside the thickness it stated.

MULTICHAIN = ('REMARK      1/2 of bilayer thickness:   11.8\n'
              'ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N\n'
              'ATOM      2  N   ALA B   1       1.000   2.000   3.000  1.00  0.00           N\n'
              'HETATM    3  O   HOH C   1       1.000   2.000   3.000  1.00  0.00           O\n')


def test_the_structures_chains_are_read_out_of_its_own_coordinate_records():
    """Both record types carry a chain, so a ligand in its own chain is listed too -- and is selectable with it."""
    assert pdc_import.structure_chains(MULTICHAIN) == ['A', 'B', 'C']


def test_a_structure_that_names_no_chain_says_so_rather_than_guessing_one():
    """A blank chain column is a real answer, not a defect to paper over with an invented 'A'."""
    blank = 'ATOM      1  N   ALA     1       1.000   2.000   3.000\n'

    assert pdc_import.structure_chains(blank) == []


def test_the_import_records_the_chain_list_beside_the_half_thickness(tmp_path):
    record = pdc_import.import_structure('1qj8', tmp_path, fetcher=lambda url: MULTICHAIN.encode(),
                                         fetched_at='2026-10-05T18:00:00+00:00')

    assert record['chains'] == ['A', 'B', 'C']
    assert record['half_thickness_nm'] == 1.18, 'the two statements come from one read of the file'
    assert json.loads((tmp_path / '1qj8.json').read_text())['chains'] == ['A', 'B', 'C']


def test_the_filter_keeps_the_chosen_chains_and_the_files_own_statements():
    """What the build points martinize2 at: the chosen chains' records, and every non-coordinate line kept."""
    filtered = pdc_import.filter_chains(MULTICHAIN, ['A'])

    assert pdc_import.structure_chains(filtered) == ['A']
    assert 'REMARK      1/2 of bilayer thickness' in filtered, 'the header a reader needs survives the filter'
    assert 'ALA B' not in filtered and 'HOH C' not in filtered
