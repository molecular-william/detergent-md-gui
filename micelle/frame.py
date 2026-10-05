"""Where a membrane is: the slab a detergent belt is placed around, and the axis it faces along.

One definition, shared by the placement, the box and the assessment. The builder used to infer the belt's thickness
and measure it from the protein's own centroid; on OPM 1qj8 that put 361 of 1,158 atoms on the wrong side of the
line, because the atom-mean sits 0.73 nm above the plane the bilayer actually straddles.

OPM's convention is that a structure arrives already rotated, so the bilayer is the xy-plane through z = 0 and no
correction is applied here. What a frame adds is the thickness the structure states and the origin the belt is
measured from -- which is the whole point, since a thickness nobody states is not a measurement.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_AXIS = (0.0, 0.0, 1.0)
# The file's own statement of its membrane. It travels with the coordinates, unlike a number on a page that linked
# them, which is why the structure is the authority and the page is not.
_HALF_THICKNESS = re.compile(r'^REMARK\s+1/2 of bilayer thickness:\s*([0-9.]+)', re.MULTILINE)


@dataclass(frozen=True)
class MembraneFrame:
    """The hydrophobic slab: two planes along an axis, and where those numbers came from.

    `plane_low_nm` and `plane_high_nm` are absolute coordinates along the axis, so a frame whose slab is not centred
    on its origin is expressible without a second convention.
    """

    plane_low_nm: float
    plane_high_nm: float
    axis: tuple = DEFAULT_AXIS
    source: str = ''

    @property
    def half_thickness_nm(self):
        return round((self.plane_high_nm - self.plane_low_nm) / 2, 6)

    @property
    def centre_nm(self):
        return round((self.plane_high_nm + self.plane_low_nm) / 2, 6)

    def as_record(self):
        """The frame as a report or a manifest holds it.

        Flat and named for a reader: the half-thickness is what a person compares against the structure's own REMARK,
        and it is the same key the catalogue and the sidecar carry. `__dict__` would have omitted it, being derived
        rather than stored.
        """
        return {'half_thickness_nm': self.half_thickness_nm, 'plane_low_nm': self.plane_low_nm,
                'plane_high_nm': self.plane_high_nm, 'centre_nm': self.centre_nm, 'axis': list(self.axis),
                'source': self.source}


def frame_from_structure(half_thickness_nm, *, axis=DEFAULT_AXIS, source=''):
    """The frame a structure states for itself, centred on the plane its own coordinates straddle.

    A frame is never constructed without a thickness. That is deliberate: the defect this replaces was a silent
    1.0 nm, and a guessed number is indistinguishable from a measured one once it is in a manifest. A structure that
    states nothing gets no frame at all, and its caller keeps the behaviour it had.
    """
    if half_thickness_nm is None:
        raise ValueError('a membrane frame needs a half-thickness; an unstated membrane is not a frame')
    half = abs(float(half_thickness_nm))
    return MembraneFrame(round(-half, 6), round(half, 6), unit_axis(axis), str(source))


def belt_mask(points, frame):
    """Which points lie inside the slab, along the frame's axis.

    The axis is projected onto, never indexed: a frame can face any way, and a reader that assumes z would call every
    atom of a y-facing bilayer outside it.
    """
    return [bool(frame.plane_low_nm <= value <= frame.plane_high_nm) for value in _axial(points, frame)]


def belt_points(points, frame):
    """The atoms inside the slab, as they are, so a caller can measure the belt's footprint and not only count it."""
    return [list(point) for point, inside in zip(points, belt_mask(points, frame)) if inside]


def unit_axis(axis):
    """A frame's direction, normalised, so a slab is measured in nanometres whatever vector it was stated with."""
    vector = np.asarray(axis, dtype=float)
    length = float(np.linalg.norm(vector))
    if not length:
        raise ValueError('a membrane frame needs a direction, and this one has no length')
    return tuple(vector / length)


def stated_half_thickness_nm(text):
    """The half-thickness a structure states for itself, in nanometres, or `None`.

    One definition, shared by the importer that records it in a sidecar and the builder that reads it out of the file
    it was handed: two readers of the same REMARK would eventually disagree about it. `None` rather than a default,
    because a structure that states nothing must stay unstated.
    """
    match = _HALF_THICKNESS.search(text)
    return round(float(match.group(1)) / 10, 4) if match else None


def frame_from_pdb(path):
    """The frame the structure at `path` states for itself, or `None` when it states no membrane.

    `None` is the answer for most structures, and it is a useful one: the caller keeps the box and the placement it
    had rather than being handed a membrane nobody measured.
    """
    half = stated_half_thickness_nm(Path(path).read_text(errors='replace'))
    if half is None:
        return None
    return frame_from_structure(half, source=f'{Path(path).name} REMARK')


def _axial(points, frame):
    """Each point's coordinate along the frame's axis, measured from the origin the planes are stated against."""
    array = np.asarray(points, dtype=float)
    if not len(array):
        return []
    return array @ np.asarray(unit_axis(frame.axis), dtype=float)
