"""Which molecules are detergents: the registry at `detergents.json` decides, not a list held in code.

`detergents.json` at the repository root is a name-to-SMILES map of the detergents this project knows, and nothing
in the code base read it -- so the panel presented `molecules/` as one kind of input, DDM beside Maltose, Sucrose and
Trehalose. It is not one kind: a protein-detergent build makes a belt out of a detergent's own beads, and a sugar
picked there is a run that cannot be built. This module is the single reader of that file.

**What an entry's abbreviation is.** The registry writes it in the parentheses at the end of the entry's name
("n-Dodecyl-β-D-maltoside (DDM)"), and a molecule directory is named after it. Two shapes do not have one: an entry
whose parentheses hold the whole chemical name instead ("CHAPS (3-[(3-Cholamidopropyl)dimethylammonio]-1-
propanesulfonate)") and one that puts a size range there ("Triton X-100 (~7-8 EO)"). Neither can be picked, and
neither should be: an abbreviation has to be usable as a directory name, which is exactly the bar applied below.

An entry whose whole name is already an abbreviation ("Anapoe-C12E8") is filed under it. Nothing is guessed from a
name's prefix, so "Sucrose Monodecanoate / Monolaurate" does not make a molecule called `Sucrose` a detergent.
"""
import json
import re
from pathlib import Path

#: The registry, relative to the project root.
REGISTRY_FILE = 'detergents.json'
#: What may name a molecule directory, which is the bar an abbreviation has to clear to be usable as one. The same
#: shape `aa.validate_id` enforces, kept here so an entry that could not be reached is not treated as one that can.
_CODE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}')
#: The parenthesis group at the very end of a name, holding no parentheses of its own -- which is why an entry whose
#: brackets nest ("CHAPS ...") has no abbreviation rather than a wrong one.
_TRAILING = re.compile(r'\(([^()]*)\)\s*$')
#: The separators the registry uses between several names for one molecule ("LDAO / C12AO").
_SEPARATORS = re.compile(r'[/·]')


def registry_path(root):
    """The registry file under a project root."""
    return Path(root) / REGISTRY_FILE


def _abbreviations(name):
    """The abbreviations one entry is filed under, from the parentheses at the end of its name."""
    match = _TRAILING.search(name)
    if match is None:
        return [name] if _CODE.fullmatch(name) else []
    return [part.strip() for part in _SEPARATORS.split(match.group(1)) if _CODE.fullmatch(part.strip())]


def _smiles(value):
    """An entry's SMILES. A plain value is the SMILES; an object carries it under `smiles`.

    Both spellings are read because the file is allowed to grow fields per entry (an experimental aggregation number
    and its citation, for one), and a reader that insisted on the flat shape would stop reading the file rather than
    read past a field it does not use.
    """
    if isinstance(value, dict):
        return value.get('smiles') or ''
    return value if isinstance(value, str) else ''


def entries(root):
    """The registry as a list, in file order: `{name, smiles, abbreviations}` per entry."""
    document = json.loads(registry_path(root).read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        raise ValueError(f'{REGISTRY_FILE} must be a map of detergent name to SMILES')
    return [{'name': name, 'smiles': _smiles(smiles), 'abbreviations': _abbreviations(name)}
            for name, smiles in document.items()]


def codes(root):
    """`{abbreviation: registry name}`: the lookup a molecule id is judged by."""
    found = {}
    for entry in entries(root):
        for code in entry['abbreviations']:
            found.setdefault(code, entry['name'])
    return found


def is_detergent(molecule_id, root):
    """Whether the registry files a molecule id under one of its entries."""
    return molecule_id in codes(root)


def require(molecule_id, root):
    """The registry entry a molecule is filed under, or a `ValueError` naming why it cannot be picked."""
    name = codes(root).get(molecule_id)
    if name is None:
        raise ValueError(f'{molecule_id} is not a detergent: {REGISTRY_FILE} files no entry under that name')
    return name


def select(records, root):
    """The molecule records that are detergents, each annotated with the registry entry that names it.

    The records are the catalogue's own, kept whole: the panel lists them and the run's molecule snapshot is built
    from one, so this filters rather than rebuilds.
    """
    index = codes(root)
    return [{**record, 'registry_name': index[record['id']]} for record in records
            if record.get('id') in index]
