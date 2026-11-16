"""The mapped molecule's AA and CG surfaces: two meshes from a mapping, no run and no GROMACS.

The Bond Interactions Model pane draws the atomistic molecule and the coarse-grained model it maps to as one pair.
Both are derived from the molecule folder and the mapping the editor already holds: the AA surface is every atom's
van der Waals sphere, the CG surface is one sphere per atom-bearing bead at its Martini size class. 'surfaces.envelope'
adds the same probe to both, so the two meshes are solvent-accessible surfaces at one probe and one spacing and are
directly comparable.

Nothing here reads a run or starts a tool. The one cost is the marching-cubes grid, so the grid is bounded: a mesh
whose bounding grid (or vertex count) would exceed MAX_GRID_CELLS/MAX_VERTICES is recomputed at a coarser spacing,
and a molecule still over the cap after MAX_COARSEN_STEPS is refused rather than left to run.
"""
from __future__ import annotations

import math

import numpy as np
from dashboard.analysis.runs.radii import AA_RADII, PROBE
from dashboard.models.sugars import coords as sugar_coords
from detergent_validation.analysis.runs import surfaces

#: The mesh spacing a surface is first built at, in nm. 0.06 keeps a small molecule's mesh under the caps below.
DEFAULT_SPACING_NM = 0.06
#: The most beads a request may name. The overlay route caps at 2000; a mapping's own bead list is far smaller.
MAX_BEADS = 2000
#: The rings and connections a request may name, and how far one ring may be dilated. The mapping schema's own ring
#: scale is 0.5-2.0, so this ceiling is the table's edit on top of it: a 2 nm constraint over a ~0.2 nm ring edge is
#: about 10x, and a request beyond that is a mistyped length rather than a ring.
MAX_RINGS = 200
MAX_RING_BEADS = 50
MAX_RING_SCALE = 10.0
MAX_CONNECTIONS = 4000
#: The bounded marching-cubes grid and output size. Beyond these a mesh is coarsened, then refused.
MAX_GRID_CELLS = 120_000
MAX_VERTICES = 120_000
#: How many times a mesh is retried at a coarser spacing before the request is refused.
MAX_COARSEN_STEPS = 3
COARSEN_FACTOR = 1.5
#: The Martini 3 size class radii, nm. The overlay's SIZE_RADII/10 states the same three numbers (they are Angstrom
#: there); a change to one without the other is a pane that draws two bead sizes for one mapping.
SIZE_RADII_NM = {'R': 0.264, 'S': 0.230, 'T': 0.191}


class SurfaceTooLarge(ValueError):
    """The molecule's surface cannot be meshed under the bounded grid at any spacing this route tries."""


def _size(bead) -> str:
    """The bead's Martini size class: the mapping's own recorded size, else the class its type prefixes."""
    recorded = str(bead.get('size') or '').strip().upper()
    if recorded in SIZE_RADII_NM:
        return recorded
    letter = str(bead.get('type') or '')[:1].upper()
    return letter if letter in SIZE_RADII_NM else 'R'


def _aa_mesh(context):
    """Every atom's van der Waals sphere, with carbon's radius for an element this repository does not carry."""
    atoms = context.get('atoms') or []
    positions = np.asarray([atom['xyz'] for atom in atoms], dtype=float)
    radii = [AA_RADII.get(str(atom.get('element') or ''), AA_RADII['C']) for atom in atoms]
    if not len(positions):
        return None
    return positions, np.asarray(radii, dtype=float)


def _checked_rings(rings):
    """The request's rings: a bead-name list and a positive scale, which is the mapping's ring scale times the edit."""
    if rings is None:
        return []
    if not isinstance(rings, list) or len(rings) > MAX_RINGS:
        raise ValueError(f'rings must be a list of at most {MAX_RINGS} entries')
    checked = []
    for ring in rings:
        names = ring.get('beads') if isinstance(ring, dict) else None
        if (not isinstance(names, list) or not 2 <= len(names) <= MAX_RING_BEADS
                or not all(isinstance(name, str) and name for name in names)):
            raise ValueError(f'Each ring must name between 2 and {MAX_RING_BEADS} beads')
        scale = ring.get('scale')
        if (isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale)
                or not 0 < scale <= MAX_RING_SCALE):
            raise ValueError(f'Each ring scale must be a number above 0 and at most {MAX_RING_SCALE:g}')
        checked.append({'beads': list(names), 'scale': float(scale)})
    return checked


def _checked_connections(connections):
    """The mapping's connections: bead-name pairs whose mapped link vectors the placement keeps."""
    if connections is None:
        return []
    if not isinstance(connections, list) or len(connections) > MAX_CONNECTIONS:
        raise ValueError(f'connections must be a list of at most {MAX_CONNECTIONS} pairs')
    checked = []
    for pair in connections:
        if (not isinstance(pair, list) or len(pair) != 2
                or not all(isinstance(name, str) and name for name in pair)):
            raise ValueError('Each connection must name two beads')
        checked.append([pair[0], pair[1]])
    return checked


def _representation(mode):
    """The mapping's carbohydrate representation. 'tc4' places a virtual site from its parents, so it can carry a link."""
    if mode is None or mode == 'tc4':
        return 'tc4'
    if mode != 'physical_only_ring_constrained':
        raise ValueError('Unknown carbohydrate representation')
    return mode


def _bead_name(bead):
    return str(bead.get('name') or bead.get('export_name') or '')


def _atom_numbers(bead, known):
    """The bead's atom ids this molecule actually carries."""
    numbers = []
    for value in bead.get('atoms') or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number in known:
            numbers.append(number)
    return numbers


def _placing_beads(context, beads, representation_mode):
    """The beads the run's placement can position: a physical bead with a known atom, and under tc4 a virtual site
    whose parents it can place.

    A bead with neither owns no sphere and no link, which is why the ring and connection lists are filtered with it:
    'sugars.coords.coordinates' reads a mean over every bead it is handed.
    """
    known = {int(atom['id']) for atom in context.get('atoms') or []}
    physical, sites = [], []
    for bead in beads:
        if not isinstance(bead, dict):
            continue
        name = _bead_name(bead)
        if not name:
            continue
        if bead.get('virtual_site'):
            sites.append({**bead, 'name': name})
            continue
        atoms = _atom_numbers(bead, known)
        if atoms:
            physical.append({**bead, 'name': name, 'atoms': atoms})
    names = {bead['name'] for bead in physical}
    placed = list(physical)
    if representation_mode == 'tc4':
        placed += [bead for bead in sites
                   if all(str(parent) in names for parent in bead['virtual_site'].get('parents') or [])]
    return placed


def _placement(context, beads, rings, connections, representation_mode):
    """The CG bead positions a run starts from: each ring dilated by its scale, connected parts shifted to keep links.

    'sugars.coords.coordinates(scaled=True)' is the placement a run's mapped .gro is written from -- the ring
    dilation and the rigid-group shift that preserves the mapped link vectors -- so the pane draws the run's own CG
    geometry rather than a picture of it. The rings it returns are the ones that survived, for the status sentence.
    """
    placed = _placing_beads(context, beads, representation_mode)
    keep = {bead['name'] for bead in placed}
    data = {
        'beads': placed,
        'rings': [{'beads': [name for name in ring['beads'] if name in keep], 'scale': ring['scale']}
                  for ring in rings],
        'connections': [[first, second] for first, second in connections
                        if first in keep and second in keep],
    }
    data['rings'] = [ring for ring in data['rings'] if len(ring['beads']) >= 2]
    if not placed:
        return {}, []
    positions = np.asarray([atom['xyz'] for atom in context.get('atoms') or []], dtype=float)
    ids = [int(atom['id']) for atom in context.get('atoms') or []]
    xyz = sugar_coords.coordinates(data, positions, atom_ids=ids, scaled=True,
                                   representation_mode=representation_mode)
    return ({bead['name']: np.asarray(xyz[index], dtype=float) for index, bead in enumerate(placed)},
            data['rings'])


def _cg_mesh(beads, centres):
    """One sphere per bead that owns at least one known atom; a virtual site or an empty bead is skipped."""
    sphere_centres, radii, records = [], [], []
    for index, bead in enumerate(beads):
        if not isinstance(bead, dict) or bead.get('virtual_site'):
            continue
        centre = centres.get(_bead_name(bead))
        if centre is None:
            continue
        size = _size(bead)
        sphere_centres.append(centre)
        radii.append(SIZE_RADII_NM[size])
        records.append({'name': _bead_name(bead) or f'B{index + 1:02d}',
                        'size': size, 'radius_nm': round(SIZE_RADII_NM[size], 5),
                        'centre_nm': [round(float(value), 5) for value in centre]})
    if not sphere_centres:
        return None, records
    return np.asarray(sphere_centres, dtype=float), np.asarray(radii, dtype=float), records


def _grid_cells(positions, radii, spacing_nm) -> int:
    """The cells 'surfaces.envelope' would allocate for this mesh, before it allocates them."""
    inflated = np.asarray(radii, dtype=float) + PROBE
    low = (positions - inflated[:, None]).min(axis=0) - spacing_nm
    high = (positions + inflated[:, None]).max(axis=0) + spacing_nm
    shape = np.ceil((high - low) / spacing_nm).astype(int) + 1
    return int(np.prod(shape))


def _fits(positions, radii, spacing_nm) -> bool:
    return positions is None or _grid_cells(positions, radii, spacing_nm) <= MAX_GRID_CELLS


def _round_vertices(vertices) -> list[list[float]]:
    return [[round(float(value), 5) for value in row] for row in vertices]


def _faces(faces) -> list[list[int]]:
    return [[int(value) for value in row] for row in faces]


def build(context, beads, *, rings=None, connections=None, representation_mode=None,
          spacing_nm=DEFAULT_SPACING_NM):
    """The AA and CG meshes for one molecule context and one mapping's bead list.

    'context' is 'mapping_context.build_context''s record (atoms carry xyz in nm, element and id), and 'beads' the
    mapping's own list. A bead that maps no known atom owns no sphere; a virtual site names no atom of its own, so it
    is skipped rather than given a borrowed one. 'rings' and 'connections' are the mapping's own, with each ring's
    scale already carrying the table's pending edit, so the CG mesh is the geometry a run would start from -- rings
    dilated, connected parts shifted to keep the mapped links. The AA mesh never moves: a ring scale is a CG
    constraint target, not a fact about the atoms. The returned spacing is the one both meshes were built at --
    coarsened from 'spacing_nm' only when the bounded grid would not fit -- and is what a caller draws both at.
    """
    checked_rings = _checked_rings(rings)
    checked_connections = _checked_connections(connections)
    representation = _representation(representation_mode)
    centres, applied_rings = _placement(context, beads, checked_rings, checked_connections, representation)
    aa = _aa_mesh(context)
    cg_positions, cg_radii, cg_records = _cg_mesh(beads, centres)
    spacing = float(spacing_nm)
    for _attempt in range(MAX_COARSEN_STEPS + 1):
        aa_fits = aa is None or _fits(aa[0], aa[1], spacing)
        if aa_fits and _fits(cg_positions, cg_radii, spacing):
            aa_vertices, aa_faces = ([], []) if aa is None else surfaces.envelope(aa[0], aa[1], spacing)
            cg_vertices, cg_faces = (([], []) if cg_positions is None
                                     else surfaces.envelope(cg_positions, cg_radii, spacing))
            if len(aa_vertices) <= MAX_VERTICES and len(cg_vertices) <= MAX_VERTICES:
                return {
                    'probe_nm': PROBE, 'spacing_nm': spacing,
                    'aa': {'vertices': _round_vertices(aa_vertices), 'faces': _faces(aa_faces),
                           'atom_count': len(context.get('atoms') or [])},
                    'cg': {'vertices': _round_vertices(cg_vertices), 'faces': _faces(cg_faces),
                           'bead_count': len(cg_records), 'beads': cg_records,
                           'rings': [{'beads': list(ring['beads']), 'scale': round(ring['scale'], 6)}
                                     for ring in applied_rings]},
                }
        spacing = round(spacing * COARSEN_FACTOR, 6)
    raise SurfaceTooLarge(f'the surface mesh would exceed {MAX_GRID_CELLS} grid cells or {MAX_VERTICES} vertices '
                          f'at every spacing tried; reduce the bead count or the molecule')
