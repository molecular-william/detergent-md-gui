"""The extension phase, and the removal that can precede it.

Design spec §8 says detergents left outside the micelle are removed and the run *continues from the assessment
phase's checkpoint*. A GROMACS checkpoint carries a particle count, so that cannot be implemented as written; the
user chose the strict reading, and this is it:

* **nothing outside the micelle** — the phase continues from the assessment's checkpoint, exactly as the spec's
  sentence intends;
* **something outside** — those detergents are **deleted**, the kept system is rebuilt (solvated, minimised,
  equilibrated with **new velocities**, because a smaller system cannot inherit the larger one's velocities) and the
  extension duration runs from there. Every attempt is recorded with the number removed and the seed it used, and the
  loop is bounded by the run's own `attempts_max`.

    python pdc_extension.py --settings ../1_system/pdc-settings.json --stage . \
        --assessment ../3_assessment --assessment-stage ../2_assessment
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ATTEMPTS = 'attempts.json'
KEPT_TOPOLOGY = 'kept.top'
RESTART_MDP = 'restart.mdp'
DEFAULT_MDRUN_FLAGS = '-ntomp 8 -gpu_id 0 -nb gpu -pin on'


def sections(text: str) -> list[str]:
    """A topology's lines, so the one section a removal edits can be found without rewriting the file."""
    return text.splitlines()


def molecule_counts(text: str) -> list[tuple[str, int]]:
    """The `[ molecules ]` rows, in order: the names and counts a topology declares."""
    rows, section = [], ''
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            continue
        if section != 'molecules' or not line:
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[-1].lstrip('-').isdigit():
            rows.append((fields[0], int(fields[-1])))
    return rows


def kept_topology(text: str, removed: int, protein: str | None = None) -> str:
    """The topology with `removed` of the detergent's molecules taken out of `[ molecules ]`.

    The detergent is the row that is not the protein's, so the protein's name comes from the caller; a count that
    would go below one is refused rather than written, because a topology claiming no detergent cannot hold any.
    """
    rows = molecule_counts(text)
    if not rows:
        raise SystemExit('the topology has no [ molecules ] section to reduce')
    if protein is None:
        protein = rows[0][0]
    lines = text.splitlines()
    section = ''
    for index, raw in enumerate(lines):
        line = raw.split(';', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            continue
        if section != 'molecules' or not line:
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[-1].lstrip('-').isdigit() and fields[0] != protein:
            remaining = int(fields[-1]) - removed
            if remaining < 1:
                raise SystemExit(f'{fields[0]}: removing {removed} would leave {remaining} molecules')
            lines[index] = '\t'.join([fields[0], str(remaining)])
    return '\n'.join(lines) + '\n'


def attempts(stage: Path) -> list[dict]:
    path = stage / ATTEMPTS
    if not path.is_file():
        return []
    try:
        return list(json.loads(path.read_text()).get('attempts') or [])
    except (OSError, json.JSONDecodeError):
        return []


def run(command, *, piped: str | None = None) -> None:
    """Run one stage command with newline-free output going to the stage's own log."""
    subprocess.run(command, input=piped, text=True, check=True,
                   stdout=subprocess.DEVNULL if piped else None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Run the extension phase, removing what the criterion left out.')
    parser.add_argument('--settings', default='../1_system/pdc-settings.json')
    parser.add_argument('--stage', default='.')
    parser.add_argument('--assessment', default='../3_assessment')
    parser.add_argument('--assessment-stage', default='../2_assessment')
    args = parser.parse_args(argv)
    stage, assessment, previous = Path(args.stage), Path(args.assessment), Path(args.assessment_stage)
    settings = json.loads(Path(args.settings).read_text())
    mdrun_flags = os.environ.get('MDRUN_FLAGS', DEFAULT_MDRUN_FLAGS)
    launcher = os.environ.get('MDRUN_LAUNCHER', '')
    decision = json.loads((assessment / 'removed.json').read_text())
    removed = decision.get('removed') or []
    (stage / 'prod').mkdir(exist_ok=True)

    if not removed:
        # The spec's own sentence: nothing outside the micelle, so the phase continues from the checkpoint.
        for name in ('run.tpr', 'run.cpt', 'run.xtc', 'run.gro'):
            source = previous / 'prod' / name
            if source.is_file():
                shutil.copy2(source, stage / name)
        extension_ps = (stage / 'extension.ps').read_text().strip()
        subprocess.run(['gmx', 'convert-tpr', '-s', 'run.tpr', '-extend', extension_ps, '-o', 'prod/run.tpr'],
                       check=True)
        subprocess.run([f'{launcher}gmx', 'mdrun', '-deffnm', 'run', '-cpi', 'run.cpt',
                        *mdrun_flags.split(), '-v'], check=True)
        shutil.copy2(stage / 'run.gro', stage / 'prod' / 'run.gro')
        shutil.copy2(stage / 'run.xtc', stage / 'prod' / 'run.xtc')
        record = {'attempt': len(attempts(stage)) + 1, 'removed': 0, 'removed_fraction': 0.0, 'mode': 'continued',
                  'seed': settings.get('seed')}
    else:
        history = attempts(stage)
        limit = int(settings.get('attempts_max', 3))
        if len(history) >= limit:
            raise SystemExit(f'{len(history)} attempts already used, and {len(removed)} detergents are still '
                             f'outside the micelle: the run has not formed the requested aggregate')
        protein = None
        if (stage / 'system_EMPTY.top').is_file():
            protein = molecule_counts((stage / 'system_EMPTY.top').read_text())[0][0]
        (stage / KEPT_TOPOLOGY).write_text(kept_topology((stage / 'system.top').read_text(), len(removed), protein))
        shutil.copy2(stage / KEPT_TOPOLOGY, stage / 'system.top')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from dashboard.execution.scripts import pdc_solvate
        pdc_solvate.main(['--stage', str(stage), '--topology', 'system.top',
                          '--structure', str(assessment / 'kept.gro'),
                          '--salt-molar', str(settings.get('salt_molar', 0.15))])
        # New velocities, and only that changes: the seeded system is the same placement, one attempt older. The
        # seed has to differ from the one the phase it replaces used, so the first restart is seed + 1.
        seed = int(settings.get('seed', 1)) + len(history) + 1
        (stage / RESTART_MDP).write_text(
            (stage / 'extension.mdp').read_text().replace('gen-vel = no', 'gen-vel = yes')
            + f'\ngen-seed = {seed}\n')
        for target, source in (('min.tpr', 'minimization.mdp'), ('eq.tpr', 'equilibration.mdp')):
            previous_structure = 'system.gro' if target == 'min.tpr' else 'min.gro'
            subprocess.run(['gmx', 'grompp', '-f', source, '-p', 'system.top', '-c', previous_structure,
                            '-o', target, '-maxwarn', '1'], check=True)
            subprocess.run([f'{launcher}gmx', 'mdrun', '-deffnm', target.split('.')[0], *mdrun_flags.split(), '-v'],
                           check=True)
        subprocess.run(['gmx', 'grompp', '-f', RESTART_MDP, '-p', 'system.top', '-c', 'eq.gro', '-t', 'eq.cpt',
                        '-o', 'prod/run.tpr', '-maxwarn', '1'], check=True)
        subprocess.run([f'{launcher}gmx', 'mdrun', '-deffnm', 'prod/run', *mdrun_flags.split(), '-v'], check=True)
        record = {'attempt': len(history) + 1, 'removed': len(removed), 'mode': 'restarted',
                  'removed_fraction': decision.get('fraction_removed'), 'seed': seed,
                  'above_threshold': bool(decision.get('fraction_removed', 0) >
                                          float(settings.get('selection_threshold_fraction', 0.10)))}

    (stage / ATTEMPTS).write_text(json.dumps({'attempts': attempts(stage) + [record]}, indent=2, sort_keys=True))
    print(f"{record['mode']}: {record['removed']} detergents removed, attempt {record['attempt']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
