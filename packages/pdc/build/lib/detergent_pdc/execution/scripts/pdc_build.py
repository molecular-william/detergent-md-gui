"""System preparation for a protein-detergent complex run: the box, the placement, and the report.

Run by `02_system/pdc_system.sh`, the shared stage script the pdc adapter records. Every rule this applies comes from an
adapter whose own unit tests cover it -- the box from `pdc_box`, the placement and its gates from
`pdc_placement`, the CG protein command from `pdc_protein`, the coordinate reader from `pdc_import`, the structure
the prepare step left from `pdc_preparation` -- so the stage cannot drift from the rules by restating them here.

The structure the coarse-graining reads is the prepare step's, when a run asked for that step and the stage left one
(`prepared_protein`): a deposited file whose side chains are incomplete coarse-grains into beads with no position, and
the rebuilt file is what martinize2 is handed instead. Which of the two it was is in the report, because a build that
simulated the prepared structure and one that simulated the deposited file are not the same system.

The membrane the belt is placed in is the protein file's own statement of it (`REMARK 1/2 of bilayer thickness`),
read through `micelle.frame` -- the file's statement travels with its coordinates, so the structure this stage was
handed is the authority and a catalogue entry is not. A protein whose file states nothing keeps the sphere the
placement has always built; so does an empty micelle, which has no membrane to state.

Two things it deliberately does not do yet, and says so rather than guessing:

* the detergent is represented by **one point per molecule** (what the placement produces), and that point is the
  molecule's **head end** -- the tube's outer surface for a belt, the shell for a sphere. Placing the
  detergent's own beads needs the template's bead geometry, which the shipped templates do not carry -- their one
  bead is typed `registered-template`.
* `system.top` is written from what `grompp` will read: martinize2's own `[ molecules ]`, reproduced row for row with
  each molecule's `.itp` included from `cg/`, and the detergent's molecule type -- but a build whose detergent is a
  bare centre (no mapping, so no bead model) stops before it, at exit 3: a `[ molecules ]` row naming a molecule whose
  beads nothing knows cannot be written.

    python -m detergent_pdc.execution.scripts.pdc_build --stage .

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

from dashboard import martini3

from detergent_pdc.execution.adapters import pdc, pdc_box, pdc_import, pdc_placement, pdc_preparation, pdc_protein
from detergent_pdc.execution.adapters.pdc import DETERGENT_GEOMETRY, DETERGENT_TOPOLOGY, REPORT_NAME, SETTINGS_NAME
from micelle import frame as micelle_frame
from micelle import output as micelle_output
from micelle import registry as micelle_registry

CG_DIRECTORY = pdc.PROTEIN_TOPOLOGY_DIRECTORY
# Where the protein's chosen chains are written when the run carries a selection. martinize2 reads this rather than
# the whole file, which is what makes a deposited assembly runnable as one of its subunits.
SELECTED_PROTEIN = 'protein_selected.pdb'

LIMITATIONS = [
    'the detergent is one point per molecule -- its head end -- not its bead geometry: the shipped templates '
    'carry no bead shape',
    'system.top lists the molecules grompp reads -- martinize2\'s own, and the detergent\'s -- but a build with no '
    'detergent model writes none: a molecule whose beads nothing knows cannot be listed',
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
    """One detergent per placement, as beads: rotated so its head points along the direction, its head end at the centre.

    The placement's direction is the way *out* of the micelle -- away from the protein and into the water the next
    stage adds (`pack_micelle`'s own shell and, for a stated membrane, the tube's meridian direction at each site;
    `pdc_placement._outward` for a self-assembled cloud). A
    micelle's heads face that water and its tails fill the core, so the molecule's own axis is taken **head-ward**:
    from the mean of its tail beads to the mean of its head beads. Taken the other way round it put every head bead
    0.317 nm inside its detergent's centre and every tail 0.845 nm outside it -- a micelle inside out, which is what
    the preview's first frames were drawn from.

    The **site names the molecule's head end**, not its middle: the head-most bead is translated onto the site and
    the rest of the molecule hangs back along the direction, so the head end stands where the placement says the
    detergent reaches. For a belt that is the whole point -- the site is the tube's outer surface, at the detergent's
    own length from the protein's cylinder, and the body then points at the centre-line -- and it is the same
    convention on the sphere, whose sites are its shell. Measured before this: the molecule's bead *mean* was put at
    the site, which left every head bead 0.25 nm past a site that was meant to be its own end.

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
    # How far the molecule's own head end stands from its middle, along that axis: what the site is anchored to.
    head_end = max(float((positions[bead['name']] - middle) @ axis) for bead in head)

    atoms = []
    for index, (centre, direction) in enumerate(zip(centres, directions), start=1):
        target = np.asarray(direction, dtype=float)
        target = target / np.linalg.norm(target)
        rotation = _rotation(axis, target)
        residue_id = first_residue + index
        for bead in beads:
            position = np.asarray(centre, dtype=float) + rotation @ (positions[bead['name']] - middle) \
                - head_end * target
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


def molecule_rows(topology: Path) -> list[tuple[str, int]]:
    """Every molecule a topology lists in its own `[ molecules ]`: names and counts, in its own order.

    Read rather than assumed, because martinize2 emits **one molecule per chain**: 1AT9's chain A gives one and
    4IAR's gives two, so neither the number of rows nor their counts is something this stage may decide. The run that
    motivated this wrote only the first row, and the second molecule's beads then sat in `system.gro` with no
    topology and no `[ molecules ]` row. A row this function cannot read is refused, not skipped: a topology it
    half-understood would produce a system `grompp` refuses after a stage has already run.
    """
    rows, section = [], ''
    for raw in Path(topology).read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if line.startswith('['):
            section = line.strip('[] \t').lower()
            continue
        if section != 'molecules' or not line:
            continue
        fields = line.split()
        if len(fields) < 2 or not fields[1].lstrip('-').isdigit():
            raise SystemExit(f'{Path(topology).name} lists a [ molecules ] row this stage cannot read: {line!r}')
        rows.append((fields[0], int(fields[1])))
    if not rows:
        raise SystemExit(f'{Path(topology).name} lists no molecule in [ molecules ], so the system cannot be '
                         'assembled')
    return rows


def protein_topology(topology: Path, stage: Path) -> tuple[list[tuple[str, int]], str, str]:
    """The protein's molecules, the `#include`s for them and its `[ molecules ]` rows, all from martinize2's topology.

    The includes name `../<this stage>/cg/<name>.itp` -- this stage's own directory, reached from any of its siblings
    under `stages/`. `system.top` is copied forward between those siblings and `grompp` resolves an include from the
    working directory, so a bare `cg/<name>.itp` would only resolve in the one directory that carries the tree. The
    tool's own `protein.top` names the same files by bare name because it was written beside them; only one of the two
    is the topology the legs run.

    The tool's header include `martini.itp` is **not** reproduced. That is vermouth's force field; this system's is
    `pdc.FORCEFIELD_FILES`, and copying the header would hand `grompp` a second, incompatible parameter set.

    Each row's `.itp` is checked for where the include says it is, so a molecule whose topology is not there is
    refused here, naming the file -- rather than by `grompp` in the middle of a run, as `Topology include file
    "molecule_0.itp" not found` was.
    """
    includes, rows = [], []
    molecules = molecule_rows(topology)
    for name, count in molecules:
        itp = Path(topology).parent / f'{name}.itp'
        if not itp.is_file():
            raise SystemExit(f'{Path(topology).name} lists molecule {name!r}, whose {itp.name} is not beside it in '
                             f'{Path(topology).parent.name}/: the system cannot be assembled')
        includes.append(f'#include "../{Path(stage).name}/{CG_DIRECTORY}/{itp.name}"\n')
        rows.append(f'{name}\t{count}\n')
    return molecules, ''.join(includes), ''.join(rows)


def _includes(stage: Path) -> str:
    """What every topology this stage writes includes: the installed Martini 3 set.

    The bead types, the water molecule type and the ion molecule types all live there, and without them `grompp`
    refuses the solvated system because `W` is undefined. The names come from the adapter, so the two cannot drift
    apart, and the paths are relative to the stage directory they are read in, so no run copies the set and a moved
    workspace still resolves it. The detergent's own topology is the run's generated original in `inputs/`, which is
    the same path from every sibling stage.
    """
    shared = ''.join(f'#include "{martini3.include(name, stage)}"\n' for name in pdc.FORCEFIELD_FILES)
    return f'{shared}#include "../../inputs/{DETERGENT_TOPOLOGY}"\n'


def write_topologies(stage: Path, protein_topology_path: Path | None, detergent_itp: Path | None,
                     detergents: int) -> dict:
    """`system_EMPTY.top` (the protein alone, the stage's declared input) and `system.top` (the whole system).

    Both reproduce the protein's molecules **exactly as the tool that built them listed them**: the include lines name
    `../02_system/cg/<name>.itp` for every row of martinize2's own `[ molecules ]`, and the rows are copied with the
    tool's own names and counts. The counts of the detergent are the count of molecules the structure actually holds --
    the invariant `grompp` checks, and the one whose violation cost three failed sugar runs.

    A protein-free build (the empty micelle) writes the same two files with no protein row, so every reader
    downstream sees the shape it expects rather than a special case.
    """
    includes_text = _includes(stage)
    if protein_topology_path is None:
        (stage / 'system_EMPTY.top').write_text(
            '; the system before the detergent arrives, filled in by the system-preparation stage\n'
            f'{includes_text}'
            '[ system ]\nempty micelle, no protein\n\n[ molecules ]\n')
        if detergent_itp is None or not detergents:
            return {'protein_molecule': None}
        detergent = molecule_name(detergent_itp.read_text())
        (stage / 'system.top').write_text(
            f'; the whole system, written by the system-preparation stage\n'
            f'{includes_text}\n[ system ]\nempty micelle, detergent only\n\n'
            f'[ molecules ]\n{detergent}\t{detergents}\n')
        return {'protein_molecule': None, 'detergent_molecule': detergent, 'detergents': detergents}
    molecules, includes, protein_rows = protein_topology(protein_topology_path, stage)
    record = {'protein_molecule': molecules[0][0], 'protein_molecules': [name for name, _ in molecules]}
    empty = (f'; the system before the detergent arrives, filled in by the system-preparation stage\n'
             f'{includes_text}{includes}\n[ system ]\nprotein-detergent complex, CG protein\n\n'
             f'[ molecules ]\n{protein_rows}')
    (stage / 'system_EMPTY.top').write_text(empty)
    if detergent_itp is None or not detergents:
        return record
    detergent = molecule_name(detergent_itp.read_text())
    (stage / 'system.top').write_text(
        f'; the whole system, written by the system-preparation stage\n'
        f'{includes_text}{includes}\n[ system ]\n'
        f'protein-detergent complex, CG protein and detergent\n\n[ molecules ]\n'
        f'{protein_rows}{detergent}\t{detergents}\n')
    return {**record, 'detergent_molecule': detergent, 'detergents': detergents}


#: The secondary-structure source this stage wires, named in the run's report. See `secondary_structure`.
SS_SOURCE = 'mdtraj.compute_dssp'
#: The source used when the one above cannot assign: what every run before mdtraj used, and what a virtualenv
#: without mdtraj still gets. Recorded exactly as the primary source is, so a reader can tell the two apart.
SS_FALLBACK_SOURCE = 'MDAnalysis.analysis.dssp'
#: The martinize2 flag each source is wired with. `-dssp` takes no argument: bare, vermouth binds
#: `vermouth.dssp.dssp.AnnotateDSSP(executable=None)` to `run_mdtraj` and martinize2 assigns the structure itself --
#: the route the Martini 3 tutorial's own martinize2 invocation uses, and the reason mdtraj is a dependency here. An
#: *argument* to the flag would make vermouth run an external DSSP binary instead, and it trusts only versions
#: 2.2.1 and 3.0.0 of one (`SUPPORTED_DSSP_VERSIONS`), which this box does not carry. `-ss` takes the letters this
#: stage assigned, which is what the source above cannot answer with when its library is not installed.
SS_FLAG = {SS_SOURCE: '-dssp', SS_FALLBACK_SOURCE: '-ss'}
#: DSSP's own one-letter alphabet -- the keys `vermouth.dssp.dssp.SS_CG` is written against.
DSSP_LETTERS = set('HBEGITSC')


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
    """An assignment's letters as the DSSP sequence `-ss` takes, or `None` when one is not.

    MDAnalysis' DSSP implementation is three-state: `H` (any helix), `E` (extended strand) and `-` (unordered).
    martinize2 takes DSSP's own alphabet, where the unordered state is `C` -- the same state DSSP itself writes as
    a space, which vermouth's reader turns into `C` (`vermouth.dssp.SS_CG`). A letter that is neither of those is
    refused rather than translated: a source this stage does not know is not something to guess the meaning of.
    """
    letters = [str(letter) for letter in letters]
    if not letters or any(letter not in 'HE-' for letter in letters):
        return None
    return ''.join('C' if letter == '-' else letter for letter in letters)


def _mdtraj_letters(structure: Path) -> tuple[list | None, str | None]:
    """The assignment mdtraj makes, or `None` and why.

    This is the call vermouth makes for the bare `-dssp` flag: `run_mdtraj` loads a PDB and calls
    `mdtraj.compute_dssp(..., simplified=False)` -- DSSP's own *eight* states (`H B E G I T S C`), with the blank
    DSSP writes for a coil turned into `C`. Making the same call here is what lets the report carry the assignment
    martinize2 is about to build rather than a paraphrase of it: measured on 1AT9's chain A (1 778 atoms, 230
    residues), these letters and the ones the tool's own topology header records are equal letter for letter.

    A letter outside that alphabet is refused rather than passed on, and `NA` -- which mdtraj writes for a residue
    it cannot call -- is outside it: vermouth's own conversion is keyed by the eight states, so a letter it does not
    know is a build it would fail on, and the stage says so instead.
    """
    try:
        import mdtraj
    except ImportError as exc:
        return None, f'mdtraj is not importable: {exc}'
    try:
        codes = mdtraj.compute_dssp(mdtraj.load(str(structure)), simplified=False)
    except Exception as exc:                     # any failure here means "no assignment", and the run says which
        return None, f'{type(exc).__name__} from {SS_SOURCE}: {exc}'
    letters = ['C' if str(code).strip() == '' else str(code).strip() for row in codes for code in row]
    unknown = sorted(set(letters) - DSSP_LETTERS)
    if unknown:
        return None, f'{SS_SOURCE} assigned letters this stage cannot hand over: {unknown}'
    return letters, None


def _mdanalysis_letters(structure: Path) -> tuple[list | None, str | None]:
    """The assignment MDAnalysis' DSSP makes, as the three-state letters `-ss` takes, or `None` and why.

    The fallback source: MDAnalysis 2.9 ships a DSSP implementation (`MDAnalysis.analysis.dssp`, a port of pydssp).
    It is asked for only when mdtraj could not answer, and the report then names it -- so a build that fell back is
    a build whose provenance says so.
    """
    try:
        import MDAnalysis
        from MDAnalysis.analysis.dssp import DSSP
    except ImportError as exc:
        return None, f'MDAnalysis is not importable: {exc}'
    try:
        assignment = DSSP(MDAnalysis.Universe(str(structure)))
        assignment.run()
        letters = [letter for row in assignment.results.dssp for letter in row]
    except Exception as exc:                     # measured: it raises below five residues
        return None, f'{type(exc).__name__} from {SS_FALLBACK_SOURCE}: {exc}'
    sequence = ss_sequence(letters)
    if sequence is None:
        return None, f'{SS_FALLBACK_SOURCE} assigned no letters this stage can hand over ({letters[:8]})'
    return list(sequence), None


def martini_classes(letters) -> dict:
    """An assignment counted in the three classes martinize2 itself sorts the letters into.

    `vermouth.dssp.dssp.convert_dssp_to_martini` is what martinize2 runs over the letters before it builds anything,
    and its `SS_CG` table is read here so these counts cannot drift from it: every DSSP helix (`H G I`) counts as a
    helix, the two extended states (`E B`) as extended, and a turn, bend or coil as the rest. The three always sum to
    the residue count, which is what makes them a reading of the assignment rather than a separate opinion on it.
    """
    from vermouth.dssp.dssp import SS_CG

    classes = [SS_CG[str(letter)] for letter in letters]
    helix = classes.count('H')
    extended = classes.count('E')
    return {'helix': helix, 'extended': extended, 'coil': len(classes) - helix - extended}


def secondary_structure(structure: Path) -> dict:
    """The secondary structure martinize2 should build the protein with, and where it came from.

    martinize2 takes an assignment two ways, and the tool's own help is what decides between them here:

    * `-dssp` -- with **no executable** -- is the route the Martini 3 tutorial's martinize2 invocation uses, and the
      one that is wired: vermouth answers the bare flag with the **mdtraj** library (`AnnotateDSSP(executable=None)`
      binds `run_mdtraj`), so martinize2 assigns the structure itself and the eight DSSP states reach its own
      conversion, helix start/end included. Measured on 1AT9's own chain A, 230 residues of bacteriorhodopsin:
      martinize2 exit 0 with no warnings, and the letters here equal to the ones its topology header records --
      `H` 161, `G` 3, `I` 13, `S` 17, `T` 9, `C` 27;
    * `-ss <sequence>` hands it a DSSP-format letter per residue, which is the fallback: the assignment then comes
      from MDAnalysis 2.9's own DSSP implementation, and it is used when mdtraj cannot answer at all (not installed,
      or a structure it refuses). It is three-state, so martinize2 gets `H E C` only. Measured on the same chain:
      `H` 181, `C` 49, martinize2 exit 0 with no warnings.

    The two routes disagree, and the record below is what lets a reader see that rather than assume otherwise: on
    1AT9's chain A they differ on 42 of 230 letters, which is 4 residues once both are read in martinize2's own three
    classes (`H G I` helix, `E B` extended, the rest coil) -- so the SS-dependent bonded potentials they produce are
    not identical either. Both end in vermouth's `AnnotateMartiniSecondaryStructures`; what differs is who assigns
    the letters, and that is what the record names.

    Returns the record the run carries: `source` and `route` (which library, which flag), `residues`, the `letters`
    themselves so the report is auditable, and `martini_classes`. When no assignment could be made -- neither library
    importable, or a protein neither can work on -- `source` and `route` are `None` and `detail` names both reasons.
    A build with no secondary structure is martinize2's own documented case, which is what `-maxwarn 1` is for; the
    stage's job is to say which case this is, not to invent an assignment.
    """
    letters, reason = _mdtraj_letters(structure)
    source = SS_SOURCE
    if letters is None:
        letters, fallback_reason = _mdanalysis_letters(structure)
        if letters is None:
            return {'source': None, 'route': None,
                    'detail': f'{SS_SOURCE}: {reason}; {SS_FALLBACK_SOURCE}: {fallback_reason}'}
        source = SS_FALLBACK_SOURCE
    return {'source': source, 'route': SS_FLAG[source], 'residues': len(letters),
            'letters': ''.join(letters), **martini_classes(letters)}


def ss_flags(record: dict) -> list[str]:
    """What is appended to the CG protein command: how martinize2 is told to assign, and room for its one warning.

    `-dssp` is asserted *bare* here -- the route's whole point -- and `-ss` carries the letters the fallback source
    assigned. A record with no assignment behind it contributes no flag at all: a flag with nothing to answer with
    would have the tool assign an empty sequence, which is not what "no assignment" means.

    `-maxwarn 1` is the tool's own documented escape hatch for the case where no secondary structure could be
    assigned: without it, and without either flag, it logs "topology will be created without secondary structure
    information" and exits 2 having written nothing at all (measured on 1AT9's chain A with the flags as they were).
    One warning of room is allowed, and no more, so a run this flag saves is still one a reader can see in its log.
    """
    route = (record or {}).get('route')
    if route == '-dssp':
        return ['-maxwarn', '1', '-dssp']
    if route == '-ss' and (record or {}).get('letters'):
        return ['-maxwarn', '1', '-ss', record['letters']]
    return ['-maxwarn', '1']


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


def cg_protein(stage: Path, protein: Path, *, executable=None) -> tuple[list, list[str] | None, dict]:
    """The CG protein's beads, running martinize2 only when the stage has not been built before.

    martinize2's own file names are its business, so what is read back is the file its own command names (`-x`, a
    PDB) rather than a name written down here: this step used to glob `*.gro` out of `cg/`, a structure the tool
    never writes, so it raised "the CG protein step left 0 structures" however well martinize2 had run.

    It is run *in* `cg/`, because that is where it writes the molecule's own `.itp`: it writes `molecule_0.itp`
    beside itself and includes it from the `.top` by that name, so run from anywhere else the topology the next
    step needs lands in the stage directory instead (measured in a scratch directory: `-o cg/protein.top` wrote
    `./molecule_0.itp`).

    `executable` is the tool as a caller has *resolved* it (`execution/tools.tool_path`, which verifies a declared
    path before use), and `None` -- what a stage passes -- keeps the tool's own name, resolved on the PATH
    `execution/tools.search_path()` builds for a stage. A caller outside a stage has no such PATH: measured in a
    plain interpreter, `subprocess.run(['martinize2', ...])` raised `FileNotFoundError` while `tools.tool_path`
    resolved the same tool at `dashboard/.venv/bin/martinize2`, so the name alone is not a portable command.

    Returns the beads, the command that was run (`None` when the step was already built) and what the secondary
    structure assignment was, all three of which the report carries.
    """
    directory = stage / CG_DIRECTORY
    directory.mkdir(exist_ok=True)
    # The command is `pdc_protein`'s to build, and the executable is handed over only when the caller resolved one:
    # `None` is not a tool, it is the absence of a resolution, and the command then keeps the tool's own name --
    # which is also what a caller that substitutes the builder with a two-argument stub expects.
    tool = pdc_protein.martinize_command(protein, directory, executable=executable) if executable \
        else pdc_protein.martinize_command(protein, directory)
    command = _absolute(tool)
    structure = _output_path(command, '-x')
    if structure.is_file():
        return (pdc_import.structure_atoms(structure), None,
                {'source': None, 'detail': f'{structure.name} was already there, so martinize2 was not run again'})
    record = secondary_structure(protein)
    command = command + ss_flags(record)
    with (stage / 'martinize.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, cwd=directory)
    if not structure.is_file():
        raise SystemExit(f'the CG protein step wrote no {structure.name} in {directory}: '
                         f'see {stage / "martinize.log"}')
    return pdc_import.structure_atoms(structure), command, record


def prepared_protein(stage: Path) -> Path | None:
    """The structure the prepare step left, when this run asked for it and the step ran.

    The plan's step 1 is a stage of its own, and this is the one place the two are joined: the file it wrote is what
    the coarse-graining reads, so a structure whose deposited side chains are incomplete is coarse-grained from the
    rebuilt one and its beads all have positions. `None` is every run that did not ask for the step -- the default --
    and every run whose step skipped, which is what keeps an existing build doing exactly what it did before.

    Read by name rather than by counting: `pdc.stage_by_name` is where this protocol says which directory a stage
    owns, and the plan's positions have already moved once. The stage directory is resolved first, so the sibling is
    found whether the caller handed over the run's own `02_system` or the `.` a stage script passes.
    """
    directory = Path(stage).resolve().parent / Path(pdc.stage_by_name('Protein preparation').relative).parent
    path = directory / pdc_preparation.PREPARED_NAME
    return path if path.is_file() else None


def build(stage: Path) -> int:
    settings = read_settings(stage)
    # The CG protein's own directory, created for every build -- including one with no protein, which coarse-grains
    # nothing and includes nothing from it. Every leg declares this tree as an input and carries it whole
    # (`pdc.PROTEIN_TOPOLOGY_DIRECTORY`), so an empty tree is the protein-free answer, and the declaration is then one
    # spelling for every build rather than one condition the stage contract would have to be told about.
    (stage / CG_DIRECTORY).mkdir(exist_ok=True)
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
    # The membrane the belt is placed in: the statement the file this stage was handed makes about itself, read
    # through the frame module rather than reconstructed here. No protein, no statement -- both are `None`, and the
    # placement is the sphere it has always been.
    frame = None
    requested_protein = (settings.get('protein') or '').strip()
    # The structure the coarse-graining reads: the prepared one when this run asked for the prepare step and the
    # stage left one, and the run's own file otherwise. Which one it was is in the report, because a build that
    # simulated the prepared structure and one that simulated the deposited file are not the same system.
    prepared = prepared_protein(stage)
    report['protein_prepared'] = str(prepared) if prepared is not None else None
    if requested_protein:
        source = prepared if prepared is not None else resolve(settings, 'protein', stage)
        protein_input, selected_chains, dropped = select_protein(stage, source, settings.get('protein_chains'))
        report['protein_input'] = protein_input.name if protein_input.name == SELECTED_PROTEIN else None
        report['protein_dropped_residues'] = dropped
        beads, command, secondary = cg_protein(stage, protein_input)
        frame = micelle_frame.frame_from_pdb(protein_input)
    points = [list(bead['position']) for bead in beads]
    placement = pdc_placement.place_detergents(points, template, settings['aggregation_number'],
                                               settings['seed'], radius_nm=settings['radius_nm'], mode=mode,
                                               margin_nm=settings['box_margin_nm'],
                                               initial_z_nm=settings['initial_z_nm'], frame=frame)
    report.update({
        'cg_command': command,
        'secondary_structure': secondary,
        'protein_beads': len(points),
        'placement_mode': placement['mode'],
        # Which shape the lattice took, and the membrane it took it in. The coordinates alone cannot say whether a
        # shell about the centroid was a decision or the absence of a membrane, so the build states both -- and, when
        # the shape is the sphere even though the file stated a membrane, the measurement that was missing.
        'placement_shape': placement['placement_shape'],
        'membrane_frame': frame.as_record() if frame is not None else None,
        'placement_band': placement['band'],
        # The shell and the capacity are what a later reader needs to tell a measured build from a fixed-radius one.
        'placement_shell': placement.get('shell'),
        'placement_capacity': placement.get('capacity_aggregation'),
        'orientation_policy': placement.get('orientation_policy'),
        'placement_belt_reason': placement['belt_reason'],
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

    # A tube is the one case where the box is built in the membrane frame: z clears the protein, the slab it sits in
    # and the belt itself, so the margin is the protein's rather than the belt's -- and since the correction the belt
    # reaches the detergent's own length either side of the membrane centre, which on a 1.48 nm slab is further than
    # the slab by itself. `extended_box` stays the rule everywhere else: a protein-free build, a protein that states
    # no membrane, and a stated membrane holding none of the protein's atoms (both of those are the sphere, and the
    # sphere is what the old rule clears).
    if frame is not None and placement['band'] is not None:
        box = pdc_box.membrane_box(points, half_thickness_nm=frame.half_thickness_nm,
                                   margin_nm=settings['box_margin_nm'], initial_z_nm=settings['initial_z_nm'],
                                   belt_reach_nm=placement['band'].get('belt_reach_nm') or 0.0)
    else:
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
        return 3

    # The topology martinize2 wrote, by the name its own command was told to use (`pdc_protein.TOPOLOGY_NAME`), rather
    # than the first `*.itp` that sorts first in `cg/`: that guess is how a two-molecule protein came to be recorded as
    # one. Its `[ molecules ]` list is the system's, and `write_topologies` reproduces all of it.
    protein_topology_path = stage / CG_DIRECTORY / pdc_protein.TOPOLOGY_NAME
    if not protein_topology_path.is_file():
        if (settings.get('protein') or '').strip():
            raise SystemExit(f'the CG protein step wrote no {pdc_protein.TOPOLOGY_NAME}, so the system cannot be '
                             'assembled')
        protein_topology_path = None
    atoms += stamp(model, placement['centers'], placement['directions'],
                   first_residue=max([bead['residue_id'] for bead in beads], default=0) + 1)
    micelle_output.write_gro(stage / 'system.gro', atoms,
                             title=f'protein-detergent complex ({template.name}, '
                                   f'AN={settings["aggregation_number"]}, {model["residue"]})', box=box)
    topologies = write_topologies(stage, protein_topology_path, stage / DETERGENT_TOPOLOGY,
                                  len(placement['centers']))
    report.update({'valid': True, 'box_nm': box, 'atoms': len(atoms),
                   'placed_detergents': len(placement['centers']),
                   'detergent_model': settings.get('detergent_model') or {},
                   'molecules': topologies,
                   'system_top': 'system.top'})
    write_report(stage, report)
    return 0


def _detergent_model(stage: Path) -> dict | None:
    """The derived detergent, when the run was prepared with one."""
    path = stage / DETERGENT_GEOMETRY
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Build the protein-detergent complex system for a run.')
    parser.add_argument('--stage', default='.', help='the stage directory holding pdc-settings.json')
    args = parser.parse_args(argv)
    # Resolved, because the generated stage script runs from its own directory and hands over `.`: the stage reached
    # through that spelling is the *current* directory, and `Path('.').parent` is `.` -- not the run this stage is
    # one step of. Measured on a real run: the prepare step's `protein_prepared.pdb` sits beside this stage, and a
    # relative parent looked for it inside the stage's own directory, found nothing, and coarse-grained the deposited
    # file it was supposed to have replaced.
    try:
        return build(Path(args.stage).resolve())
    except (ValueError, OSError) as exc:
        print(f'pdc_build: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
