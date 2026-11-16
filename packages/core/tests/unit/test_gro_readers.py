"""Golden parity and flag coverage for the .gro readers.

`read_gro` keeps its historical reading (no box or numbering checks); `read_gro_text` adds those
checks for `molecules.aa._gro`. The expected values were captured from both readers before the split.
"""
import hashlib
import json
import math

import pytest
from dashboard.analysis.runs import structures
from dashboard.models.molecules import aa as aa_molecules

from tests.harness.support import PROJECT_ROOT

FixtureGro = PROJECT_ROOT / "packages" / "core" / "tests" / "fixtures" / "cg_og" / "molecule.gro"
MaltoseGro = PROJECT_ROOT / "molecules" / "Maltose" / "results" / "MMFF" / "lig1.gro"


def atom_line(serial, name, xyz, residue_id=1, residue="OG"):
    return f"{residue_id:5d}{residue:<5}{name:>5}{serial:5d}" + "".join(f"{value:8.3f}" for value in xyz)


def gro_text(box, atoms, count=None):
    count = len(atoms) if count is None else count
    return "test\n%d\n" % count + "\n".join(atoms) + "\n" + box + "\n"


def three_atoms():
    return [atom_line(1, "TAIL1", (0.0, 0.0, 0.0)),
            atom_line(2, "TAIL2", (0.47, 0.0, 0.0)),
            atom_line(3, "HEAD", (0.94, 0.0, 0.0))]


BOX3 = "   1.00000   1.00000   1.00000"
BOX9 = "   1.00000   1.00000   1.00000   0.00000   0.00000   0.00000   0.00000   0.00000   0.00000"


def checked(text):
    return structures.read_gro_text(text, source="molecule.gro", check_numbering=True, finite_box=True)


def test_read_gro_reads_the_fixture_exactly():
    assert structures.read_gro(FixtureGro) == [
        {"residue_id": 1, "residue": "OG", "name": "TAIL1", "position": [0.0, 0.0, 0.0]},
        {"residue_id": 1, "residue": "OG", "name": "TAIL2", "position": [0.47, 0.0, 0.0]},
        {"residue_id": 1, "residue": "OG", "name": "HEAD", "position": [0.94, 0.0, 0.0]},
    ]


def test_read_gro_text_is_the_file_reader_on_the_same_text():
    text = FixtureGro.read_text()
    assert structures.read_gro_text(text) == structures.read_gro(FixtureGro)


def test_read_gro_reads_the_maltose_fixture_exactly():
    atoms = structures.read_gro(MaltoseGro)
    raw = json.dumps(atoms, sort_keys=True, separators=(",", ":")).encode()

    assert len(atoms) == 45
    assert hashlib.sha256(raw).hexdigest() == "3f0456282e6c970cefb0e372f70c14968fbb64af00a6442facc07fb9bc853ea5"


def test_aa_gro_matches_its_historical_output():
    assert aa_molecules._gro(FixtureGro.read_text()) == [
        ("OG", "TAIL1", [0.0, 0.0, 0.0]),
        ("OG", "TAIL2", [0.47, 0.0, 0.0]),
        ("OG", "HEAD", [0.94, 0.0, 0.0]),
    ]


@pytest.mark.parametrize("box", [BOX3, BOX9])
def test_both_modes_accept_a_three_and_nine_value_box(box, tmp_path):
    text = gro_text(box, three_atoms())
    path = tmp_path / "ok.gro"
    path.write_text(text)

    default = structures.read_gro(path)
    strict = checked(text)
    assert default == strict
    assert [atom["name"] for atom in strict] == ["TAIL1", "TAIL2", "HEAD"]


def test_the_default_mode_ignores_a_nonfinite_box_but_the_checked_mode_refuses_it():
    text = gro_text("   nan   1.00000   1.00000", three_atoms())

    assert [atom["name"] for atom in structures.read_gro_text(text)] == ["TAIL1", "TAIL2", "HEAD"]
    with pytest.raises(ValueError, match="molecule.gro: invalid box"):
        checked(text)
    with pytest.raises(ValueError, match="molecule.gro: invalid box"):
        aa_molecules._gro(text)


def test_the_default_mode_ignores_a_numbering_gap_but_the_checked_mode_refuses_it():
    atoms = [atom_line(1, "TAIL1", (0.0, 0.0, 0.0)),
             atom_line(3, "TAIL2", (0.47, 0.0, 0.0)),
             atom_line(3, "HEAD", (0.94, 0.0, 0.0))]
    text = gro_text(BOX3, atoms)

    assert [atom["name"] for atom in structures.read_gro_text(text)] == ["TAIL1", "TAIL2", "HEAD"]
    with pytest.raises(ValueError, match="molecule.gro: invalid coordinates or atom numbering"):
        checked(text)
    with pytest.raises(ValueError, match="molecule.gro: invalid coordinates or atom numbering"):
        aa_molecules._gro(text)


def test_a_nonfinite_position_is_refused_only_by_the_checked_mode():
    atoms = three_atoms()
    atoms[1] = atom_line(2, "TAIL2", (float("nan"), 0.0, 0.0))
    text = gro_text(BOX3, atoms)

    assert math.isnan(structures.read_gro_text(text)[1]["position"][0])
    with pytest.raises(ValueError, match="molecule.gro: invalid coordinates or atom numbering"):
        checked(text)
    with pytest.raises(ValueError, match="molecule.gro: invalid coordinates or atom numbering"):
        aa_molecules._gro(text)


def test_a_count_disagreement_keeps_both_readers_messages(tmp_path):
    text = gro_text(BOX3, three_atoms(), count=5)
    path = tmp_path / "short.gro"
    path.write_text(text)

    with pytest.raises(ValueError, match="declares 5 atoms and holds 4"):
        structures.read_gro(path)
    with pytest.raises(ValueError, match="molecule.gro: invalid atom count or missing box"):
        checked(text)
    with pytest.raises(ValueError, match="molecule.gro: invalid atom count or missing box"):
        aa_molecules._gro(text)
