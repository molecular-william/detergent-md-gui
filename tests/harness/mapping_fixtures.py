"""The smallest molecule directory the mapping reader accepts, shared by the files that need one.

It was `_write_fixture` in `test_mapping_context.py` and three other files imported it from there -- a test module
importing another test module, which the package split cannot keep. The construction is a fixture; the meaning stays
with each file.
"""


def write_fixture(root, molecule_id="Fixture"):
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
