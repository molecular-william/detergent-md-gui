"""The placement preview: the frame a protein-detergent build would write, derived for the inputs on the form.

Option (b) of the plan's three honest answers, and the only one that is a picture of *this* build rather than of a
schematic: `pdc_build` leaves a **dry** system -- `system.gro` holds the protein and the detergents, and solvation is
the first equilibration leg's opening act -- so "protein and detergents in a box, no solvent" is not a reduced view
of the system, it *is* the artifact the build writes. It is also the frame the run records as its own first snapshot
(`pdc_snapshot.write_snapshot(stage, 'placement', ...)` -> `1_system/snapshots/placement.pdb`), so the preview is the
picture the run will show, derived before the run exists.

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
  builder's gates, and their sentences are handed back as `reasons` with no coordinates -- never a picture of a system
  the build would refuse, and never a blank.

What it deliberately does not do: draw anything the build's own functions did not produce. A hand-drawn schematic
would look like a prediction of a system these inputs do not make.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from pathlib import Path

from micelle import frame as micelle_frame
from micelle import registry as micelle_registry

from .. import files
from ..models.molecules import detergent_cg
from .adapters import pdc as pdc_adapter
from .adapters import pdc_box, pdc_placement, pdc_protein, pdc_view
from .adapters.pdc import DETERGENT_TOPOLOGY
from .scripts import pdc_build

#: Where the coarse-grained proteins are kept, relative to the workspace. Deliberately not a directory any stage
#: reads or writes: a run re-derives its own `1_system/snapshots/placement.pdb` in its own stage, which is the whole
#: point of the snapshot design, so the preview's cache can never be mistaken for a run's input.
CACHE_DIRECTORY = 'preview/cg'
#: Bumped when the shape of what an entry holds changes, so an entry written by an older version is never read as if
#: it were this one's. It is part of every key, which is what makes that true of entries on disk as well.
CACHE_FORMAT = 1


def _refusal(reasons, basis, cost):
    """The builder's answer when nothing can be drawn: its own sentences, and no coordinates."""
    return {'valid': False, 'reasons': [str(reason) for reason in reasons if str(reason).strip()],
            'pdb': None, 'basis': basis, 'cost': cost}


def cache_key(protein_path, chains, executable) -> str:
    """The cache entry a protein-and-selection belongs to, from the things that decide the beads.

    The protein file's own bytes rather than its name: a re-imported structure at the same path is a different
    structure, and only one of the two is the one on screen. The chains, because a strict subset is filtered into a
    different file before martinize2 reads it -- `pdc_build.select_protein` writes `protein_selected.pdb`. The tool's
    own bytes, because a different martinize2 builds a different coarse-grained protein, and `None` when nothing
    resolved (an entry made through a stubbed step is still keyed, and says which tool it is not for).

    The elastic network's constants and the force field are in the key as well, which is what keeps a change to them
    from leaving a frame silently drawn from the old ones.
    """
    digest = hashlib.sha256()
    digest.update(str(CACHE_FORMAT).encode())
    digest.update(Path(protein_path).read_bytes())
    digest.update(b'\0' + ','.join(str(chain) for chain in (chains or [])).encode())
    executable = str(executable or '')
    digest.update(b'\0' + executable.encode())
    if executable and Path(executable).is_file():
        digest.update(b'\0' + files.sha256(executable).encode())
    digest.update(f'\0{pdc_protein.DEFAULT_FORCE_FIELD}|{pdc_protein.FORCE_CONSTANT}'
                  f'|{pdc_protein.UPPER_BOUND_NM}'.encode())
    return digest.hexdigest()[:16]


def coarse_grained(cache_root, protein_path, chains, *, executable=None):
    """The CG protein's beads, from the cache when it is there and from martinize2 when it is not.

    It calls the stage's own `pdc_build.select_protein` and `pdc_build.cg_protein`, so the file martinize2 reads, the
    command it is handed and the file read back are the build's, not a second reading of them. What differs from a
    stage is where the two write: the entry directory, under the workspace's preview cache, rather than a stage
    directory of a run that does not exist.

    The gate on running the tool at all is the one `cg_protein` already applies -- the file its own command names --
    so a preview and a build re-derive a step in the same circumstances.
    """
    entry = Path(cache_root) / cache_key(protein_path, chains, executable)
    entry.mkdir(parents=True, exist_ok=True)
    protein_input, selected, dropped = pdc_build.select_protein(entry, Path(protein_path), chains)
    structure = entry / pdc_build.CG_DIRECTORY / 'protein_cg.pdb'
    started = time.perf_counter()
    beads, command, secondary = pdc_build.cg_protein(entry, protein_input, executable=executable)
    seconds = time.perf_counter() - started

    # The command `cg_protein` would have run names the file it writes; a step that was already built returns the
    # beads with no command, which is this entry being re-used rather than a second run of the tool. The bytes are
    # the tool's own output, so they are the size the panel reports as kept.
    return beads, {'cached': command is None, 'seconds': seconds,
                   'key': entry.name, 'path': str(entry),
                   'beads_bytes': structure.stat().st_size if structure.is_file() else 0,
                   'dropped_residues': dropped, 'protein_input': protein_input.name,
                   'command': command, 'secondary_structure': secondary}


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
    from ..models.mappings import store

    candidate = store.candidate_paths().get(source.name)
    if candidate:
        return Path(candidate)
    return source if source.is_absolute() else Path(root) / source


def _discard_unreadable(cache_root, protein_path, chains, executable) -> bool:
    """Remove a cache entry whose CG structure cannot be read, so the next derive builds it again.

    A truncated or half-written `protein_cg.pdb` would otherwise be re-used forever: `pdc_build.cg_protein`'s gate is
    the file's presence, and a reader of coordinates that answers nothing is the defect this stage already had once.
    Two previews of the same protein can also be in flight at once, and the second must not be left with the first's
    partial file. Only an entry that is genuinely unreadable is removed -- a protein the tool refuses leaves no
    structure to remove.
    """
    from .adapters import pdc_import

    entry = Path(cache_root) / cache_key(protein_path, chains, executable)
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
    """The detergent's beads and the topology that bonds them, derived from the run's own mapping.

    `models.molecules.detergent_cg.derive` is the one derivation a run uses (`pdc.prepare` writes its `topology` as
    `detergent_CG.itp` and its `beads` as `detergent_CG.json`), so the preview stamps the same molecule the run will.
    Not cached: it is derived from the mapping the reader is choosing, in under a second, and a second cache of a
    second derived artifact is one more thing to invalidate for a saving the plan did not ask for.
    """
    started = time.perf_counter()
    draft = detergent_cg.derive(Path(mapping_path), Path(molecule_root), Path(project_root))
    return draft, time.perf_counter() - started


def _box(points, placement, frame, margin_nm, initial_z_nm):
    """The box the build writes, by the build's own rule (`pdc_build.build`), and no second rule here.

    A band is the one case where the box is built in the membrane frame: z clears the protein and the slab it sits in.
    Everything else -- a protein-free build, a protein that states no membrane, a stated membrane holding none of the
    protein's atoms -- is `extended_box` over the box the placement was built for.
    """
    initial = pdc_box.initial_box(points or placement['centers'], margin_nm=margin_nm, initial_z_nm=initial_z_nm)
    if frame is not None and placement['band'] is not None:
        return pdc_box.membrane_box(points, half_thickness_nm=frame.half_thickness_nm, margin_nm=margin_nm,
                                    initial_z_nm=initial_z_nm)
    return pdc_box.extended_box(initial[:2], placement['centers'], margin_nm=margin_nm)


def preview(*, project_root, cache_root, template, seed, protein=None, chains=None, mapping=None,
            molecule_id=None, aggregation_number=150, placement_mode=pdc_placement.DEFAULT_PLACEMENT_MODE,
            box_margin_nm=pdc_placement.DEFAULT_MARGIN_NM, initial_z_nm=pdc_placement.DEFAULT_INITIAL_Z_NM,
            radius_nm=pdc_placement.DEFAULT_RADIUS_NM, executable=None):
    """The placement these inputs would build, as `{valid, reasons, pdb, basis, cost}`.

    `project_root` resolves `template`, `protein` and the molecule tree a mapping is derived against -- the same root
    a run's `pdc.prepare` is given. `cache_root` is the preview's own scratch root; the only thing written under it
    is a coarse-grained protein. `molecule_id` is the detergent the mapping belongs to; a mapping is a mapping *of* a
    molecule and the residue the structure is written with comes from it.

    Raises `ValueError` for a question that cannot be asked at all -- a template or protein that is not a file, a
    chain the file does not name, a mapping that does not exist, a count below one -- because those are malformed
    requests and not this build's refusals. Everything the *builders* refuse comes back as `valid: False` with their
    own sentences.
    """
    seed = int(seed)
    aggregation_number = int(aggregation_number)
    margin = float(box_margin_nm)
    initial_z = float(initial_z_nm)
    radius = float(radius_nm)
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

    basis = {'protein': Path(protein_path).stem if protein_path else None, 'chains': list(chains or []),
             'template': template_path.name, 'detergent': None, 'residue': None, 'mapping': None,
             'aggregation_number': aggregation_number, 'placement_mode': mode, 'seed': seed,
             'beads': None, 'protein_beads': 0, 'box_nm': None, 'clearance_nm': None,
             'placement_shape': None, 'band_radius_nm': None, 'detergent_representation': None}
    cost = {'cg_cached': False, 'coarse_graining_seconds': 0.0, 'detergent_seconds': 0.0,
            'placement_seconds': 0.0, 'seconds': 0.0, 'cg_bytes': 0, 'cg_key': None}
    started = time.perf_counter()

    # The template first, because the build does: a template that cannot build a system stops the stage before
    # anything is placed, and its own validator's sentences are the refusal.
    try:
        record = micelle_registry.load_template(template_path)
    except (ValueError, OSError) as error:
        return _refusal([str(error)], basis, cost)
    basis.update({'detergent': record.name, 'residue': record.residue})
    template_issues = list(micelle_registry.validate_template(record))
    if template_issues:
        return _refusal(template_issues, basis, cost)

    # The chains are the file's question, and the adapter's own gate answers it: a chain the structure does not name
    # is refused there, with the file's own list, rather than silently building something else.
    selected_chains = None
    if protein_path is not None:
        selected_chains = pdc_adapter.validate_chains(protein_path, chains)
    basis['chains'] = list(selected_chains or [])

    beads, frame = [], None
    if protein_path is not None:
        try:
            beads, cg = coarse_grained(cache_root, protein_path, selected_chains, executable=executable)
        except (OSError, subprocess.SubprocessError, ValueError, SystemExit) as error:
            # A cache entry that cannot be read is removed rather than left to fail identically forever.
            discarded = _discard_unreadable(cache_root, protein_path, selected_chains, executable)
            cost['seconds'] = time.perf_counter() - started
            detail = '; its cached entry was unreadable and has been discarded, so the next derive builds it again' \
                if discarded else ''
            return _refusal([f'the coarse-graining step could not build this protein: {error}{detail}'], basis, cost)
        cost.update({'cg_cached': cg['cached'], 'coarse_graining_seconds': round(cg['seconds'], 3),
                     'cg_bytes': cg['beads_bytes'], 'cg_key': cg['key']})
        frame = micelle_frame.frame_from_pdb(
            (Path(cg['path']) / pdc_build.SELECTED_PROTEIN)
            if (Path(cg['path']) / pdc_build.SELECTED_PROTEIN).is_file() else protein_path)
    basis['protein_beads'] = len(beads)

    # The membrane the belt is placed in is the protein file's own statement of it, read through `micelle.frame` --
    # the same reader the build uses, so the two cannot disagree about which shape this placement takes.
    points = [list(bead['position']) for bead in beads]
    started_placement = time.perf_counter()
    placement = pdc_placement.place_detergents(points, record, aggregation_number, seed, radius_nm=radius, mode=mode,
                                              margin_nm=margin, initial_z_nm=initial_z, frame=frame)
    cost['placement_seconds'] = round(time.perf_counter() - started_placement, 3)
    basis.update({'placement_shape': placement['placement_shape'], 'clearance_nm': placement['protein_clearance_nm'],
                  'band_radius_nm': (placement['band'] or {}).get('radius_nm')})
    if not placement['valid']:
        cost['seconds'] = time.perf_counter() - started
        return _refusal(placement['issues'], basis, cost)

    box = _box(points, placement, frame, margin, initial_z)
    basis['box_nm'] = list(box)

    model, seconds = (None, 0.0)
    if mapping:
        mapping_path = resolve_mapping(mapping, root)
        if not mapping_path.is_file():
            raise ValueError(f'the detergent mapping is not a file: {mapping_path}')
        model, seconds = detergent_model(mapping_path, root / 'molecules', root)
        # A mapping is a mapping *of* a molecule, and the picture is drawn from the mapping's own beads. A form that
        # offers one detergent with another's mapping would draw the other molecule while saying this one, so the two
        # have to agree before anything is derived.
        if molecule_id and str(model['molecule_id']) != str(molecule_id):
            raise ValueError(f'the mapping {mapping_path.name} is of {model["molecule_id"]}, not of {molecule_id}')
        basis['mapping'] = mapping_path.name
    cost['detergent_seconds'] = round(seconds, 3)

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
        try:
            atoms += pdc_build.stamp(model, placement['centers'], placement['directions'],
                                     first_residue=max([bead['residue_id'] for bead in beads], default=0) + 1)
        except SystemExit as error:
            cost['seconds'] = time.perf_counter() - started
            return _refusal([str(error)], basis, cost)
        topology = pdc_view.read_moleculetype_text(model['topology'], source=DETERGENT_TOPOLOGY)
        basis['detergent_representation'] = 'the mapping\u2019s beads'

    basis['beads'] = len(atoms)
    cost['seconds'] = time.perf_counter() - started
    pdb = pdc_view.system_pdb(atoms, detergent_residue=record.residue, topology=topology,
                              title=f'placement preview ({record.name}, AN={aggregation_number}, mode={mode}, '
                                    f'seed={seed})')
    return {'valid': True, 'reasons': [], 'pdb': pdb, 'basis': basis, 'cost': cost}
