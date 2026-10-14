"""System preparation for a protein-detergent complex run: the box, the placement, and the report.

Run by `1_system/prepare_system.sh`, which the pdc adapter generates. Every rule this applies comes from an
adapter whose own unit tests cover it -- the box from `pdc_box`, the placement and its gates from
`pdc_placement`, the CG protein command from `pdc_protein`, the coordinate reader from `pdc_import` -- so the stage
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

from dashboard.execution.adapters import pdc, pdc_box, pdc_import, pdc_placement, pdc_protein
from dashboard.execution.adapters.pdc import DETERGENT_GEOMETRY, DETERGENT_TOPOLOGY, REPORT_NAME, SETTINGS_NAME
from micelle import output as micelle_output
from micelle import registry as micelle_registry

CG_DIRECTORY = 'cg'
# Where the protein's chosen chains are written when the run carries a selection. martinize2 reads this rather than
# the whole file, which is what makes a deposited assembly runnable as one of its subunits.
SELECTED_PROTEIN = 'protein_selected.pdb'

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


def select_protein(stage: Path, protein_path: Path, chains) -> tuple[Path, list[str], list[str]]:
    """The protein file martinize2 reads: the chosen chains' polymer, written beside the stage, or the file as it is.

    With no selection, or a selection that names every chain the file declares *and* a file that carries no
    `HETATM` record, the file is used unchanged -- which is every existing run's build, and what a picker that
    chooses all the subunits means. A *strict* subset is written to `protein_selected.pdb` and martinize2 is pointed
    at that, so a deposited trimer builds as the monomer that was asked for.

    A file that carries `HETATM` records is filtered too, even with every chain wanted, because martinize2 deletes
    the *whole molecule* for a residue it cannot place in its force field. Measured on 1AT9: its retinal and the OPM
    detergent it was deposited with are `HETATM` records, and either one took the CG step to exit 1 with no topology
    at all. Neither is part of the protein the run asked for, so both are dropped -- and named: what was dropped
    comes back with the path and goes into the report, so the drop is a recorded decision and not a silent one.

    A chain the file does not name is refused rather than dropped: the stage is a separate process and re-checks the
    selection against the file rather than trusting the settings.
    """
    selected = [str(chain) for chain in (chains or [])]
    text = Path(protein_path).read_text(errors='replace')
    if selected:
        available = pdc_import.structure_chains(text)
        missing = [chain for chain in selected if chain not in set(available)]
        if missing:
            named = ', '.join(available) or 'none'
            raise ValueError(f'the protein {Path(protein_path).name} names no chain(s) {", ".join(missing)}; it '
                             f'names {named}')
    # `None` keeps every chain: the filter then removes only what is not a protein residue, which is what a run with
    # no selection still needs of it (a blank chain column names no id a selection could match).
    filtered = pdc_import.filter_chains(text, selected or None)
    if filtered == text:
        return Path(protein_path), selected, []
    target = stage / SELECTED_PROTEIN
    target.write_text(filtered)
    return target, selected, pdc_import.dropped_residues(text, selected or None)


def write_report(stage: Path, report: dict) -> None:
    (stage / REPORT_NAME).write_text(json.dumps(report, indent=2, default=str))


def stamp(draft: dict, centres, directions, *, first_residue: int = 900) -> list[dict]:
    """One detergent per placement, as beads: rotated so its head points along the direction, moved to the centre.

    The placement's direction is the way *out* of the micelle -- away from the protein and into the water the next
    stage adds (`pack_micelle`'s own shell on the lattice, `pdc_placement._outward` for a self-assembled cloud). A
    micelle's heads face that water and its tails fill the core, so the molecule's own axis is taken **head-ward**:
    from the mean of its tail beads to the mean of its head beads. Taken the other way round it put every head bead
    0.317 nm inside its detergent's centre and every tail 0.845 nm outside it -- a micelle inside out, which is what
    the preview's first frames were drawn from.

    Every copy keeps the bead names the topology declares -- `grompp` reconciles topology and coordinates by atom
    name, so a per-molecule name would break the pair -- and each copy gets its own residue number, which is how a
    reader tells eight detergents apart.
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
    axis = np.mean([positions[bead['name']] for bead in head], axis=0) \
        - np.mean([positions[bead['name']] for bead in tail], axis=0)
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


# What every topology this stage writes includes: the published Martini 3 lipid set, which is where the bead types,
# the water molecule type and the ion molecule types all live. Without them `grompp` refuses the solvated system,
# because `W` is undefined. The names come from the adapter, so the two cannot drift apart.
_INCLUDES = ''.join(f'#include "{name}"\n' for name in pdc.FORCEFIELD_FILES)


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


#: The secondary-structure source this stage uses, named in the run's report. See `secondary_structure`.
SS_SOURCE = 'MDAnalysis.analysis.dssp'


def _output_path(command, flag: str) -> Path:
    """The file a martinize2 command was told to write for `flag`, read out of the command itself.

    The tool's own names are its business, so they are not copied into this module where the two could drift apart:
    the file this stage reads back is the file the command it ran names. `-x` is martinize2's only structure output
    and it is a PDB (`-x OUTPATH  Output coarse grained structure (PDB)`), `-o` its topology.
    """
    if flag not in command:
        raise SystemExit(f'the CG protein command names no {flag} output: {" ".join(str(part) for part in command)}')
    return Path(command[command.index(flag) + 1])


def ss_sequence(letters) -> str | None:
    """An assignment's letters as the DSSP sequence martinize2 takes, or `None` when one is not.

    MDAnalysis' DSSP implementation is three-state: `H` (any helix), `E` (extended strand) and `-` (unordered).
    martinize2 takes DSSP's own alphabet, where the unordered state is `C` -- the same state DSSP itself writes as
    a space, which vermouth's reader turns into `C` (`vermouth.dssp.SS_CG`). A letter that is neither of those is
    refused rather than translated: a source this stage does not know is not something to guess the meaning of.
    """
    letters = [str(letter) for letter in letters]
    if not letters or any(letter not in 'HE-' for letter in letters):
        return None
    return ''.join('C' if letter == '-' else letter for letter in letters)


def secondary_structure(structure: Path) -> tuple[str | None, dict]:
    """The secondary structure martinize2 should build the protein with, and where it came from.

    martinize2 takes an assignment two ways, and the tool's own help is what decides between them here:

    * `-dssp [executable]` runs DSSP itself -- or, with the bare flag, the **mdtraj** library, which this
      environment does not have (`import mdtraj` fails), leaving an external binary that vermouth warns it has
      tested only at versions 2.2.1 and 3.0.0 (`SUPPORTED_DSSP_VERSIONS`). PDB-REDO's `dssp` is the current 4.x
      `mkdssp`: it would be an untested version *and* a C++ build (cmake + libcifpp + Eigen) this repository does
      not carry, so it is not what is wired;
    * `-ss <sequence>` hands it a DSSP-format letter per residue, which is what this stage uses, because the
      assignment can then come from a library that *is* here: MDAnalysis 2.9 ships a DSSP implementation
      (`MDAnalysis.analysis.dssp`, a port of pydssp). Measured on 1AT9's own chain A, 230 residues of
      bacteriorhodopsin: the seven transmembrane helices come back as `H`, and martinize2 took the sequence at exit
      0 and wrote its SS-dependent bonded potentials. The `-dssp`/mdtraj path is therefore not a fallback here but
      the thing that does not work in this environment; MDAnalysis is the source.

    Both routes end in vermouth's `AnnotateMartiniSecondaryStructures`, so the same SS-dependent bonded potentials
    are built either way -- what differs is who assigns the letters, and that is recorded.

    Returns `(sequence, record)`. `None` for the sequence when no assignment could be made -- a source that is not
    importable, or a protein its algorithm cannot work on (measured: it raises below five residues) -- with the
    reason in the record. A build with no secondary structure is martinize2's own documented case, which is what
    `-maxwarn 1` is for; the stage's job is to say which case this is, not to invent an assignment.
    """
    try:
        import MDAnalysis
        from MDAnalysis.analysis.dssp import DSSP
    except ImportError as exc:
        return None, {'source': None, 'detail': f'MDAnalysis is not importable: {exc}'}
    try:
        assignment = DSSP(MDAnalysis.Universe(str(structure)))
        assignment.run()
        letters = [letter for row in assignment.results.dssp for letter in row]
    except Exception as exc:                     # any failure here means "no assignment", and the run says which
        return None, {'source': None, 'detail': f'{type(exc).__name__} from {SS_SOURCE}: {exc}'}
    sequence = ss_sequence(letters)
    if sequence is None:
        return None, {'source': None,
                      'detail': f'{SS_SOURCE} assigned no letters this stage can hand over ({letters[:8]})'}
    return sequence, {'source': SS_SOURCE, 'residues': len(sequence), 'helix': sequence.count('H'),
                      'extended': sequence.count('E'), 'coil': sequence.count('C')}


def ss_flags(sequence: str | None) -> list[str]:
    """What is appended to the CG protein command: the assignment, and room for martinize2's one warning.

    `-maxwarn 1` is the tool's own documented escape hatch for the case where no secondary structure could be
    assigned: without it, and without `-ss`, it logs "topology will be created without secondary structure
    information" and exits 2 having written nothing at all (measured on 1AT9's chain A with the flags as they were).
    One warning of room is allowed, and no more, so a run this flag saves is still one a reader can see in its log.
    """
    return ['-maxwarn', '1'] + (['-ss', sequence] if sequence else [])


def _absolute(command: list, flags=('-f', '-x', '-o')) -> list:
    """The command with the paths it names made absolute.

    It is run from `cg/`, while a stage's own paths are relative to the directory the stage script runs in
    (`--stage .` resolves to `protein.pdb`, `cg/protein_cg.pdb`). Handing those to a subprocess started somewhere
    else is the way martinize2 came to look for `protein_selected.pdb` inside `cg/` and stop with
    `FileNotFoundError` -- measured on the real tool -- so every path in the command is resolved to the one file it
    names before it is run, and the command the report records is the one that actually ran.
    """
    resolved = list(command)
    for flag in flags:
        if flag in resolved:
            index = resolved.index(flag) + 1
            resolved[index] = str(Path(resolved[index]).resolve())
    return resolved


def cg_protein(stage: Path, protein: Path) -> tuple[list, list[str] | None, dict]:
    """The CG protein's beads, running martinize2 only when the stage has not been built before.

    martinize2's own file names are its business, so what is read back is the file its own command names (`-x`, a
    PDB) rather than a name written down here: this step used to glob `*.gro` out of `cg/`, a structure the tool
    never writes, so it raised "the CG protein step left 0 structures" however well martinize2 had run.

    It is run *in* `cg/`, because that is where it writes the molecule's own `.itp`: it writes `molecule_0.itp`
    beside itself and includes it from the `.top` by that name, so run from anywhere else the topology the next
    step needs lands in the stage directory instead (measured in a scratch directory: `-o cg/protein.top` wrote
    `./molecule_0.itp`).

    Returns the beads, the command that was run (`None` when the step was already built) and what the secondary
    structure assignment was, all three of which the report carries.
    """
    directory = stage / CG_DIRECTORY
    directory.mkdir(exist_ok=True)
    command = _absolute(pdc_protein.martinize_command(protein, directory))
    structure = _output_path(command, '-x')
    if structure.is_file():
        return (pdc_import.structure_atoms(structure), None,
                {'source': None, 'detail': f'{structure.name} was already there, so martinize2 was not run again'})
    sequence, record = secondary_structure(protein)
    command = command + ss_flags(sequence)
    with (stage / 'martinize.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, cwd=directory)
    if not structure.is_file():
        raise SystemExit(f'the CG protein step wrote no {structure.name} in {directory}: '
                         f'see {stage / "martinize.log"}')
    return pdc_import.structure_atoms(structure), command, record


def build(stage: Path) -> int:
    settings = read_settings(stage)
    template = micelle_registry.load_template(resolve(settings, 'template', stage))
    template_issues = list(micelle_registry.validate_template(template))
    # Which generator places the detergents is a decision the build carries, so it is read here and written into the
    # report --- the run's provenance is not something a reader should have to re-derive from the coordinates.
    mode = pdc_placement.canonical_mode(settings.get('placement_mode', pdc_placement.DEFAULT_PLACEMENT_MODE))
    report = {
        'stage': 'system-preparation',
        'protein': settings['protein'],
        'protein_free': not (settings.get('protein') or '').strip(),
        # Which subunits go into the system: the selection, or `all` -- the whole file -- for a run that did not choose.
        'protein_chains': (settings.get('protein_chains') or 'all'),
        'protein_input': None,
        'template': str(settings['template']),
        'detergent': template.name,
        'detergent_residue': template.residue,
        'aggregation_number': settings['aggregation_number'],
        'seed': settings['seed'],
        'placement_mode': mode,
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

    beads, command, secondary = ([], None, None)
    requested_protein = (settings.get('protein') or '').strip()
    if requested_protein:
        protein_input, selected_chains, dropped = select_protein(stage, resolve(settings, 'protein', stage),
                                                                 settings.get('protein_chains'))
        report['protein_input'] = protein_input.name if protein_input.name == SELECTED_PROTEIN else None
        report['protein_dropped_residues'] = dropped
        beads, command, secondary = cg_protein(stage, protein_input)
    points = [list(bead['position']) for bead in beads]
    placement = pdc_placement.place_detergents(points, template, settings['aggregation_number'],
                                               settings['seed'], radius_nm=settings['radius_nm'], mode=mode,
                                               margin_nm=settings['box_margin_nm'],
                                               initial_z_nm=settings['initial_z_nm'])
    report.update({
        'cg_command': command,
        'secondary_structure': secondary,
        'protein_beads': len(points),
        'placement_mode': placement['mode'],
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
    """The state before a single step of dynamics: the frame a reader judges the placement from.

    The title carries the mode, so a picture cannot be mistaken for one the other generator built.
    """
    from dashboard.execution.scripts import pdc_snapshot
    pdc_snapshot.write_snapshot(stage, 'placement', stage / 'system.gro',
                                title=f'placed system before dynamics ({template.name}, '
                                      f'AN={settings["aggregation_number"]}, '
                                      f'mode={settings.get("placement_mode", pdc_placement.DEFAULT_PLACEMENT_MODE)})')


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
