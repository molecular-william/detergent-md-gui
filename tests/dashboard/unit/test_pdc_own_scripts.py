"""Every script a pdc stage runs is this workflow's own, or one nothing else names.

Measured before this change: the protein-detergent stages ran three scripts that were pdc's own work carried under
the CG half's generic naming -- `assessment.sh`, `extension.sh`, `backmap.sh` -- and the two assessment stages ran a
stage script literally called `assess.sh`, which is the file name of the CG adapter's own `5_assessment/assess.sh`
and of composition.py's `2_CG-assessment/assess.sh`. No other adapter named the three by file, so no run moved
*today*; what a name another workflow owns buys is that tomorrow's change for one workflow moves a run in the other.

So the check is a measurement rather than a list of names: the other run types' stage declarations are read here and
the intersection with what pdc's stages run is asserted empty, and every pdc stage script that is a file carries the
workflow's own `pdc_` prefix.
"""
from __future__ import annotations

from pathlib import Path

from dashboard.execution.adapters import aa, cg, composition, osmotic, pdc

SCRIPTS = Path(pdc.__file__).resolve().parents[1] / 'scripts'


def other_workflows_scripts() -> set[str]:
    """Every script file name the other run types' own stage plans name."""
    named = set()
    for module in (cg, aa, composition, osmotic):
        for stage in getattr(module, 'STAGE_DEFS', ()):
            named.add(Path(str(stage.relative)).name)
    return named


def test_no_script_a_pdc_stage_names_is_named_by_another_workflow():
    ours = {Path(stage.relative).name for stage in pdc.STAGES}
    shared = sorted(ours & other_workflows_scripts())

    assert shared == [], f'these scripts belong to another workflow as well: {shared}'


def test_every_pdc_stage_script_that_is_a_file_carries_the_workflows_own_name():
    generated = {Path(relative).name for relative in pdc.GENERATED_STAGES}

    for stage in pdc.STAGES:
        name = Path(stage.relative).name
        if name in generated:
            continue
        assert name.startswith('pdc_'), f'{stage.name} runs {name}, which is not this workflow\'s own script'
        assert (SCRIPTS / name).is_file(), f'{stage.name} names {name} and there is no such script'


def test_the_scripts_the_workflow_used_to_run_under_another_halves_naming_are_gone():
    """A file named for the CG half's convention, left in the shared directory and run by nothing, is the trap: a
    change made "for CG" that quietly moves a pdc run. Each of the three became a `pdc_`-prefixed script."""
    for name in ('assessment.sh', 'extension.sh', 'backmap.sh'):
        assert not (SCRIPTS / name).is_file(), f'{name} is still there, and no stage runs it'


def test_the_generated_stage_scripts_are_the_one_place_a_stage_is_written_rather_than_copied():
    """Stage 1's script has to carry the interpreter the run was prepared with, and the legs are the same three
    commands with the run's own numbers in them. Everything else is a file, and this pins which is which."""
    generated = {relative for relative in pdc.GENERATED_STAGES}

    assert generated <= {stage.relative for stage in pdc.STAGES}
    for relative in pdc.STAGES:
        if relative.relative in generated:
            assert relative.relative not in pdc._STAGE_SOURCES, f'{relative.name} is generated, not copied'
        else:
            assert pdc._STAGE_SOURCES[relative.relative] == Path(relative.relative).name
