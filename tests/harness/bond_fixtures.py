"""A fixture that reproduces the viewer hazard the `CONECT` guard exists for, for the two NGL panels.

NGL parses a PDB's `CONECT` records into the structure's bonds and *then* still runs its distance-based guess
(`inferBonds` defaults to `'all'`), so a file that carries the model's bonds can be drawn with the model's bonds
*plus* the viewer's own. The guess is not unconditional: it only joins atoms that NGL puts in **different residues**
and whose separation is inside its covalent cut-off (~1.5 A). Two facts that make the hazard real rather than
hypothetical:

* the Complexes panel was measured drawing 90 bonds on a placement frame the model bonds 60 ways, because that
  file gives every molecule its own residue (recorded in `execution/adapters/pdc_view.py`);
* the two panels here load files whose layout currently keeps every bonded pair either inside one residue
  (`overlay3d` writes one `MOL` residue) *or* farther apart than the cut-off (`compositions` lays beads out at
  3.5 A and more). So today they draw the model's bonds by luck of geometry, not by rule -- and a writer change
  would silently break them.

`regrouped` makes the hazard explicit on a panel's own file: it keeps every serial, coordinate and `CONECT` record
-- the model is untouched -- and changes only the residue column, so NGL groups the atoms into more than one residue
as a real coarse-grained file does. `scale` shrinks the arrangement about the origin, which is how a file whose
bonds are farther apart than NGL's cut-off is brought inside it. Both are fixtures shaped to the hazard, stated as
such, not claims about any writer's output.
"""
import re

RESIDUE_NAMES = ('MOL', 'LIG')


def regrouped(pdb, scale=1.0):
    """The same atoms, serials and CONECT records, with NGL's residue grouping and spacing made hazardous."""
    lines = []
    atom = 0
    for line in pdb.splitlines():
        if line.startswith(('HETATM', 'ATOM  ')) and len(line) >= 54:
            resname = RESIDUE_NAMES[atom % len(RESIDUE_NAMES)]
            line = line[:17] + f'{resname:>3s}' + line[20:22] + f'{atom + 1:4d}' + line[26:]
            x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
            line = line[:30] + f'{x * scale:8.3f}{y * scale:8.3f}{z * scale:8.3f}' + line[54:]
            atom += 1
        lines.append(line)
    return '\n'.join(lines) + '\n'


def model_pairs(pdb):
    """The bonds a PDB states, as 1-based structure indices: the `CONECT` records, through the written serials.

    A file's serials are not necessarily its structure indices (the mapping overlay writes each atom's mapping id as
    its serial, and only heavy atoms are written), so the serial-to-file-order map is built from the `HETATM` lines
    rather than assumed to be the identity.
    """
    order = {int(serial): position + 1
             for position, serial in enumerate(re.findall(r'^(?:HETATM|ATOM  )(.{5})', pdb, re.M))}
    pairs = set()
    for first, second in re.findall(r'^CONECT(.{5})(.{5})', pdb, re.M):
        first, second = order[int(first)], order[int(second)]
        pairs.add((min(first, second), max(first, second)))
    return pairs


def atom_count(pdb):
    """How many atoms a PDB writes -- the key a served file can be matched to the structure drawn from it."""
    return len(re.findall(r'^(?:HETATM|ATOM  )', pdb, re.M))
