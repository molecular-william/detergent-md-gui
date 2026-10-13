"""The system view: what the panel renders, written from the coordinates so the picture cannot disagree with it.

Water and ions are excluded by default. They dominate the atom count, and the point of this view is the protein and
the detergent belt around it; a viewer handed every bead shows a box of water with no visible aggregate.

The element is a neutral stand-in ('C') rather than a chemistry claim, because a coarse-grained bead has no element:
the size class lives in a mapping or a topology, and until this workflow carries one the radii are uniform. The
docstring says so rather than implying a calibrated picture.

Two things the file has to say truthfully, both measured against what a reader saw:

* **one residue per molecule.** Writing six detergents as residue 1 of one chain tells a viewer the system holds one
  molecule, which is both a false picture and the thing that stops it drawing the micelle as molecules.
* **the model's own bonds.** A viewer that is handed no bond information guesses bonds from interatomic distances --
  NGL's `inferBonds` defaults to `'all'` -- and a coarse-grained bead written with a stand-in element puts head beads
  within its guess of tail beads: a placement frame's 60 bonds were drawn as 90, head-to-tail contacts among them.
  The moleculetype's `[ bonds ]` and `[ constraints ]` are now written as CONECT records, replicated per molecule.
  A ring held by constraints is Martini practice and a viewer draws a constraint as a bond, so both sections are the
  model as far as a picture is concerned.
"""
from pathlib import Path

PROTEIN_RESIDUE = 'PRO'
DETERGENT_RESIDUE = 'DET'
WATER_RESIDUES = ('W', 'SW', 'PW', 'NA', 'CL')
BEAD_ELEMENT = 'C'
#: The sections of a moleculetype that make up what a viewer draws as bonds. `[ angles ]`, `[ dihedrals ]`,
#: `[ virtual_sitesn ]` and `[ exclusions ]` are not bonds and must not become any.
BONDED_SECTIONS = ('bonds', 'constraints')


def read_gro(path):
    """The atoms of a GROMACS .gro: one `{'residue_id', 'residue', 'name', 'position'}` per bead, in nanometres.

    The residue *number* comes back as well as the name, because a system with eight detergents has eight residues
    all called `DDM` and the criterion has to tell them apart.

    A parser rather than a dependency: the viewer route should not import a trajectory library to draw a system, and
    the format is fixed-width and trivial to read.
    """
    lines = Path(path).read_text().splitlines()
    if len(lines) < 2:
        raise ValueError(f'{path} is not a .gro file')
    try:
        count = int(lines[1].strip())
    except ValueError as exc:
        raise ValueError(f'{path} does not state an atom count on its second line') from exc
    atoms = []
    body = lines[2:2 + count]
    if len(body) != count:
        raise ValueError(f'{path} declares {count} atoms and holds {len(body)}')
    for line in body:
        if len(line) < 44:
            raise ValueError(f'{path} has a truncated atom line: {line!r}')
        try:
            residue_id = int(line[0:5])
        except ValueError as exc:
            raise ValueError(f'{path} has an unreadable residue number: {line!r}') from exc
        atoms.append({'residue_id': residue_id, 'residue': line[5:10].strip(), 'name': line[10:15].strip(),
                      'position': [float(line[20:28]), float(line[28:36]), float(line[36:44])]})
    return atoms


def read_gro_box(path) -> list[float]:
    """A .gro's box vector, so a structure written from another one can keep its own box."""
    lines = Path(path).read_text().splitlines()
    if not lines:
        raise ValueError(f'{path} is not a .gro file')
    try:
        return [float(value) for value in lines[-1].split()]
    except ValueError as exc:
        raise ValueError(f'{path} has an unreadable box line: {lines[-1]!r}') from exc


def read_moleculetype(path) -> dict:
    """The beads and the bonded terms a GROMACS moleculetype declares, as the model a picture is drawn from.

    The picture is only as honest as the model it was handed, so the model is read rather than inferred: `[ atoms ]`
    gives the bead order a structure of this molecule follows, and `[ bonds ]` + `[ constraints ]` give the bonds a
    viewer should draw. Fields after an atom's name are not read -- the name is the one column a structure and a
    topology can be checked against each other by.
    """
    path = Path(path)
    atoms, pairs = [], {section: [] for section in BONDED_SECTIONS}
    section = None
    for line in path.read_text().splitlines():
        # A moleculetype's comments are `;`; a `#include` or a preprocessor line names no bond either.
        content = line.split(';', 1)[0].split('#', 1)[0].strip()
        if not content:
            continue
        if content.startswith('['):
            section = content.strip('[]').strip().lower()
            continue
        fields = content.split()
        if section == 'atoms':
            if len(fields) < 5:
                raise ValueError(f'{path} has an atom line without a bead name: {line!r}')
            atoms.append(fields[4])
        elif section in pairs:
            if len(fields) < 2:
                raise ValueError(f'{path} has a {section} line without a pair: {line!r}')
            try:
                pairs[section].append((int(fields[0]), int(fields[1])))
            except ValueError as exc:
                raise ValueError(f'{path} has an unreadable {section} pair: {line!r}') from exc
    if not atoms:
        raise ValueError(f'{path} declares no atoms: there is no molecule to draw bonds for')
    return {'atoms': atoms, 'bonds': pairs['bonds'], 'constraints': pairs['constraints'], 'path': str(path)}


def is_detergent(atom, detergent_residue) -> bool:
    """Whether a bead belongs to the detergent the caller named, rather than to the protein."""
    return str(atom['residue']).upper() == str(detergent_residue).upper()


def molecule_bonds(topology: dict | None, beads, serials) -> list[tuple[int, int]] | None:
    """One molecule's bonds, by bead serial, or `None` when this structure is not that molecule.

    The beads are checked against the moleculetype's `[ atoms ]` order rather than assumed to match it: a bond
    drawn between two beads that are not that pair is the thing this writer exists to stop, so a structure that
    does not match the topology is left unbonded and the file says so.
    """
    if topology is None:
        return None
    if [str(bead['name']) for bead in beads] != list(topology['atoms']):
        return None
    return [(serials[first - 1], serials[second - 1])
            for first, second in (*topology['bonds'], *topology['constraints'])]


def system_pdb(atoms, *, detergent_residue='DDM', include_water=False, title='PDC system', topology=None):
    """A PDB for the viewer: one HETATM per bead, protein as PRO, detergent as DET, water and ions dropped.

    The detergent is identified by the residue the template declares, so the caller names it rather than this module
    guessing; everything that is not the detergent and not solvent is protein, which is what the box holds.

    Every molecule gets its own residue number, in the order the coordinates first show it, and `topology` -- the
    detergent's moleculetype, when the caller has it -- adds that moleculetype's own bonds as CONECT records, once
    per detergent molecule. Without a topology the file carries no bonds at all and says so, which is the one
    answer a viewer cannot turn into invented chemistry.
    """
    kept = [atom for atom in atoms if include_water or atom['residue'].upper() not in WATER_RESIDUES]

    molecules, molecule_of = [], {}
    for atom in kept:
        key = (str(atom['residue']).upper(), atom['residue_id'])
        if key not in molecule_of:
            molecule_of[key] = len(molecules)
            molecules.append([])
        molecules[molecule_of[key]].append(atom)

    records, serials = [], [[] for _ in molecules]
    for serial, atom in enumerate(kept, start=1):
        index = molecule_of[(str(atom['residue']).upper(), atom['residue_id'])]
        residue = DETERGENT_RESIDUE if is_detergent(atom, detergent_residue) else PROTEIN_RESIDUE
        x, y, z = (round(float(value) * 10.0, 3) for value in atom['position'])  # nm -> Angstrom, as PDB is
        records.append(f'HETATM{serial:5d} {str(atom["name"])[:4]:<4s} {residue:>3s} A{index + 1:4d}    '
                       f'{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {BEAD_ELEMENT:>2s}')
        serials[index].append(serial)

    detergents = [index for index, beads in enumerate(molecules)
                  if beads and is_detergent(beads[0], detergent_residue)]
    conect, unbonded = [], []
    for index in detergents:
        bonds = molecule_bonds(topology, molecules[index], serials[index])
        if bonds is None:
            unbonded.append(index)
            continue
        conect += [f'CONECT{first:5d}{second:5d}' for first, second in bonds]

    lines = [f'REMARK 950 {title.upper()}: COARSE-GRAINED SYSTEM AS SET UP, WATER AND IONS OMITTED',
             'REMARK 950 ELEMENTS ARE RADIUS STAND-INS, NOT CHEMISTRY']
    if detergents and topology is None:
        lines.append('REMARK 950 NO BONDS RECORDED: this stage carries no detergent moleculetype, so the picture '
                     'claims no bonds rather than leaving a viewer to invent them')
    if detergents and topology is not None:
        lines.append(f"REMARK 950 BONDS ARE THE MODEL'S OWN, NOT GUESSED: {len(topology['bonds'])} [ bonds ] + "
                     f"{len(topology['constraints'])} [ constraints ] of {Path(topology['path']).name}, replicated "
                     f'per detergent molecule')
    if unbonded:
        lines.append(f'REMARK 950 NO BONDS RECORDED FOR {len(unbonded)} OF {len(detergents)} DETERGENT MOLECULES: '
                     'their beads are not the moleculetype\'s beads, as it declares them in [ atoms ]')
    lines += records + conect + ['END']
    return '\n'.join(lines) + '\n'
