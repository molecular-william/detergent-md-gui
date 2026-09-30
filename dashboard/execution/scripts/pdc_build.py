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
from dashboard.execution.adapters.pdc import DETERGENT_GEOMETRY, DETERGENT_TOPOLOGY, REPORT_NAME, SETTINGS_NAME
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


def stamp(draft: dict, centres, directions, *, first_residue: int = 900) -> list[dict]:
    """One detergent per placement, as beads: rotated so its tail points along the direction, moved to the centre.

    The molecule's own axis is head-to-tail, from the mean of its tail beads to the mean of its head beads, and the
    placement's direction is the axis each placement site carries. Every copy keeps the bead names the topology
    declares -- `grompp` reconciles topology and coordinates by atom name, so a per-molecule name would break the
    pair -- and each copy gets its own residue number, which is how a reader tells eight detergents apart.
    """
    import numpy as np

    beads = draft['beads']
    tail = [bead for bead in beads if str(bead.get('type', '')).startswith('C')]
    head = [bead for bead in beads if not str(bead.get('type', '')).startswith('C')]
    if not tail or not head:
        raise SystemExit('the detergent mapping marks no hydrophobic core: its bead types must distinguish the '
                         'tail (C-type beads) from the head, or the placement cannot orient it')

    positions = {bead['name']: np.asarray(bead['position'], dtype=float) for bead in beads}
    middle = np.mean([positions[bead['name']] for bead in beads], axis=0)
    axis = np.mean([positions[bead['name']] for bead in tail], axis=0) \
        - np.mean([positions[bead['name']] for bead in head], axis=0)
    axis = axis / np.linalg.norm(axis)

    atoms = []
    for index, (centre, direction) in enumerate(zip(centres, directions), start=1):
        target = np.asarray(direction, dtype=float)
        target = target / np.linalg.norm(target)
        rotation = _rotation(axis, target)
        residue_id = first_residue + index
        for bead in beads:
            position = np.asarray(centre, dtype=float) + rotation @ (positions[bead['name']] - middle)
            atoms.append({'residue_id': residue_id, 'residue': draft['residue'], 'name': bead['name'],
                          'position': [round(float(value), 5) for value in position]})
    return atoms


def _rotation(axis, target):
    """The rotation taking one unit vector onto another, including the antiparallel case."""
    import numpy as np

    cross = np.cross(axis, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.dot(axis, target))
    if sine < 1e-9:
        if cosine > 0:
            return np.eye(3)
        # Opposite directions: any perpendicular axis turns the molecule by 180 degrees.
        perpendicular = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        perpendicular = perpendicular - axis * np.dot(perpendicular, axis)
        perpendicular = perpendicular / np.linalg.norm(perpendicular)
        return 2.0 * np.outer(perpendicular, perpendicular) - np.eye(3)
    cross = cross / sine
    skew = np.array([[0.0, -cross[2], cross[1]], [cross[2], 0.0, -cross[0]], [-cross[1], cross[0], 0.0]])
    return np.eye(3) + sine * skew + (1.0 - cosine) * (skew @ skew)


def molecule_name(topology_text: str) -> str:
    """The molecule's name as a topology declares it, because `[ molecules ]` has to spell it exactly."""
    lines = topology_text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.split(';', 1)[0].strip()
        if stripped.startswith('[') and stripped.lower().startswith('[ moleculetype'):
            for following in lines[index + 1:]:
                content = following.split(';', 1)[0].strip()
                if content:
                    return content.split()[0]
    raise SystemExit('a topology without a [ moleculetype ] name cannot be listed in [ molecules ]')


# What every topology this stage writes includes: the force field, which is where the water and ion molecule types
# live. Without it `grompp` refuses the solvated system, because `W` is undefined.
_INCLUDES = '#include "martini_v3.itp"\n'


def write_topologies(stage: Path, protein_itp: Path | None, detergent_itp: Path | None, detergents: int) -> dict:
    """`system_EMPTY.top` (the protein alone, the stage's declared input) and `system.top` (the whole system).

    Both name their molecules exactly as the two `.itp` files do, and the counts are the counts of molecules the
    structure actually holds -- the invariant `grompp` checks, and the one whose violation cost three failed sugar
    runs.

    A protein-free build (the empty micelle) writes the same two files with no protein row, so every reader
    downstream sees the shape it expects rather than a special case.
    """
    if protein_itp is None:
        (stage / 'system_EMPTY.top').write_text(
            '; the system before the detergent arrives, filled in by the system-preparation stage\n'
            f'{_INCLUDES}'
            '[ system ]\nempty micelle, no protein\n\n[ molecules ]\n')
        if detergent_itp is None or not detergents:
            return {'protein_molecule': None}
        detergent = molecule_name(detergent_itp.read_text())
        (stage / 'system.top').write_text(
            f'; the whole system, written by the system-preparation stage\n'
            f'{_INCLUDES}#include "{detergent_itp.name}"\n\n[ system ]\nempty micelle, detergent only\n\n'
            f'[ molecules ]\n{detergent}\t{detergents}\n')
        return {'protein_molecule': None, 'detergent_molecule': detergent, 'detergents': detergents}
    protein = molecule_name(protein_itp.read_text())
    empty = (f'; the system before the detergent arrives, filled in by the system-preparation stage\n'
             f'{_INCLUDES}#include "{protein_itp.name}"\n\n[ system ]\nprotein-detergent complex, CG protein\n\n'
             f'[ molecules ]\n{protein}\t1\n')
    (stage / 'system_EMPTY.top').write_text(empty)
    if detergent_itp is None or not detergents:
        return {'protein_molecule': protein}
    detergent = molecule_name(detergent_itp.read_text())
    (stage / 'system.top').write_text(
        f'; the whole system, written by the system-preparation stage\n'
        f'{_INCLUDES}#include "{protein_itp.name}"\n#include "{detergent_itp.name}"\n\n[ system ]\n'
        f'protein-detergent complex, CG protein and detergent\n\n[ molecules ]\n'
        f'{protein}\t1\n{detergent}\t{detergents}\n')
    return {'protein_molecule': protein, 'detergent_molecule': detergent, 'detergents': detergents}


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
        'protein_free': not (settings.get('protein') or '').strip(),
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

    beads, command = ([], None)
    requested_protein = (settings.get('protein') or '').strip()
    if requested_protein:
        beads, command = cg_protein(stage, resolve(settings, 'protein', stage))
    points = [list(bead['position']) for bead in beads]
    placement = pdc_placement.place_detergents(points, template, settings['aggregation_number'],
                                               settings['seed'], radius_nm=settings['radius_nm'])
    report.update({
        'cg_command': command,
        'protein_beads': len(points),
        'protein_clearance_nm': placement['protein_clearance_nm'],
        'placement_issues': placement['issues'],
    })
    if not placement['valid']:
        report.update({'valid': False, 'box_nm': None, 'box_nm_initial': None, 'reasons': placement['issues']})
        write_report(stage, report)
        return 2

    # The box is measured on whatever the system actually has: the protein's beads, or -- for an empty micelle --
    # the placed detergents, because a box around no coordinates is not a box. It is computed here rather than
    # before the placement so that a failed placement is reported as a placement failure and not as a box error.
    initial = pdc_box.initial_box(points or placement['centers'], margin_nm=settings['box_margin_nm'],
                                  initial_z_nm=settings['initial_z_nm'])
    report['box_nm_initial'] = initial

    box = pdc_box.extended_box(initial[:2], placement['centers'], margin_nm=settings['box_margin_nm'])
    atoms = [{'residue_id': bead['residue_id'], 'residue': bead['residue'], 'name': bead['name'],
              'position': bead['position']} for bead in beads]
    model = _detergent_model(stage)
    if model is None:
        # A build whose detergent is a bare centre: the picture is honest and the topology stays unwritten, because
        # a `[ molecules ]` line naming a molecule whose bead count nothing knows cannot be written at all.
        atoms += [{'name': f'{template.residue[:2]}{index + 1:03d}', 'residue': template.residue,
                   'position': centre} for index, centre in enumerate(placement['centers'])]
        micelle_output.write_gro(stage / 'system.gro', atoms,
                                 title=f'protein-detergent complex ({template.name}, '
                                       f'AN={settings["aggregation_number"]})', box=box)
        report.update({'valid': True, 'box_nm': box, 'atoms': len(atoms),
                       'placed_detergents': len(placement['centers']),
                       'system_top': 'not written: the detergent is one centre per molecule, not a model'})
        write_report(stage, report)
        _record_placement(stage, template, settings)
        return 3

    protein_itp = next(iter(sorted((stage / CG_DIRECTORY).glob('*.itp'))), None)
    if protein_itp is None and (settings.get('protein') or '').strip():
        raise SystemExit('the CG protein step wrote no topology, so the system cannot be assembled')
    atoms += stamp(model, placement['centers'], placement['directions'],
                   first_residue=max([bead['residue_id'] for bead in beads], default=0) + 1)
    micelle_output.write_gro(stage / 'system.gro', atoms,
                             title=f'protein-detergent complex ({template.name}, '
                                   f'AN={settings["aggregation_number"]}, {model["residue"]})', box=box)
    topologies = write_topologies(stage, protein_itp, stage / DETERGENT_TOPOLOGY, len(placement['centers']))
    report.update({'valid': True, 'box_nm': box, 'atoms': len(atoms),
                   'placed_detergents': len(placement['centers']),
                   'detergent_model': settings.get('detergent_model') or {},
                   'molecules': topologies,
                   'system_top': 'system.top'})
    write_report(stage, report)
    _record_placement(stage, template, settings)
    return 0


def _detergent_model(stage: Path) -> dict | None:
    """The derived detergent, when the run was prepared with one."""
    path = stage / DETERGENT_GEOMETRY
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _record_placement(stage: Path, template, settings: dict) -> None:
    """The state before a single step of dynamics: the frame a reader judges the placement from."""
    from dashboard.execution.scripts import pdc_snapshot
    pdc_snapshot.write_snapshot(stage, 'placement', stage / 'system.gro',
                                title=f'placed system before dynamics ({template.name}, '
                                      f'AN={settings["aggregation_number"]})')


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
