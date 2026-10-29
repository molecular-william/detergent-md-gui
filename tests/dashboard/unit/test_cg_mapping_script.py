"""The one mapper, on the case no run has exercised: a mapping with no rings.

`sugar_mapping.py` used to be copied only for ringed mappings, so a mapping without rings went through bundled
`ff_map` plus a script that checked its output. Both are gone, which makes the rings-less case the mapper's own --
and nothing had ever run it. Its expected values are hand-computable, so this pins arithmetic rather than behaviour
that only looks right.
"""
import json
import os
import subprocess
import sys

import MDAnalysis as mda
import numpy as np
import pytest

from tests.harness.support import PACKAGE, PROJECT_ROOT

ROOT = PROJECT_ROOT
SCRIPT = PACKAGE / 'execution/scripts/sugar_mapping.py'
# Two beads of two atoms each, and no rings: bead A is atoms 1-2, bead B is atoms 3-4.
MODEL = {'beads': [{'name': 'A', 'export_name': 'B01', 'atoms': [1, 2]},
                   {'name': 'B', 'export_name': 'B02', 'atoms': [3, 4]}]}
FRAMES = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 4.0]],
                   [[0.0, 0.0, 2.0], [1.0, 0.0, 2.0], [0.0, 2.0, 2.0], [0.0, 0.0, 6.0]],
                   [[2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [2.0, 2.0, 0.0], [2.0, 0.0, 4.0]]], dtype=np.float32)
# A box that grows per frame, so "the AA frame's own box" is not the same value every time and a mapper that
# invented one would not pass by accident.
BOXES = np.array([[5.0, 5.0, 5.0, 90.0, 90.0, 90.0],
                  [6.0, 6.0, 6.0, 90.0, 90.0, 90.0],
                  [7.0, 7.0, 7.0, 90.0, 90.0, 90.0]], dtype=np.float32)


def _reference(directory):
    """A four-atom, three-frame atomistic reference, written the way a run's own copy is: a .gro and an .xtc."""
    directory.mkdir(parents=True, exist_ok=True)
    universe = mda.Universe.empty(4, n_residues=1, atom_resindex=[0, 0, 0, 0], trajectory=True)
    universe.add_TopologyAttr('names', ['C1', 'C2', 'C3', 'C4'])
    universe.add_TopologyAttr('resnames', ['LIG'])
    universe.add_TopologyAttr('resids', [1])
    with mda.Writer(str(directory / 'lig.xtc'), n_atoms=4) as writer:
        for index, positions in enumerate(FRAMES):
            universe.atoms.positions = positions
            universe.trajectory.ts.time = float(index)
            universe.dimensions = BOXES[index]
            if index == 0:
                universe.atoms.write(str(directory / 'lig.gro'))
            writer.write(universe.atoms)
    return directory


def _run(work, reference, **extra):
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=work, capture_output=True, text=True,
                          env={**os.environ, 'AA_REFERENCE_DIR': str(reference), **extra})


@pytest.fixture
def mapping_dir(tmp_path):
    reference = _reference(tmp_path / '1_AA-reference' / 'prod')
    work = tmp_path / '2_mapping'
    work.mkdir()
    (work / 'model.json').write_text(json.dumps(MODEL))
    return work, reference


def test_a_mapping_with_no_rings_maps_and_records_itself(mapping_dir):
    """No rings means nothing to expand and no ring targets -- not a failure, which is what the old branch implied."""
    work, reference = mapping_dir

    finished = _run(work, reference)
    assert finished.returncode == 0, finished.stderr

    produced = ('mapped.xtc', 'mapped.gro', 'mapped_scaled.xtc', 'mapped_scaled.gro',
                'ring_targets.json', 'mapping_validation.json')
    assert [name for name in produced if not (work / name).is_file()] == []

    record = json.loads((work / 'mapping_validation.json').read_text())
    assert record['frames'] == 3 and record['scientifically_validated'] is False
    assert json.loads((work / 'ring_targets.json').read_text())['constraints'] == []


def test_the_beads_are_the_heavy_atom_centres_of_geometry(mapping_dir):
    """The arithmetic, against values computed by hand rather than against the mapper's own idea of them."""
    work, reference = mapping_dir
    assert _run(work, reference).returncode == 0

    mapped = mda.Universe(str(work / 'mapped.gro'))
    assert list(mapped.atoms.names) == ['B01', 'B02']
    assert np.allclose(mapped.atoms.positions, [[0.5, 0.0, 0.0], [0.0, 1.0, 2.0]], atol=0.05)


def test_the_mapper_refuses_to_overwrite_an_earlier_mapping(mapping_dir):
    """The second half of the old script's job that has to survive: a re-run must not quietly replace a mapping."""
    work, reference = mapping_dir
    assert _run(work, reference).returncode == 0

    again = _run(work, reference)

    assert again.returncode != 0
    assert 'mapped.xtc' in (again.stderr + again.stdout)


def test_the_molecule_name_reaches_the_mapped_residue(mapping_dir):
    """A run-local script names the residue it writes; the stage passes the molecule, not a hard-coded default."""
    work, reference = mapping_dir
    assert _run(work, reference, MOLECULE_TYPE='DDM').returncode == 0

    assert mda.Universe(str(work / 'mapped.gro')).residues[0].resname == 'DDM'


def test_each_mapped_frame_keeps_its_own_time_and_box(mapping_dir):
    """Half of what the deleted script did for `ff_map`'s output: bundled `ff_map` stamped dt = 1 ps and its own box,
    so the frames stopped describing the frames they came from. This mapper carries both across, and a mapping read
    back with invented times would silently mis-date every later analysis of it."""
    work, reference = mapping_dir
    assert _run(work, reference).returncode == 0

    mapped = mda.Universe(str(work / 'mapped.xtc'))
    times = [float(frame.time) for frame in mapped.trajectory]
    boxes = [list(frame.dimensions[:3]) for frame in mapped.trajectory]

    assert times == [0.0, 1.0, 2.0]
    assert np.allclose(boxes, BOXES[:, :3])
