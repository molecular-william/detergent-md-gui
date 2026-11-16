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

import numpy as np
from dashboard.analysis.runs.radii import AA_RADII, PROBE
from detergent_validation.analysis.runs import surfaces

#: The mesh spacing a surface is first built at, in nm. 0.06 keeps a small molecule's mesh under the caps below.
DEFAULT_SPACING_NM = 0.06
#: The most beads a request may name. The overlay route caps at 2000; a mapping's own bead list is far smaller.
MAX_BEADS = 2000
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


def _cg_mesh(context, beads):
    """One sphere per bead that owns at least one known atom; a virtual site or an empty bead is skipped."""
    by_id = {int(atom['id']): atom for atom in context.get('atoms') or []}
    centres, radii, records = [], [], []
    for index, bead in enumerate(beads):
        if not isinstance(bead, dict) or bead.get('virtual_site'):
            continue
        points = []
        for value in bead.get('atoms') or []:
            try:
                atom = by_id.get(int(value))
            except (TypeError, ValueError):
                atom = None
            if atom is not None:
                points.append(atom['xyz'])
        if not points:
            continue
        centre = np.asarray(points, dtype=float).mean(axis=0)
        size = _size(bead)
        centres.append(centre)
        radii.append(SIZE_RADII_NM[size])
        records.append({'name': str(bead.get('name') or bead.get('export_name') or f'B{index + 1:02d}'),
                        'size': size, 'radius_nm': round(SIZE_RADII_NM[size], 5),
                        'centre_nm': [round(float(value), 5) for value in centre]})
    if not centres:
        return None, records
    return np.asarray(centres, dtype=float), np.asarray(radii, dtype=float), records


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


def build(context, beads, *, spacing_nm=DEFAULT_SPACING_NM):
    """The AA and CG meshes for one molecule context and one mapping's bead list.

    'context' is 'mapping_context.build_context''s record (atoms carry xyz in nm, element and id), and 'beads' the
    mapping's own list. A bead that maps no known atom owns no sphere; a virtual site names no atom of its own, so it
    is skipped rather than given a borrowed one. The returned spacing is the one both meshes were built at --
    coarsened from 'spacing_nm' only when the bounded grid would not fit -- and is what a caller draws both at.
    """
    aa = _aa_mesh(context)
    cg_positions, cg_radii, cg_records = _cg_mesh(context, beads)
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
                           'bead_count': len(cg_records), 'beads': cg_records},
                }
        spacing = round(spacing * COARSEN_FACTOR, 6)
    raise SurfaceTooLarge(f'the surface mesh would exceed {MAX_GRID_CELLS} grid cells or {MAX_VERTICES} vertices '
                          f'at every spacing tried; reduce the bead count or the molecule')
