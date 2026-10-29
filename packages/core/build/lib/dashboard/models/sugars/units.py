"""Which unit a structure's coordinates are in.

One convention, stated once: structures built from the molecule context (they carry `molecule_id` or
`snapshot`) hold nanometres, because the context converts its sources; the legacy packaged references
parsed straight out of SwissParam PDB files hold angstroms.

The bonded generator has always made this distinction. The sugar topology writer and the mapping export
did not -- they divided by ten unconditionally -- so for every molecule chosen in the dashboard the
generated constraint lengths and the exported coordinates came out a factor of ten too small. The
reference's own ring constraints are about 0.3 to 0.47 nm; the generated ones were measured at 0.032 to
0.043 nm against them.

This lives inside the sugars package because that package is shipped whole into the mapping export
bundle, where nothing above it exists.
"""


def angstrom_factor(structure):
    """The factor that converts a structure's coordinates to nanometres."""
    legacy_angstrom = not structure.get('molecule_id') and not structure.get('snapshot')
    return 0.1 if legacy_angstrom else 1.0
