import json
import shutil
from pathlib import Path

import pytest

from dashboard.execution import workflow
from dashboard.models.molecules import aa as aa_molecules
from tests.dashboard.support import PROJECT_ROOT


def test_generic_input_dependencies_and_aa_capability(tmp_path):
    source=PROJECT_ROOT/'molecules/DDM'
    folder=tmp_path/'Example'; shutil.copytree(source,folder)
    folder=folder/'results/MMFF'
    original=(folder/'lig1.itp').read_text()
    (folder/'parts').mkdir(); (folder/'parts/body.itp').write_text(original)
    (folder/'lig1.itp').write_text('#include "parts/body.itp"\n')
    snapshot=aa_molecules.selection(tmp_path,'Example',run_type='aa_only')
    assert 'results/MMFF/parts/body.itp' in snapshot['sha256']
    assert snapshot['adapter']=='aa-charmm36'
    (folder/'lig1.itp').write_text('#include "../outside.itp"\n')
    with pytest.raises(ValueError,match='include|traversal'):
        aa_molecules.selection(tmp_path,'Example',run_type='aa_only')


def test_aa_preparation_has_only_aa_stages_and_consistent_temperature(tmp_path,monkeypatch):
    from dashboard.execution.adapters import aa
    molecule_root=PROJECT_ROOT/'molecules'
    selected=aa_molecules.selection(molecule_root,'DDM',run_type='aa_only')
    monkeypatch.setattr(aa,'tool_metadata',lambda:{'gmx':{'path':'gmx','version_output':'test'}})
    aa.prepare_run(tmp_path,molecule_root,selected,{'temperature_k':315,'aa_nvt_ps':1,'aa_npt_ps':1,'aa_production_ps':2,'output_interval_ps':1})
    data=json.loads((tmp_path/'manifest.json').read_text())
    assert data['run_type']=='aa_only'
    assert len(data['stage_plan'])==7
    assert not (tmp_path/'stages/2_mapping').exists()
    nvt=(tmp_path/'stages/04_nvt/run.mdp').read_text()
    assert 'gen-temp = 315' in nvt and 'ref-t = 315' in nvt
    assert 'gen-seed = 20260917' in nvt
    npt=(tmp_path/'stages/05_npt/run.mdp').read_text()
    assert 'gen-vel = no' in npt and 'continuation = yes' in npt
    minimization=(tmp_path/'stages/03_minimization/run.sh').read_text()
    assert '-gpu_id 0 -nb gpu -pin on' in minimization
    assert '-pme gpu' not in minimization and '-pmefft gpu' not in minimization
    for stage in ('04_nvt', '05_npt', '06_production'):
        script=(tmp_path/'stages'/stage/'run.sh').read_text()
        assert '-gpu_id 0 -nb gpu -pin on' in script
        assert '-pme gpu' in script and '-pmefft gpu' in script
    assert workflow.resumable_stages(tmp_path)==[aa.STAGES[0][0]]


def test_aa_settings_do_not_require_cg_duration():
    from dashboard.execution.adapters import aa
    settings=aa.normalize_settings({'aa_production_ps':100,'output_interval_ps':50})
    assert settings['output_interval_ps']==50
    with pytest.raises(ValueError):aa.normalize_settings({'cg_production_ps':1})
    with pytest.raises(ValueError):aa.normalize_settings({'box_padding_nm':1})


def test_aa_resume_uses_server_stages_and_rejects_changed_upstream(tmp_path,monkeypatch):
    import subprocess

    from dashboard import files
    from dashboard.execution.adapters import aa
    root=tmp_path/'source';root.mkdir();(root/'logs').mkdir()
    molecules=PROJECT_ROOT/'molecules'
    selected=aa_molecules.selection(molecules,'DDM',run_type='aa_only')
    monkeypatch.setattr(aa,'tool_metadata',lambda:{})
    aa.prepare_run(root,molecules,selected)
    data=json.loads((root/'manifest.json').read_text());data['stage_plan']=['untrusted script path']
    files.atomic_json(root/'manifest.json',data)
    def execute(command,**kwargs):
        assert Path(command[-1]).parent.name=='01_solvation'
        (Path(kwargs['cwd'])/'system.gro').write_text('completed solvation output')
        return subprocess.CompletedProcess(command,0)
    workflow.run(root,root/'logs/console.log',execute=execute,stop_after=aa.STAGES[0][0])
    assert workflow.resumable_stages(root)==[name for name,_ in aa.STAGES[:2]]
    recorded=json.loads((root/'manifest.json').read_text())['stages'][0]['outputs_sha256']
    assert all(not name.endswith(('run.sh', 'run.mdp')) for name in recorded)
    stage_script=root/'stages/01_solvation/run.sh'
    stage_script.write_text(stage_script.read_text()+'\n# regenerated launcher\n')
    target=tmp_path/'resumed';target.mkdir()
    workflow.prepare_resume(target,root,aa.STAGES[1][0])
    metadata=json.loads((target/'manifest.json').read_text())
    assert metadata['stages'][0]['status']=='reused'
    assert all(not name.endswith('run.sh') for name in metadata['stages'][0]['outputs_sha256'])
    assert (target/'stages/01_solvation/system.gro').read_text()=='completed solvation output'
    assert '# regenerated launcher' not in (target/'stages/01_solvation/run.sh').read_text()
    (root/'stages/01_solvation/system.gro').write_text('tampered')
    bad=tmp_path/'bad';bad.mkdir()
    with pytest.raises(ValueError,match='changed'):
        workflow.prepare_resume(bad,root,aa.STAGES[1][0])
