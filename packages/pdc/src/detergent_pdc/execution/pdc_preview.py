"""The placement preview: the frame a protein-detergent build would write, derived for the inputs on the form.

Option (b) of the plan's three honest answers, and the only one that is a picture of *this* build rather than of a
schematic: `pdc_build` leaves a **dry** system -- `system.gro` holds the protein and the detergents, and solvation is
the first equilibration leg's opening act. The preview derives that dry frame before the run exists, then adds the
initial solvent context: Insane's water and salt placement in the same box, cached by the dry frame's own bytes and
the salt concentration. The box boundaries and the low-opacity solvent are the cell a run would start from; the dry
beads stay the subject. Nothing is a hand-drawn prediction -- the solvent is the same `insane_solvate.place` call the
stage makes.

The pipeline is the build's own, in the build's own order, and every step is a call to the function the stage calls:

    pdc_build.select_protein -> pdc_build.cg_protein (martinize2, cached)
                             -> pdc_placement.place_detergents
                             -> pdc_box.initial_box / membrane_box / extended_box
                             -> pdc_build.stamp  (the mapping's own beads, head outward)
                             -> pdc_view.system_pdb  (the model's own bonds as CONECT records)

Two things this module exists to state rather than to hide:

* **the expensive half is the coarse-graining, and it is cached.** martinize2 is seconds (measured on this machine:
  6.7 s for one 231-residue chain, 13.6 s for 690 residues), and it depends only on the protein file's own bytes, the
  chain selection and the tool -- none of which the reader moves quickly. The cache lives under the workspace's
  `preview/cg/` directory, keyed by exactly those three things plus the protocol's own constants. Nothing a run reads
  is written here, and no run is created: a frame is derived per request and not kept at all.
* **a refusal is an answer, not a failure.** The template's own validator and the placement's clearance gate are the
  builder's gates, and their sentences are handed back as `reasons` -- with the `step` they belong to, and never with
  coordinates -- so a panel can say which gate refused even when the gate had no sentence of its own. Never a picture
  of a system the build would refuse, and never a blank.

What it deliberately does not do: draw anything the build's own functions did not produce. The solvent is Insane's
placement, not a hand-drawn grid, and a placement that cannot run leaves the dry frame and a reason rather than a
made-up cloud.

The beads are a coarse-graining of a structure, so the picture carries both halves: `basis['protein_structure']`
names the **all-atom file martinize2 was handed** -- its cache key and the URL that serves it
(`PROTEIN_STRUCTURE_ROUTE`), never the file itself, which would double every placement answer -- and the card draws
it as a neutral ribbon underneath the beads. The two are in one frame (martinize2 writes its beads in the coordinates
it read), so nothing is transformed to overlay them.

The detergent's **bonded terms** are the ones the run would simulate, which is not always the derivation: a mapping
that carries a current parameterization is simulated on that fit (`detergent_cg.adopt_stored`, the same resolver
`pdc.prepare` uses), so this module adopts the same topology rather than drawing a bond set the run would never
simulate. `basis['detergent_terms']` says which of the two the picture's bonds are -- the sentence the run's own
record carries, the count, and the revision -- because the card states that these bonds are the model's own, and
which model that is has to be answerable. Only the bonds can move between the two: the fit decides the terms, the
mapping decides where the beads are.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from dashboard import files, paths
from dashboard.analysis.runs import structures as pdc_view
from dashboard.execution.scripts import insane_solvate
from detergent_pdc.execution.adapters import pdc as pdc_adapter
from detergent_pdc.execution.adapters import pdc_box, pdc_placement, pdc_preparation, pdc_protein
from detergent_pdc.execution.adapters.pdc import DETERGENT_TOPOLOGY
from detergent_pdc.execution.scripts import pdc_build
from detergent_pdc.models.molecules import detergent_cg
from micelle import frame as micelle_frame
from micelle import registry as micelle_registry

#: Where the coarse-grained proteins are kept, relative to the workspace. Deliberately not a directory any stage
#: reads or writes: the preview derives its own frame and keeps only the coarse-grained protein, so its cache can
#: never be mistaken for a run's input.
CACHE_DIRECTORY = 'preview/cg'
#: Bumped when the shape of what an entry holds changes, so an entry written by an older version is never read as if
#: it were this one's. It is part of every key, which is what makes that true of entries on disk as well. Format 3: a
#: preview no longer asks martinize2 for a secondary-structure assignment, so an entry its older command built must not
#: be re-used as if the new derive had produced it. Format 2: an entry can hold a **prepared** protein --
#: `protein_prepared.pdb`, the preparer's log and its own `protein_input.pdb` -- which is a different entry from the one
#: the same protein coarse-grained unprepared.
CACHE_FORMAT = 3


def _refusal(step, reasons, basis, cost, *, subject=None):
    """The builder's answer when nothing can be drawn: its own sentences, the step that refused, and no coordinates.

    The sentences the builder gave are handed back exactly as it wrote them. What this adds is the step they belong
    to, and a fallback for the case where there is no sentence at all -- an exception with an empty message, a gate
    with nothing to add. A refusal that cannot say why is not the "answer, not a failure" this module promises, so
    the sentence then names the step and the file or command it was working on. The panel renders that rather than
    inventing a sentence of its own; the phrase it used to fall back on ("the build gave no reason") named nothing,
    which is how the user's 4iar refusal arrived on screen with no reason in it.
    """
    sentences = []
    for reason in reasons or []:
        if reason is None:
            continue
        text = str(reason).strip()
        if text:
            sentences.append(text)
    if not sentences:
        where = f' while working on {subject}' if subject else ''
        sentences = [f'the {step} step refused these inputs and named no reason{where}']
    return {'valid': False, 'step': step, 'reasons': sentences, 'pdb': None, 'basis': basis, 'cost': cost}


#: A cache entry's name: `cache_key`'s digest to `CACHE_KEY_LENGTH` hex characters, and the only spelling anything
#: resolving an entry will take. The preview's protein route validates against this pattern rather than against the
#: filesystem, so a key can never name a path outside the cache root -- there is no separator, no dot and no case in
#: it to escape with -- and a typo is answered as a malformed request instead of as a missing file.
CACHE_KEY_LENGTH = 16
CACHE_KEY_PATTERN = re.compile(rf'[0-9a-f]{{{CACHE_KEY_LENGTH}}}')

#: The all-atom structure inside an entry, in the order it is looked for: the **prepared** protein when the derive
#: asked for `prepare_protein` (that is the file `coarse_grained` hands martinize2 in a run, so it is the one the
#: beads came from), and the **chain selection** otherwise (`pdc_build.select_protein`'s own output). Either is in the
#: frame martinize2 wrote the beads in, which is what lets a ribbon drawn from it overlay the beads with no transform;
#: an entry whose source file needed neither holds neither, and then there is no all-atom structure to draw.
PROTEIN_STRUCTURES = (pdc_preparation.PREPARED_NAME, pdc_build.SELECTED_PROTEIN)

#: The route that serves an entry's all-atom protein. The placement's `basis` names this URL beside the key, so the
#: client never builds a URL -- one spelling of it, in the module that answers with the other half of the picture.
PROTEIN_STRUCTURE_ROUTE = '/api/pdc/preview/protein'


def protein_structure_path(entry):
    """The all-atom structure martinize2 was handed for a cache entry, or `None` when the entry holds none.

    One rule, used by the service that names the structure and by the route that serves it, so the two cannot point
    at different files: the prepared protein first (a prepared entry coarse-grains that one), the chain selection
    otherwise. A directory that is not an entry -- no `protein_selected.pdb`, no `protein_prepared.pdb` -- answers
    `None` rather than falling back to whatever the caller would have read next.
    """
    for name in PROTEIN_STRUCTURES:
        path = Path(entry) / name
        if path.is_file():
            return path
    return None


def protein_structure_basis(key, entry):
    """The all-atom protein's key and URL, for the basis of a frame whose beads were coarse-grained from it.

    `None` unless the entry really holds that structure: a basis that named a URL answering `404` would put a
    control on the card for a layer that cannot be drawn, and a build with no protein has no entry at all. The key is
    the entry's own name (`cost['cg_key']`), validated as one, so the URL is a read of the cache and nothing else.
    """
    token = str(key or '')
    if not entry or not CACHE_KEY_PATTERN.fullmatch(token) or protein_structure_path(entry) is None:
        return None
    return {'key': token, 'url': f'{PROTEIN_STRUCTURE_ROUTE}?key={token}'}


def cache_key(protein_path, chains, executable, *, prepare=False, prepare_executable=None) -> str:
    """The cache entry a protein-and-selection belongs to, from the things that decide the beads.

    The protein file's own bytes rather than its name: a re-imported structure at the same path is a different
    structure, and only one of the two is the one on screen. The chains, because a strict subset is filtered into a
    different file before martinize2 reads it -- `pdc_build.select_protein` writes `protein_selected.pdb`. The tool's
    own bytes, because a different martinize2 builds a different coarse-grained protein, and `None` when nothing
    resolved (an entry made through a stubbed step is still keyed, and says which tool it is not for).

    The prepare step is in the key too, both the choice and the preparer that would answer it: an entry whose beads
    were built from a structure PDB2PQR rebuilt is a different coarse-grained protein from the same file's, and
    reading one as the other would draw a frame the run would not build. The preparer's own bytes are read when it
    resolves, so a different release is a different entry -- and only when the step is asked for, so an unprepared
    entry's key does not move with a tool it never runs.

    The elastic network's constants and the force field are in the key as well, which is what keeps a change to them
    from leaving a frame silently drawn from the old ones.
    """
    digest = hashlib.sha256()
    digest.update(str(CACHE_FORMAT).encode())
    digest.update(Path(protein_path).read_bytes())
    digest.update(b'\0' + ','.join(str(chain) for chain in (chains or [])).encode())
    digest.update(b'\0prepare:' + (b'1' if prepare else b'0'))
    if prepare:
        preparer = str(prepare_executable or '')
        digest.update(b'\0' + preparer.encode())
        if preparer and Path(preparer).is_file():
            digest.update(b'\0' + files.sha256(preparer).encode())
    executable = str(executable or '')
    digest.update(b'\0' + executable.encode())
    if executable and Path(executable).is_file():
        digest.update(b'\0' + files.sha256(executable).encode())
    digest.update(f'\0{pdc_protein.DEFAULT_FORCE_FIELD}|{pdc_protein.FORCE_CONSTANT}'
                  f'|{pdc_protein.UPPER_BOUND_NM}'.encode())
    return digest.hexdigest()[:CACHE_KEY_LENGTH]


def coarse_grained(cache_root, protein_path, chains, *, executable=None, prepare=False,
                   prepare_executable=None):
    """The CG protein's beads, from the cache when it is there and from martinize2 when it is not.

    It calls the stage's own `pdc_build.select_protein` and `pdc_build.cg_protein`, so the file martinize2 reads, the
    command it is handed and the file read back are the build's, not a second reading of them. What differs from a
    stage is where the two write: the entry directory, under the workspace's preview cache, rather than a stage
    directory of a run that does not exist.

    `prepare` runs the plan's step 1 in the same entry, before the coarse-graining and only when the entry has no
    coarse-grained structure yet -- a cached entry re-derives without paying the preparer again. The prepared
    structure is what martinize2 is handed, exactly as `pdc_build.prepared_protein` hands it in a run, so a preview
    and the build it previews coarse-grain one file. A preparation the tool refuses raises
    `pdc_preparation.PreparationRefused`, which the caller turns into a refusal naming that step: the shape every
    other builder gate's refusal arrives in.

    The gate on running the tool at all is the one `cg_protein` already applies -- the file its own command names --
    so a preview and a build re-derive a step in the same circumstances.
    """
    entry = Path(cache_root) / cache_key(protein_path, chains, executable, prepare=prepare,
                                         prepare_executable=prepare_executable)
    entry.mkdir(parents=True, exist_ok=True)
    protein_input, selected, dropped = pdc_build.select_protein(entry, Path(protein_path), chains)
    structure = entry / pdc_build.CG_DIRECTORY / 'protein_cg.pdb'
    prepared_path = entry / pdc_preparation.PREPARED_NAME
    record = None
    # The prepared structure is coarse-grained whenever it is here, and here it is whenever the form asked for it:
    # the entry is keyed on that choice, so a prepared file cannot reach a derive that did not ask for one.
    if prepare and not (structure.is_file() and prepared_path.is_file()):
        record = pdc_preparation.prepare(protein_input, entry, executable=prepare_executable)
        if not record.get('ok'):
            raise pdc_preparation.PreparationRefused(record.get('reason')
                                                     or 'the protein preparation step could not run')
        prepared_path = Path(record['path'])
    if prepared_path.is_file():
        protein_input = prepared_path
    started = time.perf_counter()
    # The preview wants the beads and no secondary-structure assignment: the picture does not colour a backbone by
    # one, and asking for it here would hand martinize2 a flag the build this preview stands for does not use.
    beads, command, _ = pdc_build.cg_protein(entry, protein_input, executable=executable, assign_structure=False)
    seconds = time.perf_counter() - started

    # The command `cg_protein` would have run names the file it writes; a step that was already built returns the
    # beads with no command, which is this entry being re-used rather than a second run of the tool. The bytes are
    # the tool's own output, so they are the size the panel reports as kept.
    return beads, {'cached': command is None, 'seconds': seconds,
                   'key': entry.name, 'path': str(entry),
                   'beads_bytes': structure.stat().st_size if structure.is_file() else 0,
                   'dropped_residues': dropped, 'protein_input': protein_input.name,
                   'structure': str(protein_input), 'command': command,
                   # The step's own record and its wall time, or `None` and zero for a derive that did not ask for
                   # it. `prepare_seconds` is what the panel's Cost row reports for it.
                   'prepare': record, 'prepare_seconds': round(float(record['seconds']), 3) if record else 0.0}


def resolve_mapping(mapping, root):
    """A saved candidate by whichever of its names the caller used, resolved as `pdc.prepare` resolves one.

    The panel offers the names the mapping store lists, so a run resolves a candidate by *name* before it looks for a
    path -- and the preview has to answer about the mapping the run would build from, not about a file at a path the
    reader's spelling happens to make. A name the store does not hold falls back to a path under the project root,
    exactly as `pdc.prepare` does, so an explicit path still works.
    """
    source = Path(str(mapping))
    if source.is_file():
        return source
    from dashboard.models.mappings import store

    candidate = store.candidate_paths().get(source.name)
    if candidate:
        return Path(candidate)
    return source if source.is_absolute() else Path(root) / source


def _discard_unreadable(cache_root, protein_path, chains, executable, *, prepare=False,
                       prepare_executable=None) -> bool:
    """Remove a cache entry whose CG structure cannot be read, so the next derive builds it again.

    A truncated or half-written `protein_cg.pdb` would otherwise be re-used forever: `pdc_build.cg_protein`'s gate is
    the file's presence, and a reader of coordinates that answers nothing is the defect this stage already had once.
    Two previews of the same protein can also be in flight at once, and the second must not be left with the first's
    partial file. Only an entry that is genuinely unreadable is removed -- a protein the tool refuses leaves no
    structure to remove. The entry is keyed by the same choices the derive was keyed by, so a prepared derive discards
    the prepared entry rather than the unprepared one it never looked at.
    """
    from detergent_pdc.execution.adapters import pdc_import

    entry = Path(cache_root) / cache_key(protein_path, chains, executable, prepare=prepare,
                                         prepare_executable=prepare_executable)
    structure = entry / pdc_build.CG_DIRECTORY / 'protein_cg.pdb'
    if not structure.is_file():
        return False
    try:
        pdc_import.structure_atoms(structure)
    except (ValueError, OSError):
        shutil.rmtree(entry, ignore_errors=True)
        return True
    return False


def detergent_model(mapping_path, molecule_root, project_root):
    """The detergent's beads and the topology that bonds them, as the run will build that topology.

    `models.molecules.detergent_cg.derive` is the one derivation a run uses (`pdc.prepare` writes its `topology` as
    `detergent_CG.itp` and its `beads` as `detergent_CG.json`), so the preview stamps the same molecule the run will.

    The *terms* are the run's too. A mapping that carries a current parameterization is simulated on that fit's
    bonded terms (`pdc.prepare` adopts it through `detergent_cg.adopt_stored`), so the preview adopts the same
    topology rather than handing the card a derivation the run would never simulate -- the card says the bonds are
    the model's own, and a derived bond set under a fitted run is a false statement, not a cosmetic one. The fit
    decides the terms and the mapping decides where the beads are, so the geometry, and every position in the frame,
    is identical either way; only the bonds can differ, which is exactly what this function must get right.

    `source` is `detergent_cg.terms_source`'s sentence -- the one the run's own record carries -- so the card and the
    manifest cannot describe the same build two ways. A fitted model states the fit's own term count and drops the
    derivation's reference/fallback split, because it simulates none of those terms.

    Not cached: it is derived from the mapping the reader is choosing, in under a second, and a second cache of a
    second derived artifact is one more thing to invalidate for a saving the plan did not ask for.
    """
    started = time.perf_counter()
    draft = detergent_cg.derive(Path(mapping_path), Path(molecule_root), Path(project_root))
    adopted = detergent_cg.adopt_stored(draft, detergent_cg.candidate(Path(mapping_path)))
    source = detergent_cg.terms_source(adopted, draft)
    if not adopted:
        return {**draft, 'source': source}, time.perf_counter() - started
    # A fitted model carries the fit's own term count and no reference/fallback split: it derived none of those
    # terms, and a reader comparing the two counts would be reading one model's numbers beside another's topology.
    fitted = {key: value for key, value in draft.items() if key not in ('reference_terms', 'fallback_terms')}
    return ({**fitted, 'topology': adopted['topology'], 'terms': adopted['total'],
             'parameterization': adopted['parameterization'], 'source': source}, time.perf_counter() - started)


#: The version of the preview's solvent cache entry. Bumped when the entry's shape changes, so an older file is
#: regenerated rather than read as if it were this one's.
SOLVENT_CACHE_VERSION = 2
#: Water and ions a preview shows. They are the real Insane placement, cached by the dry system's own bytes and the
#: salt concentration: the first derive pays for it, the next one on the same frame reads the cache.
SOLVENT_CACHE_DIRECTORY = 'solvent'


def _gro_text(atoms, box):
    """The dry system as a `.gro` Insane reads: a title, the count, one fixed-width line per bead, and the box."""
    lines = ['placement preview solute', f'{len(atoms):5d}']
    for index, atom in enumerate(atoms, start=1):
        residue = str(atom['residue'])[:5]
        name = str(atom['name'])[:5]
        x, y, z = (float(value) for value in atom['position'])
        lines.append(f'{int(atom["residue_id"]):5d}{residue:<5}{name:>5}{index:5d}'
                     f'{x:8.3f}{y:8.3f}{z:8.3f}')
    lines.append(''.join(f'{float(value):9.5f}' for value in box[:3]))
    return '\n'.join(lines) + '\n'


def _read_solvated(path, solute_count):
    """The solute's placed positions and the solvent beads Insane wrote, in that order."""
    lines = Path(path).read_text().splitlines()
    if len(lines) < 2:
        raise ValueError(f'Insane wrote no atoms to {path}')
    beads = []
    for line in lines[2:-1]:
        beads.append({'residue_id': int(line[:5]), 'residue': line[5:10].strip(),
                      'name': line[10:15].strip(),
                      'position': [float(line[20 + 8 * axis:28 + 8 * axis]) for axis in range(3)]})
    solute, solvent = beads[:solute_count], beads[solute_count:]
    return solute, solvent


def _solvent(atoms, box, salt_molar, cache_root):
    """The initial solvated cell: Insane's water and salt, with the solute moved as Insane writes it.

    The dry frame is the build's artifact; the solvent is the first equilibration leg's opening act. Showing it is
    only honest if it is the placement a run would get, so this calls the same helper the stage calls -- never a
    hand-drawn grid -- and caches the result under the workspace's preview scratch, keyed by the dry system and the
    salt concentration. The cache is preview-only and no stage reads it.
    """
    text = _gro_text(atoms, box)
    key = hashlib.sha256(f'{SOLVENT_CACHE_VERSION}\n{salt_molar}\n{text}'.encode()).hexdigest()
    directory = Path(cache_root) / SOLVENT_CACHE_DIRECTORY
    cached = directory / f'{key}.json'
    if cached.is_file():
        try:
            answer = json.loads(cached.read_text())
        except (OSError, ValueError):
            answer = None
        if isinstance(answer, dict) and answer.get('version') == SOLVENT_CACHE_VERSION:
            answer['cached'] = True
            return answer
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as scratch:
        structure, output = Path(scratch) / 'solute.gro', Path(scratch) / 'solvated.gro'
        structure.write_text(text)
        insane_solvate.place(structure, output, salt_molar=salt_molar, charge='auto')
        solute, solvent = _read_solvated(output, len(atoms))
    # Insane centres its own solute before it places the solvent; keep the aligned dry system where it was and undo
    # that one translation on the solvent. The order is the build's: build, align the system's centre, solvate.
    insane_shift = [float(solute[0]['position'][axis]) - float(atoms[0]['position'][axis]) for axis in range(3)]
    residue_id = max((int(atom['residue_id']) for atom in atoms), default=0)
    water, ions = [], []
    for bead in solvent:
        residue_id += 1
        kind = bead['residue']
        if kind == 'W':
            target = water
        elif kind in ('NA', 'CL'):
            target = ions
        else:
            continue
        target.append({'residue_id': residue_id, 'residue': kind, 'name': bead['name'],
                       'position': [round(float(value) - shift, 5)
                                    for value, shift in zip(bead['position'], insane_shift)]})
    answer = {'version': SOLVENT_CACHE_VERSION, 'cached': False,
              'water': water, 'ions': ions,
              'water_residues': [water[0]['residue_id'], water[-1]['residue_id']] if water else None,
              'ion_residues': [ions[0]['residue_id'], ions[-1]['residue_id']] if ions else None,
              'molecules': {'W': len(water), 'NA': sum(1 for ion in ions if ion['residue'] == 'NA'),
                            'CL': sum(1 for ion in ions if ion['residue'] == 'CL')}}
    files.atomic_json(cached, answer)
    return answer


def _wrap(atoms, origin, box):
    """Put every molecule in the primary cell the box edges draw, whole.

    Insane writes a solvated frame without wrapping its solute/solvent into the cell -- the stage lets GROMACS do
    that when it reads the structure -- but the preview's PDB has no periodic machinery, so a bead outside the drawn
    cell would look like a second, broken system. Wrapping each atom alone would cut a detergent molecule in half
    across a face; the molecule's centre decides the translation and every bead of it moves together. Wrapping is
    display-only: the run's own structure is not changed.
    """
    lengths = [float(value) for value in box[:3]]
    molecules = {}
    for atom in atoms:
        molecules.setdefault((str(atom['residue']), int(atom['residue_id'])), []).append(atom)
    for beads in molecules.values():
        centre = [sum(float(bead['position'][axis]) for bead in beads) / len(beads) for axis in range(3)]
        shift = [round(float(origin[axis])
                       + (centre[axis] - float(origin[axis])) % lengths[axis] - centre[axis], 5)
                 for axis in range(3)]
        for bead in beads:
            bead['position'] = [round(float(bead['position'][axis]) + shift[axis], 5) for axis in range(3)]
    return atoms


def _box(points, placement, frame, margin_nm, initial_z_nm):
    """The box the build writes, by the build's own rule (`pdc_build.build`), and no second rule here.

    A band is the one case where the box is built in the membrane frame: z clears the protein and the slab it sits in.
    Everything else -- a protein-free build, a protein that states no membrane, a stated membrane holding none of the
    protein's atoms -- is `extended_box` over the box the placement was built for.
    """
    initial = pdc_box.initial_box(points or placement['centers'], margin_nm=margin_nm, initial_z_nm=initial_z_nm)
    if frame is not None and placement['band'] is not None:
        belt_reach_nm = placement['band'].get('belt_reach_nm') or 0.0
        return pdc_box.membrane_box(points, half_thickness_nm=frame.half_thickness_nm, margin_nm=margin_nm,
                                    initial_z_nm=initial_z_nm, belt_reach_nm=belt_reach_nm)
    return pdc_box.extended_box(initial[:2], placement['centers'], margin_nm=margin_nm)


def preview(*, project_root, cache_root, template, seed, protein=None, chains=None, mapping=None,
            molecule_id=None, aggregation_number=150, placement_mode=pdc_placement.DEFAULT_PLACEMENT_MODE,
            box_margin_nm=pdc_placement.DEFAULT_MARGIN_NM, initial_z_nm=pdc_placement.DEFAULT_INITIAL_Z_NM,
            radius_nm=pdc_placement.DEFAULT_RADIUS_NM, executable=None, prepare_protein=False,
            prepare_executable=None, conformation_library=None, workspace=None, belt_gap_nm=0.0,
            min_body_gap_nm=pdc_placement.DEFAULT_MIN_BODY_GAP_NM,
            belt_axial_window_nm=pdc_placement.DEFAULT_BELT_AXIAL_WINDOW_NM,
            salt_molar=0.15,
            belt_vertical_spread=pdc_placement.DEFAULT_BELT_VERTICAL_SPREAD,
            belt_offset_nm=pdc_placement.DEFAULT_BELT_OFFSET_NM):
    """The placement these inputs would build, as `{valid, step, reasons, pdb, basis, cost}`.

    `project_root` resolves `template`, `protein` and the molecule tree a mapping is derived against -- the same root
    a run's `pdc.prepare` is given. `cache_root` is the preview's own scratch root; the only thing written under it
    is a coarse-grained protein, and with `prepare_protein` a prepared one besides. `molecule_id` is the detergent the
    mapping belongs to; a mapping is a mapping *of* a molecule and the residue the structure is written with comes
    from it.

    `basis['detergent']` and `basis['residue']` name the molecule the frame is drawn from, and when a detergent model
    was derived -- from the mapping, or from the conformation library's own derive -- both come from that model rather
    than from the template: the catalogue ships DDM's skeleton for every detergent, and an OG mapping previewed with
    the template's residue would write its beads as protein. A centres-only build has no model and keeps the
    template's residue.

    `basis['protein_residues']` is the number of distinct protein residue keys `(residue.upper(), residue_id)` the
    frame's leading protein atoms hold -- the origin of the residue numbers `system_pdb` gives them. It is `0` for an
    empty micelle, and the browser reads it to draw only the detergent (`residue number > protein_residues`).

    `basis['detergent_terms']` is which terms the picture's bonds are: `{source, terms, revision}` when the mapping
    was given. `source` is the sentence the run's own record carries (`detergent_cg.terms_source`), `terms` the count
    of the topology drawn, and `revision` the parameterization revision that topology was adopted from, or `None` for
    a derivation. It is `None` for a centres-only build, which draws no bonds to attribute.

    `prepare_protein` is the plan's step 1, and it is the reader's choice rather than the service's: with it, the
    protein is rebuilt and protonated by `pdb2pqr` (or `prepare_executable`, where the route has resolved one) before
    the coarse-graining reads it, exactly as the stage hands it over in a run. A preparation that cannot run comes
    back as a refusal naming that step, with the tool's own sentence -- never as a frame built from the file the
    caller asked to have prepared.

    `conformation_library` is the run's own setting, in either of its shapes (source runs to build from, or a stored
    key and digest), resolved against `workspace` -- the workspace a run would be prepared in, or the current one.
    The library is matched bead for bead against the mapping's model before anything is placed, the placement draws
    one entry and one azimuth per site from it, and `stamp` turns each body by its drawn azimuth. The resolved key,
    size, mode and source run ids travel in `basis['conformations']` and never the coordinates; `None` is the
    single-conformation build this service has always drawn. A spec the library package refuses is a `ValueError`
    (a malformed request); a library that is missing, changed or not this run's detergent is a refusal here, with
    the package's own sentence.

    `belt_gap_nm` is the run's extra stand-off between the protein's measured cylinder surface and the belt's
    detergent bodies, forwarded to the placement and to nothing else: a sphere placement never reads it, so an
    unstated gap keeps the frame a build has always written and `0.0` is byte-identical to it. `min_body_gap_nm` and
    `belt_axial_window_nm` are the belt's packing and local-surface settings, forwarded the same way and recorded in
    `basis`; both reach only a belt, exactly as in the build.

    `salt_molar` is the run's salt setting; the initial water and ions are Insane's placement at that concentration,
    cached under `cache_root` and named in `basis['solvent']` (`W`, `NA`, `CL`, `salt_molar`, `cached`) with the
    residue ranges the card uses to draw them. A solvent placement that cannot run leaves `basis['solvent']` None and
    `basis['solvent_reason']` set; the dry frame and its box are still answered.

    Raises `ValueError` for a question that cannot be asked at all -- a template or protein that is not a file, a
    chain the file does not name, a mapping that does not exist, a count below one, a preparation asked for with no
    protein to prepare -- because those are malformed requests and not this build's refusals. Everything the
    *builders* refuse comes back as `valid: False` with their own sentences.
    """
    seed = int(seed)
    aggregation_number = int(aggregation_number)
    margin = float(box_margin_nm)
    initial_z = float(initial_z_nm)
    radius = float(radius_nm)
    salt_molar = float(salt_molar)
    if salt_molar < 0:
        raise ValueError('salt concentration cannot be negative')
    mode = pdc_placement.canonical_mode(placement_mode)

    root = Path(project_root)
    template_path = Path(template)
    if not template_path.is_absolute():
        template_path = root / template_path
    if not template_path.is_file():
        raise ValueError(f'the pdc template is not a file: {template_path}')
    protein_path = None
    if protein:
        candidate = Path(protein)
        protein_path = candidate if candidate.is_absolute() else root / candidate
        if not protein_path.is_file():
            raise ValueError(f'the pdc protein is not a file: {protein_path}')
    # A step about a protein cannot be asked for a form that has none: the same refusal `pdc.prepare` makes, in the
    # terms this service answers in.
    if prepare_protein and protein_path is None:
        raise ValueError('protein preparation (PDB2PQR) needs a structure, and this form selects no protein')

    basis = {'protein': Path(protein_path).stem if protein_path else None, 'chains': list(chains or []),
             'template': template_path.name, 'detergent': None, 'residue': None, 'mapping': None,
             'aggregation_number': aggregation_number, 'placement_mode': mode, 'seed': seed,
             'beads': None, 'protein_beads': 0, 'box_nm': None, 'clearance_nm': None,
             'salt_molar': None, 'solvent': None, 'solvent_reason': None,
             'water_residues': None, 'ion_residues': None, 'centring': None,
             'box_origin_nm': [0.0, 0.0, 0.0], 'belt_offset_nm': None,
             'placement_shape': None, 'band_radius_nm': None, 'band_radius_min_nm': None,
             'band_radius_max_nm': None, 'slab_radius_nm': None,
             'detergent_representation': None,
             # Which terms the picture's bonds are -- the mapping's fit or its derivation -- in the run's own words.
             # `None` for a centres-only build, which draws no bonds to attribute.
             'detergent_terms': None,
             # The plan's step 1: whether this derive would prepare the protein, and the record when it did.
             'prepare_protein': bool(prepare_protein), 'prepare': None,
             # The number of distinct protein residues the frame's leading atoms hold. `0` until a frame is drawn,
             # and for an empty micelle: the browser draws only the detergent from `residue number > this`.
             'protein_residues': 0,
             # The all-atom protein the beads were coarse-grained from: `{key, url}` for the route that serves it, so
             # the card can draw a ribbon of the structure the beads stand for. `None` for a build with no protein,
             # and for a derive whose entry holds no such structure -- see `protein_structure_basis`.
             'protein_structure': None,
             # The conformation library this derive draws from: `{key, size, mode, sources}` once one is resolved,
             # never its coordinates. `None` is the single-conformation build, and so is a derive that is refused
             # before the library resolves.
             'conformations': None}
    cost = {'cg_cached': False, 'coarse_graining_seconds': 0.0, 'detergent_seconds': 0.0,
            'placement_seconds': 0.0, 'seconds': 0.0, 'cg_bytes': 0, 'cg_key': None, 'prepare_seconds': 0.0,
            'solvation_seconds': 0.0}
    started = time.perf_counter()

    # The template first, because the build does: a template that cannot build a system stops the stage before
    # anything is placed, and its own validator's sentences are the refusal.
    try:
        record = micelle_registry.load_template(template_path)
    except (ValueError, OSError) as error:
        return _refusal('template', [str(error)], basis, cost, subject=template_path)
    basis.update({'detergent': record.name, 'residue': record.residue})
    template_issues = list(micelle_registry.validate_template(record))
    if template_issues:
        return _refusal('template', template_issues, basis, cost, subject=template_path)

    # The chains are the file's question, and the adapter's own gate answers it: a chain the structure does not name
    # is refused there, with the file's own list, rather than silently building something else.
    selected_chains = None
    if protein_path is not None:
        selected_chains = pdc_adapter.validate_chains(protein_path, chains)
    basis['chains'] = list(selected_chains or [])

    beads, frame, cg = [], None, {}
    if protein_path is not None:
        try:
            beads, cg = coarse_grained(cache_root, protein_path, selected_chains, executable=executable,
                                       prepare=prepare_protein, prepare_executable=prepare_executable)
        except pdc_preparation.PreparationRefused as error:
            # The plan's step 1 refused, and its sentence is the tool's own. A refusal from *this* step is not a
            # coarse-graining failure: it is the answer to "this structure could not be prepared", and the card says
            # which step it came from.
            cost['seconds'] = time.perf_counter() - started
            return _refusal('protein preparation', [str(error)], basis, cost,
                            subject=f'{protein_path} ({prepare_executable or pdc_preparation.TOOL})')
        except (OSError, subprocess.SubprocessError, ValueError, SystemExit) as error:
            # A cache entry that cannot be read is removed rather than left to fail identically forever.
            discarded = _discard_unreadable(cache_root, protein_path, selected_chains, executable,
                                            prepare=prepare_protein, prepare_executable=prepare_executable)
            cost['seconds'] = time.perf_counter() - started
            detail = '; its cached entry was unreadable and has been discarded, so the next derive builds it again' \
                if discarded else ''
            return _refusal('coarse-graining',
                            [f'the coarse-graining step could not build this protein: {error}{detail}'], basis, cost,
                            subject=f'{protein_path} ({executable or "martinize2"})')
        cost.update({'cg_cached': cg['cached'], 'coarse_graining_seconds': round(cg['seconds'], 3),
                     'cg_bytes': cg['beads_bytes'], 'cg_key': cg['key'],
                     'prepare_seconds': cg.get('prepare_seconds', 0.0)})
        basis['prepare'] = cg.get('prepare')
        # The frame is read from the file martinize2 was actually handed -- the prepared structure when this derive
        # asked for one, the selection otherwise -- because that file's own membrane statement is the frame the belt
        # is placed in. A caller that substituted the coarse-graining step answers with no such path, and falls back
        # to the protein the run named.
        structure = Path(cg['structure']) if cg.get('structure') else None
        frame = micelle_frame.frame_from_pdb(
            structure if structure is not None and structure.is_file()
            else ((Path(cg['path']) / pdc_build.SELECTED_PROTEIN)
                  if (Path(cg['path']) / pdc_build.SELECTED_PROTEIN).is_file() else protein_path))
    basis['protein_beads'] = len(beads)

    # A conformation library is drawn at the sites, so it resolves before the placement -- and it is matched against
    # the run's own detergent, so the model it is matched against is derived here rather than after the placement.
    # `None` is today's derive: nothing about it moves, and the model is still derived below on that path.
    library, conformations, spec = None, None, None
    model, model_seconds, mapping_path = None, 0.0, None
    if conformation_library is not None:
        from detergent_pdc import conformations as conformations_package
        # A malformed spec is a question that cannot be asked, so it stays a `ValueError` the route answers with 400:
        # the package's sentence names the field that is wrong.
        spec = conformations_package.normalise_spec(conformation_library)
        if not mapping:
            cost['seconds'] = time.perf_counter() - started
            return _refusal('conformation library',
                            ['the form names a conformation library and no detergent mapping: the library is matched '
                             'bead for bead against the mapping\u2019s model, so there is nothing to shape or to match '
                             'it against'], basis, cost, subject=template_path)
        mapping_path = resolve_mapping(mapping, root)
        if not mapping_path.is_file():
            raise ValueError(f'the detergent mapping is not a file: {mapping_path}')
        model, model_seconds = detergent_model(mapping_path, root / 'molecules', root)
        if molecule_id and str(model['molecule_id']) != str(molecule_id):
            raise ValueError(f'the mapping {mapping_path.name} is of {model["molecule_id"]}, not of {molecule_id}')
        basis['mapping'] = mapping_path.name
        workspace_root = Path(workspace) if workspace is not None else paths.current().workspace
        store = conformations_package.store_root(workspace_root)
        held = {path.resolve() for path in store.glob('*/*')} if store.is_dir() else set()
        started_library = time.perf_counter()
        try:
            library = conformations_package.resolve(workspace_root, spec, build=True)
        except (OSError, ValueError) as error:
            cost['seconds'] = time.perf_counter() - started
            return _refusal('conformation library', [str(error)], basis, cost, subject=workspace_root)
        cost['conformations_seconds'] = round(time.perf_counter() - started_library, 3)
        # The store already holding the key is what a cached resolve is: it re-read and verified the copy instead of
        # reading the source trajectories. A resolve that had to repair a corrupt copy pays the build and says so in
        # the seconds beside this flag.
        cost['conformations_cached'] = library.path.parent.resolve() in held
        try:
            library.assert_matches(residue=model.get('residue') or record.residue,
                                   beads=[bead['name'] for bead in model['beads']],
                                   mapping_sha256=files.sha256(mapping_path))
        except ValueError as error:
            cost['seconds'] = time.perf_counter() - started
            return _refusal('conformation library', [str(error)], basis, cost, subject=workspace_root)
        conformations = library.conformations()
        # The resolved copy, never its coordinates: what the card prints, and what a reader needs to find the same
        # library again. `mode` is how the run named it; `sources` are the runs the stored file itself names.
        basis['conformations'] = {'key': library.key, 'size': library.size, 'mode': spec['mode'],
                                  'sources': [entry['run_id'] for entry in library.sources]}

    # The detergent model is derived **before** the placement: the clearance and packing gates and the belt's own
    # stand-off measure the beads the build actually stamps, so gating on the template's all-atom file would refuse a
    # belt whose stamped bodies fit. The library's branch above may already have derived it, and a build with no
    # mapping has no model -- an explicit `None` body profile is its centres-only answer.
    if model is None and mapping:
        if mapping_path is None:
            mapping_path = resolve_mapping(mapping, root)
        if not mapping_path.is_file():
            raise ValueError(f'the detergent mapping is not a file: {mapping_path}')
        model, model_seconds = detergent_model(mapping_path, root / 'molecules', root)
        # A mapping is a mapping *of* a molecule, and the picture is drawn from the mapping's own beads. A form that
        # offers one detergent with another's mapping would draw the other molecule while saying this one, so the two
        # have to agree before anything is derived.
        if molecule_id and str(model['molecule_id']) != str(molecule_id):
            raise ValueError(f'the mapping {mapping_path.name} is of {model["molecule_id"]}, not of {molecule_id}')
        basis['mapping'] = mapping_path.name
    body_profile = pdc_placement.detergent_profile_from_model(model, record) if model is not None else None

    # The membrane the belt is placed in is the protein file's own statement of it, read through `micelle.frame` --
    # the same reader the build uses, so the two cannot disagree about which shape this placement takes.
    points = [list(bead['position']) for bead in beads]
    started_placement = time.perf_counter()
    placement = pdc_placement.place_detergents(points, record, aggregation_number, seed, radius_nm=radius, mode=mode,
                                              margin_nm=margin, initial_z_nm=initial_z, frame=frame,
                                              conformations=conformations, belt_gap_nm=float(belt_gap_nm),
                                              min_body_gap_nm=float(min_body_gap_nm),
                                              belt_axial_window_nm=float(belt_axial_window_nm),
                                              vertical_spread=float(belt_vertical_spread),
                                              belt_offset_nm=float(belt_offset_nm),
                                              body_profile=body_profile)
    cost['placement_seconds'] = round(time.perf_counter() - started_placement, 3)
    # The belt's own radius, and the numbers it was derived from. A belt's surface follows the protein locally, so
    # `band_radius_nm` is the mean local surface and `band_radius_min_nm`/`band_radius_max_nm` are its range; the
    # card states the range where it varies. `slab_radius_nm` is the cylinder's one global measurement, kept beside
    # it so a reader can see what a single furthest atom would have reported.
    band = placement['band'] or {}
    shell = placement.get('shell') or {}
    # The shell's own numbers, and the density they and the count make. `shell`/`band` are never both set: a belt's
    # volume is the torus's (Pappus) and a sphere's is the ball's, so the panel reads one pair of fields for either
    # shape and the shape's name says which geometry produced them.
    shape_record = shell or band
    basis.update({'placement_shape': placement['placement_shape'], 'clearance_nm': placement['protein_clearance_nm'],
                  'band_radius_nm': band.get('radius_nm'),
                  'band_radius_min_nm': band.get('radius_min_nm'),
                  'band_radius_max_nm': band.get('radius_max_nm'),
                  'slab_radius_nm': band.get('slab_radius_nm'),
                  'detergent_length_nm': band.get('detergent_length_nm'),
                  # The cylinder the belt was measured about, and the vertical band and tilt the sites were given,
                  # so the panel can name the shape without re-deriving it from the coordinates.
                  'cylinder': band.get('cylinder'),
                  'vertical_half_band_nm': band.get('vertical_half_band_nm'),
                  'tilt_deg': band.get('tilt_deg'),
                  # The belt's two packing settings, as the placement measured under them. `None` for the sphere and
                  # for a self-assembled cloud, which read neither.
                  'min_body_gap_nm': band.get('min_body_gap_nm'),
                  'axial_window_nm': band.get('axial_window_nm'),
                  'vertical_spread': band.get('vertical_spread'),
                  # The sphere's measured radius (a belt's is `band_radius_nm` above), and which number decided it --
                  # the protein's own extent or the radius setting used as a floor. A run that selects one subunit
                  # measures a smaller shell, and these two fields are where that shows.
                  'shell_radius_nm': shell.get('radius_nm'),
                  'radius_source': (shell.get('radius_source') or band.get('radius_source')
                                    or placement.get('radius_source')),
                  'radius_floor_nm': shell.get('radius_floor_nm') or band.get('radius_floor_nm'),
                  'measured_extent_nm': shell.get('measured_extent_nm'),
                  # How the orientations were come by, and the detergent's own body as the clearance gate read it.
                  'orientation_policy': placement.get('orientation_policy'),
                  'body_profile': placement.get('body_profile'),
                  'body_profile_reason': placement.get('body_profile_reason'),
                  'bead_clearance_nm': placement.get('bead_clearance_nm'),
                  # Crowding, reported and never acted on, and -- when the requested count cannot be placed -- what
                  # the shape would hold, measured over the placer's own gate. The refusal's `reasons` carry the same
                  # measurement as a sentence; this is the number behind it, for the panel's "Use N" control.
                  'estimated_density_per_nm3': shape_record.get('estimated_density_per_nm3'),
                  'capacity_nm3_per_detergent': shape_record.get('capacity_nm3_per_detergent'),
                  'volume_nm3': shape_record.get('volume_nm3'),
                  'capacity_aggregation': placement.get('capacity_aggregation')})
    if not placement['valid']:
        cost['seconds'] = time.perf_counter() - started
        return _refusal('placement', placement['issues'], basis, cost, subject=protein_path or f'{mode} placement')

    box = _box(points, placement, frame, margin, initial_z)
    basis['box_nm'] = list(box)
    basis['belt_offset_nm'] = float(belt_offset_nm)

    seconds = model_seconds
    cost['detergent_seconds'] = round(seconds, 3)
    # The molecule and residue the picture says it is drawn from. A derived model's own, because the catalogue's
    # template is DDM's skeleton for every detergent: an OG mapping written with the template's residue would be
    # classified as protein by `system_pdb`, with no CONECT bonds and no family code. A centres-only build has no
    # model and keeps the template's residue.
    if model is not None:
        basis['detergent'] = str(model['molecule_id'])
        basis['residue'] = model['residue']
    detergent_residue = basis['residue']

    atoms = [{'residue_id': bead['residue_id'], 'residue': bead['residue'], 'name': bead['name'],
              'position': bead['position']} for bead in beads]
    topology = None
    if model is None:
        # A build whose detergent is a bare centre: what the placement produced, one point per molecule, and no
        # bonds to draw because nothing here has declared any (`pdc_build` records the same limitation and writes no
        # topology for it). The picture says so in its own REMARK rather than leaving a viewer to guess. Each centre
        # is its own residue, which is the writer's own rule -- one residue per molecule, or a viewer is told the
        # system holds one molecule.
        atoms += [{'residue_id': index + 1, 'name': f'{record.residue[:2]}{index + 1:03d}',
                   'residue': record.residue, 'position': centre}
                  for index, centre in enumerate(placement['centers'])]
        basis['detergent_representation'] = 'one centre per molecule'
    else:
        # The bodies the placement drew, read back as geometry: the placement's record carries the entry index and
        # the azimuth each site got, and the library carries the head-anchored bodies. Stamping those same numbers
        # is what makes the picture the build's own frame rather than one template repeated.
        entries = twists = None
        if library is not None:
            offsets = library.offsets()
            entries = [offsets[index] for index in placement['conformations']['entries']]
            twists = placement['conformations']['twists']
        try:
            atoms += pdc_build.stamp(model, placement['centers'], placement['directions'],
                                     first_residue=max([bead['residue_id'] for bead in beads], default=0) + 1,
                                     entries=entries, twists=twists)
        except SystemExit as error:
            cost['seconds'] = time.perf_counter() - started
            return _refusal('detergent model', [str(error)], basis, cost, subject=mapping_path)
        topology = pdc_view.read_moleculetype_text(model['topology'], source=DETERGENT_TOPOLOGY)
        basis['detergent_representation'] = 'the mapping\u2019s beads'
        # The card says these bonds are the model's own, so it also says *which* model's: the sentence the run's own
        # record carries, the count of the topology drawn, and -- when the mapping was fitted -- the revision it came
        # from. A fitted run and a derived one are different systems, and this is the only place a reader is told.
        basis['detergent_terms'] = {'source': model['source'], 'terms': model['terms'],
                                    'revision': (model.get('parameterization') or {}).get('revision')}

    # The build centres the system before it writes it: protein extents for a protein build, the detergent cloud's
    # mean for an empty micelle. The preview must show the same cell, so the same helper and box are used here, not a
    # second rule. The all-atom ribbon is shifted by this vector in the browser, because its cached file is in the
    # coordinates martinize2 read.
    # The system's centre -- protein and detergents together -- is the preview's anchor. The build's own centring
    # helper is for the dry artifact; the preview is a solvated-cell picture, so the whole system's centroid decides
    # where the cell sits.
    anchor_nm = [round(sum(float(atom['position'][axis]) for atom in atoms) / len(atoms), 6)
                 for axis in range(3)]
    dry_shift = [round(float(box[axis]) / 2 - anchor_nm[axis], 6) for axis in range(3)]
    pdc_build.translate_atoms(atoms, dry_shift)
    basis['centring'] = {'anchor': 'system centre', 'anchor_nm': anchor_nm, 'shift_nm': dry_shift}

    basis['beads'] = len(atoms)
    if beads:
        # The distinct protein residue keys the frame's leading atoms hold. `system_pdb` numbers molecules by that
        # key in this order, so the detergent's first residue is `protein_residues + 1`.
        basis['protein_residues'] = len({(str(bead['residue']).upper(), int(bead['residue_id'])) for bead in beads})
        # The all-atom protein the beads stand for, named by the entry that holds it and the route that serves it:
        # the card draws it as a ribbon under the beads, so what was coarse-grained and what it became are in one
        # picture. A derive whose coarse-graining was answered by something other than a cache entry names none,
        # and so does an entry that holds neither a prepared nor a selected structure.
        basis['protein_structure'] = protein_structure_basis(cg.get('key'), cg.get('path'))
    # The dry frame is what the build writes; the solvent is the next leg's opening act. Show both, but keep them
    # distinguishable: the solvent comes from the same Insane placement a run uses, cached by this dry system's
    # bytes and the salt concentration.
    solvation_started = time.perf_counter()
    solvated = None
    try:
        solvated = _solvent(atoms, box, salt_molar, cache_root)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # A solvent that cannot be placed is not a refusal of the *placement*: the dry frame is still the build's own,
        # and the sentence travels beside it so the card can say why the context layer is missing.
        basis['solvent_reason'] = f'the initial solvent could not be placed: {error}'
    cost['solvation_seconds'] = round(time.perf_counter() - solvation_started, 3)
    basis['salt_molar'] = salt_molar
    if solvated is not None:
        basis['water_residues'] = solvated['water_residues']
        basis['ion_residues'] = solvated['ion_residues']
        basis['solvent'] = {**solvated['molecules'], 'salt_molar': salt_molar,
                            'cached': bool(solvated.get('cached'))}
        atoms += solvated['water'] + solvated['ions']
    basis['box_origin_nm'] = [0.0, 0.0, 0.0]
    _wrap(atoms, basis['box_origin_nm'], box)
    cost['seconds'] = time.perf_counter() - started
    pdb = pdc_view.system_pdb(atoms, detergent_residue=detergent_residue, topology=topology,
                              include_water=bool(solvated),
                              title=f'placement preview ({record.name}, AN={aggregation_number}, mode={mode}, '
                                    f'seed={seed})')
    return {'valid': True, 'step': None, 'reasons': [], 'pdb': pdb, 'basis': basis, 'cost': cost}
