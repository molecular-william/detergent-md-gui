"""Stage everything CG2AT2 needs to convert a detergent, from the run's own mapping.

`pdc_backmap.sh` used to hand the tool a CG structure and hope: the detergent had no fragment and the conversion's force
field had no types for it, so a complex carrying DDM stopped at `DDM is not in the fragment database!` and, once that was
answered, at `Invalid order for directive atomtypes`. Both answers are data the repository holds, and this module puts them
where the tool reads them -- inside the stage, never in the vendored tree:

* `cg2at_fragment.write` turns the mapping, the molecule's topology and its coordinates into the fragment.
* `cg2at_fragment.extend_forcefield` builds the force-field directory that carries the molecule's own atom types, as a
  symlink farm beside the vendored tree so nothing of its 6.7 MB is copied.
* `cg2at_fragment.renamed_gro` rewrites the CG structure's bead names to the four characters a PDB atom-name field holds,
  because the tool round-trips its input through PDB and `TAIL1`/`TAIL2`/`TAIL3` all arrive as `TAIL`.
* the fragment library is mirrored the same way, because `-fg` takes a *path* and the molecule's fragment has to sit
  inside a library directory: the mirror holds symlinks to every vendored fragment and one real directory for this run's.

    python -m dashboard.execution.scripts.pdc_backmap --stage . [--project-root /path]

Writes `backmap_inputs.json` beside the stage: what was built, from which mapping, and the two paths the invocation
needs. A run with no mapping records why and exits 3 -- a complex whose detergent cannot be converted is a stage that
cannot do its job, not one with nothing to do.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from dashboard.execution.adapters.pdc import SETTINGS_NAME
from dashboard.execution.scripts import cg2at_fragment as fragment

OUTPUT_NAME = 'backmap_inputs.json'
RECORD_NAME = 'backmap.json'
LIBRARY = 'martini_3-0_charmm36'
FORCE_FIELD = 'charmm36-mar2019-updated.ff'
#: Where the tool keeps its own database, relative to the repository.
DATABASE = Path('tools/cg2at/database')
#: The atomistic topology and coordinates a mapping's bead indices refer to, by the packaged convention.
MOLECULE_TOPOLOGY = Path('results/MMFF/lig1.itp')
MOLECULE_COORDINATES = Path('results/MMFF/lig1.pdb')
SKIPPED, REFUSED = 4, 3


def settings(stage: Path) -> dict:
    """The run's own decisions, from the one file every pdc stage reads them from."""
    path = stage.parent.parent / 'inputs' / SETTINGS_NAME
    if not path.is_file():
        raise SystemExit(f'{path} is missing: this stage reads the run\'s decisions from it')
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mirror(tree: Path, out: Path) -> Path:
    """A directory that is `tree` by symlink, so a run can add to it without writing into a vendored database.

    `-fg` takes a path and reads `<parent>/<name>/non_protein/...`, so the mirror keeps the library's own name and
    structure; its subdirectories are real (a fragment has to be added to one) and everything inside them is linked.
    """
    target = out / tree.name
    target.mkdir(parents=True, exist_ok=True)
    for entry in sorted(tree.iterdir()):
        link = target / entry.name
        if entry.is_dir():
            if link.exists() or link.is_symlink():
                continue
            link.mkdir()
            for child in sorted(entry.iterdir()):
                if not (link / child.name).exists():
                    (link / child.name).symlink_to(child.resolve(), target_is_directory=child.is_dir())
        elif not (link.exists() or link.is_symlink()):
            link.symlink_to(entry.resolve())
    return target


def stage_inputs(stage: Path, project_root: Path) -> dict:
    """Build the fragment, the force field and the renamed structure; return what the invocation needs."""
    values = settings(stage)
    model = values.get('detergent_model') or {}
    mapping_path = Path(str(model.get('mapping') or ''))
    residue = str(model.get('residue') or '').strip()
    if not residue or not mapping_path.is_file():
        raise SystemExit(f'the run records no mapping for its detergent ({mapping_path or "none"}), so the complex cannot '
                         f'be converted: CG2AT2 needs a fragment for {residue or "the detergent"}')

    molecule = project_root / 'molecules' / residue
    topology, coordinates = molecule / MOLECULE_TOPOLOGY, molecule / MOLECULE_COORDINATES
    for path in (topology, coordinates):
        if not path.is_file():
            raise SystemExit(f'{path} is missing: the fragment is written from the molecule\'s own topology and '
                             f'coordinates, which is what the mapping\'s atom indices refer to')

    base = stage / 'cg2at'
    base.mkdir(exist_ok=True)
    written = fragment.write(base / 'staged_fragment', mapping_path, topology, coordinates, residue)
    library = mirror(project_root / DATABASE / 'fragments' / LIBRARY, base / 'fragments')
    installed = library / 'non_protein' / residue
    installed.mkdir(parents=True, exist_ok=True)
    for name in ('pdb', 'itp'):
        shutil.copy2(base / 'staged_fragment' / f'{residue}.{name}', installed / f'{residue}.{name}')

    force_field = fragment.extend_forcefield(project_root / DATABASE / 'forcefields' / FORCE_FIELD,
                                             written['atomtypes'], base / FORCE_FIELD, written['pairtypes'])

    run_gro = stage.parent / '08_extension' / 'prod' / 'run.gro'
    if not run_gro.is_file():
        # Without removal there is no extension stage; the production phase is the only structure.
        run_gro = stage.parent / '06_assessment' / 'prod' / 'run.gro'
    if not run_gro.is_file():
        raise SystemExit(f'{run_gro} is missing: this stage converts the run\'s final CG structure')
    mapping = json.loads(mapping_path.read_text())
    names = fragment.safe_names([bead['name'] for bead in mapping['beads']])
    structure = stage / 'cg2at_input.gro'
    structure.write_text(fragment.renamed_gro(run_gro.read_text(), residue, names))

    record = {'mapping': str(mapping_path), 'mapping_sha256': digest(mapping_path), 'residue': residue,
              'library': str(library), 'force_field': str(force_field), 'structure': str(structure),
              'atoms': written['atoms'], 'beads': written['beads'], 'renamed': written['renamed'],
              'fragment': {f'{residue}.{ext}': digest(installed / f'{residue}.{ext}') for ext in ('pdb', 'itp')},
              'topology': str(topology), 'coordinates': str(coordinates),
              'box_nm': run_gro.read_text().splitlines()[-1].split()[:3]}
    (stage / OUTPUT_NAME).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Stage the fragment, force field and structure a back-map converts.')
    parser.add_argument('--stage', default='.')
    parser.add_argument('--project-root', default=None)
    args = parser.parse_args(argv)
    stage = Path(args.stage).resolve()
    if args.project_root:
        project_root = Path(args.project_root).resolve()
    else:
        # The stage script hands the repository over; a caller running this by hand can name it or export PROJECT_ROOT.
        named = os.environ.get('PROJECT_ROOT')
        project_root = Path(named).resolve() if named else stage.parents[4]
    try:
        record = stage_inputs(stage, project_root)
    except SystemExit as exc:
        print(f'pdc_backmap: {exc}', file=sys.stderr)
        return REFUSED
    print(f'staged {record["residue"]}: {record["atoms"]} atoms in {len(record["beads"])} beads, '
          f'library {record["library"]}, force field {record["force_field"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
