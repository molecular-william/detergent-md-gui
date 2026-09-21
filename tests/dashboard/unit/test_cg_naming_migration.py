"""Migration script correctness: idempotent, safe, reports manual lines."""
import importlib.util
from pathlib import Path

from tests.dashboard.fixtures import PROJECT_ROOT


MODULE_PATH = PROJECT_ROOT / 'dashboard/execution/scripts/migrate_cg_naming.py'


def _load():
    spec = importlib.util.spec_from_file_location('migrate_cg_naming', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SAMPLE = """#!/bin/bash
set -euxo pipefail
gmx grompp -f run.mdp -c mapped.gro -p topol.top -o mapped.tpr
ff_map -f ../1_AA-reference/prod/lig.xtc -m DDM_initial.itp -o mapped.xtc
ff_inter -itp DDM_initial.itp -fitted DDM.itp
gmx trjconv -f ../1_AA-reference/prod/lig.xtc -s ../1_AA-reference/prod/lig.tpr -o lig.xtc
ff_assess -mols DDM -itp DDM.itp
"""


def test_migrate_text_rewrites_literals_and_inserts_sentinel():
    """Pure-function test: no filesystem, deterministic, independent of order."""
    module = _load()
    migrated, report = module._migrate_text(SAMPLE)
    assert module.REF_DIR_LINE_MARKER in migrated
    assert '$INITIAL_ITP' in migrated
    assert '$FINAL_ITP' in migrated
    assert '../1_AA-reference/prod/' not in migrated
    assert 'DDM_initial.itp' not in migrated
    # Bare DDM (the -mols argument and the printf selectors) is reported, not rewritten.
    assert any('MANUAL:' in line for line in report), report


def test_migrate_text_is_idempotent():
    """Feeding already-migrated text produces no further text changes.

    The report may still contain MANUAL: lines because the migrator
    deliberately does not rewrite group selectors that require a human
    decision. Idempotency is about the emitted text, not the report.
    """
    module = _load()
    first, _ = module._migrate_text(SAMPLE)
    second, _ = module._migrate_text(first)
    assert second == first
    # Every surviving MANUAL line must also have been reported on the first pass.
    _, first_report = module._migrate_text(SAMPLE)
    _, second_report = module._migrate_text(first)
    manual_first = {line for line in first_report if 'MANUAL:' in line}
    manual_second = {line for line in second_report if 'MANUAL:' in line}
    assert manual_second <= manual_first


def test_apply_writes_backup_and_file(tmp_path):
    module = _load()
    script = tmp_path / 'fit_topology.sh'
    script.write_text(SAMPLE)
    applied = module._apply(script, apply=True)
    assert any('migrated' in line for line in applied)
    assert any('MANUAL:' in line for line in applied)
    text = script.read_text()
    assert module.REF_DIR_LINE_MARKER in text
    assert '$INITIAL_ITP' in text
    assert '$FINAL_ITP' in text
    assert (tmp_path / 'fit_topology.sh.pre-4.2.bak').read_text() == SAMPLE


def test_apply_is_idempotent_on_disk(tmp_path):
    module = _load()
    script = tmp_path / 'assess.sh'
    script.write_text(SAMPLE)
    module._apply(script, apply=True)
    first = script.read_text()
    again = module._apply(script, apply=True)
    assert again == [f'{script.name}: already migrated']
    assert script.read_text() == first


def test_check_reports_pending(tmp_path):
    module = _load()
    here = tmp_path
    for name in module.SCRIPTS:
        (here / name).write_text(SAMPLE)
    module.HERE = here
    assert module._check([here / name for name in module.SCRIPTS]) == 1
    for name in module.SCRIPTS:
        module._apply(here / name, apply=True)
    assert module._check([here / name for name in module.SCRIPTS]) == 0


def test_group_selector_line_is_reported_but_not_rewritten(tmp_path):
    """The two printf 'DDM' group selectors must survive the migrator verbatim."""
    module = _load()
    source = (
        "#!/bin/bash\n"
        "printf 'DDM\\nDDM\\n' | gmx trjconv -f md.xtc -o prod/lig_CG.xtc\n"
        "printf 'DDM\\n' | gmx convert-tpr -s md.tpr -o prod/lig_CG.tpr\n"
    )
    migrated, report = module._migrate_text(source)
    assert sum(1 for line in report if 'MANUAL: line' in line) == 2, report
    assert "printf 'DDM\\nDDM\\n'" in migrated
    assert "printf 'DDM\\n'" in migrated
    assert module.REF_DIR_LINE_MARKER in migrated
    # Applying the file preserves both lines unchanged.
    script = tmp_path / 'cg_simulation.sh'
    script.write_text(source)
    module._apply(script, apply=True)
    text = script.read_text()
    assert "printf 'DDM\\nDDM\\n'" in text
    assert "printf 'DDM\\n'" in text


def test_status_reports_migrated_after_apply_for_script_without_topology_literals(tmp_path):
    module = _load()
    script = tmp_path / 'sasa.sh'
    script.write_text("#!/bin/bash\necho hello\n")
    module._apply(script, apply=True)
    assert module.REF_DIR_LINE_MARKER in script.read_text()
    assert module._status(script) == 'migrated'


def test_apply_is_idempotent_for_script_without_topology_literals(tmp_path):
    module = _load()
    script = tmp_path / 'assess.sh'
    script.write_text("#!/bin/bash\necho hello\n")
    module._apply(script, apply=True)
    first = script.read_text()
    report = module._apply(script, apply=True)
    assert script.read_text() == first
    assert report == [f'{script.name}: already migrated']