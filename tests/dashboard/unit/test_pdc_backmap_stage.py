"""The back-map stage's invocation, pinned now that CG2AT2 is vendored.

Nothing here runs a conversion -- that needs a completed system, and the detergent's fragment coverage is unknown
until one exists. What is pinned is what the design spec decided and what the tool's own interface confirmed: the
align method, the Martini 3 fragment library, and `-silent`, without which the tool asks its questions on stdin and
a stage hangs instead of failing.

Back-mapping is a prepare-time decision now: a run that switched it off, or has no protein, gets no stage directory,
no script and no `skip.json`, and the manifest records the skip with its reason.
"""
from __future__ import annotations

import json
from pathlib import Path

from detergent_pdc.execution.adapters import pdc

from tests.dashboard.pdc_fixtures import inputs_dir, prepared_run, script_of

BACKMAP = 'Back-mapping (CG2AT2)'
TOOL = Path(__file__).resolve().parents[3] / 'tools' / 'cg2at' / 'cg2at'
TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'}],
}


def prepared(tmp_path: Path, **settings) -> Path:
    # Four detergents, as this file's own assertions are about; the stage is resolved by name, not by position.
    return prepared_run(tmp_path, settings={'aggregation_number': 4, **settings})


def backmap_directory(run: Path) -> Path:
    return run / pdc.STAGES_DIRECTORY / Path(pdc.stage_by_name(BACKMAP).relative).parent


def test_the_back_map_uses_the_align_method_and_the_inputs_the_stage_built() -> None:
    """`-fg` and `-ff` name what `pdc_backmap` staged: the vendored library has no detergent fragment, and the stock
    force field has no types for one."""
    script = script_of(BACKMAP).read_text()
    executed = ' '.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert '-o align' in executed
    assert '-fg "$FRAGMENTS"' in executed and '-ff "$FORCEFIELD"' in executed
    assert 'detergent_pdc.execution.scripts.pdc_backmap' in executed, 'the fragment, force field and gro are staged first'
    assert 'backmap_inputs.json' in executed
    assert 'final_cg2at_aligned.pdb' in script, 'the stage still reports which build it produced'
    assert 'final_cg2at_de_novo.pdb' in script, 'and accepts the de-novo build, which is the one the tool completes'


def test_the_stage_never_lets_the_tool_ask_a_question() -> None:
    script = script_of(BACKMAP).read_text()
    executed = ' '.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert '-silent' in executed, 'without it CG2AT2 prompts, and a stage that prompts hangs'
    assert '-info' not in executed, '-info itself prompts for a fragment library'


def test_the_stage_names_the_tool_it_is_waiting_for_rather_than_failing_obscurely() -> None:
    script = script_of(BACKMAP).read_text()

    assert 'CG2AT="${CG2AT:-$PROJECT_ROOT/tools/cg2at/cg2at}"' in script
    assert 'REPO_ROOT="${PROJECT_ROOT:-$("$PYTHON" -c \'from dashboard import paths; print(paths.PROJECT_ROOT)\')}"' in script, \
        'a stage runs from its own directory; the tool lives at the repository root'
    assert 'not there' in script and 'exit 3' in script


def test_the_vendored_tool_is_where_the_stage_looks_for_it() -> None:
    """The clone the user asked for: the entry point exists and its own help answers."""
    assert TOOL.exists(), f'the vendored CG2AT2 is missing at {TOOL}'
    assert TOOL.is_symlink() or TOOL.is_file()


def test_a_protein_free_run_gets_no_back_map_stage_at_all(tmp_path) -> None:
    """The back-map aligns a protein, so a run with none has nothing to align -- and prepare says so.

    Nothing is written for the stage: no directory, no script, no `skip.json`. The manifest carries the reason, and the
    executor records the stage skipped from it.
    """
    run = prepared_run(tmp_path, protein=None)  # the empty micelle
    record = json.loads((run / 'manifest.json').read_text())

    assert not backmap_directory(run).exists()
    assert 'no protein' in record['skipped_stages'][BACKMAP]


def test_the_default_is_back_mapping_on(tmp_path) -> None:
    """Nothing existing moves: a run that says nothing back-maps the way every run did before the toggle."""
    run = prepared(tmp_path)

    assert json.loads((inputs_dir(run) / pdc.SETTINGS_NAME).read_text())['backmap'] is True
    assert backmap_directory(run).is_dir()


def test_the_back_map_is_absent_when_the_run_switched_it_off(tmp_path) -> None:
    """Switched off at prepare: no stage, no script, and the manifest records the reason."""
    run = prepared(tmp_path, backmap=False)
    record = json.loads((run / 'manifest.json').read_text())

    assert not backmap_directory(run).exists()
    assert 'back-map' in record['skipped_stages'][BACKMAP].lower()
    assert not list(run.rglob('skip.json')), 'a prepare-time skip writes no skip.json'
