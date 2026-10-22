"""A detergent's coarse-grained draft, derived from its saved mapping and the atomistic structure.

The mapping is the human decision (which atoms form a bead, what type it is, where the ring virtual sites are); this
module is the machinery that turns it into the two things a stage needs: a CG topology (from
`bonded.generation`, which takes the bonded terms from whatever Martini 3 references cover the bead-type pairs and
falls back to the geometry where none do) and the beads' own coordinates, so a placement can stamp a real molecule
rather than a dot.

Everything here is derived, so nothing is stored: a run re-derives it from the mapping it recorded, which is why the
provenance (how many terms were references and how many were fallbacks) travels with the answer instead of with a
file someone might edit.

There is one thing a mapping may carry that is *not* derived: a fitted parameterization (`bonded.parameterization`),
the mapping's own bonded terms with a revision behind them. `adopt` takes that topology instead of generating one,
renaming its atoms to the mapping's own bead names and refusing a fit of a different molecule -- a run that has been
fitted must simulate the fit, and one that has not must say it did not.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..bonded import generation, parameterization
from ..mappings.context import as_structure, build_context
from ..sugars.units import angstrom_factor


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

    The coordinates are converted by the structure's *own* unit factor rather than by a fixed ten. A structure from
    the molecule context already holds nanometres, and dividing it again is the defect the sugar topology writer and
    the mapping export each had -- `dashboard/models/sugars/units.py` states it -- where the generated ring
    constraints came out a factor of ten short of the reference's. Here it came out as a placeable molecule a tenth
    of its size, stamped beside a topology whose constraints were in the right unit: measured on `pdc` run
    `8a73fe6448f2`, the beads of one detergent sat 0.021-0.037 nm apart while their ring constraints asked for
    0.32-0.43 nm.
    """
    factor = angstrom_factor(structure)
    coordinates = {int(atom['id']): [float(value) * factor for value in atom.get('xyz', (0, 0, 0))]
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


def adopt(draft: dict, revision: dict) -> dict:
    """A parameterization revision's topology, with its atoms named the way the mapping names them.

    The fit's own topology names its beads `B01`..`B11`: those are the export names `bonded.generation` writes, not
    the mapping's (`S1A`, `TAIL1`). `pdc_build.stamp` writes the mapping's names into `system.gro`, and `grompp`
    reconciles a topology with its coordinates by atom name, so the two spellings are a build that fails eleven times
    over at the first stage that runs `grompp`. Only the `[ atoms ]` name column is rewritten -- every other section
    addresses atoms by number, so a bond, an angle and a ring constraint are the same term afterwards -- and the
    comment header, the molecule type and every parameter line are left byte-for-byte as the fit wrote them.

    What it refuses, and why here rather than at `grompp`: a topology whose atom count, bead types or molecule name
    disagree with this mapping is a fit of a *different* model, and adopting it would simulate one molecule under
    another molecule's name. The count and the types are the two facts the two records share, so they are what is
    checked, and the refusal names the atom whose type differs -- "12 against 11" without a position is a search.

    Returns the renamed text, the revision's own term counts, the bead names it wrote, and one line of provenance.
    """
    topology = str((revision or {}).get('topology') or '')
    if not topology.strip():
        raise ValueError('the parameterization revision carries no topology to adopt')
    beads = list(draft.get('beads') or [])
    names = [str(bead.get('name') or '') for bead in beads]
    types = [str(bead.get('type') or '') for bead in beads]
    lines = topology.splitlines()
    section = ''
    atoms: list[int] = []
    molecule = None
    for index, line in enumerate(lines):
        content = line.split(';', 1)[0].strip()
        if content.startswith('[') and content.endswith(']'):
            section = content[1:-1].strip().lower()
            continue
        if not content:
            continue
        if section == 'atoms':
            atoms.append(index)
        elif section == 'moleculetype' and molecule is None:
            molecule = content.split()[0]
    if not atoms:
        raise ValueError("the parameterization's topology has no [ atoms ] section")
    if len(atoms) != len(beads):
        raise ValueError(f"the parameterization's topology declares {len(atoms)} atoms and the mapping has "
                         f'{len(beads)}')
    residue = str(draft.get('residue') or '')
    if molecule is not None and residue and molecule != residue:
        raise ValueError(f"the parameterization's topology names its molecule {molecule} and the mapping's residue "
                         f'is {residue}: grompp matches a topology to its coordinates by name')
    for position, (index, name, type_) in enumerate(zip(atoms, names, types), start=1):
        body, separator, comment = lines[index].partition(';')
        fields = list(re.finditer(r'\S+', body))
        if len(fields) < 5:
            raise ValueError(f"the parameterization's topology declares atom {position} with fewer than five "
                             'columns, so it has no name to adopt')
        declared = fields[1].group()
        if declared != type_:
            raise ValueError(f'atom {position} is {declared} in the parameters and {type_} in the mapping')
        start, end = fields[4].span()
        lines[index] = f'{body[:start]}{name}{body[end:]}{separator}{comment}'
    counts = revision.get('terms')
    counts = dict(counts) if isinstance(counts, dict) and counts else parameterization.term_counts(revision)
    source = (f"the mapping's current parameterization: revision {revision.get('revision')}, "
              f"engine {revision.get('engine')}, content hash {revision.get('mapping_content_hash')}")
    return {'topology': '\n'.join(lines) + ('\n' if topology.endswith('\n') else ''),
            'terms': counts, 'total': parameterization.total_terms(revision),
            'bead_names': names, 'molecule': molecule, 'source': source}
