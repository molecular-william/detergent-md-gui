"""`ngl-beads.js` carries the model's radii, not a second opinion about them.

The panel draws a bead at the radius its size class has in Martini 3, and the one table of those radii is
`models/sugars/recognition.py`'s `RADII_NM`. A JavaScript copy of the numbers is unavoidable -- the viewer cannot
import Python -- so the copy is held here: if either table moves, this test fails rather than the picture quietly
drawing a size the model does not state. The element stand-ins are checked against the writer that uses them
(`models/compositions/topology.py`), because the panel reads a file that carries the class in that column.
"""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.models.compositions.topology import render_pdb  # noqa: E402
from dashboard.models.sugars import RADII_NM  # noqa: E402

SOURCE = PROJECT_ROOT / 'dashboard/web/static/js/ngl-beads.js'


def _table(name):
    match = re.search(rf'{name}\s*=\s*\{{([^}}]*)\}}', SOURCE.read_text())
    assert match, f'{name} is not in {SOURCE.name}'
    return match.group(1)


def _numbers(name):
    """One `{KEY: number}` table out of the module's text."""
    return {key.strip(): float(value) for key, value in re.findall(r'([A-Za-z]+)\s*:\s*([0-9.]+)', _table(name))}


def _strings(name):
    """One `{KEY: 'string'}` table out of the module's text."""
    return {key.strip(): value for key, value in re.findall(r"([A-Za-z]+)\s*:\s*'([A-Za-z]+)'", _table(name))}


def composition_pdb():
    """A composition PDB carrying one bead of every size class, written by its own renderer."""
    tail = {'beads': [{'name': 'T1', 'type': 'C1', 'mass': 54.0}], 'coordinates': [[0.0, 0.0, 0.0]]}
    mapping = {'beads': [{'name': 'R1', 'type': 'P1', 'size': 'R'},
                         {'name': 'S1', 'type': 'SP1', 'size': 'S'},
                         {'name': 'T2', 'type': 'TC4', 'size': 'T'},
                         {'name': 'T1', 'type': 'C1', 'size': 'R'}]}
    return render_pdb({'tail': tail, 'mapping': mapping,
                       'topology': {'bonds': [{'a': 'R1', 'b': 'S1', 'function': 1}]}})


def test_the_radii_table_is_the_models_own():
    """`BEAD_RADII_NM` and `recognition.RADII_NM` are the same three numbers, in the same unit (nanometres)."""
    assert _numbers('BEAD_RADII_NM') == {size: float(radius) for size, radius in RADII_NM.items()}


def test_the_element_stand_ins_are_the_ones_the_composition_writer_uses():
    """Each class' element in the file maps back to that class, as the composition writer writes them."""
    elements = {line[12:16].strip(): (line[17:20].strip(), line[76:78].strip()) for line
                in composition_pdb().splitlines() if line.startswith('HETATM')}
    stand_ins = _strings('SIZE_ELEMENTS')
    for name, (residue, element) in elements.items():
        if residue == 'SUG':                      # a head bead carries the mapping's own size class
            assert stand_ins[element] in RADII_NM, f'{name}: element {element} is not a class stand-in'
    assert len({stand_ins[element] for _, element in elements.values()}) == 3, elements


def test_the_scale_knob_defaults_to_the_models_own_radius():
    """`1` draws what the table states; a bigger number is a reading aid and never a new model."""
    assert re.search(r'BEAD_RADIUS_SCALE\s*=\s*1\s*;', SOURCE.read_text())
