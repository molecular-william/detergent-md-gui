"""The operator's commands for the conformation library.

    python -m detergent_pdc.conformations build --workspace <ws> --runs <id>[,<id>...] --size 2000 [--seed 0]
    python -m detergent_pdc.conformations show  <library.json|key> --workspace <ws>

`build` prints the operator's record -- key, path, digest, size, pool, per-source counts, seconds and the producer
versions -- because the counts belong to the build and not to `library.json`, whose bytes a rebuild must reproduce.
`show` prints a stored library's summary and no coordinates: it is there to read a key back, or to confirm a copied
directory before a run is prepared with it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .library import DEFAULT_SIZE, MAX_SIZE, available, build, load, normalise_spec, verify


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m detergent_pdc.conformations',
                                     description='Build or inspect a detergent conformation library.')
    commands = parser.add_subparsers(dest='command', required=True)
    builder = commands.add_parser('build', help='build a library from completed, protein-free pdc runs')
    builder.add_argument('--workspace', required=True, help='the workspace directory the store and runs live under')
    builder.add_argument('--runs', required=True, help='one or more run ids, comma separated')
    builder.add_argument('--size', type=int, default=DEFAULT_SIZE, help=f'the number of entries (1..{MAX_SIZE})')
    builder.add_argument('--seed', type=int, default=0, help='the selection seed, recorded in the library key')
    shower = commands.add_parser('show', help="print a stored library's summary")
    shower.add_argument('target', help='a library.json path, or a stored key')
    shower.add_argument('--workspace', required=True, help='the workspace directory the store lives under')
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == 'build':
            spec = normalise_spec({'runs': [value for value in arguments.runs.split(',') if value.strip()],
                                   'size': arguments.size, 'seed': arguments.seed})
            _library, record = build(arguments.workspace, spec)
            print(json.dumps(record, indent=2, sort_keys=True))
            return 0
        print(json.dumps(_summary(_shown(arguments.target, arguments.workspace)), indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')


def _shown(target, workspace):
    """The library a `show` argument names: a file or directory on disk, else a key in the workspace store."""
    path = Path(target)
    if path.exists():
        library = load(path)
        verify(library)
        return library
    stored = [entry for entry in available(workspace) if entry['key'] == target]
    if not stored:
        raise ValueError(f'{target} is neither a file nor a library stored in {Path(workspace) / 'conformations'}')
    library = load(stored[0]['path'])
    verify(library, key=target)
    return library


def _summary(library):
    """What a reader needs to trust and select a library, and nothing that is coordinates."""
    return {'key': library.key, 'sha256': library.sha256, 'path': str(library.path), 'residue': library.residue,
            'beads': library.beads, 'mapping_sha256': library.mapping_sha256, 'size': library.size,
            'pool': library.document['pool'], 'sources': library.sources}


if __name__ == '__main__':  # pragma: no cover - the module's own command line
    raise SystemExit(main())
