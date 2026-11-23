"""LINCS warnings a run's stage log recorded, and the frame GROMACS wrote beside it.

GROMACS names the constrained atoms in every ``LINCS WARNING`` block and, for the severe ones, writes
``step<step>b.pdb`` (initial coordinates) and ``step<step>c.pdb`` (coordinates after constraining) next to the stage's
log. The warning's atom numbers are 1-based system indices and are the PDB serials of those files, so one reader maps
the warning to residue/bead names and measures the neighbourhood the reader has to look at.

This is a diagnostic reader, not a producer: it touches no file, starts no tool, and never invents a frame. A warning
whose step has no written pair keeps its exact bond table and reports no coordinates.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

WARNING = re.compile(r'^Step\s+(\d+),\s+time\s+([\d.eE+-]+)\s+\(ps\)\s+LINCS WARNING\s*$', re.M)
MAX_PAIR = re.compile(r'max\s+([\d.eE+-]+)\s+\(between atoms\s+(\d+)\s+and\s+(\d+)\)')
BOND_ROW = re.compile(r'^\s*(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.]+)\s*$', re.M)
FATAL = re.compile(r'Too many LINCS warnings\s*\((\d+)\)')
FRAME_NAME = re.compile(r'^step(\d+)([bc])\.pdb$')

#: Residues a neighbour is reported as solvent for. GROMACS writes the whole system into the warning frame; water and
#: ions are context, not the thing a reader is looking for, so they get their own row kind rather than being called a
#: short nonbonded contact.
SOLVENT_RESIDUES = {'W', 'SW', 'PW', 'SOL', 'HOH', 'TIP3', 'NA', 'CL', 'ION', 'K', 'CA', 'MG'}
#: The neighbourhood the card reports, in nm: enough to see the ring of beads around the failure without turning the
#: table into the whole box. The short-contact mark is deliberately below a bead radius: it names a clash, not a bond.
NEIGHBOUR_CUTOFF_NM = 0.5
SHORT_CONTACT_NM = 0.25
NEIGHBOUR_LIMIT = 30


def warnings_from_log(text: str) -> list[dict]:
    """Every ``LINCS WARNING`` block in one stage log, in the order mdrun wrote them.

    A block is the text between one warning header and the next. Only the block's own numbers are read: the step and
    time from the header, the maximum relative constraint deviation and its atom pair, and the table of bonds that
    rotated more than the profile's warning angle. Repeated rows are collapsed -- mdrun repeats a bond line while the
    system is already exploding, and one row per constrained bond is what a reader can use.
    """
    matches = list(WARNING.finditer(text))
    warnings = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end():end]
        pair = MAX_PAIR.search(block)
        bonds, seen = [], set()
        for a, b, angle, previous, current, constraint in BOND_ROW.findall(block):
            key = (int(a), int(b))
            if key in seen:
                continue
            seen.add(key)
            bonds.append({'a': int(a), 'b': int(b), 'angle_deg': float(angle),
                          'previous_nm': float(previous), 'current_nm': float(current),
                          'constraint_nm': float(constraint)})
        warnings.append({
            'step': int(match.group(1)),
            'time_ps': float(match.group(2)),
            'max_deviation': float(pair.group(1)) if pair else None,
            'atoms': [int(pair.group(2)), int(pair.group(3))] if pair else [],
            'bonds': bonds,
        })
    return warnings


def fatal_warnings(text: str) -> int | None:
    """The count mdrun reported when it stopped, when this log is the one that stopped it."""
    match = FATAL.search(text)
    return int(match.group(1)) if match else None


def read_pdb(path) -> dict:
    """The atoms of a warning frame by their serial, with the residue and bead name each record states.

    The serial is the identity the log's atom numbers use, so nothing here depends on the order of a second file. A
    malformed record is skipped rather than aborting the diagnostic: the rest of the frame is still readable.
    """
    atoms = {}
    for line in Path(path).read_text(errors='replace').splitlines():
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        try:
            serial = int(line[6:11])
            position = [float(line[30:38]) / 10.0, float(line[38:46]) / 10.0, float(line[46:54]) / 10.0]
        except ValueError:
            continue
        atoms[serial] = {'serial': serial, 'name': line[12:16].strip(), 'residue': line[17:20].strip(),
                         'residue_id': line[22:26].strip(), 'position_nm': position}
    return atoms


def frames_for(stage_directory, step: int) -> dict:
    """The written initial/constrained frame paths for one warning step, when GROMACS wrote them."""
    if stage_directory is None:
        return {}
    directory = Path(stage_directory)
    found = {}
    for suffix, key in (('b', 'initial'), ('c', 'constrained')):
        path = directory / f'step{step}{suffix}.pdb'
        if path.is_file() and not path.is_symlink():
            found[key] = path
    return found


def identities(atoms: dict, serials) -> dict:
    """The named atoms a warning references, keyed by serial, from the frame that was read."""
    named = {}
    for serial in serials:
        atom = atoms.get(int(serial))
        if atom:
            named[int(serial)] = {'serial': atom['serial'], 'name': atom['name'],
                                  'residue': atom['residue'], 'residue_id': atom['residue_id']}
    return named


def _kind(pair, bonds, other, atoms) -> str:
    if frozenset(pair) in bonds:
        return 'bonded'
    residue = atoms.get(other, {}).get('residue', '').upper()
    return 'solvent' if residue in SOLVENT_RESIDUES else 'nonbonded'


def neighbours(atoms: dict, pair, bonds, *, cutoff_nm: float = NEIGHBOUR_CUTOFF_NM,
               short_nm: float = SHORT_CONTACT_NM, limit: int = NEIGHBOUR_LIMIT) -> list[dict]:
    """The nearest atoms to the warning's max-deviation pair, with the kind of contact each one is.

    Distances are measured in the initial frame when the caller hands it: the constrained frame is already the
    explosion, so a saturated distance there says nothing about the geometry that failed. A bonded pair is shown
    because its constraint length is what the warning is about; a nonbonded pair below ``short_nm`` is the mark a
    reader should look at first. The limit keeps the table readable; the caller can lower the cutoff rather than
    printing the box.
    """
    if not atoms or len(pair) < 1:
        return []
    serials = sorted(atoms)
    xyz = np.asarray([atoms[serial]['position_nm'] for serial in serials], dtype=float)
    seeds = [int(serial) for serial in pair if int(serial) in atoms]
    bond_pairs = {frozenset((row['a'], row['b'])) for row in bonds}
    found, seen = [], set()
    for seed in seeds:
        distances = np.linalg.norm(xyz - np.asarray(atoms[seed]['position_nm'], dtype=float), axis=1)
        for index, serial in enumerate(serials):
            other = int(serial)
            if other == seed:
                continue
            contact = frozenset((seed, other))
            if contact in seen:
                continue
            distance = float(distances[index])
            if distance >= cutoff_nm:
                continue
            seen.add(contact)
            kind = _kind((seed, other), bond_pairs, other, atoms)
            found.append({
                'atom': seed, 'other': other, 'distance_nm': round(distance, 4), 'kind': kind,
                'short': kind == 'nonbonded' and distance < short_nm,
            })
    found.sort(key=lambda row: (row['distance_nm'], row['atom'], row['other']))
    return found[:limit]
