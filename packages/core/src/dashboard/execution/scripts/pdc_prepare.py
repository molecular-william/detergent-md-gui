"""The prepare stage's entry point: the run's own decision, the tool the machine has, and the record.

Run by `01_prepare/pdc_prepare.sh`, the repository script every pdc run records in `stage_scripts`. Everything the
step *does* is `execution/adapters/pdc_preparation.py`'s; this module is the stage's half of it -- where the run's
settings are read, which of the contract's outcomes applies, and what is written for a reader afterwards.

    python -m dashboard.execution.scripts.pdc_prepare --stage .

The step is optional, and the run's settings decide it at prepare time: a run that does not ask for it -- or has no
protein -- gets no stage directory and the manifest records the skip. A stage that exists answers `skipped` (exit 4)
with its reason in `skip.json` when the preparer is not resolvable on this machine, and exit 2 is a refusal -- the
run asked for this structure to be prepared and the machine cannot prepare it -- with the reason and the tool's own
log tail in `prepare_protein.json`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dashboard.execution.adapters import pdc_preparation
from dashboard.execution.adapters.pdc import SETTINGS_NAME

SKIPPED = 4
REFUSED = 2


def read_settings(stage: Path) -> dict:
    """The run's own decisions, from the one stage that owns them.

    `pdc-settings.json` is written into the run's `inputs/` by `pdc.prepare`, and every stage that needs a run's
    numbers reads it there -- this one included, so a value the panel sent and the build reads is the same value this
    step reads.
    """
    path = stage.parent.parent / 'inputs' / SETTINGS_NAME
    if not path.is_file():
        raise SystemExit(f'{path} is missing: this stage reads the run\'s decisions from it')
    return json.loads(path.read_text())


def source_protein(stage: Path, settings: dict):
    """The structure to prepare, resolved from the run's own record.

    The protein is referenced where it lived at prepare time, so its path travels in `pdc-settings.json` (absolute, or
    relative to the recorded project root) rather than in a copy inside the run. `None` means the run names none,
    which is the empty micelle -- a run whose prepare-time skip already kept this stage from existing.
    """
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

    # The step is on by default, so it must be able to say "not on this machine" rather than refusing every run: a
    # default no machine is obliged to satisfy would turn a missing optional tool into a blocked pipeline. A tool that
    # *is* resolvable and then fails is still a refusal -- that is a structure this machine was asked to prepare and
    # could not, not a step with nothing owed.
    if pdc_preparation.resolve_tool() is None:
        return skip(stage, f'{pdc_preparation.TOOL} is not resolvable on this machine, so the protein is '
                           f'coarse-grained as deposited')
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
