"""The PDB the composition panel hands to a molecular viewer is well formed, and says what it is.

A viewer is unforgiving about columns and silent about nonsense, so these tests parse the file the way a
viewer does -- fixed slices -- and check the two claims the file makes: one pseudo-atom per bead in
Angstrom, and an element that is a radius stand-in rather than a chemistry statement.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# `compositions` is a `dashboard` subpackage -- it imports through `from ... import`.
from dashboard.models.compositions.topology import (  # noqa: E402
    preview_geometry,
    render_pdb,
    tail_recipe_catalog,
)


def _preview():
    """Three head beads (size S) and a two-bead tail (mass 54 -> size R), joined by one link bond."""
    tail = {"id": "test", "recipe_id": tail_recipe_catalog()[0]["id"], "carbon_count": 2,
            "beads": [{"name": "C01", "type": "C1", "mass": 54.0}, {"name": "C02", "type": "C1", "mass": 54.0}],
            "coordinates": [[0.0, 0.0, 0.0], [0.47, 0.0, 0.0]]}
    mapping = {"beads": [{"name": "A", "type": "SP1", "size": "S"}, {"name": "B", "type": "SP1", "size": "S"},
                         {"name": "C", "type": "SP1", "size": "S"}, {"name": "C01", "type": "C1", "size": "S"},
                         {"name": "C02", "type": "C1", "size": "S"}]}
    topology = {"bonds": [{"a": "A", "b": "B", "function": 1}, {"a": "B", "b": "C", "function": 1},
                          {"a": "A", "b": "C01", "function": 1}, {"a": "C01", "b": "C02", "function": 1}]}
    return {"tail": tail, "mapping": mapping, "topology": topology}


def _records(pdb):
    return [line for line in pdb.splitlines() if line.startswith("HETATM")]


def test_every_bead_becomes_one_atom_in_angstrom():
    geometry = preview_geometry(_preview())
    records = _records(render_pdb(_preview()))
    assert len(records) == len(geometry["joined"]["beads"]) == 5
    for record, bead in zip(records, geometry["joined"]["beads"]):
        # Slices, exactly as a viewer reads them.
        assert record[12:16].strip() == bead["name"]
        for column, offset in ((30, 0), (38, 1), (46, 2)):
            assert abs(float(record[column:column + 8]) - bead["position"][offset] * 10.0) < 1e-6


def test_the_records_stay_in_the_plane_the_layout_promised():
    for record in _records(render_pdb(_preview())):
        assert float(record[46:54]) == 0.0, record


def test_the_element_is_a_radius_stand_in_and_never_a_virtual_site():
    records = _records(render_pdb(_preview()))
    elements = {record[12:16].strip(): record[76:78].strip() for record in records}
    assert elements["A"] == "N", elements  # head beads are size S
    assert elements["C01"] == "C", elements  # a mass-54 tail bead is size R
    assert "VS" not in elements
    assert all(value in {"C", "N", "O"} for value in elements.values()), elements


def test_the_bonds_are_written_once_each_and_reference_real_serials():
    records = _records(render_pdb(_preview()))
    serials = {record[12:16].strip(): int(record[6:11]) for record in records}
    conect = [line for line in render_pdb(_preview()).splitlines() if line.startswith("CONECT")]
    pairs = [(int(line[6:11]), int(line[11:16])) for line in conect]
    assert len(pairs) == len(set(pairs)) == 4, pairs  # the link is in the edge list already; no duplicate
    assert {serials["A"], serials["C01"]} in [set(pair) for pair in pairs]
    assert all(first in serials.values() and second in serials.values() for first, second in pairs)


def test_the_records_place_the_residue_and_chain_in_their_columns():
    """The fragment selection depends on this: read one character off and SUG matches nothing.

    Columns are the PDB's, 1-based: name 13-16, altLoc 17, resName 18-20, iCode 21, chainID 22, resSeq 23-26.
    A viewer that misreads the residue name silently ignores the selection built from it, which is how a
    one-character slip turned the head panel into the whole molecule.
    """
    records = _records(render_pdb(_preview()))
    residues = {}
    for record in records:
        assert record[16] == ' ', f'altLoc must be blank: {record!r}'
        assert record[20] == ' ', f'iCode must be blank: {record!r}'
        assert record[21] == 'A', f'chainID: {record!r}'
        assert record[22:26].strip() == '1', f'resSeq: {record!r}'
        residues[record[12:16].strip()] = record[17:20].strip()
    assert residues['A'] == 'SUG' and residues['C01'] == 'TAI', residues


def test_the_file_is_terminated_and_holds_nothing_but_its_records():
    geometry = preview_geometry(_preview())
    pdb = render_pdb(_preview())
    assert pdb.endswith("END\n")
    assert all(line.startswith(("REMARK", "HETATM", "CONECT", "END")) for line in pdb.splitlines())
    # Two header remarks, plus a remark and an atom for each bead, the bonds, the terminator.
    assert len(pdb.splitlines()) == 2 + 2 * len(geometry["joined"]["beads"]) + 4 + 1


def test_every_bead_carries_its_type_in_a_remark():
    geometry = preview_geometry(_preview())
    beads = geometry["joined"]["beads"]
    remarks = {fields[3]: (fields[4], fields[5]) for fields in
               (line.split() for line in render_pdb(_preview()).splitlines() if line.startswith("REMARK 950 BEAD"))}
    assert len(remarks) == len(beads) == 5
    for bead in beads:
        assert remarks[bead["name"]] == (str(bead["type"]), str(bead["size"])), bead
