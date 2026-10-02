"""A molecule's own fitted terms are preferred to a published value for the same bead-type pair.

The ranking's first key is whether the term's source path carries the molecule, and it was dead: it was handed the
mapping's *whole* name (`DDM draft from the automatic recogniser (Martini 3)`) and tested that as a substring of the
path, which is never true. `references/bartender/DDM.itp` could therefore sit in the tree and never be chosen -- which
is exactly what the file below would have done before this test existed.

The tree is built here rather than read from the checkout: the fitted file is a real repository asset, but the decoy
that proves the molecule is what decides is the test's own.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from dashboard.models.bonded import generation

REPO_ROOT = Path(__file__).resolve().parents[3]
FITTED = REPO_ROOT / 'references' / 'bartender' / 'DDM.itp'

#: The same bead types as the fitted file, with different values and another molecule's name: whichever molecule is
#: asked for must win on its own name alone.
DECOY = """; a decoy reference, so that the molecule is the only thing that can decide between the two
[ moleculetype ]
SUC                 1

[ atoms ]
1 SP1r 1 SUC A 1 0 54
2 C1   1 SUC B 2 0 72

[ bonds ]
1 2 1 0.999 1234.5
"""


def project(tmp_path) -> Path:
    root = tmp_path / 'project'
    target = root / 'references' / 'bartender'
    target.mkdir(parents=True)
    shutil.copy2(FITTED, target / 'DDM.itp')
    (target / 'Sucrose.itp').write_text(DECOY)
    return root


def test_the_fitted_terms_are_indexed_by_bead_type(tmp_path):
    index = generation.reference_bond_index(project(tmp_path))

    records = index['bonds']['C1|SP1r']

    fitted = [record for record in records
              if any('bartender/ddm.itp' in reference['path'].lower() for reference in record['references'])]
    assert fitted, 'the fitted junction bond is indexed under the types it joins'
    assert fitted[0]['parameters'] == [0.528, 394.25], 'and carries the fit, not a published value'


def test_the_molecule_decides_which_reference_wins(tmp_path):
    index = generation.reference_bond_index(project(tmp_path))

    _, mine, _ = generation._select_reference(index, 'bonds', ['C1', 'SP1r'], 'DDM')
    _, theirs, _ = generation._select_reference(index, 'bonds', ['C1', 'SP1r'], 'Sucrose')

    assert mine['parameters'] == [0.528, 394.25], 'DDM gets its own fit'
    assert theirs['parameters'] == [0.999, 1234.5], 'and another molecule does not'


def test_without_a_molecule_nothing_is_preferred_by_name(tmp_path):
    """The ranking still has to work for a mapping with no molecule: the published paths decide then."""
    index = generation.reference_bond_index(project(tmp_path))

    _, chosen, _ = generation._select_reference(index, 'bonds', ['C1', 'SP1r'], '')

    assert chosen['parameters'] in ([0.528, 394.25], [0.999, 1234.5]), chosen
