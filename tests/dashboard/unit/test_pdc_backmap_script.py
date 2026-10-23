"""A stage script resolves the repository, not its own directory.

Back-mapping refused with exit 3 -- `back-mapping needs CG2AT2 under tools/ (task D1); tools/cg2at/cg2at is not there` -- while
that symlink sat exactly where the repository root says it is. A stage script runs from `runs/<id>/6_backmap`, so the
relative default `tools/cg2at/cg2at` named a path inside the run, and `-e` was false. The script now takes the root the
adapter stamps into it, in the same place and by the same mechanism as the interpreter and `PYTHONPATH`.
"""
from pathlib import Path

from dashboard.execution.adapters import pdc

ROOT = Path('/srv/detergent-md-gui')
TEMPLATE = Path(__file__).resolve().parents[3] / 'dashboard/execution/scripts/pdc_backmap.sh'


def stamped(tmp_path, body):
    script = tmp_path / 'pdc_backmap.sh'
    script.write_text(body)
    pdc._stamp_interpreter(script, ROOT)
    return script.read_text()


def test_the_root_the_script_resolves_against_is_this_repository(tmp_path):
    text = stamped(tmp_path, '#!/bin/bash\nset -euxo pipefail\nCG2AT="${CG2AT:-$PROJECT_ROOT/tools/cg2at/cg2at}"\n')

    assert f'export PROJECT_ROOT=${{PROJECT_ROOT:-{ROOT}}}' in text
    assert text.index('export PROJECT_ROOT=') < text.index('set -euxo pipefail')


def test_an_override_kept_by_the_caller_wins(tmp_path):
    text = stamped(tmp_path, '#!/bin/bash\nset -euxo pipefail\n')

    assert '${PROJECT_ROOT:-' in text, 'a caller that exports PROJECT_ROOT is not overridden'


def test_a_script_that_already_states_the_root_is_left_alone(tmp_path):
    body = '#!/bin/bash\nexport PROJECT_ROOT=/elsewhere\nset -euxo pipefail\n'

    assert stamped(tmp_path, body).count('PROJECT_ROOT=') == 1


def test_the_invocation_names_every_flag_that_would_otherwise_prompt(tmp_path):
    """Each of these was measured as a prompt, not an error, on a stage with no terminal."""
    text = stamped(tmp_path, TEMPLATE.read_text())

    assert '-ff charmm36-mar2019-updated' in text, 'charmm36 is not a name in the database; jul2022 has no merged.rtp'
    assert '-w tip3p' in text, 'the water model is asked for when it is left out'
    assert '< /dev/null' in text, 'a prompt must fail at once rather than wait for an answer that cannot come'


def test_the_structure_handed_over_is_a_gro_so_the_box_travels_with_it(tmp_path):
    """A gro carries its own box line, so there is no CRYST1 to write and no `-box` to get wrong.

    The shape matters for a second reason: the tool rewrites whatever it is given to PDB, and the bead names have to
    survive that round trip, which is why the stage hands over a *renamed* gro rather than a pdb from `gmx editconf`.
    """
    text = stamped(tmp_path, TEMPLATE.read_text())
    executed = ' '.join(line for line in text.splitlines() if not line.strip().startswith('#'))

    assert 'STRUCTURE=cg2at_input.gro' in executed
    assert '-c "$STRUCTURE"' in executed
    assert 'editconf' not in executed, 'no pdb round trip to carry the box through'
    assert 'pdc_backmap.py' in executed, 'the renamed gro is what that helper writes'


def test_the_stage_clears_the_conversion_it_is_about_to_redo(tmp_path):
    """A leftover topology and structure are one system only with each other; a re-run must not inherit them."""
    text = stamped(tmp_path, TEMPLATE.read_text())
    executed = ' '.join(line for line in text.splitlines() if not line.strip().startswith('#'))

    assert 'rm -rf FINAL' in executed
    assert executed.index('rm -rf FINAL') < executed.index('STRUCTURE=cg2at_input.gro'), 'before anything is staged'


def test_the_alignment_uses_the_protonated_reference_when_there_is_one(tmp_path):
    text = stamped(tmp_path, TEMPLATE.read_text())

    assert '../0_prepare/protein_prepared.pdb' in text and '-a cg2at_atomistic.pdb' in text
    assert 'missing atoms' in text, 'the reason is written down: pdb2gmx refuses the heavy-atom-only file'


def test_the_backmap_template_resolves_the_tool_under_that_root(tmp_path):
    """The template is the thing copied into a run, so the default it carries is the one the stage executes."""
    text = stamped(tmp_path, TEMPLATE.read_text())

    assert 'CG2AT="${CG2AT:-$PROJECT_ROOT/tools/cg2at/cg2at}"' in text
    assert 'CG2AT="${CG2AT:-tools/cg2at/cg2at}"' not in text, 'a relative default is what exit 3 was'
    assert 'CG2AT' in text and 'exit 3' in text, 'a missing tool still fails by name, with the override named'
