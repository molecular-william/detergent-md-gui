"""Neutralise the atomistic system a back-map produced, and record the sum before and after.

CG2AT2 converts a coarse-grained complex into atoms and stops there: the atomistic protein's protonation states are
pdb2gmx's, the ions are the ones the CG system carried, and nothing makes the two balance. The 4iar/DDM complex came out at
**-5**, which GROMACS does not treat as a tolerance -- "You are using Ewald electrostatics in a system with net charge. This
can lead to severe artifacts" -- and the steering leg that aligns the de-novo build to the CG input refused to run for it.

So this step adds the ions it takes to make the sum zero, and writes what it measured:

* The water moleculetype must be named as its residues are. CG2AT2 writes `[ moleculetype ] tip3p` while the residues are
  `SOL`, and `genion` replaces solvent by *moleculetype* name: until the two agree it stops with "No line with moleculetype
  'SOL' found the [ molecules ] section". The rename is inside the stage's own copy of the conversion, and only the water.
* `genion` fits ions to a tpr, so a no-dynamics mdp makes one first. It is the same shape the CG half uses for the same
  reason: no dynamics, no output, just something the ions can be placed into.
* `grompp`'s warning budget belongs to the topology, not to us: the converted complex carries CHARMM's duplicate dihedral
  line and the very net charge this step exists to fix, so the budget is raised here and the number of warnings recorded
  rather than assumed.

    python pdc_neutralise.py --system FINAL [--stage .]

Writes `neutralisation.json` beside the stage: the charges before and after, the ions added, the commands, and the
warnings grompp raised. Nothing is claimed that was not read back from the topology.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

WATER_RESIDUE = 'SOL'
ION_NAMES = ('NA', 'CL')
RECORD_NAME = 'neutralisation.json'
#: The force-field sections that are not the molecule: everything a converted itp may carry ahead of `[ moleculetype ]`.
MOLECULETYPE = re.compile(r'^\[\s*moleculetype\s*\]', re.IGNORECASE | re.MULTILINE)

IONS_MDP = """\
; A topology fix-up run for genion: no dynamics, no output, just a tpr the ions can be fitted to.
integrator    = steep
nsteps        = 0
cutoff-scheme = Verlet
coulombtype   = PME
rcoulomb      = 1.0
rvdw          = 1.0
pbc           = xyz
"""


def sections(text: str) -> dict[str, list[list[str]]]:
    """Every `[ section ]` of an itp or top, as its whitespace-separated data rows."""
    found: dict[str, list[list[str]]] = {}
    name = ''
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            name = line[1:-1].strip().lower()
            found.setdefault(name, [])
            continue
        found.setdefault(name, []).append(line.split())
    return found


def moleculetype_of(text: str) -> str:
    """The molecule a converted itp describes: the first data row under `[ moleculetype ]`."""
    found = MOLECULETYPE.search(text)
    if not found:
        return ''
    for raw in text[found.end():].splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('['):
            return ''
        return line.split()[0]
    return ''


def resolve(defined: dict[str, Path], name: str) -> Path | None:
    """A moleculetype by name: GROMACS writes `[ molecules ]` rows in the case the build chose, the itp in its own."""
    return defined.get(name) or defined.get(name.lower()) or defined.get(name.upper())


def moleculetypes(root: Path) -> dict[str, Path]:
    """Which file in a converted system defines each moleculetype."""
    found = {}
    for path in sorted(root.glob('*.itp')):
        name = moleculetype_of(path.read_text())
        if name:
            found.setdefault(name, path)
    return found


def composition(topology: Path) -> list[tuple[str, int]]:
    """`[ molecules ]` in the order written: which molecule, how many."""
    rows = []
    for fields in sections(topology.read_text()).get('molecules', []):
        if len(fields) >= 2 and fields[-1].lstrip('-').isdigit():
            rows.append((fields[0], int(fields[-1])))
    return rows


def counts(topology: Path) -> dict[str, int]:
    """Molecule counts summed over rows: `genion` appends its own row rather than editing the existing one."""
    totals: dict[str, int] = {}
    for name, number in composition(topology):
        totals[name] = totals.get(name, 0) + number
    return totals


def charge_of(path: Path) -> float:
    """The summed charge of one moleculetype, from the charges its own `[ atoms ]` states."""
    total = 0.0
    for fields in sections(path.read_text()).get('atoms', []):
        if len(fields) >= 7:
            try:
                total += float(fields[6])
            except ValueError:
                continue
    return total


def total_charge(root: Path) -> tuple[float, dict[str, float]]:
    """The system's net charge, and each moleculetype's share of it."""
    defined = moleculetypes(root)
    per: dict[str, float] = {}
    for name, count in composition(root / 'topol_final.top'):
        path = resolve(defined, name)
        if path is None:
            raise SystemExit(f'the topology names {name}, which no itp in {root} defines')
        per[name] = per.get(name, 0.0) + charge_of(path) * count
    return sum(per.values()), per


def water_name(root: Path) -> str:
    """The moleculetype that is the solvent: the one with the most molecules that is not an ion."""
    defined = moleculetypes(root)
    rows = composition(root / 'topol_final.top')
    # The most numerous molecule that is not an ion. Counting its atoms instead would fail here: CG2AT2's TIP3P itp lists
    # seven `[ atoms ]` rows for a three-site water, so a size test excludes the solvent it is looking for.
    candidates = [(count, name) for name, count in rows
                  if resolve(defined, name) is not None and name.upper() not in ION_NAMES]
    if not candidates:
        raise SystemExit(f'no solvent moleculetype found in {root / "topol_final.top"}')
    return max(candidates)[1]


def rename_water(root: Path, wanted: str = WATER_RESIDUE) -> dict:
    """Make the solvent's moleculetype and its `[ molecules ]` row carry the residue name `genion` is asked for."""
    name = water_name(root)
    if name == wanted:
        return {'renamed': None}
    path = resolve(moleculetypes(root), name)
    text = path.read_text()
    out = []
    in_type = False
    for line in text.splitlines():
        if line.strip().startswith('['):
            in_type = line.strip().lower().startswith('[ moleculetype')
            out.append(line)
            continue
        if in_type and line.strip() and not line.lstrip().startswith(';'):
            out.append(f'{wanted}\t\t2')
            in_type = False
            continue
        out.append(line)
    path.write_text('\n'.join(out) + '\n')
    topology = root / 'topol_final.top'
    topology.write_text(re.sub(rf'(?m)^{re.escape(name)}(\s+)(\d+)\s*$', rf'{wanted}\1\2', topology.read_text()))
    return {'renamed': {'from': name, 'to': wanted, 'file': path.name}}


def run(command: list[str], *, log: Path, stdin: str | None = None, cwd: Path) -> int:
    """Run one command in the converted system's own directory.

    `cwd` is not cosmetic: `genion` writes its edited topology to a temporary file in the working directory and renames it
    over the target, and a working directory on another filesystem -- a scratch dir under `$HOME` against a repository
    under `/mnt/data` -- makes that rename fail *after* it has already moved the original aside. The stage lost its
    topology to exactly that; running in the conversion's own directory keeps the rename on one filesystem.
    """
    with log.open('a') as handle:
        return subprocess.run(command, input=stdin, stdout=handle, stderr=subprocess.STDOUT,
                              text=True, check=False, cwd=str(cwd)).returncode


def neutralise(root: Path, stage: Path, *, water: str = WATER_RESIDUE) -> dict:
    """Add the ions that make the converted system neutral; return what was measured."""
    logs = stage / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    topology = root / 'topol_final.top'
    if not topology.is_file():
        raise SystemExit(f'{topology} is missing: the conversion did not finish')

    before, per = total_charge(root)
    molecules_before = counts(topology)
    renamed = rename_water(root, water)
    (stage / 'ions.mdp').write_text(IONS_MDP)
    commands = []

    # Absolute paths throughout: the stage runs from its own directory and a relative `-f` resolves against the caller's
    # working directory, not the stage's -- "File 'ions.mdp' does not exist".
    grompp = ['gmx', 'grompp', '-f', str(stage / 'ions.mdp'), '-c', str(root / 'final_cg2at_de_novo.pdb'),
              '-p', str(topology), '-o', str(stage / 'ions.tpr'), '-maxwarn', '5']
    commands.append(grompp)
    code = run(grompp, log=stage / 'neutralise.log', cwd=root)
    if code != 0:
        raise SystemExit(f'grompp failed ({code}); see {stage / "neutralise.log"}')

    genion = ['gmx', 'genion', '-s', str(stage / 'ions.tpr'), '-o', str(root / 'final_cg2at_neutral.pdb'),
              '-p', str(topology), '-pname', ION_NAMES[0], '-nname', ION_NAMES[1], '-neutral']
    commands.append(genion)
    code = run(genion, log=stage / 'neutralise.log', stdin=f'{water}\n', cwd=root)
    if code != 0:
        raise SystemExit(f'genion failed ({code}); see {stage / "neutralise.log"}')

    after, per_after = total_charge(root)
    molecules_after = counts(topology)
    log_path = stage / 'neutralise.log'
    warnings = sum(1 for line in log_path.read_text().splitlines() if line.startswith('WARNING')) \
        if log_path.is_file() else 0
    return {'charge_before': round(before, 4), 'charge_after': round(after, 4) + 0.0,
            'per_moleculetype_before': {name: round(value, 4) for name, value in per.items()},
            'per_moleculetype_after': {name: round(value, 4) for name, value in per_after.items()},
            'ions_added': {name: molecules_after.get(name, 0) - molecules_before.get(name, 0) for name in ION_NAMES},
            'water': water, **renamed, 'grompp_warnings': warnings,
            'commands': commands, 'structure': str(root / 'final_cg2at_neutral.pdb')}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Neutralise the atomistic system a back-map produced.')
    parser.add_argument('--system', default='FINAL', help='the directory the conversion wrote')
    parser.add_argument('--stage', default='.')
    args = parser.parse_args(argv)
    stage = Path(args.stage).resolve()
    record = neutralise(stage / args.system, stage)
    (stage / RECORD_NAME).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(f'neutralised: {record["charge_before"]} -> {record["charge_after"]}, '
          f'ions {record["ions_added"]}, structure {record["structure"]}')
    return 0 if abs(record['charge_after']) < 1e-3 else 2


if __name__ == '__main__':
    sys.exit(main())
