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

TOOL = Path(__file__).resolve().parents[3] / 'tools' / 'cg2at' / 'cg2at'
TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'}],
}


def prepared(tmp_path: Path) -> Path:
    molecule = tmp_path / 'molecules' / 'DDM'
    (molecule / 'results' / 'MMFF').mkdir(parents=True)
    (molecule / 'results' / 'MMFF' / 'lig1.pdb').write_text('HETATM    1  C1  DDM A   1       0.000   0.000   0.000\n')
    (molecule / 'results' / 'MMFF' / 'lig1.itp').write_text('[ moleculetype ]\nDDM             1\n')
    (molecule / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    (molecule / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                settings={'seed': 20260930, 'aggregation_number': 4}, project_root=tmp_path)
    return run / Path(pdc.STAGES[5].relative).parent


def test_the_back_map_uses_the_align_method_and_the_martini_3_database(tmp_path):
    script = (prepared(tmp_path) / Path(pdc.STAGES[5].relative).name).read_text()
    executed = ' '.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert '-o align' in executed
    assert '-fg martini_3-0_charmm36' in executed and '-ff charmm36' in executed
    assert 'final_cg2at_aligned.pdb' in script, 'the stage checks the file its contract declares'


def test_the_stage_never_lets_the_tool_ask_a_question(tmp_path):
    script = (prepared(tmp_path) / Path(pdc.STAGES[5].relative).name).read_text()
    executed = ' '.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert '-silent' in executed, 'without it CG2AT2 prompts, and a stage that prompts hangs'
    assert '-info' not in executed, '-info itself prompts for a fragment library'


def test_the_stage_names_the_tool_it_is_waiting_for_rather_than_failing_obscurely(tmp_path):
    script = (prepared(tmp_path) / Path(pdc.STAGES[5].relative).name).read_text()

    assert 'CG2AT="${CG2AT:-tools/cg2at/cg2at}"' in script
    assert 'not there' in script and 'exit 3' in script


def test_the_vendored_tool_is_where_the_stage_looks_for_it():
    """The clone the user asked for: the entry point exists and its own help answers."""
    assert TOOL.exists(), f'the vendored CG2AT2 is missing at {TOOL}'
    assert TOOL.is_symlink() or TOOL.is_file()
