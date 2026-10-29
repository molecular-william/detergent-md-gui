"""The atomistic-to-CG protein step: martinize2 with the elastic network the protocol asks for.

Flags verified against the installed tool's own help rather than assumed:

    -ef RB_FORCE_CONSTANT   elastic bond force constant Fc in kJ/mol/nm^2 (default 700)
    -el RB_LOWER_BOUND      lower cutoff: F = Fc if rij < lo (default 0)
    -eu RB_UPPER_BOUND      upper cutoff: F = 0 if rij > up (default 0.9)

So "an elastic network between all Ca atoms within 10 A at 1000 kJ/mol" is `-elastic -ef 1000 -eu 1.0`: the cutoff
is the upper bound, not the lower one, and the unit is the nanometre the tool documents. The bead selection is left
to the force field, which is one backbone bead per residue -- a C-alpha -- and `-eu` is what decides the distance.
"""
from pathlib import Path

FORCE_CONSTANT = 1000          # kJ/mol/nm^2, the force constant the request names
UPPER_BOUND_NM = 1.0           # 10 A, in the units the tool documents
DEFAULT_FORCE_FIELD = 'martini3001'
#: The command name the tool answers to when no caller has resolved one. A stage script relies on this -- its PATH is
#: the one `execution/tools.search_path()` built, so whatever tool it finds there is the declared one -- while a caller
#: that has already resolved the executable (`execution/tools.tool_path`) hands that path in instead.
DEFAULT_EXECUTABLE = 'martinize2'
#: The name the tool is told to write its topology under, in the output directory it runs in. It is where
#: `[ molecules ]` -- the list the system topology has to reproduce -- comes from, so the builder of the command and
#: the reader of that list cannot name two different files.
TOPOLOGY_NAME = 'protein.top'


def martinize_command(protein_pdb, out_dir, *, executable=DEFAULT_EXECUTABLE, force_field=DEFAULT_FORCE_FIELD,
                      structure_name='protein_cg.pdb', topology_name=TOPOLOGY_NAME):
    """The command that produces the CG protein and its topology from the atomistic structure.

    The executable is a parameter rather than a lookup: the stage resolves it through `execution/tools.py`, where a
    declared path is verified before use, and keeping it here would make this function untestable without GROMACS.
    """
    pdb = Path(protein_pdb)
    if not pdb.is_file():
        raise ValueError(f'protein structure not found: {pdb}')
    if FORCE_CONSTANT <= 0 or UPPER_BOUND_NM <= 0:
        raise ValueError('the elastic network needs a positive force constant and cutoff')
    out = Path(out_dir)
    return [executable, '-f', str(pdb), '-x', str(out / structure_name), '-o', str(out / topology_name),
            '-ff', force_field, '-elastic', '-ef', str(FORCE_CONSTANT), '-eu', str(UPPER_BOUND_NM)]
