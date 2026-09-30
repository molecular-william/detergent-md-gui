"""The removal decision: delete and restart, or nothing outside and continue.

Two paths, and the difference is a decision rather than a command, so both are exercised here through a stand-in for
`gmx`: the topology edit that a deletion needs, the restart mdps with new velocities, and the attempt record that
bounds the loop.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.execution.scripts import pdc_extension, pdc_solvate

TOPOLOGY = ('#include "protein_CG.itp"\n#include "detergent_CG.itp"\n\n[ system ]\nname\n\n[ molecules ]\n'
            'PROT\t1\nDDM\t8\n')
SETTINGS = {'seed': 20260930, 'attempts_max': 3, 'salt_molar': 0.15,
            'selection_threshold_fraction': 0.10, 'extension_ns': 900}


def test_the_molecule_rows_are_read_as_names_and_counts():
    assert pdc_extension.molecule_counts(TOPOLOGY) == [('PROT', 1), ('DDM', 8)]


def test_a_removal_takes_the_detergents_out_and_leaves_the_protein_alone():
    kept = pdc_extension.kept_topology(TOPOLOGY, 3, protein='PROT')

    assert pdc_extension.molecule_counts(kept) == [('PROT', 1), ('DDM', 5)]
    assert '#include "detergent_CG.itp"' in kept and '[ system ]' in kept


def test_a_removal_that_would_empty_the_detergent_is_refused():
    with pytest.raises(SystemExit, match='would leave 0 molecules'):
        pdc_extension.kept_topology(TOPOLOGY, 8, protein='PROT')


def test_a_topology_without_molecules_cannot_be_reduced():
    with pytest.raises(SystemExit, match='no \\[ molecules \\]'):
        pdc_extension.kept_topology('#include "x.itp"\n', 1)


def test_a_corrupt_attempt_file_reads_as_no_attempts_rather_than_failing_the_stage(tmp_path):
    assert pdc_extension.attempts(tmp_path) == []
    (tmp_path / pdc_extension.ATTEMPTS).write_text('{not json')
    assert pdc_extension.attempts(tmp_path) == []


class FakeGmx:
    """A stand-in for gmx: it records the commands and leaves behind the files the stage expects."""

    def __init__(self, stage: Path):
        self.stage = stage
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if '-deffnm' in command:
            base = command[command.index('-deffnm') + 1]
            (self.stage / f'{base}.gro').write_text('system\n0\n   1.00000   1.00000   1.00000\n')
            (self.stage / f'{base}.xtc').write_text('frames\n')
        return None


def staged(tmp_path: Path, decision: dict, settings: dict | None = None):
    stage = tmp_path / '4_extension'
    assessment = tmp_path / '3_assessment'
    previous = tmp_path / '2_assessment'
    for directory in (stage, assessment, previous / 'prod'):
        directory.mkdir(parents=True)
    (stage / 'extension.ps').write_text('900000\n')
    (stage / 'extension.mdp').write_text('dt = 0.02\ngen-vel = no\nnsteps = 1000\n')
    (stage / 'system.top').write_text(TOPOLOGY)
    (stage / 'system_EMPTY.top').write_text('[ molecules ]\nPROT\t1\n')
    (tmp_path / '1_system').mkdir()
    (tmp_path / '1_system' / 'pdc-settings.json').write_text(json.dumps({**SETTINGS, **(settings or {})}))
    (assessment / 'removed.json').write_text(json.dumps(decision))
    (assessment / 'kept.gro').write_text('system\n1\n    1PRO  B01    1   0.000   0.000   0.000\n'
                                         '   1.00000   1.00000   1.00000\n')
    for name in ('run.tpr', 'run.cpt', 'run.xtc', 'run.gro'):
        (previous / 'prod' / name).write_text('previous\n')
    return stage, assessment, previous


def arguments(stage: Path, assessment: Path, previous: Path) -> list[str]:
    return ['--stage', str(stage), '--assessment', str(assessment), '--assessment-stage', str(previous),
            '--settings', str(stage.parent / '1_system' / 'pdc-settings.json')]


def test_nothing_outside_the_micelle_continues_from_the_checkpoint(tmp_path, monkeypatch):
    stage, assessment, previous = staged(tmp_path, {'removed': [], 'fraction_removed': 0.0})
    fake = FakeGmx(stage)
    monkeypatch.setattr(pdc_extension.subprocess, 'run', fake)

    assert pdc_extension.main(arguments(stage, assessment, previous)) == 0

    convert = next(command for command in fake.commands if 'convert-tpr' in command)
    mdrun = next(command for command in fake.commands if 'mdrun' in command)
    assert convert[convert.index('-extend') + 1] == '900000'
    assert '-cpi' in mdrun and mdrun[mdrun.index('-cpi') + 1] == 'run.cpt'
    record = json.loads((stage / pdc_extension.ATTEMPTS).read_text())['attempts']
    assert record == [{'attempt': 1, 'removed': 0, 'removed_fraction': 0.0, 'mode': 'continued', 'seed': 20260930}]
    assert (stage / 'prod' / 'run.gro').is_file()


def test_something_outside_is_deleted_and_the_phase_restarts(tmp_path, monkeypatch):
    stage, assessment, previous = staged(tmp_path, {
        'removed': [{'name': 'DDM3', 'residue_id': 3, 'beads': 11, 'tail_beads': 3}],
        'stayed': ['DDM1', 'DDM2'], 'fraction_removed': 0.125, 'aggregation_number': 8})
    fake = FakeGmx(stage)
    monkeypatch.setattr(pdc_extension.subprocess, 'run', fake)
    solvated = {}
    monkeypatch.setattr(pdc_solvate, 'main', lambda argv: solvated.update({'argv': argv}) or 0)

    assert pdc_extension.main(arguments(stage, assessment, previous)) == 0

    assert pdc_extension.molecule_counts((stage / 'kept.top').read_text()) == [('PROT', 1), ('DDM', 7)]
    assert pdc_extension.molecule_counts((stage / 'system.top').read_text()) == [('PROT', 1), ('DDM', 7)]
    assert solvated['argv'][-1] == '0.15' and str(assessment / 'kept.gro') in solvated['argv']

    restart = (stage / pdc_extension.RESTART_MDP).read_text()
    assert 'gen-vel = yes' in restart and 'gen-seed = 20260931' in restart, 'a retry changes only the velocities'
    assert not any('convert-tpr' in command for command in fake.commands), 'a deletion cannot continue a checkpoint'
    mdrun = [command for command in fake.commands if 'mdrun' in command]
    assert mdrun[-1][mdrun[-1].index('-deffnm') + 1] == 'prod/run'

    record = json.loads((stage / pdc_extension.ATTEMPTS).read_text())['attempts']
    assert record[0]['mode'] == 'restarted' and record[0]['removed'] == 1
    assert record[0]['above_threshold'] is True and record[0]['seed'] == 20260931


def test_the_loop_is_bounded_and_says_why_it_stopped(tmp_path, monkeypatch):
    stage, assessment, previous = staged(tmp_path, {'removed': [{'name': 'DDM3'}], 'fraction_removed': 0.2})
    (stage / pdc_extension.ATTEMPTS).write_text(json.dumps({'attempts': [{'attempt': 1}, {'attempt': 2},
                                                                         {'attempt': 3}]}))
    monkeypatch.setattr(pdc_extension.subprocess, 'run', FakeGmx(stage))

    with pytest.raises(SystemExit, match='3 attempts already used'):
        pdc_extension.main(arguments(stage, assessment, previous))
