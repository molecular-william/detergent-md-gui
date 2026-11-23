"""Place Martini water with Insane, then hand the solvated system back to the stage.

`gmx solvate` reuses a prebuilt water box and only keeps `-radius` away from the solute; the mapping's bead radii
are not in the topology, so measured water-to-head contacts sit closer than the two beads' radii. Insane places its
own water on the system's grid with a solvent diameter instead, and does not need a water-box coordinate template.

The stage still owns the topology and the ions: this module runs Insane over the solute, rewrites the ion residue
names Insane writes (`NA+`/`CL-`) to the Martini 3 molecule names (`NA`/`CL`), and appends the solvent rows to the
existing `[ molecules ]`.  The system's own box is passed unchanged (`-box` plus `-pbc keep`), so the placement the
build made is not re-boxed.  Ions are left to the stage's existing `gmx genion` step for the protein-detergent legs;
an empty micelle/single-molecule CG run passes `-charge 0` and adds no ions.
"""
from __future__ import annotations

import argparse
import subprocess
from collections import Counter
from pathlib import Path

from dashboard.execution import tools

WATER = 'W'
#: Insane writes these residue/atom names; the installed Martini 3 ions file names the molecules `NA` and `CL`.
ION_ALIASES = {'NA+': 'NA', 'CL-': 'CL'}


def box(structure: Path) -> list[str]:
    """The box line of a `.gro`, as the nine or three values Insane's `-box` takes unchanged."""
    lines = Path(structure).read_text().splitlines()
    if not lines:
        raise ValueError(f'{structure} is empty')
    values = lines[-1].split()
    if len(values) not in (3, 9):
        raise ValueError(f'{structure} has an unreadable box line: {lines[-1]!r}')
    return values


def command(structure, output, topology: Path, *, executable=None, salt_molar=None, charge='0') -> list[str]:
    """The Insane invocation: the solute, the same box, and the stage's chosen ions.

    A stage adds water only (`salt_molar=None`, `charge='0'`) and leaves the salt to `genion`; the new-run preview
    asks for the whole solvated cell, so it passes its salt concentration and `charge='auto'`.
    """
    resolved = executable or tools.tool_path('insane') or 'insane'
    command = [str(resolved), '-f', str(structure), '-o', str(output), '-p', str(topology),
               '-box', ','.join(box(Path(structure))), '-pbc', 'keep', '-sol', WATER, '-charge', str(charge)]
    if salt_molar is not None:
        command += ['-salt', str(salt_molar)]
    return command


def molecules(structure: Path) -> dict[str, int]:
    """The solvent molecules Insane wrote, by the Martini 3 molecule name the topology must use."""
    counts = Counter()
    for line in Path(structure).read_text().splitlines()[2:-1]:
        residue = line[5:10].strip()
        if residue in ION_ALIASES or residue == WATER:
            counts[ION_ALIASES.get(residue, residue)] += 1
    return dict(counts)


def normalise_ions(structure: Path) -> None:
    """Rewrite Insane's `NA+`/`CL-` residues and atoms to `NA`/`CL`, the installed set's own spelling."""
    lines = Path(structure).read_text().splitlines()
    for index, line in enumerate(lines[2:-1], start=2):
        residue = line[5:10].strip()
        if residue not in ION_ALIASES:
            continue
        name = ION_ALIASES[residue]
        lines[index] = line[:5] + f'{name:<5}' + f'{name:>5}' + line[15:]
    Path(structure).write_text('\n'.join(lines) + '\n')


def update_topology(topology: Path, counts: dict) -> None:
    """Append the solvent rows to the existing `[ molecules ]`, replacing any previous ones."""
    lines = Path(topology).read_text().splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip().startswith('[ molecules ]'))
    except StopIteration as error:
        raise ValueError(f'{topology} has no [ molecules ] section') from error
    kept = []
    for line in lines[start + 1:]:
        name = line.split(';', 1)[0].split()
        if name and name[0] in (WATER, *ION_ALIASES.values()):
            continue
        kept.append(line)
    rows = [f'{name:<10} {count:7d}' for name, count in counts.items() if count]
    Path(topology).write_text('\n'.join(lines[:start + 1] + kept + rows) + '\n')


def place(structure, output, *, executable=None, salt_molar=None, charge='0') -> dict:
    """Run Insane over a solute and return its command and the solvent counts it wrote."""
    output = Path(output)
    top = output.with_name(output.stem + '.insane.top')
    invoked = command(Path(structure), output, top, executable=executable, salt_molar=salt_molar, charge=charge)
    subprocess.run(invoked, check=True)
    normalise_ions(output)
    counts = molecules(output)
    top.unlink(missing_ok=True)
    return {'commands': [invoked], 'molecules': counts}


def solvate(structure, topology, output, *, executable=None) -> dict:
    """Run Insane and update the stage's topology; return the command and the solvent counts."""
    structure, topology, output = Path(structure), Path(topology), Path(output)
    placed = place(structure, output, executable=executable)
    update_topology(topology, placed['molecules'])
    return placed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Solvate a CG solute with Insane.')
    parser.add_argument('--structure', default='system.gro')
    parser.add_argument('--topology', default='system.top')
    parser.add_argument('--output', default='solvated.gro')
    parser.add_argument('--log', default=None)
    args = parser.parse_args(argv)
    invoked = command(args.structure, args.output, Path(args.output).with_suffix('.insane.top'))
    if args.log:
        with open(args.log, 'w') as log:
            subprocess.run(invoked, stdout=log, stderr=subprocess.STDOUT, check=True)
    else:
        subprocess.run(invoked, check=True)
    normalise_ions(Path(args.output))
    update_topology(Path(args.topology), molecules(Path(args.output)))
    Path(args.output).with_suffix('.insane.top').unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
