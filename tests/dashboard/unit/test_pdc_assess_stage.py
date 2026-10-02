"""The micelle assessment stage: the system read, the criterion applied, the three outputs written.

These run `pdc_assess.main` against GRO files built here, so the stage's behaviour is checked without a simulation:
the grouping that tells eight detergents apart, the tail selection that decides what a contact even is, and the two
files a removal decision reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.execution.adapters import pdc
from dashboard.execution.scripts import pdc_assess

TEMPLATE = {
    'name': 'DDM',
    'residue': 'DDM',
    'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp',
    'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'},
              {'name': 'TAIL2', 'type': 'C1', 'role': 'tail'},
              {'name': 'HEAD', 'type': 'SN6', 'role': 'head'}],
}


def gro(path: Path, atoms, box=(5.0, 5.0, 5.0), title='system') -> Path:
    """A .gro whose residue numbers are the caller's, so molecules are distinguishable the way they are in a run."""
    lines = [title, str(len(atoms))]
    for index, (residue_id, residue, name, xyz) in enumerate(atoms, 1):
        lines.append(f'{residue_id:5d}{residue:<5}{name:>5}{index:5d}'
                     f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}')
    lines.append(''.join(f'{value:10.5f}' for value in box))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')
    return path


def detergent(residue_id: int, centre: float, *, head_at: float | None = None, residue='DDM'):
    """One detergent: two tail beads 0.1 nm apart, and a head bead where the caller puts it."""
    head = centre if head_at is None else head_at
    return [(residue_id, residue, 'TAIL1', (centre, 0.0, 0.0)),
            (residue_id, residue, 'TAIL2', (centre + 0.1, 0.0, 0.0)),
            (residue_id, residue, 'HEAD', (head, 1.0, 0.0))]


def protein(count: int = 3, at=(0.0, -2.0, 0.0)):
    return [(99, 'PRO', f'B{index + 1:02d}', (at[0] + index * 0.3, at[1], at[2])) for index in range(count)]


def staged(tmp_path: Path, atoms, **settings):
    """A prepared run's stage 3, with the given structure in place."""
    molecule = tmp_path / 'molecules' / 'DDM'
    molecule.mkdir(parents=True)
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    (molecule / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                settings={'seed': 20260930, 'aggregation_number': 2, **settings}, project_root=tmp_path)
    stage = run / Path(pdc.STAGES[2].relative).parent
    gro(stage / 'prod' / 'run.gro', atoms)
    return run, stage


def assess(stage: Path, run: Path, *extra):
    return pdc_assess.main(['--stage', str(stage), '--structure', 'prod/run.gro',
                            '--settings', str(run / '1_system' / pdc.SETTINGS_NAME), *extra])


def test_the_reader_tells_the_detergents_apart_by_residue_number(tmp_path):
    structure = gro(tmp_path / 'system.gro', protein() + detergent(1, 1.0) + detergent(2, 3.0))

    beads, molecules = pdc_assess.system_structure(structure, 'DDM')

    assert len(beads) == 3 and all(atom['residue'] == 'PRO' for atom in beads)
    assert [len(group) for group in molecules] == [3, 3]
    assert [group[0]['residue_id'] for group in molecules] == [1, 2]
    assert [atom['name'] for atom in molecules[0]] == ['TAIL1', 'TAIL2', 'HEAD']


def test_only_the_tail_beads_decide_a_contact(tmp_path):
    """Two detergents whose heads touch and whose tails do not are not a micelle."""
    atoms = protein() + detergent(1, 0.0, head_at=0.0) + detergent(2, 1.5, head_at=0.5)

    run, stage = staged(tmp_path, atoms)
    assert assess(stage, run) == 0
    record = json.loads((stage / pdc_assess.ASSESSMENT_NAME).read_text())

    assert record['verdict'] is False and record['largest_cluster'] == 1
    assert record['tail_beads'] == ['TAIL1', 'TAIL2']


def test_a_micelle_is_judged_and_what_survives_is_written(tmp_path):
    # A protein build needs the cluster to touch the protein, so the fixture's protein sits beside the micelle.
    atoms = protein(at=(0.0, -0.4, 0.0)) + detergent(1, 0.0) + detergent(2, 0.3) + detergent(3, 20.0)

    run, stage = staged(tmp_path, atoms, aggregation_number=2)
    assert assess(stage, run) == 0
    record = json.loads((stage / pdc_assess.ASSESSMENT_NAME).read_text())
    kept = (stage / pdc_assess.KEPT_NAME).read_text().splitlines()
    removed = json.loads((stage / pdc_assess.REMOVED_NAME).read_text())

    assert record['verdict'] is True and record['largest_cluster'] == 2
    assert record['detergents_present'] == 3 and record['protein_beads'] == 3
    assert record['structure_sha256'] == pdc_assess.digest(stage / 'prod' / 'run.gro')
    assert int(kept[1]) == 3 + 6, 'the protein beads and the two detergents that are in the micelle'
    assert removed['removed'] == [{'name': 'DDM3', 'residue_id': 3, 'beads': 3, 'tail_beads': 2}]
    assert removed['fraction_removed'] == pytest.approx(1 / 3, abs=1e-6)
    assert removed['kept'] == ['DDM1', 'DDM2']
    # The gallery's numbers are the verdict's numbers, because both came from the same call.
    from dashboard.execution.scripts import pdc_snapshot
    index = json.loads((stage / pdc_snapshot.INDEX_NAME).read_text())
    assert index['snapshots'][0]['verdict']['largest_cluster'] == record['largest_cluster']
    assert index['snapshots'][0]['verdict']['verdict'] == record['verdict']


def test_a_micelle_away_from_the_protein_is_not_judged_to_hold_it(tmp_path):
    atoms = protein(at=(0.0, -4.0, 0.0)) + detergent(1, 0.0) + detergent(2, 0.3) + detergent(3, 20.0)

    run, stage = staged(tmp_path, atoms, aggregation_number=2)
    assess(stage, run)
    record = json.loads((stage / pdc_assess.ASSESSMENT_NAME).read_text())

    assert record['largest_cluster'] == 2 and record['verdict'] is False
    assert any('comes within 0.6 nm of the protein' in reason for reason in record['reasons'])


def test_the_kept_structure_keeps_the_molecules_residues_and_the_box(tmp_path):
    atoms = protein(at=(0.0, -0.4, 0.0)) + detergent(1, 0.0) + detergent(2, 0.25) + detergent(3, 30.0)
    run, stage = staged(tmp_path, atoms, aggregation_number=2)

    assess(stage, run)
    kept = (stage / pdc_assess.KEPT_NAME).read_text().splitlines()

    assert kept[-1].split() == ['5.00000'] * 3, 'the box comes from the structure the stage assessed'
    body = kept[2:-1]
    assert [line[5:10].strip() for line in body].count('DDM') == 6
    residue_numbers = {line[0:5].strip() for line in body}
    assert {'1', '2'} <= residue_numbers, 'the kept detergents keep their own residue numbers'
    assert '99' in residue_numbers, 'and the protein keeps its own'


def test_the_criterion_refuses_a_run_that_never_named_its_tail_beads(tmp_path):
    run, stage = staged(tmp_path, protein() + detergent(1, 0.0) + detergent(2, 0.2))
    settings_path = run / '1_system' / pdc.SETTINGS_NAME
    settings = json.loads(settings_path.read_text())
    settings['tail_beads'] = []
    settings_path.write_text(json.dumps(settings))

    with pytest.raises(SystemExit, match='no tail beads'):
        assess(stage, run)


def test_a_structure_without_detergents_refuses_rather_than_judging_nothing(tmp_path):
    run, stage = staged(tmp_path, protein())

    with pytest.raises(SystemExit, match='holds no DDM beads'):
        assess(stage, run)


def test_the_template_declares_the_tail_beads_the_run_records(tmp_path):
    _, stage = staged(tmp_path, protein() + detergent(1, 0.0) + detergent(2, 0.2))
    settings = json.loads((stage.parent / '1_system' / pdc.SETTINGS_NAME).read_text())

    assert settings['tail_beads'] == ['TAIL1', 'TAIL2'], 'the role on the bead decides, not the name'


def test_both_assessment_stages_carry_the_same_script(tmp_path):
    run, _ = staged(tmp_path, protein() + detergent(1, 0.0) + detergent(2, 0.2))

    for stage in (pdc.STAGES[2], pdc.STAGES[4]):
        script = (run / stage.relative).read_text()
        executed = '\n'.join(line for line in script.splitlines() if not line.strip().startswith('#'))
        assert 'python pdc_assess.py' in executed
        assert 'pdc_assessment' not in executed, 'the criterion is not restated in the stage script'
        assert (run / Path(stage.relative).parent / 'pdc_assess.py').is_file()


def test_the_kept_structure_is_dry_because_the_restart_solvates_again(tmp_path):
    """Measured: it carried `W 5369` and `ION 128` beside three detergents.

    The restart's re-solvation then had nothing to fill -- the box was already full, and it added four water beads --
    while the dry topology the restart writes described a different system, so grompp refused the pair. The kept
    structure is the restart's input, and the restart supplies the solvent.
    """
    solvent = [(90, 'W', 'W', (1.0, 1.0, 1.0)), (91, 'ION', 'NA', (1.4, 1.0, 1.0))]
    atoms = protein(at=(0.0, -0.4, 0.0)) + solvent + detergent(1, 0.0) + detergent(2, 0.25) + detergent(3, 30.0)

    run, stage = staged(tmp_path, atoms, aggregation_number=2)
    assert assess(stage, run) == 0
    body = (stage / pdc_assess.KEPT_NAME).read_text().splitlines()[2:-1]
    names = {line[5:10].strip() for line in body}

    assert 'W' not in names and 'ION' not in names, 'the restart adds the solvent back itself'
    assert 'DDM' in names, 'the detergents that stay are the point of the file'
    assert '99' in {line[0:5].strip() for line in body}, 'and the protein stays, because the micelle is judged on it'
