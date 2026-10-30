"""The readers understand a protein-detergent run in the numbered layout, and still read the legacy spelling.

A current pdc run writes `stages/01_prepare` … `stages/10_backmap`, one directory per stage, and records a stage it
decided not to run in the manifest's `skipped_stages` with no directory at all. Two runs in this workspace still hold
the old root-level names (`1_system`, `4_extension`, …), so the same readers have to answer both shapes through one
resolver -- and a skipped stage has to read as "the run decided not to do this, because …" rather than as a hole in
the timeline.
"""
from __future__ import annotations

from pathlib import Path

from dashboard import files
from dashboard.analysis.runs import layout, segments
from detergent_pdc import layout as pdc_layout

GRO = 'system {count}\n{count:5d}\n    1DET      R1     1   0.100   0.200   0.300\n   8.00000   8.00000   8.00000\n'


def write(path: Path, text: str = '', size: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text else 'x' * size)
    return path


def manifest(root: Path, **fields) -> Path:
    path = root / 'manifest.json'
    files.atomic_json(path, {'run_type': 'pdc', 'status': 'completed', 'stages': [], **fields})
    return path


def numbered_run(root: Path) -> Path:
    """A run shaped like the numbered layout: ten stage directories, one system rebuilt at the assessment boundary."""
    write(root / 'stages/02_system/system.gro', GRO.format(count=8))
    write(root / 'stages/02_system/detergent_CG.itp', '[ moleculetype ]\nDET 1\n')
    write(root / 'stages/02_system/cg/molecule_0.itp', '[ moleculetype ]\nPRO 1\n')
    write(root / 'stages/03_minimisation/system.gro', GRO.format(count=40))
    write(root / 'stages/04_nvt/system.gro', GRO.format(count=40))
    write(root / 'stages/04_nvt/system.xtc', size=120)
    write(root / 'stages/05_npt/system.gro', GRO.format(count=40))
    write(root / 'stages/05_npt/system.xtc', size=140)
    write(root / 'stages/06_assessment/prod/run.gro', GRO.format(count=40))
    write(root / 'stages/06_assessment/prod/whole.xtc', size=160)
    write(root / 'stages/07_micelle_assessment/kept.gro', GRO.format(count=32))
    write(root / 'stages/07_micelle_assessment/assessment.json', '{}')
    write(root / 'stages/08_extension/prod/run.gro', GRO.format(count=32))
    write(root / 'stages/08_extension/prod/whole.xtc', size=180)
    write(root / 'stages/08_extension/prod/run.xtc', size=90)
    write(root / 'stages/09_final_assessment/prod/run.gro', GRO.format(count=32))
    write(root / 'stages/09_final_assessment/assessment.json', '{}')
    write(root / 'stages/10_backmap/FINAL/FINAL/final_cg2at_neutral.pdb', 'ATOM      1  BB  PRO A   1\nEND\n')
    manifest(root)
    return root


def legacy_run(root: Path) -> Path:
    """The spelling the two runs written before the numbering keep, at the run root."""
    write(root / '1_system/system.gro', GRO.format(count=8))
    write(root / '1_system/detergent_CG.itp', '[ moleculetype ]\nDET 1\n')
    write(root / '1_system/cg/molecule_0.itp', '[ moleculetype ]\nPRO 1\n')
    write(root / '2_minimisation/system.gro', GRO.format(count=40))
    write(root / '3_nvt/system.gro', GRO.format(count=40))
    write(root / '3_nvt/system.xtc', size=120)
    write(root / '4_npt/system.gro', GRO.format(count=40))
    write(root / '4_npt/system.xtc', size=140)
    write(root / '2_assessment/prod/run.gro', GRO.format(count=40))
    write(root / '2_assessment/prod/whole.xtc', size=160)
    write(root / '3_assessment/kept.gro', GRO.format(count=32))
    write(root / '4_extension/prod/run.gro', GRO.format(count=32))
    write(root / '4_extension/prod/whole.xtc', size=180)
    write(root / '4_extension/prod/run.xtc', size=90)
    write(root / '5_assessment/prod/run.gro', GRO.format(count=32))
    write(root / '5_assessment/prod/run.xtc', size=90)
    write(root / '6_backmap/FINAL/FINAL/final_cg2at_neutral.pdb', 'ATOM      1  BB  PRO A   1\nEND\n')
    manifest(root)
    return root


def test_the_stage_root_is_stages_when_the_run_has_it_and_the_run_root_otherwise(tmp_path):
    numbered, legacy = numbered_run(tmp_path / 'numbered'), legacy_run(tmp_path / 'legacy')

    assert layout.stage_root(numbered) == numbered / 'stages'
    assert layout.stage_root(legacy) == legacy
    assert layout.stage_dir(numbered, 'extension') == numbered / 'stages/08_extension'
    assert layout.stage_dir(legacy, 'extension') == legacy / '4_extension'


def test_a_numbered_run_resolves_its_topology_trajectory_and_segments(tmp_path):
    root = numbered_run(tmp_path)

    assert pdc_layout.topology(root) == root / 'stages/02_system/detergent_CG.itp'
    assert layout.coarse_topology(root, 'pdc').name == 'detergent_CG.itp'

    trajectory, structure, role = layout.frame_source(root)
    assert role == 'pdc_trajectory'
    assert trajectory == root / 'stages/08_extension/prod/whole.xtc'
    assert structure == root / 'stages/08_extension/prod/run.gro'

    answer = segments.segments(root, 'pdc')
    by_name = {entry['name']: entry for entry in answer['segments']}
    assert list(by_name) == ['System preparation', 'Energy minimisation', 'NVT equilibration', 'NPT equilibration',
                             'CG assessment MD', 'Micelle assessment', 'CG extension MD', 'Final assessment',
                             'Back-mapping (CG2AT2)'], list(by_name)
    with_trajectory = {name for name, entry in by_name.items() if entry.get('trajectory')}
    assert with_trajectory == {'NVT equilibration', 'NPT equilibration', 'CG assessment MD', 'CG extension MD'}
    # Run-relative paths carry the `stages/` prefix: that is the spelling the artifact and structure routes take.
    assert by_name['CG extension MD']['trajectory'] == 'stages/08_extension/prod/whole.xtc'
    assert by_name['CG assessment MD']['trajectory'] == 'stages/06_assessment/prod/whole.xtc'
    assert by_name['Micelle assessment']['structure'] == 'stages/07_micelle_assessment/kept.gro'
    assert by_name['Back-mapping (CG2AT2)']['structure'] == \
        'stages/10_backmap/FINAL/FINAL/final_cg2at_neutral.pdb'


def test_a_numbered_runs_stage_root_is_what_the_built_system_route_reads(tmp_path):
    root = numbered_run(tmp_path)

    stage_root = layout.stage_root(root)

    assert layout.stage_path(stage_root, 'system', 'system.gro') == \
        root / 'stages/02_system/system.gro'


def test_a_legacy_run_still_resolves_the_same_roles_and_segments(tmp_path):
    root = legacy_run(tmp_path)

    assert pdc_layout.topology(root).name == 'detergent_CG.itp'
    trajectory, structure, role = layout.frame_source(root)
    assert role == 'pdc_trajectory'
    assert trajectory == root / '4_extension/prod/whole.xtc' and structure == root / '4_extension/prod/run.gro'

    by_name = {entry['name']: entry for entry in segments.segments(root, 'pdc')['segments']}
    assert by_name['CG assessment MD']['trajectory'] == '2_assessment/prod/whole.xtc'
    assert by_name['CG extension MD']['trajectory'] == '4_extension/prod/whole.xtc'
    assert by_name['Final assessment']['duplicate_of'] == 'CG extension MD'
    assert by_name['Back-mapping (CG2AT2)']['structure'] == '6_backmap/FINAL/FINAL/final_cg2at_neutral.pdb'


def test_a_skipped_extension_and_final_assessment_read_as_skipped_not_missing(tmp_path):
    root = numbered_run(tmp_path)
    # The prepare-time decision: no `07_micelle_assessment/`, `08_extension/` or `09_final_assessment/` directory
    # was written at all.
    for relative in ('stages/07_micelle_assessment', 'stages/08_extension', 'stages/09_final_assessment'):
        for path in sorted((root / relative).rglob('*'), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        (root / relative).rmdir()
    manifest(root, skipped_stages={
        'Micelle assessment': 'the run switched out-of-micelle removal off, so there is no assessment to make',
        'CG extension MD': 'the run switched out-of-micelle removal off, so there is nothing to extend or assess',
        'Final assessment': 'the run switched out-of-micelle removal off, so there is nothing to extend or assess',
    })

    by_name = {entry['name']: entry for entry in segments.segments(root, 'pdc')['segments']}

    for name in ('Micelle assessment', 'CG extension MD', 'Final assessment'):
        assert name in by_name, f'{name} is recorded as skipped, so it must not look absent'
        assert by_name[name]['structure'] is None and by_name[name]['trajectory'] is None
        assert 'out-of-micelle removal off' in by_name[name]['skipped']
        assert by_name[name]['note'].startswith('skipped:')
    assert 'CG assessment MD' in by_name and by_name['CG assessment MD']['trajectory'], \
        'the production that did run is still playable'
