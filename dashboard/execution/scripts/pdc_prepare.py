"""The prepare stage's entry point: the run's own decision, the tool the machine has, and the record.

Run by `0_prepare/pdc_prepare.sh`, which the pdc adapter writes into every run. Everything the step *does* is
`execution/adapters/pdc_preparation.py`'s; this module is the stage's half of it -- where the run's settings are
read, which of the contract's four outcomes applies, and what is written for a reader afterwards.

    python pdc_prepare.py --stage .

The step is optional, and that is the whole of its first branch: a run that does not ask for it records `skipped`
(exit 4) with its reason in `skip.json` beside the script, and the run carries on. Exit 2 is a refusal -- the run
asked for this structure to be prepared and the machine cannot prepare it -- with the reason and the tool's own log
tail in `prepare_protein.json`, because a run that went on without it would coarse-grain a structure the caller did
not ask to coarse-grain.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dashboard.execution.adapters import pdc, pdc_preparation
from dashboard.execution.adapters.pdc import SETTINGS_NAME

#: The adapter's own declaration, so the file this stage reads is the file the build writes and neither has to spell
#: the input's name twice.
DECLARED_INPUT = Path(pdc.stage_by_name('Protein preparation').inputs[0]).name

SKIPPED = 4
REFUSED = 2


def read_settings(stage: Path) -> dict:
    """The run's own decisions, from the one stage that owns them.

    `pdc-settings.json` is written into the system-preparation stage's directory by `pdc.prepare`, and every stage
    that needs a run's numbers reads it there -- this one included, so a value the panel sent and the build reads is
    the same value this step reads.
    """
    system = stage.parent / Path(pdc.stage_by_name('System preparation').relative).parent
    path = system / SETTINGS_NAME
    if not path.is_file():
        raise SystemExit(f'{path} is missing: this stage reads the run\'s decisions from it')
    return json.loads(path.read_text())


def source_protein(stage: Path, settings: dict):
    """The structure to prepare: the file this stage was handed, else the one the run names.

    The declaration is the first answer because it is what the stage was *given* -- the adapter emits the copy from
    the stage's own declaration -- so a stage run by hand outside the executor still resolves the run's own protein
    rather than refusing with nothing to do.
    """
    declared = stage / DECLARED_INPUT
    if declared.is_file():
        return declared
    value = str(settings.get('protein') or '').strip()
    if not value:
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else Path(settings['project_root']) / candidate


def skip(stage: Path, reason: str) -> int:
    """The contract's fourth outcome: nothing attempted, nothing owed, and the reason beside the script."""
    (stage / 'skip.json').write_text(json.dumps({'skipped': True, 'reason': reason}, indent=2) + '\n')
    print(f'skipped: {reason}', file=sys.stderr)
    return SKIPPED


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Rebuild the missing atoms of a run\'s protein, and protonate it.')
    parser.add_argument('--stage', default='.', help='the stage directory to prepare the protein in')
    args = parser.parse_args(argv)
    # Resolved, because a stage runs from its own directory and is handed `.`: `Path('.').parent` is `.`, so the run
    # root a stage reached through a relative spelling is the stage's own directory and not the run's.
    stage = Path(args.stage).resolve()
    settings = read_settings(stage)

    if not settings.get('prepare_protein'):
        return skip(stage, 'the run does not ask for protein preparation, so this stage has nothing to do')
    source = source_protein(stage, settings)
    if source is None or not source.is_file():
        return skip(stage, f'there is no protein to prepare: this run names '
                           f'{settings.get("protein") or "no structure"}')

    record = pdc_preparation.prepare(source, stage, chains=settings.get('protein_chains'))
    if record.get('skipped'):
        # The preparer's own structural answer: the file it was handed holds no coordinate records at all.
        return skip(stage, record['reason'])
    (stage / pdc_preparation.RECORD_NAME).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    if not record.get('ok'):
        print(f'pdc_prepare: {record["reason"]}', file=sys.stderr)
        if record.get('log_tail'):
            print(record['log_tail'], file=sys.stderr)
        return REFUSED
    print(f'prepared {record["path"]}: {record["heavy_atoms_added"]} heavy atom(s) in '
          f'{len(record["residues_rebuilt"])} residue(s), {record["hydrogens_added"]} hydrogen(s), '
          f'{record["seconds"]} s with {record["tool"]} {record["tool_version"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
