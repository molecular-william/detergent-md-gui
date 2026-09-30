"""System preparation for a protein-detergent complex run: the box, the placement, and the report.

Run by `1_system/prepare_system.sh`, which the pdc adapter generates. Every rule this applies comes from an
adapter whose own unit tests cover it -- the box from `pdc_box`, the placement and its gates from
`pdc_placement`, the CG protein command from `pdc_protein`, the coordinate reader from `pdc_view` -- so the stage
cannot drift from the rules by restating them here.

Two things it deliberately does not do yet, and says so rather than guessing:

* the detergent is represented by **one centre per molecule** (what the placement produces). Placing the
  detergent's own beads needs the template's bead geometry, which the shipped templates do not carry -- their one
  bead is typed `registered-template`.
* `system.top` is not written. Its `[ molecules ]` section needs the molecule names from the two `.itp` files
  (`protein_CG.itp` and the detergent's), and that assembly is the next slice; the stage exits 3 instead of
  writing a topology it cannot check.

    python -m dashboard.execution.scripts.pdc_build --stage .

Reads `pdc-settings.json` and `protein.pdb` from the stage directory. Writes `cg/` (martinize2's own output),
`system.gro` and `prepare_report.json`.

Exit codes: 0 built, 2 a gate refused (the report names which), 3 a step whose rules do not exist yet.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from dashboard.execution.adapters import pdc_box, pdc_placement, pdc_protein, pdc_view
from dashboard.execution.adapters.pdc import REPORT_NAME, SETTINGS_NAME
from micelle import output as micelle_output
from micelle import registry as micelle_registry

CG_DIRECTORY = 'cg'

LIMITATIONS = [
    'the detergent is one centre per molecule, not its bead geometry: the shipped templates carry no bead shape',
    'system.top is not written yet, because its [ molecules ] names come from the two .itp files',
]


def read_settings(stage: Path) -> dict:
    path = stage / SETTINGS_NAME
    if not path.is_file():
        raise SystemExit(f'{path} is missing: this stage reads its decisions from it')
    return json.loads(path.read_text())


def resolve(settings: dict, key: str, stage: Path) -> Path:
    """A settings path, absolute or relative to the project root the settings record."""
    value = settings.get(key)
    if not value:
        raise SystemExit(f'the settings name no {key}')
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else Path(settings['project_root']) / candidate
    if not path.is_file():
        raise SystemExit(f'{key} is missing: {path}')
    return path


def write_report(stage: Path, report: dict) -> None:
    (stage / REPORT_NAME).write_text(json.dumps(report, indent=2, default=str))


def cg_protein(stage: Path, protein: Path) -> tuple[list, list[str] | None]:
    """The CG protein's beads, running martinize2 only when the stage has not been built before.

    martinize2's own file names are its business: it writes into `cg/` and this reads whatever single `.gro` is
    there, rather than naming a file the command might not produce.
    """
    directory = stage / CG_DIRECTORY
    directory.mkdir(exist_ok=True)
    command = None
    if not list(directory.glob('*.gro')):
        command = pdc_protein.martinize_command(protein, directory)
        with (stage / 'martinize.log').open('w') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    structures = sorted(directory.glob('*.gro'))
    if len(structures) != 1:
        raise SystemExit(f'the CG protein step left {len(structures)} structures in {directory}')
    return pdc_view.read_gro(structures[0]), command


def build(stage: Path) -> int:
    settings = read_settings(stage)
    template = micelle_registry.load_template(resolve(settings, 'template', stage))
    template_issues = list(micelle_registry.validate_template(template))
    report = {
        'stage': 'system-preparation',
        'protein': settings['protein'],
        'template': str(settings['template']),
        'detergent': template.name,
        'detergent_residue': template.residue,
        'aggregation_number': settings['aggregation_number'],
        'seed': settings['seed'],
        'radius_nm': settings['radius_nm'],
        'box_margin_nm': settings['box_margin_nm'],
        'initial_z_nm': settings['initial_z_nm'],
        'template_issues': template_issues,
        'detergent_representation': 'one centre per molecule',
        'limitations': list(LIMITATIONS),
    }
    # A template that cannot build a system stops the stage before anything is placed, so the run's record says
    # what a reader would have to fix rather than what a half-built system looks like.
    if template_issues:
        report.update({'valid': False, 'box_nm': None, 'protein_beads': 0, 'reasons': template_issues})
        write_report(stage, report)
        return 2

    beads, command = cg_protein(stage, resolve(settings, 'protein', stage))
    points = [list(bead['position']) for bead in beads]
    initial = pdc_box.initial_box(points, margin_nm=settings['box_margin_nm'],
                                  initial_z_nm=settings['initial_z_nm'])
    placement = pdc_placement.place_detergents(points, template, settings['aggregation_number'],
                                               settings['seed'], radius_nm=settings['radius_nm'])
    report.update({
        'cg_command': command,
        'protein_beads': len(points),
        'box_nm_initial': initial,
        'protein_clearance_nm': placement['protein_clearance_nm'],
        'placement_issues': placement['issues'],
    })
    if not placement['valid']:
        report.update({'valid': False, 'box_nm': None, 'reasons': placement['issues']})
        write_report(stage, report)
        return 2

    box = pdc_box.extended_box(initial[:2], placement['centers'], margin_nm=settings['box_margin_nm'])
    atoms = [{'name': bead['name'], 'residue': bead['residue'], 'position': bead['position']} for bead in beads]
    atoms += [{'name': f'{template.residue[:3]}{index + 1:03d}', 'residue': template.residue,
               'position': centre} for index, centre in enumerate(placement['centers'])]
    micelle_output.write_gro(stage / 'system.gro', atoms,
                             title=f'protein-detergent complex ({template.name}, '
                                   f'AN={settings["aggregation_number"]})', box=box)
    report.update({'valid': True, 'box_nm': box, 'atoms': len(atoms),
                   'placed_detergents': len(placement['centers']),
                   'system_top': 'not written: the detergent representation above is not a parameterised model'})
    write_report(stage, report)
    return 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Build the protein-detergent complex system for a run.')
    parser.add_argument('--stage', default='.', help='the stage directory holding pdc-settings.json')
    args = parser.parse_args(argv)
    try:
        return build(Path(args.stage))
    except (ValueError, OSError) as exc:
        print(f'pdc_build: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
