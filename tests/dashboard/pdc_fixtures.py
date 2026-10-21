"""The molecule tree and prepared run the pdc tests share.

Thirteen files carried their own `molecule_tree`, thirteen their own `prepared`, and the bodies had already drifted:
`aggregation_number` was 4 in some files and 8 in others, the seed 20260930 in one and 20261014 in another. The
duplication was not only reader effort -- a change to the defaults was a nine-file edit, and the files disagreed.

What stays per file is what a file *means*: the settings it varies and the directory it wants back. A file writes

    def prepared(tmp_path, **settings):
        return prepared_run(tmp_path, settings={'assessment_ns': 100} | settings, suffix=ASSESSMENT)

and the construction -- the tree, the template, the run directory, `pdc.prepare` -- lives here once.

`template` is an argument rather than a constant because five distinct template bodies are in use across the block;
a single default would silently change what four of them build. The files that share the common body use
`TEMPLATE`; a file with a different one passes it.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.execution.adapters import pdc

#: The template eight of the pdc test files use. A file with a different one passes its own to `molecule_tree`.
TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'DDM', 'type': 'registered-template'}],
}
PROTEIN = 'molecules/DDM/protein.pdb'
TEMPLATE_PATH = 'molecules/DDM/micelle_template.json'
#: The two settings every pdc test prepared with, before the file says what it is varying.
DEFAULT_SETTINGS = {'seed': 20260930, 'aggregation_number': 8}

PDB_LINE = 'HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n'
ITP_LINE = '[ moleculetype ]\nDDM             1\n'
PROTEIN_LINE = 'ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n'


def molecule_tree(tmp_path: Path, template: dict | None = None) -> Path:
    """A molecule directory shaped like the ones the catalogue lists, under the test's own root."""
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True, exist_ok=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text(PDB_LINE)
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text(ITP_LINE)
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE if template is None else template))
    (molecule / 'protein.pdb').write_text(PROTEIN_LINE)
    return tmp_path


def prepared_run(tmp_path: Path, *, settings: dict | None = None, suffix=None,
                 protein: str = PROTEIN, template: str = TEMPLATE_PATH, template_body: dict | None = None,
                 project_root: Path | None = None, directory: str = 'run') -> Path:
    """A prepared pdc run under `tmp_path`, optionally resolved to one stage directory.

    `suffix` is the stage path a file wants back (`ASSESSMENT`, `EXTENSION`); without it the run directory itself is
    returned, which is what a file asserting on the manifest needs.
    """
    root = molecule_tree(tmp_path, template_body) if project_root is None else project_root
    numbers = {**DEFAULT_SETTINGS, **(settings or {})}
    run = tmp_path / directory
    run.mkdir(parents=True, exist_ok=True)
    pdc.prepare(run, protein=protein, template=template, settings=numbers, project_root=root)
    return run / suffix if suffix else run


def stage_dir(run: Path, stage_name: str) -> Path:
    """The directory a named stage runs in, resolved through the protocol rather than by counting positions."""
    return run / Path(pdc.stage_by_name(stage_name).relative).parent
