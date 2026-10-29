"""Fill a protein-detergent system with Martini water and 0.15 M NaCl, and record what arrived.

Run by the Energy minimisation leg, which is the stage that solvates the built system, and by `pdc_extension.py`
when the criterion left detergents outside the micelle and the removal path rebuilds the kept system. The commands
come from `pdc_solvation`, which is the tested place that decides the bead radius, the ion names and the water group
`genion` is allowed to replace; this module runs them, pipes the group in, and reads the composition back off the
topology that results.

    python -m dashboard.execution.scripts.pdc_solvate [--salt-molar 0.15]

Writes `solvation.json` beside the stage: the commands as they ran, and the molecule counts the topology holds
afterwards, which is what makes a run's composition a recorded number rather than a claim.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from dashboard.execution.adapters import pdc_solvation

OUTPUT_NAME = 'solvation.json'


def molecules(topology: Path) -> dict[str, int]:
    """The `[ molecules ]` counts of a topology, in the order written."""
    counts: dict[str, int] = {}
    section = ''
    for raw in topology.read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            continue
        if section != 'molecules' or not line:
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[-1].lstrip('-').isdigit():
            counts[fields[0]] = counts.get(fields[0], 0) + int(fields[-1])
    return counts


def run(commands, *, logs: Path, group_selection: str) -> list[list[str]]:
    """Run the solvation commands in order, piping the ion group into `genion` and nothing into the rest."""
    with (logs / 'solvation.log').open('w') as log:
        for command in commands:
            piped = command[1] == 'genion'
            subprocess.run(command, input=group_selection if piped else None,
                           stdout=log, stderr=subprocess.STDOUT, text=True, check=True)
    return commands


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Solvate a protein-detergent system and add salt.')
    parser.add_argument('--topology', default='system.top')
    parser.add_argument('--structure', default='system.gro')
    parser.add_argument('--salt-molar', type=float, default=0.15)
    parser.add_argument('--stage', default='.')
    args = parser.parse_args(argv)
    stage = Path(args.stage)
    topology, logs = stage / args.topology, stage / 'logs'
    logs.mkdir(exist_ok=True)

    commands = pdc_solvation.solvation_commands(str(topology), str(stage / args.structure), 'system.tpr',
                                                salt_molar=args.salt_molar)
    run(commands, logs=logs, group_selection=pdc_solvation.ion_group_selection())
    (stage / OUTPUT_NAME).write_text(json.dumps(
        {'commands': commands, 'salt_molar': args.salt_molar,
         'water_bead_radius_nm': pdc_solvation.MARTINI_WATER_RADIUS_NM,
         'water_group': pdc_solvation.WATER_BEADS, 'ion_names': list(pdc_solvation.ION_NAMES),
         'molecules': molecules(topology)}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
