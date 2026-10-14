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


# A HETATM record is not a protein residue, and martinize2 deletes the *whole molecule* for one it cannot place in
# its force field. Measured on 1AT9 (bacteriorhodopsin): the retinal (RET) is a HETATM of chain A -- the same chain
# as the protein -- so the filter used to hand it on and the CG step logged
# `Cannot recognize residue 'RET' ... Deleting the molecule.` and exited 1 with no topology at all.
LIGAND_IN_THE_CHAIN = ('ATOM      1  N   ALA A   1       1.000   2.000   3.000  1.00  0.00           N\n'
                       'HETATM    2  C1  RET A 249A      7.378  16.376   2.137  1.00 15.00           C\n'
                       'HETATM    3  O   HOH A 500       1.000   2.000   3.000  1.00  0.00           O\n')


def test_the_filter_drops_a_heteroatom_that_travels_in_the_chosen_chain():
    """1AT9's retinal rides in the protein's own chain, which is why filtering by chain alone is not enough."""
    filtered = pdc_import.filter_chains(LIGAND_IN_THE_CHAIN, ['A'])

    assert 'ALA A' in filtered
    assert 'RET' not in filtered and 'HOH' not in filtered
    assert 'ATOM' in filtered and 'HETATM' not in filtered


def test_the_residues_the_filter_dropped_are_nameable_so_the_drop_is_not_silent():
    assert pdc_import.dropped_residues(LIGAND_IN_THE_CHAIN, ['A']) == ['HOH', 'RET']
    assert pdc_import.dropped_residues(LIGAND_IN_THE_CHAIN, ['B']) == [], \
        'nothing is dropped out of a chain the filter does not keep anyway'


# The stage reads the CG structure martinize2 writes with `-x`, which is a PDB: Angstroms, fixed columns, and the
# same `{'residue_id', 'residue', 'name', 'position'}` shape `pdc_view.read_gro` returns for GROMACS' own units.
CG_PDB = ('ATOM      1 BB   ALA A   1     -17.433  15.205  19.472  1.00  0.00\n'
          'ATOM      2 SC1  ALA A   1     -18.788  15.544  17.737  1.00  0.00\n'
          'CONECT    1    2\n'
          'END\n')


def test_the_structure_reader_returns_the_beads_in_nanometres(tmp_path):
    structure = tmp_path / 'protein_cg.pdb'
    structure.write_text(CG_PDB)

    atoms = pdc_import.structure_atoms(structure)

    assert [atom['name'] for atom in atoms] == ['BB', 'SC1']
    assert [atom['residue'] for atom in atoms] == ['ALA', 'ALA']
    assert [atom['residue_id'] for atom in atoms] == [1, 1]
    assert atoms[0]['position'] == pytest.approx([-1.7433, 1.5205, 1.9472]), \
        'a PDB writes Angstroms, every builder here nanometres'


def test_a_file_that_holds_no_coordinate_records_is_refused_rather_than_read_as_empty(tmp_path):
    """An empty structure is the shape of the defect this stage already had: a step that found nothing to read."""
    empty = tmp_path / 'empty.pdb'
    empty.write_text('REMARK nothing here\nEND\n')

    with pytest.raises(ValueError, match='no coordinate'):
        pdc_import.structure_atoms(empty)
