"""The protein's own Martini moleculetypes, from the build stage a pdc run writes.

martinize2 emits one `molecule_N.itp` per chain under the build stage's `cg/` directory; the protein's beads are the
leading atoms of every trajectory that follows. A protein-free build has no directory and no protein molecules, which
is a state (`[]`), not an error.
"""
from __future__ import annotations

from pathlib import Path

from dashboard.analysis.runs import layout, structures

BUILD_STAGE = 'system'


def read_protein_topologies(run_dir) -> list[dict]:
    """The protein's moleculetypes, in trajectory (chain) order."""
    root = Path(run_dir)
    directory = layout.stage_dir(root, BUILD_STAGE)
    if directory is None or not (directory / 'cg').is_dir():
        return []

    def order(path):
        # Chain order is the trajectory's leading-atom order, so `molecule_10` follows `molecule_9`; a name sort
        # would put it before `molecule_2` and bond the wrong block.
        suffix = path.stem.rsplit('_', 1)[-1]
        return (0, int(suffix), path.name) if suffix.isdigit() else (1, 0, path.name)

    paths = sorted((directory / 'cg').glob('molecule_*.itp'), key=order)
    return [structures.read_moleculetype(path) for path in paths] if paths else []
