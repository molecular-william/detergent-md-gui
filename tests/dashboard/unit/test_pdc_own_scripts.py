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

from dashboard.execution.adapters import aa, cg, composition, osmotic
from detergent_pdc.execution.adapters import pdc

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


def test_every_pdc_stage_script_is_a_repository_file_of_this_workflow():
    """A stage runs a file under `dashboard/execution/scripts/`, recorded by path and digest -- never a copy.

    The three equilibration legs share one script body, because they are the same commands with the run's own
    numbers; every other stage has its own. Nothing is generated at prepare time any more, so this is the whole
    table: ten stages, one directory each, a `pdc_`-named repository script for each.
    """
    assert len({stage.relative for stage in pdc.STAGES}) == len(pdc.STAGES), 'one directory per stage'
    for stage in pdc.STAGES:
        script = Path(stage.script)
        assert script.parent.as_posix() == 'dashboard/execution/scripts', stage.script
        assert script.name.startswith('pdc_'), f'{stage.name} runs {script.name}, which is not this workflow\'s own'
        assert (SCRIPTS / script.name).is_file(), f'{stage.name} names {script.name} and there is no such script'


def test_the_legs_share_one_script_and_no_stage_reaches_another_workflows_file():
    shared = {stage.script for stage in pdc.STAGES}

    assert pdc.stage_by_name('Energy minimisation').script == pdc.stage_by_name('NVT equilibration').script
    assert pdc.stage_by_name('NVT equilibration').script == pdc.stage_by_name('NPT equilibration').script
    other = other_workflows_scripts()
    assert not (shared & other), f'pdc runs a script another workflow owns: {sorted(shared & other)}'
    assert not any(Path(stage.relative).name in other for stage in pdc.STAGES)


def test_no_stage_is_generated_at_prepare_time():
    """The scripts live in one place; there is no per-run text and no copy inside a run."""
    assert not hasattr(pdc, 'GENERATED_STAGES')
    assert not hasattr(pdc, '_STAGE_SOURCES')
    assert not hasattr(pdc, '_stamp_interpreter')
    assert not hasattr(pdc, '_stage_declared_inputs')
