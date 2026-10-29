"""Fetching a membrane structure from OPM: the file, what it says about itself, and what came with it.

An import happens once, on request, into the workspace -- which `.gitignore` already ignores, so a downloaded file
is local by construction and cannot reach the index. Nothing here runs during a build: a run records the paths and
versions it used and has to work again offline, so reaching the network is a decision someone makes and not a step
a run takes on its own.
"""
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# The asset host, not the site. `opm.phar.umich.edu` is a React application that answers *every* path with the same
# 1.4 KB shell -- including `/pdb/1qj8.pdb` -- so a fetch from the site reads as a 200 and is not a structure.
ASSET_URL = 'https://biomembhub.org/shared/opm-assets/pdb/{pdbid}.pdb'

_PDB_ID = re.compile(r'[A-Za-z0-9]{4}\Z')


def canonical_id(pdbid):
    """The id as OPM itself spells it: validated, and lower case.

    A PDB id becomes a file name and a URL path, so this is the trust boundary -- a caller's string must not be
    able to name a path. PDB ids are case-insensitive and the asset host's own links are lower case, so the case is
    settled once, here, rather than at each of the two places that read it.
    """
    if not isinstance(pdbid, str) or not _PDB_ID.fullmatch(pdbid):
        raise ValueError(f'a PDB id is four letters or digits, not {pdbid!r}')
    return pdbid.lower()


def structure_name(pdbid):
    """`1qj8` -> `1qj8.pdb`."""
    return f'{canonical_id(pdbid)}.pdb'


def structure_path(dest_dir, pdbid):
    return Path(dest_dir) / structure_name(pdbid)


def sidecar_path(dest_dir, pdbid):
    return Path(dest_dir) / f'{canonical_id(pdbid)}.json'


def membrane_statement(text):
    """What the structure says about its own membrane, or `None`.

    `None` rather than a default value: the defect this replaces was a silent 1.0 nm, and a guessed thickness is
    indistinguishable from a measured one once it is written into a manifest.

    The parsing itself lives with the frame it is used to build, so the importer that records a statement and the
    builder that reads one out of a file cannot drift apart. The import is inside the function because
    `micelle/__init__` pulls the builder's own CLI.
    """
    from micelle.frame import stated_half_thickness_nm

    half = stated_half_thickness_nm(text)
    return {'half_thickness_nm': half} if half is not None else None


def structure_chains(text):
    """The chain ids the structure's coordinate records name, sorted, and empty when it names none.

    Read from the same place the half-thickness is: the file's own text. Both record types carry a chain, so a ligand
    in its own chain is listed -- and it is selectable with it. A blank chain column names no chain, which is
    reported as an empty list rather than a guessed `A`: an invented id is indistinguishable from a read one once a
    selection is built on it. A structure is not refused for it, because nothing here has to choose.
    """
    seen = set()
    for line in text.splitlines():
        if line[:6].strip() in ('ATOM', 'HETATM'):
            chain = line[21:22].strip()
            if chain:
                seen.add(chain)
    return sorted(seen)


def filter_chains(text, chains=None):
    """The structure's text with the chosen chains' *polymer* records kept, and nothing else's.

    Every non-coordinate line is kept, so a statement the file carries (its membrane remark above all) survives the
    filter and a reader downstream sees the same thing. A coordinate record whose chain is not among the chosen ones
    is dropped rather than rewritten: the file names the object, and this is the object. `chains` of `None` (or an
    empty selection) keeps every chain: that is the filtering a run with no selection still needs, and a blank chain
    column -- which names no id a selection could match -- is kept with them rather than dropped.

    `HETATM` records are dropped whatever chain they name, because a `HETATM` is not a protein residue and
    martinize2 removes the *whole molecule* for a residue it cannot place in its force field. Measured on 1AT9
    (bacteriorhodopsin, the trimer the panel offers): its retinal is `HETATM ... RET A 249A`, in the protein's own
    chain A, and filtering by chain alone handed it on -- martinize2 then logged `Cannot recognize residue 'RET' ...
    Deleting the molecule.` and exited 1 having written no topology at all. So a ligand, a crystallisation additive
    or a water travelling in the chosen chain is left out here; `dropped_residues` names what was left out, which is
    what keeps the drop from being silent.
    """
    wanted = {str(chain) for chain in (chains or [])}
    kept = []
    for line in text.splitlines():
        record = line[:6].strip()
        if record == 'HETATM':
            continue
        if record == 'ATOM' and wanted and line[21:22].strip() not in wanted:
            continue
        kept.append(line)
    return '\n'.join(kept) + ('\n' if kept and text.endswith('\n') else '')


def dropped_residues(text, chains=None):
    """The residue names `filter_chains` leaves out: the `HETATM` records it would see, sorted and unique.

    `chains` as `filter_chains` takes it. Read by the build and carried into the run's report, because a build that
    quietly simulated something other than the file it was given is the failure this name exists to prevent.
    """
    wanted = {str(chain) for chain in (chains or [])}
    names = {line[17:20].strip() for line in text.splitlines()
             if line[:6].strip() == 'HETATM' and (not wanted or line[21:22].strip() in wanted)}
    return sorted(name for name in names if name)


#: The scale from a PDB's Angstroms to the nanometres every builder here works in.
ANGSTROM_NM = 0.1


def structure_atoms(path):
    """A structure file's coordinate records, as `{'residue_id', 'residue', 'name', 'position'}` per atom.

    In nanometres, because that is the unit the builders that place, box and write the system work in: a PDB writes
    Angstroms, and a reader that passed those on would put every bead ten times too far out. The shape is the one
    `pdc_view.read_gro` returns for a structure in GROMACS' own units, so a caller can read either.

    The CG step reads martinize2's `-x` output with this: `-x` is the tool's only structure output and it is a PDB
    (`Output coarse grained structure (PDB)` in its own help), which is why the step no longer looks for a `.gro`.
    A file holding no coordinate records is refused rather than returned as an empty structure -- reading nothing as
    if it were something is the defect this stage already had once.
    """
    atoms = []
    for line in Path(path).read_text(errors='replace').splitlines():
        if line[:6].strip() not in ('ATOM', 'HETATM'):
            continue
        try:
            residue_id = int(line[22:26])
            position = [float(line[start:start + 8]) * ANGSTROM_NM for start in (30, 38, 46)]
        except ValueError as exc:
            raise ValueError(f'{path} has an unreadable coordinate record: {line!r}') from exc
        atoms.append({'residue_id': residue_id, 'residue': line[17:20].strip(),
                      'name': line[12:16].strip(), 'position': position})
    if not atoms:
        raise ValueError(f'{path} holds no coordinate records: there is no structure to read')
    return atoms


def import_structure(pdbid, dest_dir, *, fetcher=None, fetched_at=None):
    """Write the structure and its sidecar into `dest_dir`, and return the sidecar's record.

    Fetch first and write second, in that order: a sidecar is a claim that a file is there, so one is never written
    beside nothing. `fetcher` and `fetched_at` are injected so a test never opens a socket and never reads a clock.
    """
    pdbid = canonical_id(pdbid)          # validated before anything is fetched or created
    url = ASSET_URL.format(pdbid=pdbid)
    fetch = fetcher or (lambda source: urllib.request.urlopen(source, timeout=60).read())
    payload = fetch(url)
    # `fetched_at` is the stamp as it will be recorded, which is what lets a test pin it.
    stamp = fetched_at if fetched_at is not None else datetime.now(timezone.utc).isoformat(timespec='seconds')
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    structure_path(dest, pdbid).write_bytes(payload)
    text = payload.decode('utf-8', 'replace')
    record = {'pdbid': pdbid, 'source_url': url, 'sha256': hashlib.sha256(payload).hexdigest(),
              'bytes': len(payload), 'fetched_at': stamp, 'chains': structure_chains(text),
              **(membrane_statement(text) or {})}
    sidecar_path(dest, pdbid).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def read_sidecar(structure):
    """The record written beside a structure, or `None` when there is none.

    Keyed on the file rather than on an id, because a hand-placed structure need not be named after a PDB id and a
    reader must not refuse it for that -- the import writes both names, and anyone can drop a file in.
    """
    try:
        payload = json.loads(Path(structure).with_suffix('.json').read_text())
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
