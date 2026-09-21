from dashboard.models.mapping_context import build_context


def _write_fixture(root, molecule_id="Fixture"):
    folder = root / molecule_id
    folder.mkdir(parents=True)
    (folder / "molecule.itp").write_text(
        "[ moleculetype ]\nLIG 1\n[ atoms ]\n"
        "1 CT 1 LIG C1 1 0 12.011\n"
        "2 CT 1 LIG C2 2 0 12.011\n"
        "3 CT 1 LIG C3 3 0 12.011\n"
        "4 CT 1 LIG C4 4 0 12.011\n"
        "5 HC 1 LIG H1 5 0 1.008\n"
        "[ bonds ]\n1 2 1 0.15 1000\n2 3 1 0.15 1000\n"
        "3 4 1 0.15 1000\n1 5 1 0.10 1000\n"
    )
    gro = ["Fixture", "5"]
    for i, name in enumerate(("C1", "C2", "C3", "C4", "H1"), 1):
        gro.append(f"{1:5d}{'LIG':<5}{name:>5}{i:5d}{i * .1:8.3f}{0.:8.3f}{0.:8.3f}")
    (folder / "molecule.gro").write_text("\n".join(gro + ["1 1 1", ""]))
    return folder


def test_context_keeps_atom_ids_and_source_changes(tmp_path):
    folder = _write_fixture(tmp_path)
    before = build_context(tmp_path, "Fixture")
    assert [a["id"] for a in before["atoms"]] == [1, 2, 3, 4, 5]
    assert [a["id"] for a in before["atoms"] if a["heavy"]] == [1, 2, 3, 4]
    assert before["capabilities"]["manual"]["available"]
    topology = folder / "molecule.itp"
    topology.write_text(topology.read_text() + "; changed source\n")
    after = build_context(tmp_path, "Fixture")
    assert before["snapshot"] != after["snapshot"]


def test_context_is_read_only_and_marks_fallback(tmp_path):
    folder = _write_fixture(tmp_path)
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    context = build_context(tmp_path, "Fixture")
    assert context["source_quality"]["bond_order"] == "fallback"
    assert not context["capabilities"]["automatic"]["available"]
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before


def test_context_rejects_coordinate_atom_order_mismatch(tmp_path):
    folder = _write_fixture(tmp_path)
    path = folder / "molecule.gro"
    text = path.read_text().replace("   C1", "   C9", 1)
    path.write_text(text)
    try:
        build_context(tmp_path, "Fixture")
    except ValueError as exc:
        assert "atom order" in str(exc)
    else:
        raise AssertionError("expected coordinate order rejection")


def test_verified_mol2_updates_bond_order_and_display_coordinates(tmp_path):
    folder = _write_fixture(tmp_path)
    (folder / "molecule.mol2").write_text("""@<TRIPOS>MOLECULE
Fixture
5 4 0 0 0
SMALL
NO_CHARGES

@<TRIPOS>ATOM
1 C1 0.0 0.0 0.0 C.3 1 LIG 0
2 C2 1.0 0.0 0.0 C.3 1 LIG 0
3 C3 2.0 0.0 0.0 C.3 1 LIG 0
4 C4 3.0 0.0 0.0 C.3 1 LIG 0
5 H1 3.5 0.0 0.0 H 1 LIG 0
@<TRIPOS>BOND
1 1 2 1
2 2 3 2
3 3 4 1
4 4 5 1
""")
    context = build_context(tmp_path, "Fixture")
    assert context["source_quality"]["bond_order"] == "chemical"
    assert next(b for b in context["bonds"] if b["a"] == 2 and b["b"] == 3)["order"] == 2.0
