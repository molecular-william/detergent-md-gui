"""The system view: what the panel renders, written from the coordinates so the picture cannot disagree with it.

Water and ions are excluded by default. They dominate the atom count, and the point of this view is the protein and
the detergent belt around it; a viewer handed every bead shows a box of water with no visible aggregate.

The element is a stand-in rather than a chemistry claim, because a coarse-grained bead has no element: the size class
lives in a mapping or a topology, and this writer reads it from the moleculetype it is handed and writes the element
that class is drawn with (`SIZE_ELEMENTS`). A viewer handed only a stand-in draws a ranking of sizes -- carbon and
nitrogen are nearly equal -- while Martini 3's classes are R 0.264 / S 0.230 / T 0.191 nm, so the column carries the
class and the radii come out in the model's proportion (`models/compositions/topology.py`'s `render_pdb` and
`ngl-beads.js` are the other two ends of that one convention). A bead whose class the model does not state -- a
protein bead, a bead the moleculetype does not name, or any bead when there is no topology at all -- keeps the neutral
`C` stand-in, which is the model's R: an unstated class is not a smaller one.

Two things the file has to say truthfully, both measured against what a reader saw:

* **one residue per molecule.** Writing six detergents as residue 1 of one chain tells a viewer the system holds one
  molecule, which is both a false picture and the thing that stops it drawing the micelle as molecules.
* **the model's own bonds.** A viewer that is handed no bond information guesses bonds from interatomic distances --
  NGL's `inferBonds` defaults to `'all'` -- and a coarse-grained bead written with a stand-in element puts head beads
  within its guess of tail beads: a placement frame's 60 bonds were drawn as 90, head-to-tail contacts among them.
  The moleculetype's `[ bonds ]` and `[ constraints ]` are now written as CONECT records, replicated per molecule.
  A ring held by constraints is Martini practice and a viewer draws a constraint as a bond, so both sections are the
  model as far as a picture is concerned.

Two columns carry what a bead's chemistry cannot, and each is a code the file's own REMARKs explain. The element
column is the size class (`SIZE_ELEMENTS`), which a viewer turns into the model's radius. The b-factor column is the
Martini 3 *polarity family* (`BEAD_FAMILIES`), which a viewer turns into the bead's colour: a representation colours
from one column, not from a per-atom colour, and the family is the one thing a bead's size cannot say -- two beads of
one class can be a polar sugar head and an apolar tail. Both are read from the same place, the moleculetype's type
column, and `ngl-beads.js` holds the viewer's end of the same two tables.
"""
from pathlib import Path

PROTEIN_RESIDUE = 'PRO'
DETERGENT_RESIDUE = 'DET'
WATER_RESIDUES = ('W', 'SW', 'PW', 'NA', 'CL')
#: The stand-in element each size class' beads are written with. `models/compositions/topology.py` chooses the same
#: three, whose van der Waals radii divide by one factor into 0.264 / 0.230 / 0.191 nm, so one radius scale serves
#: every class and a viewer's per-element radii are the model's proportion.
SIZE_ELEMENTS = {'R': 'C', 'S': 'N', 'T': 'H'}
#: What a bead whose class is not resolved is written with: the R stand-in, because an unstated class is not a
#: smaller one and this is the shell the pictures were drawn with before any class was stated.
BEAD_ELEMENT = SIZE_ELEMENTS['R']
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


def size_class(bead_type) -> str:
    """The Martini 3 size class a bead type names: an `S` or `T` first letter, else R.

    Martini 3 spells the class in the type: `SP1r`, `SN6`, `ST2` are small, `TC4`, `TN2` tiny, and a regular bead's
    type carries no prefix at all (`C1`, `P1`). `models/molecules/draft.py` reconciles a mapping's stated size with
    its bead type by that same letter, so this is the repository's own reading of the column rather than a second
    convention; the saved DDM mapping's types (`SP1r`, `SN6`, `SP4r`, `TC4`, `C1`) come back as the R/S/T it states
    for them. A type that is empty or names neither letter states no class and is read as R -- the class whose
    stand-in element an unstated class is written with anyway -- rather than guessed at from a chemical letter.
    """
    letter = str(bead_type or '').strip()[:1].upper()
    return letter if letter in ('S', 'T') else 'R'


def bead_element(bead_type) -> str:
    """The stand-in element a bead of this type is written with, chosen from the class its type names."""
    return SIZE_ELEMENTS[size_class(bead_type)]


#: Martini 3's polarity families, in the order the code written into the file's b-factor column numbers them. A
#: bead's *type* states its family the way it states its size class: `SP1r` is small *and* polar, `TC4` tiny *and*
#: apolar, `Q5` charged, `N...` nonpolar. Code 0 is not a family -- it is a bead whose type states none of the four,
#: which is every protein bead this writer is handed and every bead when there is no topology at all. Putting it at
#: zero means a file that carries no family column reads as unstated rather than as whichever family came first.
BEAD_FAMILIES = ('unstated', 'C', 'N', 'P', 'Q')
FAMILY_UNSTATED = BEAD_FAMILIES[0]


def bead_family(bead_type) -> str:
    """The Martini 3 polarity family a bead type names, or `unstated` when it names none.

    It is read the way `size_class` reads the class and from the same column: the first letter after a one-letter
    `S`/`T` class prefix, if that letter is one of `Q`/`P`/`N`/`C`. A type that is empty, or that leads with
    anything else (`W` water, `I` an ion, a protein bead's own name), states no family and is reported as such
    rather than being guessed into an apolar bead.
    """
    code = str(bead_type or '').strip().upper()
    rest = code[1:] if code[:1] in ('S', 'T') else code
    family = rest[:1]
    return family if family in BEAD_FAMILIES[1:] else FAMILY_UNSTATED


def bead_family_code(bead_type) -> int:
    """The family's code, the number written into the file's b-factor column for a bead of this type."""
    return BEAD_FAMILIES.index(bead_family(bead_type))


def bead_families(topology: dict | None) -> dict[str, str]:
    """The family each bead a moleculetype names belongs to, by bead name -- the same identity bonds are matched by."""
    if not topology:
        return {}
    types = list(topology.get('types') or [''] * len(topology['atoms']))
    return {str(name).strip().upper(): bead_family(bead_type)
            for name, bead_type in zip(topology['atoms'], types)}


def bead_elements(topology: dict | None) -> dict[str, str]:
    """The element each bead a moleculetype names is written with, by bead name.

    The class belongs to the bead the model declares, so it is looked up by name -- the same identity the bonds are
    matched by -- and a moleculetype that states no type column yields the R stand-in for every bead rather than a
    class nothing stated.
    """
    if not topology:
        return {}
    types = list(topology.get('types') or [''] * len(topology['atoms']))
    return {str(name).strip().upper(): bead_element(bead_type)
            for name, bead_type in zip(topology['atoms'], types)}


def read_moleculetype(path) -> dict:
    """The beads and the bonded terms a GROMACS moleculetype declares, as the model a picture is drawn from.

    The picture is only as honest as the model it was handed, so the model is read rather than inferred: `[ atoms ]`
    gives the bead order a structure of this molecule follows, and `[ bonds ]` + `[ constraints ]` give the bonds a
    viewer should draw. Fields after an atom's name are not read -- the name is the one column a structure and a
    topology can be checked against each other by.
    """
    path = Path(path)
    return read_moleculetype_text(path.read_text(), source=str(path))


def read_moleculetype_text(text: str, *, source: str = '<text>') -> dict:
    """One moleculetype read out of text, for a caller that derived it and has no file to point at.

    The system preview derives a detergent's topology from its mapping and can draw it in the same request:
    `pdc_view`'s own reader is the one place that knows what a moleculetype's bonds are, so the derivation's text is
    read through it rather than through a second parser (or a scratch file written only to be read back). `source`
    is what the caller's record calls the file this model came from -- the name the run writes it under -- and it
    travels into the returned record, and from there into the PDB's own REMARK, so the picture keeps saying where
    its bonds came from.

    Two columns of an `[ atoms ]` row are read: the bead's *name*, which is the one column a structure and a
    topology can be checked against each other by, and its *type*, which is where a Martini 3 bead's size class is
    spelled (`size_class`). The rest -- residue number, charge, mass -- say nothing this writer draws.
    """
    atoms, types, pairs = [], [], {section: [] for section in BONDED_SECTIONS}
    section = None
    for line in str(text).splitlines():
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
                raise ValueError(f'{source} has an atom line without a bead name: {line!r}')
            atoms.append(fields[4])
            types.append(fields[1])
        elif section in pairs:
            if len(fields) < 2:
                raise ValueError(f'{source} has a {section} line without a pair: {line!r}')
            try:
                pairs[section].append((int(fields[0]), int(fields[1])))
            except ValueError as exc:
                raise ValueError(f'{source} has an unreadable {section} pair: {line!r}') from exc
    if not atoms:
        raise ValueError(f'{source} declares no atoms: there is no molecule to draw bonds for')
    return {'atoms': atoms, 'types': types, 'bonds': pairs['bonds'], 'constraints': pairs['constraints'],
            'path': str(source)}


def topology_residue(atoms, topology: dict | None, fallback: str) -> str:
    """The residue name a moleculetype describes, as this structure spells it.

    The molecule a run's topology belongs to is the one whose beads are the moleculetype's `[ atoms ]`, in order --
    not whichever residue the file happens to write first. Measured on a run's own `4_CG_sim/md.gro`: the first
    bead is solvent, and naming the molecule after it would leave the solute drawn with no bonds in the one picture
    a reader most wants. `fallback` is the answer when the topology describes nothing here, which is the case the
    caller reports rather than bonds for.
    """
    if topology is None:
        return fallback
    names = list(topology['atoms'])
    for key in dict.fromkeys((atom['residue'], atom['residue_id']) for atom in atoms):
        beads = [atom for atom in atoms if (atom['residue'], atom['residue_id']) == key]
        if [str(bead['name']) for bead in beads] == names:
            return str(key[0])
    return fallback


def structure_pdb(path, *, topology: dict | None = None, title: str | None = None) -> str:
    """A run's own structure file as a PDB, with the model's own bonds where a topology is given.

    A `.gro` carries coordinates and no bond records, and this repository's vendored viewer infers none from a
    `.gro` whatever `inferBonds` says -- so a coarse-grained run's mapped model, drawn straight from its stage
    file, comes out as beads with no connectivity at all, while the run's own moleculetype states exactly which
    beads are bonded. That moleculetype's `[ bonds ]` and `[ constraints ]` are written here through `system_pdb`,
    the same writer the complex system view uses, with the molecule it describes -- found by its beads, not by
    whichever residue the file lists first -- treated as the one it bonds.

    A `.pdb` is refused rather than rewritten: it already carries, or declines, its own records and the artifact
    route serves it, so a second writer for the same bytes would be a second source of truth. And a structure whose
    beads are not the moleculetype's is left unbonded with the reason in a REMARK -- never with a bond the model
    does not state.
    """
    path = Path(path)
    if path.suffix.lower() != '.gro':
        raise ValueError(f'{path} is not a .gro: this writer adds the bonds a .gro cannot carry, and a .pdb '
                         'already states its own records')
    atoms = read_gro(path)
    if not atoms:
        raise ValueError(f'{path} holds no atoms')
    return system_pdb(atoms, detergent_residue=topology_residue(atoms, topology, atoms[0]['residue']),
                      topology=topology, title=title or f'{path.name} - a run structure')


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

    The element column is the stand-in for each detergent bead's own size class (`bead_elements`), because that is
    the one column a viewer resolves a radius from: written uniformly, every bead is drawn at the model's R however
    the model sizes it. The classes are the moleculetype's, so they belong to the detergent; a protein bead, and a
    bead the moleculetype does not name, are written with the `C` stand-in the file's REMARK states.

    The b-factor column carries each bead's Martini 3 *polarity family* (`bead_families`), because the family is the
    one thing a bead's size cannot say and a viewer colours from a column rather than from a per-atom colour. It is
    a code, not a temperature factor, and the file's own REMARK says so; a bead whose type states no family -- a
    protein bead, or any bead when there is no topology -- is written the code for `unstated`.
    """
    records, conect, counts = structure_records(atoms, detergent_residue=detergent_residue,
                                               include_water=include_water, topology=topology)
    lines = structure_remarks(title, topology, counts)
    lines += records + conect + ['END']
    return '\n'.join(lines) + '\n'


def structure_records(atoms, *, detergent_residue, include_water=False, topology=None):
    """One structure's `HETATM` records, its `CONECT` records, and the counts a REMARK needs to report.

    Split out of `system_pdb` because a sampled frame series writes the same three conventions once per model --
    the element stand-in by size class, the Martini 3 family code in the b-factor column, and the moleculetype's
    own bonds as `CONECT` -- and a second writer for them would be a second set of conventions. The counts come
    back so the caller's REMARKs can say what it could and could not bond.
    """
    kept = [atom for atom in atoms if include_water or atom['residue'].upper() not in WATER_RESIDUES]
    elements = bead_elements(topology)
    families = bead_families(topology)

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
        detergent = is_detergent(atom, detergent_residue)
        residue = DETERGENT_RESIDUE if detergent else PROTEIN_RESIDUE
        element = elements.get(str(atom['name']).strip().upper()) if detergent else None
        family = families.get(str(atom['name']).strip().upper()) if detergent else None
        x, y, z = (round(float(value) * 10.0, 3) for value in atom['position'])  # nm -> Angstrom, as PDB is
        records.append(f'HETATM{serial:5d} {str(atom["name"])[:4]:<4s} {residue:>3s} A{index + 1:4d}    '
                       f'{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}'
                       f'{float(BEAD_FAMILIES.index(family or FAMILY_UNSTATED)):6.2f}'
                       f'          {element or BEAD_ELEMENT:>2s}')
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
    return records, conect, {'detergent_molecules': len(detergents), 'unbonded': len(unbonded)}


def structure_remarks(title, topology, counts, *, extra=(), clause='COARSE-GRAINED SYSTEM AS SET UP, '
                                                                  'WATER AND IONS OMITTED'):
    """The block that says what the element column, the b-factor column and the bonds in a file of ours mean.

    One function for every structure this module writes, so a series and a single frame cannot describe their own
    columns two ways. `extra` is where a caller adds what only it knows -- a series states how many models it holds
    and at what cadence.
    """
    lines = [f'REMARK 950 {title.upper()}: {clause}',
             f'REMARK 950 ELEMENTS ARE RADIUS STAND-INS, NOT CHEMISTRY: EACH BEAD IS WRITTEN WITH ITS OWN SIZE '
             f'CLASS ({", ".join(f"{size} {element}" for size, element in sorted(SIZE_ELEMENTS.items()))}), AND A '
             f'BEAD WHOSE CLASS THE MODEL DOES NOT STATE IS WRITTEN {BEAD_ELEMENT}',
             'REMARK 950 THE B-FACTOR COLUMN CARRIES A MARTINI 3 POLARITY FAMILY, NOT A TEMPERATURE FACTOR: '
             + ', '.join(f'{code} {family.upper()}' for code, family in enumerate(BEAD_FAMILIES))
             + ", READ FROM EACH BEAD'S OWN TYPE; A VIEWER COLOURS FROM IT"]
    if counts['detergent_molecules'] and topology is None:
        lines.append('REMARK 950 NO BONDS RECORDED: this stage carries no detergent moleculetype, so the picture '
                     'claims no bonds rather than leaving a viewer to invent them')
    if counts['detergent_molecules'] and topology is not None:
        lines.append(f"REMARK 950 BONDS ARE THE MODEL'S OWN, NOT GUESSED: {len(topology['bonds'])} [ bonds ] + "
                     f"{len(topology['constraints'])} [ constraints ] of {Path(topology['path']).name}, replicated "
                     f'per detergent molecule')
    if counts['unbonded']:
        lines.append(f"REMARK 950 NO BONDS RECORDED FOR {counts['unbonded']} OF {counts['detergent_molecules']} "
                     "DETERGENT MOLECULES: their beads are not the moleculetype's beads, as it declares them in "
                     '[ atoms ]')
    return lines + list(extra)


def series_pdb(frames, *, topology=None, detergent_residue=None, title='frame series', note=None,
               include_water=False):
    """A run's sampled frames as one multi-model PDB, written with the conventions the run's own structure uses.

    `frames` is one atom list per sampled moment, each `read_gro`-shaped: `name`, `residue`, `residue_id` and
    `position` in nanometres. A viewer plays a series out of `MODEL`/`ENDMDL` blocks in one file, and the two things
    a frame needs to be *readable* are the two a single structure needs -- the family code that colours a bead and
    the model's own bonds -- written per model, because a reader addresses `CONECT` within a model.

    Reading a trajectory straight into a PDB writer gives neither. Measured: the first series this repository
    published came out of MDAnalysis's writer with b-factor `0.00` on every bead and no `CONECT` record at all, so
    the run view drew uncoloured, unbonded spheres beside the same run's own structure, which carries both. The
    residue is the moleculetype's, found in the coordinates rather than assumed, and a caller with no topology gets
    a file that says it carries no bonds rather than one a viewer will guess at.
    """
    if detergent_residue is None and frames:
        detergent_residue = topology_residue(frames[0], topology, str(frames[0][0]['residue']))
    built = [structure_records(atoms, detergent_residue=detergent_residue, include_water=include_water,
                               topology=topology) for atoms in frames]
    extra = [f'REMARK 950 SAMPLED SERIES: {len(frames)} models' + (f', {note}' if note else '')]
    counts = built[0][2] if built else {'detergent_molecules': 0, 'unbonded': 0}
    lines = structure_remarks(title, topology, counts, extra=extra)
    for index, (records, conect, _) in enumerate(built, start=1):
        lines += [f'MODEL     {index:4d}'] + records + conect + ['ENDMDL']
    lines.append('END')
    return '\n'.join(lines) + '\n'
