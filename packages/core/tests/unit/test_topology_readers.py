"""Golden parity for the topology readers now sharing `dashboard.itp`.

Each digest was captured from the reader as it stood before the conversion, over a real fixture:
the DDM ITP, the published Martini 3 sugar reference, and the vsites fixtures. A converted
reader that changes a record, a row order or a section assignment fails on the digest.
"""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from dashboard import itp
from dashboard.models.mappings import context as mapping_context
from dashboard.models.mappings import references as mapping_references
from dashboard.models.molecules import aa as aa_molecules
from dashboard.models.molecules import vsites

from tests.harness.support import PROJECT_ROOT

Ddm = PROJECT_ROOT / "molecules" / "DDM" / "v1" / "results" / "MMFF"
SugarReference = PROJECT_ROOT / "references" / "martini_v3.0.0_sugars_v2.itp"
VsitesFixture = PROJECT_ROOT / "packages" / "core" / "tests" / "fixtures" / "vsites"


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def test_rows_returns_each_matching_section_in_file_order():
    text = (
        "[ moleculetype ]\nMOL 1\n\n[ bonds ]\n1 2 1 0.30 5000 ; first\n"
        "\n[ angles ]\n1 2 3 1 120 25\n\n[ bonds ]\n3 4 1 0.31 5000\n"
    )

    assert itp.rows(text, "bonds") == [
        (5, ["1", "2", "1", "0.30", "5000"]),
        (11, ["3", "4", "1", "0.31", "5000"]),
    ]
    assert itp.rows(text, "missing") == []


def test_rows_evaluates_the_preprocessor_branch_when_asked():
    text = "[ bonds ]\n#ifndef FLEXIBLE\n1 2 1 0.30 5000\n#else\n1 2 2 0.30 5000\n#endif\n"

    assert [fields for _number, fields in itp.rows(text, "bonds", defines=())] == [["1", "2", "1", "0.30", "5000"]]
    assert [fields for _number, fields in itp.rows(text, "bonds", defines=("FLEXIBLE",))] == [["1", "2", "2", "0.30", "5000"]]


def test_the_mapping_context_reader_is_unchanged():
    expanded, _dependencies = aa_molecules.topology_tree(Ddm, "lig1.itp")
    atoms, bonds = mapping_context._parse_topology(expanded)

    assert (len(atoms), len(bonds)) == (81, 82)
    assert digest([atoms, bonds]) == "a18ac7a87ed6ca43a84cdc0582b48fd513529b02150d3d98ff2d8f4e63ea07f7"


def test_the_aa_itp_reader_is_unchanged():
    text = (Ddm / "lig1.itp").read_text()
    molecule, atoms, charge = aa_molecules._itp(text)

    assert (molecule, len(atoms)) == ("LIG1", 81)
    assert charge == -5.551115123125783e-16
    assert digest([molecule, atoms, charge]) == "3ca8aa5fd966d4735002b8b35cd7b6f9dc7b1f40e9d88325455498f8d411befd"


def test_the_reference_index_reader_is_unchanged(monkeypatch):
    monkeypatch.chdir(PROJECT_ROOT)
    records = mapping_references._parse_itp(Path("references") / SugarReference.name, 1, "sugars")

    assert len(records) == 50
    assert digest(records) == "bf136347b2ea3c4d60d501cf349e24a62aa3549c2982b10e2b1d041620b27f77"


def test_the_vsites_itp_reader_is_unchanged():
    path = Ddm / "lig1.itp"
    text = path.read_text()
    molecule, diagnostics = vsites._parse_itp(path, text, hashlib.sha256(text.encode()).hexdigest())

    assert diagnostics == []
    assert (len(molecule.atoms), len(molecule.bonds), len(molecule.angles)) == (81, 82, 155)
    assert digest(asdict(molecule)) == "2782fa46781802e777b6910c344af893b28dc360aad2f6dbd8115a40db3a8837"


def test_the_vsites_rtp_reader_is_unchanged():
    path = VsitesFixture / "lig.rtp"
    text = path.read_text()
    molecule, diagnostics = vsites._parse_rtp(path, text, hashlib.sha256(text.encode()).hexdigest(), "LIG")

    assert diagnostics == []
    assert digest(asdict(molecule)) == "d9f76ff0473fa7b481642610203e23665638e8d5cad1993e37d704da32d84164"
