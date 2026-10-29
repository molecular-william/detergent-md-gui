"""The placement preview: the frame a protein-detergent build would write, derived for the inputs on the form.

Option (b) of the plan's three honest answers, and the only one that is a picture of *this* build rather than of a
schematic: `pdc_build` leaves a **dry** system -- `system.gro` holds the protein and the detergents, and solvation is
the first equilibration leg's opening act -- so "protein and detergents in a box, no solvent" is not a reduced view
of the system, it *is* the artifact the build writes. The preview derives the same frame before the run exists, so
the picture and the built `system.gro` are one claim rather than two.

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

What it deliberately does not do: draw anything the build's own functions did not produce. A hand-drawn schematic
would look like a prediction of a system these inputs do not make.

The protein's **secondary structure** travels with the frame rather than being left behind at the coarse-graining
step. martinize2 is handed an assignment out of `pdc_build.secondary_structure` (mdtraj's DSSP, `SS_SOURCE`), the CG
beads are built from it, and `basis['secondary_structure']` carries those letters keyed by the residue number the
frame gives each protein residue, the three classes they sort into, and their counts -- so the panel can colour a
backbone bead by its residue's class without measuring anything itself. The mapping of DSSP's letters onto the three
classes is one table in this module (`SECONDARY_CLASSES`), and a residue the frame cannot give one class to is left
uncoloured rather than guessed at.

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
import time
from pathlib import Path

from dashboard import files
from dashboard.analysis.runs import structures as pdc_view
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
#: it were this one's. It is part of every key, which is what makes that true of entries on disk as well. Format 2:
#: an entry can now hold a **prepared** protein -- `protein_prepared.pdb`, the preparer's log and its own
#: `protein_input.pdb` -- which is a different entry from the one the same protein coarse-grained unprepared.
CACHE_FORMAT = 2


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


#: DSSP's eight letters, sorted into the three classes a picture can draw. This is the **one** table: the per-residue
#: classes the panel colours from, the summary the card prints and the unit tests all read it, so a helix cannot be
#: red here and coil there. vermouth's own `SS_CG` -- which `pdc_build.martini_classes` counts with, because that is
#: what martinize2 runs over the same letters -- is the same partition under martinize2's names, its `extended` being
#: this `sheet`; `packages/pdc/tests/unit/test_pdc_preview.py` pins the two against each other on the DSSP alphabet.
SECONDARY_CLASSES = {'H': 'helix', 'G': 'helix', 'I': 'helix', 'E': 'sheet', 'B': 'sheet'}
#: Every letter the table does not name -- DSSP's `T`, `S` and `C` -- is a coil. It is a rule rather than an entry
#: per letter because the table's whole claim is "three classes", and a letter added to either source's alphabet is
#: then a coil rather than an unknown state a picture would have to invent a colour for.
SECONDARY_DEFAULT_CLASS = 'coil'
#: The order the card's legend and the summary sentence use. `sheet` rather than martinize2's `extended` because that
#: is the word for what the beads are: an extended strand is a sheet's residue.
SECONDARY_CLASS_ORDER = ('helix', 'sheet', 'coil')

#: The file inside a cache entry holding the assignment martinize2 was built with. Optional: an entry written before
#: it existed has none, and a record that carries no letters is not written at all -- see `_secondary_record`.
SECONDARY_RECORD = 'secondary_structure.json'

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


def secondary_class(letter) -> str:
    """The class a DSSP letter belongs to, from the one table above (`SECONDARY_CLASSES`)."""
    return SECONDARY_CLASSES.get(str(letter).strip().upper(), SECONDARY_DEFAULT_CLASS)


def protein_residues(beads) -> list[tuple[tuple[str, int], int]]:
    """The protein residues a frame's beads hold, as `((resname, residue_id), frame residue number)` in bead order.

    A *residue occurrence*, not a distinct key: martinize2 writes one bead group per residue in the order the file
    holds them, and a structure of three chains restarts its residue numbering at each chain, so two residues can
    carry the same `(resname, residue_id)`. Both are list entries here, which is what lets the assignment's letters
    stay lined up with the beads residue for residue.

    The frame's **residue number** is `pdc_view.system_pdb`'s own rule -- one number per distinct
    `(residue, residue_id)` in the order the coordinates first show it, `1` upward -- so the number here is the number
    a viewer sees and can select on. It is counted over the protein's beads alone, which is the frame's numbering
    because a preview writes the protein's atoms before the detergent's and a template's residue name cannot collide
    with an amino acid's. Two residues that share a key therefore share a number, which the caller has to handle
    rather than this function guessing which of them a viewer is looking at.
    """
    occurrences, numbering, previous = [], {}, None
    for bead in beads:
        key = (str(bead['residue']).upper(), int(bead['residue_id']))
        if key not in numbering:
            numbering[key] = len(numbering) + 1
        # One entry per residue *group*: a residue's beads are written consecutively, so a key that differs from the
        # bead before it is a new residue -- including the second chain's `LEU 19`, which has the same key as the
        # first chain's and must still be its own entry for the letters to stay lined up.
        if key != previous:
            occurrences.append(key)
            previous = key
    return [(key, numbering[key]) for key in occurrences]


def secondary_structure_basis(record, beads) -> dict:
    """The assignment `record` carries, keyed the way the frame names its protein residues, with its class counts.

    `record` is `pdc_build.secondary_structure`'s own record -- `letters` (one DSSP letter per residue, in the order
    the file martinize2 read holds them), `source`, `route` -- and `beads` are the coarse-grained protein's atoms, in
    the order `pdc_view.system_pdb` writes them. The letters are matched to the residues positionally, because that
    is what the two have in common: martinize2 writes its beads residue by residue in the order of the file it was
    handed, and mdtraj assigned the letters over that same file. The counts are checked before anything is keyed --
    an assignment of 230 letters for a frame of 379 residues cannot be handed on without saying which residue each
    letter belongs to, and guessing is the one thing this cannot do.

    **A bead that covers residues of different classes is not coloured by secondary structure at all.** That is the
    rule here, and it has one case in this writer: the frame numbers a residue by `(name, residue_id)`, so two chains
    that both hold `LEU 19` share frame residue 19 -- and if those two residues are a helix and a coil, no colour can
    be put on that number without claiming a secondary structure one of the two beads does not have. Such a number
    is `None` in `classes` and in `letters`, so the panel draws those beads in their family colour and says nothing
    about their structure; the number itself stays unstated rather than being resolved to the first or the majority.
    The same applies to a bead whose residue the assignment does not reach at all. `summary` still counts every
    letter, because it is a statement about the protein's assignment rather than about what could be drawn.

    Returns the record the basis carries. It is always a dict, so a caller can render "no assignment, and why"
    instead of an absence: `source`, `route`, `residues` (letters handed on), `protein_residues` (residue
    occurrences the frame holds), `letters` and `classes` keyed by frame residue number, `summary` and, when no
    assignment could be keyed, `detail` naming the reason.
    """
    occurrences = protein_residues(beads)
    basis = {'source': (record or {}).get('source'), 'route': (record or {}).get('route'),
             'residues': 0, 'protein_residues': len(occurrences),
             'letters': {}, 'classes': {}, 'summary': None, 'detail': None}
    letters = str((record or {}).get('letters') or '')
    if not letters:
        basis['detail'] = ((record or {}).get('detail')
                           or 'no secondary-structure assignment was made for this protein')
        return basis
    if len(letters) != len(occurrences):
        basis['detail'] = (f'the assignment holds {len(letters)} letters for the {len(occurrences)} residues this '
                           f'frame holds, so no residue can be given one without guessing which')
        return basis

    grouped = {}
    for (_, number), letter in zip(occurrences, letters):
        grouped.setdefault(number, []).append(str(letter))
    for number in sorted(grouped):
        assigned = grouped[number]
        classes = {secondary_class(letter) for letter in assigned}
        basis['letters'][str(number)] = assigned[0] if len(set(assigned)) == 1 else None
        basis['classes'][str(number)] = classes.pop() if len(classes) == 1 else None
    basis['residues'] = len(letters)
    summary = {name: 0 for name in SECONDARY_CLASS_ORDER}
    for letter in letters:
        summary[secondary_class(letter)] += 1
    basis['summary'] = summary
    return basis


def _secondary_record(entry, protein_input, record):
    """The assignment martinize2 was given, from this derive, from the entry's sidecar, or by asking again.

    `pdc_build.cg_protein` reports the assignment only when it *ran* martinize2: a re-used entry answers
    `{'source': None, 'detail': 'protein_cg.pdb was already there, so martinize2 was not run again'}`, which is
    honest about the step and says nothing about the structure. The assignment is a property of the file martinize2
    read, and that file is in the entry, so a re-used entry is assigned the same way it was the first time --
    `pdc_build.secondary_structure`, the same call on the same bytes -- rather than the panel losing its colours the
    second time it is asked. The answer is kept beside the beads so a warm derive does not pay for it again.

    A record that carries no letters is deliberately not persisted: its reason is a library that is not importable or
    a structure neither source can work on, and the next derive is entitled to ask again rather than inherit it.
    """
    path = Path(entry) / SECONDARY_RECORD
    if (record or {}).get('letters'):
        try:
            files.atomic_json(path, record)
        except OSError:
            pass        # a sidecar that cannot be written costs the next derive an assignment, and nothing else
        return record
    if path.is_file():
        try:
            stored = json.loads(path.read_text())
        except (OSError, ValueError):
            stored = None
        if isinstance(stored, dict) and stored.get('letters'):
            return stored
    if not Path(protein_input).is_file():
        return record
    try:
        fresh = pdc_build.secondary_structure(Path(protein_input))
    except (OSError, ValueError, SystemExit):
        return record
    if fresh.get('letters'):
        try:
            files.atomic_json(path, fresh)
        except OSError:
            pass
    return fresh


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
    beads, command, secondary = pdc_build.cg_protein(entry, protein_input, executable=executable)
    seconds = time.perf_counter() - started
    # The assignment travels with the beads, including for an entry martinize2 was not run for this time: see
    # `_secondary_record`.
    secondary = _secondary_record(entry, protein_input, secondary)

    # The command `cg_protein` would have run names the file it writes; a step that was already built returns the
    # beads with no command, which is this entry being re-used rather than a second run of the tool. The bytes are
    # the tool's own output, so they are the size the panel reports as kept.
    return beads, {'cached': command is None, 'seconds': seconds,
                   'key': entry.name, 'path': str(entry),
                   'beads_bytes': structure.stat().st_size if structure.is_file() else 0,
                   'dropped_residues': dropped, 'protein_input': protein_input.name,
                   'structure': str(protein_input), 'command': command, 'secondary_structure': secondary,
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
            radius_nm=pdc_placement.DEFAULT_RADIUS_NM, executable=None, prepare_protein=False,
            prepare_executable=None):
    """The placement these inputs would build, as `{valid, step, reasons, pdb, basis, cost}`.

    `project_root` resolves `template`, `protein` and the molecule tree a mapping is derived against -- the same root
    a run's `pdc.prepare` is given. `cache_root` is the preview's own scratch root; the only thing written under it
    is a coarse-grained protein, and with `prepare_protein` a prepared one besides. `molecule_id` is the detergent the
    mapping belongs to; a mapping is a mapping *of* a molecule and the residue the structure is written with comes
    from it.

    `basis['secondary_structure']` is the assignment martinize2 coarse-grained this protein with
    (`secondary_structure_basis`): the DSSP letters keyed by the residue number the frame gives each protein residue,
    the class each letter falls in, and how many residues each class holds. It is `None` for a build with no protein,
    and a dict that names its reason when a protein has no assignment to hand on -- so the panel can say the one
    thing or the other, and never colour a bead from a structure that was not stated.

    `basis['detergent_terms']` is which terms the picture's bonds are: `{source, terms, revision}` when the mapping
    was given. `source` is the sentence the run's own record carries (`detergent_cg.terms_source`), `terms` the count
    of the topology drawn, and `revision` the parameterization revision that topology was adopted from, or `None` for
    a derivation. It is `None` for a centres-only build, which draws no bonds to attribute.

    `prepare_protein` is the plan's step 1, and it is the reader's choice rather than the service's: with it, the
    protein is rebuilt and protonated by `pdb2pqr` (or `prepare_executable`, where the route has resolved one) before
    the coarse-graining reads it, exactly as the stage hands it over in a run. A preparation that cannot run comes
    back as a refusal naming that step, with the tool's own sentence -- never as a frame built from the file the
    caller asked to have prepared.

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
             'placement_shape': None, 'band_radius_nm': None, 'slab_radius_nm': None, 'tube_radius_nm': None,
             'detergent_representation': None,
             # Which terms the picture's bonds are -- the mapping's fit or its derivation -- in the run's own words.
             # `None` for a centres-only build, which draws no bonds to attribute.
             'detergent_terms': None,
             # The plan's step 1: whether this derive would prepare the protein, and the record when it did.
             'prepare_protein': bool(prepare_protein), 'prepare': None,
             # The assignment martinize2 builds the protein with, keyed by the frame's own residue numbers. `None`
             # until a frame is actually drawn from a coarse-grained protein: a refusal carries no coordinates, so
             # it has no residues to give a class to, and says that rather than naming an assignment for a picture
             # that does not exist.
             'secondary_structure': None,
             # The all-atom protein the beads were coarse-grained from: `{key, url}` for the route that serves it, so
             # the card can draw a ribbon of the structure the beads stand for. `None` for a build with no protein,
             # and for a derive whose entry holds no such structure -- see `protein_structure_basis`.
             'protein_structure': None}
    cost = {'cg_cached': False, 'coarse_graining_seconds': 0.0, 'detergent_seconds': 0.0,
            'placement_seconds': 0.0, 'seconds': 0.0, 'cg_bytes': 0, 'cg_key': None, 'prepare_seconds': 0.0}
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

    # The membrane the belt is placed in is the protein file's own statement of it, read through `micelle.frame` --
    # the same reader the build uses, so the two cannot disagree about which shape this placement takes.
    points = [list(bead['position']) for bead in beads]
    started_placement = time.perf_counter()
    placement = pdc_placement.place_detergents(points, record, aggregation_number, seed, radius_nm=radius, mode=mode,
                                              margin_nm=margin, initial_z_nm=initial_z, frame=frame)
    cost['placement_seconds'] = round(time.perf_counter() - started_placement, 3)
    # The belt's own radius, and the two numbers it was derived from. `band_radius_nm` is what the card renders as
    # "the belt is a band of radius X nm in the membrane plane", so it is the torus's **centre-line** -- the measured
    # slab radius the belt was placed about. It used to carry the band record's `radius_nm`, which after the belt
    # became a torus is the *tube's* radius (the detergent's own length, a constant for every protein and every
    # selection): a reader checking whether the plane shrank with the subunits was shown one number that never moved.
    # The tube's radius is stated under its own name, and the measurement beside it, so all three can be re-added.
    band = placement['band'] or {}
    shell = placement.get('shell') or {}
    # The shell's own numbers, and the density they and the count make. `shell`/`band` are never both set: a belt's
    # volume is the torus's (Pappus) and a sphere's is the ball's, so the panel reads one pair of fields for either
    # shape and the shape's name says which geometry produced them.
    shape_record = shell or band
    basis.update({'placement_shape': placement['placement_shape'], 'clearance_nm': placement['protein_clearance_nm'],
                  'band_radius_nm': band.get('centre_line_radius_nm'), 'slab_radius_nm': band.get('slab_radius_nm'),
                  'tube_radius_nm': band.get('tube_radius_nm'),
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

    model, seconds, mapping_path = None, 0.0, None
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
            return _refusal('detergent model', [str(error)], basis, cost, subject=mapping_path)
        topology = pdc_view.read_moleculetype_text(model['topology'], source=DETERGENT_TOPOLOGY)
        basis['detergent_representation'] = 'the mapping\u2019s beads'
        # The card says these bonds are the model's own, so it also says *which* model's: the sentence the run's own
        # record carries, the count of the topology drawn, and -- when the mapping was fitted -- the revision it came
        # from. A fitted run and a derived one are different systems, and this is the only place a reader is told.
        basis['detergent_terms'] = {'source': model['source'], 'terms': model['terms'],
                                    'revision': (model.get('parameterization') or {}).get('revision')}

    basis['beads'] = len(atoms)
    # The assignment martinize2 built the protein with, keyed by the residue number the frame below gives each
    # protein residue. Only on the valid path: a refusal carries no coordinates, so it has no residue to give a class
    # to, and its basis says `None` rather than naming an assignment for a picture that does not exist.
    if beads:
        basis['secondary_structure'] = secondary_structure_basis(cg.get('secondary_structure'), beads)
        # The all-atom protein the beads stand for, named by the entry that holds it and the route that serves it:
        # the card draws it as a ribbon under the beads, so what was coarse-grained and what it became are in one
        # picture. A derive whose coarse-graining was answered by something other than a cache entry names none,
        # and so does an entry that holds neither a prepared nor a selected structure.
        basis['protein_structure'] = protein_structure_basis(cg.get('key'), cg.get('path'))
    cost['seconds'] = time.perf_counter() - started
    pdb = pdc_view.system_pdb(atoms, detergent_residue=record.residue, topology=topology,
                              title=f'placement preview ({record.name}, AN={aggregation_number}, mode={mode}, '
                                    f'seed={seed})')
    return {'valid': True, 'step': None, 'reasons': [], 'pdb': pdb, 'basis': basis, 'cost': cost}
