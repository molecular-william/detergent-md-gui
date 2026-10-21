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


def molecule_tree(tmp_path: Path, template: dict | None = None, protein_text: str | None = None) -> Path:
    """A molecule directory shaped like the ones the catalogue lists, under the test's own root.

    `protein_text` because some files build a protein that states chains or remarks: the construction is shared, the
    structure a file is about is its own.
    """
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True, exist_ok=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text(PDB_LINE)
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text(ITP_LINE)
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE if template is None else template))
    (molecule / 'protein.pdb').write_text(PROTEIN_LINE if protein_text is None else protein_text)
    return tmp_path


def prepared_run(tmp_path: Path, *, settings: dict | None = None, suffix=None,
                 protein: str = PROTEIN, template: str = TEMPLATE_PATH, template_body: dict | None = None,
                 protein_text: str | None = None, project_root: Path | None = None,
                 directory: str = 'run') -> Path:
    """A prepared pdc run under `tmp_path`, optionally resolved to one stage directory.

    `suffix` is the stage path a file wants back (`ASSESSMENT`, `EXTENSION`); without it the run directory itself is
    returned, which is what a file asserting on the manifest needs.
    """
    root = molecule_tree(tmp_path, template_body, protein_text) if project_root is None else project_root
    numbers = {**DEFAULT_SETTINGS, **(settings or {})}
    run = tmp_path / directory
    run.mkdir(parents=True, exist_ok=True)
    pdc.prepare(run, protein=protein, template=template, settings=numbers, project_root=root)
    return run / suffix if suffix else run


def stage_dir(run: Path, stage_name: str) -> Path:
    """The directory a named stage runs in, resolved through the protocol rather than by counting positions."""
    return run / Path(pdc.stage_by_name(stage_name).relative).parent

def gro_line(residue_id, residue, name, serial, xyz) -> str:
    """One fixed-width `gro` atom line: nm, three decimals, the columns GROMACS actually reads."""
    return (f'{residue_id:5d}{residue:5s}{name:5s}{serial:5d}'
            f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}')


def write_gro(path: Path, atoms, box=(8.0, 8.0, 8.0)) -> Path:
    """A `gro` file a stage can read back: title, count, atoms, box."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['a system written by a test', str(len(atoms))]
    lines += [gro_line(residue_id, residue, name, index, xyz)
              for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    lines.append(''.join(f'{length:9.5f}' for length in box))
    path.write_text('\n'.join(lines) + '\n')
    return path


def write_cg_pdb(path: Path, atoms) -> Path:
    """The CG structure as martinize2 writes it (`-x`): `ATOM` records in Angstroms, the stage reads them back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'ATOM  {index:5d} {name:^4s} {residue:>3s} A{residue_id:4d}    '
             f'{xyz[0] * 10.0:8.3f}{xyz[1] * 10.0:8.3f}{xyz[2] * 10.0:8.3f}  1.00  0.00'
             for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1)]
    path.write_text('\n'.join(lines) + '\nEND\n')
    return path


def candidate_file(tmp_path: Path) -> Path:
    """A saved mapping candidate over the real DDM, two beads, shaped like the editor's export."""
    path = tmp_path / 'ddm_mapping.json'
    path.write_text(json.dumps({
        'schema_version': 3, 'molecule_id': 'DDM', 'name': 'two beads over the real DDM', 'martini_version': 3,
        'beads': [{'name': 'TAIL1', 'type': 'C1', 'atoms': [1, 2, 3, 4]},
                  {'name': 'HEAD', 'type': 'SN6', 'atoms': [5, 6, 7, 8]}],
        'connections': [['TAIL1', 'HEAD']]}))
    return path
