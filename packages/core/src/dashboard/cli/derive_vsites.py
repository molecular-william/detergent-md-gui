"""Derive GROMACS virtual-site parameters from a molecule topology (MkVsites port).

The heavy lifting is in :mod:`dashboard.models.molecules.vsites`; this command is the stable
entry point:

    python -m dashboard.cli.derive_vsites --itp molecule.itp [--force-field DIR] [--out FILE]
    python -m dashboard.cli.derive_vsites --rtp residues.rtp --residue LIG --force-field DIR

JSON goes to stdout unless ``--out`` names a file. Exit status is 2 for an unreadable or
unsupported topology and 0 when the topology is readable but a construct could not be derived;
the latter is reported under ``diagnostics``.

Each ``forcefield`` key is a block to paste into a GROMACS file:

``constraints`` and ``angle_constraints``
    ``[ constraints ]`` in ``ffbonded.itp`` (dummy--dummy, dummy--anchor, then heavy--hydrogen).
``dummy_masses``
    ``[ atomtypes ]`` in ``ffnonbonded.itp`` (zero-mass dummy particle types).
``atomtypes``
    ``atomtypes.atp`` (the same names and zero mass).
``vsd``
    the force field's ``.vsd`` file (``center heavy dummy`` patterns).

The algorithm is the MkVsites method: Per Larsson, Rosita Carolina Kneisz, Erik G Marklund,
J. Comput. Chem. 41(2):1564-1569 (2020), doi:10.1002/jcc.26198. MkVsites is MIT-licensed
(https://github.com/ErikMarklund/mkvsites, commit 3878974); this is an adapted implementation,
not a copy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..models.molecules import vsites
from ..models.molecules.vsites import VsiteError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Derive MkVsites virtual-site and angle-constraint parameters from an ITP/TOP or RTP file.',
        epilog=(
            'Force-field snippet destinations: forcefield.constraints and '
            'forcefield.angle_constraints -> [ constraints ] in ffbonded.itp; '
            'forcefield.dummy_masses -> [ atomtypes ] in ffnonbonded.itp; '
            'forcefield.atomtypes -> atomtypes.atp; forcefield.vsd -> the .vsd file.'),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--itp', type=Path, metavar='PATH', help='ITP or TOP file with one moleculetype')
    source.add_argument('--rtp', type=Path, metavar='PATH', help='RTP file with the residue to read')
    parser.add_argument('--residue', metavar='NAME', help='residue name in the RTP file (required with --rtp)')
    parser.add_argument('--force-field', type=Path, metavar='DIR',
                        help='directory with ffbonded.itp and ffnonbonded.itp (required with --rtp)')
    parser.add_argument('--out', type=Path, metavar='PATH', help='write JSON here instead of stdout')
    return parser


def _derive(args: argparse.Namespace) -> dict:
    if args.itp is not None:
        if args.residue:
            raise VsiteError('--residue is only valid with --rtp')
        return vsites.derive_from_itp(args.itp, args.force_field)
    if not args.residue:
        raise VsiteError('--rtp requires --residue NAME')
    if args.force_field is None:
        raise VsiteError('--rtp requires --force-field DIR: RTP rows normally carry no bond or angle parameters')
    return vsites.derive_from_rtp(args.rtp, args.residue, args.force_field)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = _derive(args)
        text = json.dumps(result, indent=2, sort_keys=True) + '\n'
        if args.out is not None:
            args.out.write_text(text, encoding='utf-8')
        else:
            sys.stdout.write(text)
    except (VsiteError, OSError) as exc:
        print(f'derive_vsites: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
