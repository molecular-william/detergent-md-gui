"""The back-map stage's invocation, pinned now that CG2AT2 is vendored.

Nothing here runs a conversion — that needs a completed system, and the detergent's fragment coverage is unknown
until one exists. What is pinned is what the design spec decided and what the tool's own interface confirmed: the
align method, the Martini 3 fragment library, and `-silent`, without which the tool asks its questions on stdin and
a stage hangs instead of failing.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard.execution.adapters import pdc
from tests.dashboard.pdc_fixtures import prepared_run

BACKMAP = Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative).parent

TOOL = Path(__file__).resolve().parents[3] / 'tools' / 'cg2at' / 'cg2at'
TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'}],
}


def prepared(tmp_path: Path) -> Path:
    # Four detergents, as this file's own assertions are about; the stage is resolved by name, not by position.
    return prepared_run(tmp_path, settings={'aggregation_number': 4}, suffix=BACKMAP)


def test_the_back_map_uses_the_align_method_and_the_inputs_the_stage_built(tmp_path):
    """`-fg` and `-ff` name what `pdc_backmap.py` staged: the vendored library has no detergent fragment, and the stock
    force field has no types for one."""
    script = (prepared(tmp_path) / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative).name).read_text()
    executed = ' '.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert '-o align' in executed
    assert '-fg "$FRAGMENTS"' in executed and '-ff "$FORCEFIELD"' in executed
    assert 'pdc_backmap.py' in executed, 'the fragment, force field and gro are staged before the tool runs'
    assert 'backmap_inputs.json' in executed
    assert 'final_cg2at_aligned.pdb' in script, 'the stage still reports which build it produced'
    assert 'final_cg2at_de_novo.pdb' in script, 'and accepts the de-novo build, which is the one the tool completes'


def test_the_stage_never_lets_the_tool_ask_a_question(tmp_path):
    script = (prepared(tmp_path) / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative).name).read_text()
    executed = ' '.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert '-silent' in executed, 'without it CG2AT2 prompts, and a stage that prompts hangs'
    assert '-info' not in executed, '-info itself prompts for a fragment library'


def test_the_stage_names_the_tool_it_is_waiting_for_rather_than_failing_obscurely(tmp_path):
    script = (prepared(tmp_path) / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative).name).read_text()

    assert 'CG2AT="${CG2AT:-$PROJECT_ROOT/tools/cg2at/cg2at}"' in script
    assert 'export PROJECT_ROOT=' in script, 'a stage runs from its own directory; the tool lives at the repository root'
    assert 'not there' in script and 'exit 3' in script


def test_the_vendored_tool_is_where_the_stage_looks_for_it():
    """The clone the user asked for: the entry point exists and its own help answers."""
    assert TOOL.exists(), f'the vendored CG2AT2 is missing at {TOOL}'
    assert TOOL.is_symlink() or TOOL.is_file()


def protein_free(tmp_path: Path) -> Path:
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    run = tmp_path / 'empty-micelle'
    run.mkdir()
    pdc.prepare(run, protein_free=True, template='molecules/DDM/micelle_template.json',
                settings={'seed': 20260930, 'aggregation_number': 4}, project_root=tmp_path)
    return run / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative).parent


def test_a_protein_free_run_skips_the_back_map_and_says_why(tmp_path):
    """The back-map aligns a protein. A run with none has nothing to align, which is not a failure -- so the stage
    skips (exit 4, the contract's fourth outcome) and the run is free to complete.
    """
    import subprocess

    stage = protein_free(tmp_path)
    script = stage / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative).name
    result = subprocess.run(['bash', str(script)], cwd=stage, capture_output=True, text=True)

    assert result.returncode == 4, result.stderr
    assert json.loads((stage / 'skip.json').read_text())['skipped'] is True
    assert 'no protein' in json.loads((stage / 'skip.json').read_text())['reason']
    assert 'nothing to align' in result.stderr


# --- back-mapping is optional: a run that switched it off records `skipped` and carries on -----------------------

def prepared_with(tmp_path: Path, **settings) -> Path:
    """A prepared run with the run's own back-map setting, and the back-map stage directory it wrote."""
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    (molecule / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                settings={'seed': 20260930, 'aggregation_number': 4, **settings}, project_root=tmp_path)
    return run / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative).parent


def test_the_default_is_back_mapping_on(tmp_path):
    """Nothing existing moves: a run that says nothing back-maps the way every run did before the toggle."""
    stage = prepared_with(tmp_path)

    assert json.loads((stage.parent / '1_system' / pdc.SETTINGS_NAME).read_text())['backmap'] is True


def test_the_back_map_is_skipped_when_the_run_switched_it_off(tmp_path):
    """Switched off, the stage records the contract's `skipped` (exit 4) with its reason in `skip.json`, so the run
    still terminates `complete` -- the same outcome the protein-free case already uses."""
    import subprocess

    from dashboard.execution import workflow

    stage = prepared_with(tmp_path, backmap=False)
    script = stage / Path(pdc.stage_by_name('Back-mapping (CG2AT2)').relative).name
    result = subprocess.run(['bash', str(script)], cwd=stage, capture_output=True, text=True)

    assert result.returncode == workflow.SKIPPED_EXIT_CODE == 4, result.stderr
    record = json.loads((stage / 'skip.json').read_text())
    assert record['skipped'] is True
    assert 'back-map' in record['reason'].lower()
    assert 'back-map' in result.stderr.lower()
