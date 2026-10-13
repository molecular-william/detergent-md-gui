"""One place that writes what a run looks like at a moment, and the numbers that go with the picture.

Design note `2026-09-30-pdc-detergent-model-and-snapshots.md`: a snapshot is *derived*, never stored truth, and it
is written together with the criterion's numbers at that moment so a gallery cannot disagree with a verdict. The
index (`snapshots.json`) is the record; the panel reads the PDBs and the index through the existing viewer route.

Called by the stages that already hold the coordinates -- stage 1 before any dynamics, and each assessment phase --
rather than by a stage of its own, so a resumed run re-derives its snapshots instead of keeping stale ones.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from dashboard.execution.adapters import pdc_view

DIRECTORY = 'snapshots'
INDEX_NAME = 'snapshots.json'
#: The run's detergent moleculetype, written into the system stage and copied into every stage that simulates.
DETERGENT_TOPOLOGY = 'detergent_CG.itp'


def topology_path(stage: Path) -> Path | None:
    """The detergent moleculetype the run used: beside the stage, or in the run's other stages.

    A stage that simulates carries its own copy of the topology, and a phase that only judges carries none --
    measured: `3_assessment` and `5_assessment` run the snapshot script and write a picture of their phase, but the
    stage declaration copies `detergent_CG.itp` only into the stages that run dynamics, so a search of the stage
    alone would leave their pictures with no bonds in them. `None` is the answer when the run has none at all, and
    the picture then claims no bonds rather than being left to a viewer's guess.
    """
    stage = Path(stage)
    candidates = [stage / DETERGENT_TOPOLOGY, *sorted(stage.resolve().parent.glob(f'*/{DETERGENT_TOPOLOGY}'))]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def index(stage: Path) -> dict:
    path = Path(stage) / INDEX_NAME
    if path.is_file():
        return json.loads(path.read_text())
    return {'snapshots': [], 'note': 'derived: a resumed run re-derives these rather than keeping stale files'}


def sample_times(duration_ns: float, interval_ns: float, cap: int) -> list[float]:
    """The moments a trajectory is sampled at: the settings' cadence, capped, never past its end.

    The cadence is a setting rather than a constant so two runs' series are comparable by construction, which is the
    same reason the diagnostics heatmap has one colour scale.
    """
    if interval_ns <= 0:
        raise ValueError('the sampling interval must be positive')
    if cap < 1:
        raise ValueError('the sampling cap must be at least one')
    times, moment = [], float(interval_ns)
    while moment <= float(duration_ns) and len(times) < cap:
        times.append(round(moment, 6))
        moment += float(interval_ns)
    return times


def start_structure(stage: Path, start: Path | None = None) -> Path | None:
    """The structure a phase began from, for the rule that the initial state is always recorded.

    Measured: the assessment phase found its own `prod/start.gro` and the *extension* phase found nothing, because the
    restart path never writes that name -- it begins from the rebuilt system -- so the extension's series came back
    empty. A phase is now told what it started from, and `prod/start.gro` remains the fallback for the phase that
    writes it.
    """
    for candidate in (start, Path(stage) / 'prod' / 'start.gro'):
        if candidate is not None and Path(candidate).is_file():
            return Path(candidate)
    return None


def frames(stage: Path, trajectory: Path, tpr: Path, settings: dict, *, phase: str, gmx='gmx',
           label: str | None = None, start: Path | None = None) -> list[dict]:
    """One snapshot per sampled moment, each judged by the same function that decides the report's verdict.

    The frames come out of the trajectory with `trjconv -dump`: one call per moment asks GROMACS for that moment
    without writing a second trajectory, and the whole-system group is piped in because trjconv asks for one.
    """
    import subprocess

    from dashboard.execution.scripts import pdc_assess

    settings = dict(settings)
    duration = float(settings['assessment_ns' if phase == 'assessment' else 'extension_ns'])
    records = []
    for moment in sample_times(duration, float(settings.get('snapshot_interval_ns', 10.0)),
                               int(settings.get('snapshot_cap', 20))):
        name = f'{label or phase}_{moment:g}ps'
        structure = Path(stage) / DIRECTORY / f'{name}.gro'
        structure.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([gmx, 'trjconv', '-f', str(trajectory), '-s', str(tpr), '-dump', str(moment),
                        '-o', str(structure)], input='System\n', text=True, check=True)
        judged = pdc_assess.judge(structure, settings)
        verdict = judged['verdict']
        records.append(write_snapshot(stage, name, structure, detergent_residue=judged['detergent_residue'],
                                      time_ps=moment, title=f'{phase} at {moment:g} ps',
                                      criterion={'verdict': verdict['verdict'],
                                                 'largest_cluster': verdict['largest_cluster'],
                                                 'aggregation_number': verdict['aggregation_number'],
                                                 'fraction_of_requested': verdict['fraction_of_requested'],
                                                 'protein_contact_count': verdict['protein_contact_count'],
                                                 'reasons': verdict['reasons']}))
    if not records:
        # The design note's rule: the initial state is always recorded. A phase shorter than the cadence samples no
        # moment at all -- a 2 ns assessment on a 20 ns interval samples nothing -- and a phase with no picture in it
        # is indistinguishable from one whose series was never wired up.
        beginning = start_structure(stage, start)
        if beginning is not None:
            judged = pdc_assess.judge(beginning, settings)
            verdict = judged['verdict']
            records.append(write_snapshot(stage, f'{phase}_start', beginning, time_ps=0.0,
                                          detergent_residue=judged['detergent_residue'],
                                          title=f'{phase} start (shorter than the {settings.get("snapshot_interval_ns")} ns cadence)',
                                          criterion={'verdict': verdict['verdict'],
                                                     'largest_cluster': verdict['largest_cluster'],
                                                     'aggregation_number': verdict['aggregation_number'],
                                                     'fraction_of_requested': verdict['fraction_of_requested'],
                                                     'protein_contact_count': verdict['protein_contact_count'],
                                                     'reasons': verdict['reasons']}))
    return records


def main(argv=None) -> int:
    """The stage-facing entry point: dump this phase's frames and record them, criterion numbers and all."""
    import argparse

    from dashboard.execution.scripts import pdc_assess

    parser = argparse.ArgumentParser(description='Record snapshots through a phase trajectory.')
    parser.add_argument('--settings', default='../1_system/pdc-settings.json')
    parser.add_argument('--stage', default='.')
    parser.add_argument('--phase', choices=('assessment', 'extension'), required=True)
    parser.add_argument('--trajectory', required=True)
    parser.add_argument('--tpr', required=True)
    parser.add_argument('--start', default=None,
                        help='the structure this phase began from, when it is not `prod/start.gro`')
    parser.add_argument('--gmx', default='gmx')
    args = parser.parse_args(argv)

    stage = Path(args.stage)
    settings = pdc_assess.read_settings(args.settings)
    records = frames(stage, stage / args.trajectory, stage / args.tpr, settings, phase=args.phase, gmx=args.gmx,
                     start=stage / args.start if args.start else None)
    print(f'{len(records)} snapshots recorded for the {args.phase} phase')
    return 0


def write_snapshot(stage: Path, name: str, structure: Path, *, title: str, time_ps: float | None = None,
                   criterion: dict | None = None, detergent_residue: str = 'DDM',
                   include_water: bool = False) -> dict:
    """Write one PDB and add it to the stage's index, with the numbers the moment was judged on.

    The picture carries the model's own bonds: the run's detergent moleculetype is found beside the stage (or in the
    stage that wrote it) and its `[ bonds ]` and `[ constraints ]` are written as CONECT records, once per detergent
    molecule. Measured: without them a viewer guessed -- 90 bonds drawn on a frame the model bonds 60 ways -- so a
    topology that cannot be read is reported rather than passed over, and the file says what it is missing.
    """
    stage = Path(stage)
    structure = Path(structure)
    atoms = pdc_view.read_gro(structure)
    topology = None
    path = topology_path(stage)
    if path is not None:
        try:
            topology = pdc_view.read_moleculetype(path)
        except (OSError, ValueError) as error:
            # A derived picture is not worth failing a stage that has already done its work, and a file that names
            # no bonds is better than one that claims the wrong ones; the log and the REMARK both say so.
            print(f'pdc_snapshot: {path} could not be read for its bonds: {error}', file=sys.stderr)
    directory = stage / DIRECTORY
    directory.mkdir(exist_ok=True)
    target = directory / f'{name}.pdb'
    target.write_text(pdc_view.system_pdb(atoms, detergent_residue=detergent_residue,
                                          include_water=include_water, title=title, topology=topology))
    record = {'name': name, 'time_ps': time_ps, 'pdb': str(target.relative_to(stage)),
              'source': str(structure), 'source_sha256': hashlib.sha256(structure.read_bytes()).hexdigest(),
              'atoms': len(atoms), 'water_and_ions': include_water,
              'topology': str(path) if topology else None, 'verdict': criterion}
    document = index(stage)
    document['snapshots'] = [entry for entry in document['snapshots'] if entry.get('name') != name] + [record]
    (stage / INDEX_NAME).write_text(json.dumps(document, indent=2, sort_keys=True))
    return record


if __name__ == '__main__':
    raise SystemExit(main())
