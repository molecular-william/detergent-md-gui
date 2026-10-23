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
RAMP_MDP = 'ramp.mdp'
# A short, gentler first segment before the extension's 20 fs production. The first extension attempt this workspace ran
# died at 13.04 ns on a LINCS failure inside one DDM headgroup's rigid triangle (S2A-S2B, a 0.29596 nm constraint), with
# bulk temperature, pressure and density healthy to the last saved frame and a clean 5 ns equilibration, and a reseeded retry
# of the same system passed 32 ns without a warning -- so the failure was local and the step-up is what to soften, not the
# fit. `RAMP_PS` at `RAMP_DT_PS`, then the production the run asked for, unchanged.
RAMP_DT_PS = 0.01
RAMP_PS = 100.0
# The case with no executor and no device named: threads only. The device comes from the executor's
# MDRUN_FLAGS, which one builder writes from `mdrun_gpu` -- a copy here would be a second opinion about it.
DEFAULT_MDRUN_FLAGS = '-ntomp 8'


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


def kept_topology(text: str, removed: int, protein: str | None = None,
                  detergent: str | None = None, drop: tuple = ()) -> str:
    """The topology with `removed` of the detergent's molecules taken out of `[ molecules ]`.

    The caller names the detergent when it can, and it should: for a protein-free build there is no protein row to
    contrast it with, and inferring one -- taking the first row as the protein -- reduces the *water* instead. That
    is what a measured run did, leaving `DDM 6` beside two fewer water beads. A count that would go below one is
    refused rather than written, because a topology claiming no detergent cannot hold any.
    """
    rows = molecule_counts(text)
    if not rows:
        raise SystemExit('the topology has no [ molecules ] section to reduce')
    if detergent is None and protein is None:
        protein = rows[0][0]
    # One row is the detergent's, and only that row is reduced. Naming the detergent is exact; the older spelling --
    # "the row that is not the protein's" -- is what a caller that knows only the protein gets.
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
        if len(fields) >= 2 and fields[-1].lstrip('-').isdigit() and fields[0] in drop:
            # Solvent and ions: the restart re-solvates the kept coordinates, and grompp reconciles topology and
            # structure by count. Leaving them here also breaks genion -- `The solvent group W is not continuous` --
            # because ions sit scattered among the water beads of a system that has already been solvated.
            lines[index] = ''
            continue
        is_detergent = (fields and fields[0] == detergent) if detergent is not None else (fields and fields[0] != protein)
        if len(fields) >= 2 and fields[-1].lstrip('-').isdigit() and is_detergent:
            remaining = int(fields[-1]) - removed
            if remaining < 1:
                raise SystemExit(f'{fields[0]}: removing {removed} would leave {remaining} molecules')
            lines[index] = '\t'.join([fields[0], str(remaining)])
    return '\n'.join(lines) + '\n'


def restart_mdp(text: str, seed: int) -> str:
    """The extension mdp with a fresh velocity seed, ready to restart from a checkpoint.

    A restart has to generate new velocities -- that is the whole difference from continuing -- and the template mdp
    already names a `gen-seed` and says `continuation = yes`, so both are rewritten rather than appended to. Two
    measured refusals came from getting this wrong, one for each field:

        Parameter "gen-seed" doubly defined
        Generating velocities is inconsistent with attempting to continue a previous run

    The checkpoint still supplies the state; `continuation = no` only drops the claim that nothing was reset.
    """
    lines = []
    seeded = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('gen-vel'):
            line = 'gen-vel = yes'
        elif stripped.startswith('gen-seed'):
            line, seeded = f'gen-seed = {seed}', True
        elif stripped.startswith('continuation'):
            line = 'continuation = no'
        lines.append(line)
    if not seeded:
        lines.append(f'gen-seed = {seed}')
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
    """Run one stage command, announcing it the way a shell's `set -x` would.

    Every other stage that runs mdrun is a shell script under `set -euxo pipefail`, and the dashboard reads progress out of
    that trace: `+ gmx mdrun -deffnm X` starts a leg, and the `+ gmx grompp ... -f mdp -o X.tpr` before it names the mdp
    whose `nsteps` the leg's step counter is divided by. This stage launches its tools from Python, which traces nothing, so
    its bar read empty through a whole 5 ns equilibration and a 100 ns production while the log carried every step.
    """
    print('+ ' + ' '.join(str(part) for part in command), file=sys.stderr, flush=True)
    subprocess.run(command, input=piped, text=True, check=True,
                   stdout=subprocess.DEVNULL if piped else None)


def ramp_mdp(text: str, dt_ps: float = RAMP_DT_PS, ps: float = RAMP_PS) -> str:
    """The restart mdp at a smaller timestep for a short first segment.

    Only `dt` and `nsteps` change. The integrator, cutoffs, thermostat, barostat and seed stay byte-identical, so the segment
    is the same physics at half the step, and its length is `ps / dt` steps rather than a second duration setting that could
    disagree with the timestep it is divided by.
    """
    nsteps = int(round(ps / dt_ps))
    rewritten = {'dt': f'{dt_ps}', 'nsteps': f'{nsteps}'}
    lines, seen = [], set()
    for line in text.splitlines():
        key = line.split('=', 1)[0].strip().lower()
        if key in rewritten:
            seen.add(key)
            lines.append(f'{key} = {rewritten[key]} ; the extension ramp')
        else:
            lines.append(line)
    missing = set(rewritten) - seen
    if missing:
        raise ValueError(f'the extension mdp states no {" or ".join(sorted(missing))}')
    return '\n'.join(lines) + '\n'


def restart_plan(launcher: str = '', mdrun_flags: str = DEFAULT_MDRUN_FLAGS) -> list[list[str]]:
    """The commands that restart the phase, in order: minimise, equilibrate, ramp, produce.

    Each segment continues from the checkpoint of the one before it, which is what makes the ramp work at all -- the
    velocities it hands the production are its own. `-t` is the checkpoint and `-c` the structure it must match.
    """
    def grompp(mdp: str, structure: str, tpr: str, checkpoint: str | None = None) -> list[str]:
        command = ['gmx', 'grompp', '-f', mdp, '-p', 'system.top', '-c', structure]
        if checkpoint:
            command += ['-t', checkpoint]
        return command + ['-o', tpr, '-maxwarn', '1']

    def mdrun(name: str) -> list[str]:
        return [f'{launcher}gmx', 'mdrun', '-deffnm', name, *mdrun_flags.split(), '-v']

    return [
        grompp('minimization.mdp', 'system.gro', 'min.tpr'), mdrun('min'),
        grompp('equilibration.mdp', 'min.gro', 'eq.tpr'), mdrun('eq'),
        grompp(RAMP_MDP, 'eq.gro', 'ramp.tpr', 'eq.cpt'), mdrun('ramp'),
        grompp(RESTART_MDP, 'ramp.gro', 'prod/run.tpr', 'ramp.cpt'), mdrun('prod/run'),
    ]


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
        run(['gmx', 'convert-tpr', '-s', 'run.tpr', '-extend', extension_ps, '-o', 'prod/run.tpr'])
        run([f'{launcher}gmx', 'mdrun', '-deffnm', 'run', '-cpi', 'run.cpt', *mdrun_flags.split(), '-v'])
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
        from dashboard.execution.adapters import pdc_solvation
        detergent = (settings.get('detergent_model') or {}).get('residue') or None
        solvent = (pdc_solvation.WATER_BEADS, *pdc_solvation.ION_NAMES)
        (stage / KEPT_TOPOLOGY).write_text(kept_topology((stage / 'system.top').read_text(), len(removed), protein,
                                                         detergent=detergent, drop=solvent))
        shutil.copy2(stage / KEPT_TOPOLOGY, stage / 'system.top')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from dashboard.execution.scripts import pdc_solvate
        pdc_solvate.main(['--stage', str(stage), '--topology', 'system.top',
                          '--structure', str(assessment / 'kept.gro'),
                          '--salt-molar', str(settings.get('salt_molar', 0.15))])
        # New velocities, and only that changes: the seeded system is the same placement, one attempt older. The
        # seed has to differ from the one the phase it replaces used, so the first restart is seed + 1.
        seed = int(settings.get('seed', 1)) + len(history) + 1
        (stage / RESTART_MDP).write_text(restart_mdp((stage / 'extension.mdp').read_text(), seed))
        (stage / RAMP_MDP).write_text(ramp_mdp((stage / RESTART_MDP).read_text()))
        for command in restart_plan(launcher, mdrun_flags):
            run(command)
        record = {'attempt': len(history) + 1, 'removed': len(removed), 'mode': 'restarted',
                  'ramp': {'dt_ps': RAMP_DT_PS, 'ps': RAMP_PS},
                  'removed_fraction': decision.get('fraction_removed'), 'seed': seed,
                  'above_threshold': bool(decision.get('fraction_removed', 0) >
                                          float(settings.get('selection_threshold_fraction', 0.10)))}

    (stage / ATTEMPTS).write_text(json.dumps({'attempts': attempts(stage) + [record]}, indent=2, sort_keys=True))
    print(f"{record['mode']}: {record['removed']} detergents removed, attempt {record['attempt']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
