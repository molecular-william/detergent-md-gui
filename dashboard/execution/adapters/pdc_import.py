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
    record = {'pdbid': pdbid, 'source_url': url, 'sha256': hashlib.sha256(payload).hexdigest(),
              'bytes': len(payload), 'fetched_at': stamp,
              **(membrane_statement(payload.decode('utf-8', 'replace')) or {})}
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
