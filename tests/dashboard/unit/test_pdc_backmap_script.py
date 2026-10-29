"""A stage script resolves the repository, not its own directory.

Back-mapping refused with exit 3 -- `back-mapping needs CG2AT2 under tools/ (D1); tools/cg2at/cg2at is not there` -- while
that symlink sat exactly where the repository root says it is. A stage script runs from `runs/<id>/stages/10_backmap`, so
a relative default `tools/cg2at/cg2at` named a path inside the run, and `-e` was false. The script is a repository file
now, so it derives the root from its own location (`dashboard/execution/scripts/` is three levels under it) and a caller
that exports `PROJECT_ROOT` still wins.
"""

from tests.dashboard.support import PACKAGE

TEMPLATE = PACKAGE / 'execution/scripts/pdc_backmap.sh'
ROOT_LINE = 'REPO_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"'


def text() -> str:
    return TEMPLATE.read_text()


def test_the_root_the_script_resolves_against_is_the_repository() -> None:
    script = text()

    assert ROOT_LINE in script
    assert 'export PROJECT_ROOT="$REPO_ROOT"' in script
    assert 'export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"' in script


def test_an_override_kept_by_the_caller_wins() -> None:
    assert '${PROJECT_ROOT:-' in text(), 'a caller that exports PROJECT_ROOT is not overridden'


def test_the_backmap_script_resolves_the_tool_under_that_root() -> None:
    """The default it carries is the one the stage executes."""
    script = text()

    assert 'CG2AT="${CG2AT:-$PROJECT_ROOT/tools/cg2at/cg2at}"' in script
    assert 'CG2AT="${CG2AT:-tools/cg2at/cg2at}"' not in script, 'a relative default is what exit 3 was'
    assert 'CG2AT' in script and 'exit 3' in script, 'a missing tool still fails by name, with the override named'


def test_the_invocation_names_every_flag_that_would_otherwise_prompt() -> None:
    """Each of these was measured as a prompt, not an error, on a stage with no terminal."""
    script = text()

    assert '-ff charmm36-mar2019-updated' in script, 'charmm36 is not a name in the database; jul2022 has no merged.rtp'
    assert '-w tip3p' in script, 'the water model is asked for when it is left out'
    assert '< /dev/null' in script, 'a prompt must fail at once rather than wait for an answer that cannot come'


def test_the_structure_handed_over_is_a_gro_so_the_box_travels_with_it() -> None:
    """A gro carries its own box line, so there is no CRYST1 to write and no `-box` to get wrong.

    The shape matters for a second reason: the tool rewrites whatever it is given to PDB, and the bead names have to
    survive that round trip, which is why the stage hands over a *renamed* gro rather than a pdb from `gmx editconf`.
    """
    script = text()
    executed = ' '.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert 'STRUCTURE=cg2at_input.gro' in executed
    assert '-c "$STRUCTURE"' in executed
    assert 'editconf' not in executed, 'no pdb round trip to carry the box through'
    assert 'pdc_backmap' in executed, 'the renamed gro is what that helper writes'


def test_the_stage_clears_the_conversion_it_is_about_to_redo() -> None:
    """A leftover topology and structure are one system only with each other; a re-run must not inherit them."""
    script = text()
    executed = ' '.join(line for line in script.splitlines() if not line.strip().startswith('#'))

    assert 'rm -rf FINAL' in executed
    assert executed.index('rm -rf FINAL') < executed.index('STRUCTURE=cg2at_input.gro'), 'before anything is staged'


def test_the_alignment_uses_the_protonated_reference_when_there_is_one() -> None:
    script = text()

    assert '../01_prepare/protein_prepared.pdb' in script and '-a cg2at_atomistic.pdb' in script
    assert 'missing atoms' in script, 'the reason is written down: pdb2gmx refuses the heavy-atom-only file'
