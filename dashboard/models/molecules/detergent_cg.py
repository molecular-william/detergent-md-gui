"""A detergent's coarse-grained draft, derived from its saved mapping and the atomistic structure.

The mapping is the human decision (which atoms form a bead, what type it is, where the ring virtual sites are); this
module is the machinery that turns it into the two things a stage needs: a CG topology (from
`bonded.generation`, which takes the bonded terms from whatever Martini 3 references cover the bead-type pairs and
falls back to the geometry where none do) and the beads' own coordinates, so a placement can stamp a real molecule
rather than a dot.

Everything here is derived, so nothing is stored: a run re-derives it from the mapping it recorded, which is why the
provenance (how many terms were references and how many were fallbacks) travels with the answer instead of with a
file someone might edit.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..bonded import generation
from ..mappings.context import as_structure, build_context


def candidate(path) -> dict:
    """A saved mapping, with the two fields a derivation needs checked before anything is computed."""
    data = json.loads(Path(path).read_text())
    if not isinstance(data.get('beads'), list) or not data['beads']:
        raise ValueError(f'{path} carries no beads: it is not a mapping candidate')
    if not data.get('molecule_id'):
        raise ValueError(f'{path} names no molecule, so its structure cannot be resolved')
    return data


def bead_centres(data: dict, structure: dict) -> dict[str, list[float]]:
    """Each bead's own position, in nanometres: the mean of its atoms, or the centroid of its parents when virtual.

    A ring virtual site is not an atom group, so its position is built the way the topology declares it (function 1:
    the centre of its parents). A bead with neither atoms nor parents is a mapping that cannot be placed.
    """
    coordinates = {int(atom['id']): [float(value) / 10.0 for value in atom.get('xyz', (0, 0, 0))]
                   for atom in structure.get('atoms', [])}
    centres: dict[str, list[float]] = {}
    for bead in data['beads']:
        atoms = [int(index) for index in bead.get('atoms') or []]
        if atoms:
            if any(index not in coordinates for index in atoms):
                raise ValueError(f'{bead["name"]}: the mapping names atoms the structure does not have')
            centres[bead['name']] = [sum(coordinates[index][axis] for index in atoms) / len(atoms)
                                     for axis in range(3)]
            continue
        site = bead.get('virtual_site') or {}
        parents = [str(name) for name in site.get('parents') or []]
        if int(site.get('function', 0)) != 1 or len(parents) < 2:
            raise ValueError(f'{bead["name"]}: a bead with no atoms must be a function-1 virtual site with parents')
        if any(name not in centres for name in parents):
            raise ValueError(f'{bead["name"]}: its parents {parents} are not beads placed before it')
        centres[bead['name']] = [sum(centres[name][axis] for name in parents) / len(parents) for axis in range(3)]
    return centres


def named_topology(text: str, residue: str) -> str:
    """The generated topology with its molecule and its atoms named after the mapping's molecule.

    `bonded.generation` writes a fixed molecule name everywhere, and `grompp` matches the topology's molecule name
    against the structure's residue name -- two names for one molecule is the mismatch that cost three failed sugar
    runs, so the rename happens here rather than being asserted for later. The `[ atoms ]` rows carry the residue in
    their own column, which is what a reader sees beside the coordinates.
    """
    lines = text.splitlines()
    section = ''
    renamed = False
    for index, line in enumerate(lines):
        stripped = line.split(';', 1)[0].strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1].strip().lower()
            if section == 'moleculetype':
                continue
        elif section == 'moleculetype' and stripped:
            lines[index] = ' '.join([residue, *stripped.split()[1:]]) + _comment(line)
            renamed = True
            section = 'named'
        elif section == 'atoms' and stripped:
            fields = stripped.split()
            if len(fields) >= 5:
                lines[index] = ' '.join([fields[0], fields[1], fields[2], residue, *fields[4:]]) + _comment(line)
    if not renamed:
        raise ValueError('the generated topology has no [ moleculetype ] section to name')
    return '\n'.join(lines) + '\n'


def _comment(line: str) -> str:
    return f'  ;{line.split(";", 1)[1]}' if ';' in line else ''


def derive(candidate_path, molecule_root, project_root) -> dict:
    """The draft: the topology text, the beads with their coordinates, and how the terms were decided.

    The residue is the mapping's molecule, so the topology's `[ moleculetype ]` name is the same word the structure
    writes for the residue -- `grompp` reconciles topology and coordinates by name, and two names for one molecule is
    the failure that is worth designing out rather than testing for later.
    """
    data = candidate(candidate_path)
    residue = str(data['molecule_id'])[:5]
    structure = as_structure(build_context(Path(molecule_root), data['molecule_id']))
    generated = generation.generate(data, structure, Path(project_root))
    centres = bead_centres(data, structure)
    provenance = [term.get('provenance') or {} for term in generated['interactions']]
    beads = [{'name': bead['name'], 'residue': residue, 'type': bead.get('type'),
              'position': centres[bead['name']], 'virtual_site': bool(bead.get('virtual_site'))}
             for bead in data['beads']]
    return {'molecule_id': data['molecule_id'], 'residue': residue, 'beads': beads,
            'topology': named_topology(generated['topology'], residue),
            'terms': len(generated['interactions']),
            'reference_terms': sum(1 for entry in provenance if not entry.get('fallback')),
            'fallback_terms': sum(1 for entry in provenance if entry.get('fallback')),
            'diagnostics': list(generated['diagnostics']),
            'mapping_file': str(candidate_path)}
