"""Versioned single-solute CHARMM AA protocol, independent of CG tooling."""
from pathlib import Path
import datetime
import json
import math
import shutil
import subprocess
from ...models.molecules import aa as aa_molecules
from ... import files
from ...analysis.runs import references as aa_references
from ..environment import FORCE_FIELD, environment, probe_tool
from .. import tools
from ..stages import Stage, stage_tables
from .. import protocol

# Modules copied into every run's common/ directory. The names are part of the
# run contract, not a detail: the generated stage scripts invoke
# ../common/aa_references.py, and the copied publication helper imports
# aa_molecules by module name. Copying each module under its own __file__ name
# silently breaks both whenever a module moves.
RUN_HELPERS = (('aa_references.py', aa_references),
               ('aa_molecules.py', aa_molecules),
               ('files.py', files))

VERSION='charmm36-single-solute-v1'
MDRUN_GPU_NONBONDED_FLAGS='-gpu_id 0 -nb gpu -pin on'
MDRUN_GPU_PME_FLAGS=f'{MDRUN_GPU_NONBONDED_FLAGS} -pme gpu -pmefft gpu'


STAGE_DEFS = (
    Stage('AA solvation', '01_solvation/run.sh',
          ('../common/molecule/molecule.gro', 'system.top'),
          ('system.gro', 'system.top')),
    Stage('AA neutralization', '02_ions/run.sh',
          ('../01_solvation/system.gro', '../01_solvation/system.top'),
          ('system.gro', 'system.top')),
    Stage('AA minimization', '03_minimization/run.sh',
          ('../02_ions/system.gro', '../02_ions/system.top', 'run.mdp'),
          ('run.gro', 'run.tpr', 'run.edr', 'run.log')),
    Stage('AA NVT equilibration', '04_nvt/run.sh',
          ('../03_minimization/run.gro', '../03_minimization/system.top', 'run.mdp'),
          ('run.gro', 'run.tpr', 'run.edr', 'run.log', 'run.cpt', 'run.xtc')),
    Stage('AA NPT equilibration', '05_npt/run.sh',
          ('../04_nvt/run.gro', '../04_nvt/system.top', 'run.mdp', '../04_nvt/run.cpt'),
          ('run.gro', 'run.tpr', 'run.edr', 'run.log', 'run.cpt', 'run.xtc')),
    Stage('AA NPT production', '06_production/run.sh',
          ('../05_npt/run.gro', '../05_npt/system.top', 'run.mdp', '../05_npt/run.cpt'),
          ('run.gro', 'run.tpr', 'run.edr', 'run.log', 'run.cpt', 'run.xtc')),
    Stage('AA reference publication', '07_reference/run.sh',
          ('../06_production/run.xtc', '../06_production/run.tpr', '../06_production/run.gro'),
          ('lig.gro', 'lig.xtc', 'lig.tpr', 'reference.json')),
)

STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(STAGE_DEFS)


DEFAULTS=dict(aa_nvt_ps=100,aa_npt_ps=1000,aa_production_ps=10000,temperature_k=300,
              pressure_bar=1,output_interval_ps=10,box_padding_nm=1.5,aa_seed=20260917)
# One shape across every run type: (label, lo, hi). The label is what a caller renders.
SETTING_SPECS={'aa_nvt_ps':('AA NVT duration',1,1000000),'aa_npt_ps':('AA NPT duration',1,1000000),
               'aa_production_ps':('AA production duration',1,1000000),
               'temperature_k':('Temperature',200,500),'pressure_bar':('Pressure',.1,100),
               'output_interval_ps':('Trajectory output interval',.002,100000),
               'box_padding_nm':('Box padding',1.3,10),'aa_seed':('AA random seed',1,2147483646)}


def stage_defaults():
    return {'values':dict(DEFAULTS),'sources':{'AA':VERSION+' · CHARMM36 July 2022 / CHARMM TIP3P'},'profile':VERSION}


def normalize_settings(settings=None):
    if settings is not None and not isinstance(settings,dict):raise ValueError('AA settings must be an object')
    result=dict(DEFAULTS)
    for key,value in (settings or {}).items():
        if key not in SETTING_SPECS:raise ValueError('Unknown AA setting: '+key)
        if isinstance(value,bool):raise ValueError('AA settings must be numeric')
        try:value=float(value)
        except (ValueError,TypeError) as exc:raise ValueError(key+' must be numeric') from exc
        label,lo,hi=SETTING_SPECS[key]
        if not math.isfinite(value) or not lo<=value<=hi:raise ValueError(f'{key} must be between {lo} and {hi}')
        result[key]=value
    if int(result['aa_seed'])!=result['aa_seed']:raise ValueError('AA seed must be an integer')
    result['aa_seed']=int(result['aa_seed'])
    if result['output_interval_ps']>result['aa_production_ps']:raise ValueError('Output interval exceeds AA production duration')
    return result


def tool_metadata():
    executable=tools.tool_path('gmx')
    if not executable:raise ValueError('GROMACS executable is unavailable')
    result=subprocess.run([executable,'--version'],capture_output=True,text=True,check=True,timeout=30,env=environment())
    return {'gmx':{'path':executable,'version_output':result.stdout,'sha256':files.sha256(executable)}}


def readiness(molecule_root,molecule_id):
    checks=[];blockers=[]
    try:
        selected=aa_molecules.selection(molecule_root,molecule_id,run_type='aa_only')
        checks.append({'label':'AA molecule','path':selected['path'],'ready':True,'detail':'Input consistency checked; GROMACS verifies parameter resolution before MD.'})
    except (ValueError,OSError) as exc:blockers.append(str(exc))
    executable=tools.tool_path('gmx')
    ok,detail=probe_tool(executable) if executable else (False,'Executable not found')
    checks.append({'label':'GROMACS','path':executable or 'gmx','ready':ok,'detail':detail})
    if not ok:blockers.append('GROMACS: '+detail)
    if not (FORCE_FIELD/'forcefield.itp').is_file():blockers.append('CHARMM36 force field is missing')
    declared_checks,declared_blockers=tools.declared_tool_checks()
    checks.extend(declared_checks);blockers.extend(declared_blockers)
    return {'ready':not blockers,'checks':checks,'blockers':blockers,'scientifically_validated':False}


def mdp(settings,kind):
    common={'cutoff-scheme':'Verlet','nstlist':20,'rlist':1.2,'coulombtype':'PME','rcoulomb':1.2,
            'vdwtype':'Cut-off','vdw-modifier':'Force-switch','rvdw-switch':1.0,'rvdw':1.2,
            'DispCorr':'no','pbc':'xyz','constraints':'h-bonds','constraint-algorithm':'lincs'}
    if kind in ('em','ions'):
        common.update(integrator='steep',nsteps=20000,emtol=1000,emstep=.01)
        if kind=='ions':common.update(coulombtype='Cut-off',nsteps=0)
    else:
        duration=settings[{'nvt':'aa_nvt_ps','npt':'aa_npt_ps','production':'aa_production_ps'}[kind]]
        steps=max(1,round(settings['output_interval_ps']/.002))
        common.update(integrator='md',dt=.002,nsteps=round(duration/.002),continuation='no' if kind=='nvt' else 'yes')
        common.update({'tcoupl':'V-rescale','tc-grps':'System','tau-t':1,'ref-t':settings['temperature_k'],
                       'gen-vel':'yes' if kind=='nvt' else 'no','gen-temp':settings['temperature_k'],
                       'gen-seed':settings['aa_seed'],'ld-seed':settings['aa_seed'],
                       'pcoupl':'no' if kind=='nvt' else ('C-rescale' if kind=='npt' else 'Parrinello-Rahman'),
                       'nstxout-compressed':steps,'nstenergy':min(steps,500),'nstlog':min(steps,500)})
        if kind!='nvt':common.update({'pcoupltype':'isotropic','tau-p':5,'ref-p':settings['pressure_bar'],'compressibility':'4.5e-5'})
    return '\n'.join(f'{k} = {v:.12g}' if isinstance(v,float) else f'{k} = {v}' for k,v in common.items())+'\n'


def prepare_run(run_dir,molecule_root,molecule_snapshot,settings=None):
    run_dir=Path(run_dir); settings=normalize_settings(settings)
    aa_molecules.verify_selection(molecule_root,molecule_snapshot)
    stages=run_dir/'stages'; stages.mkdir()
    common=stages/'common'; common.mkdir(); molecule=common/'molecule'; molecule.mkdir()
    source=Path(molecule_root)/molecule_snapshot['id']
    for relative in molecule_snapshot['sha256']:
        target=molecule/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/relative,target)
    files.verify(molecule,molecule_snapshot['sha256'])
    # Preserve original filenames/includes; normalize only the run-local entry points.
    inputs=molecule_snapshot.get('inputs', {'topology':'molecule.itp', 'coordinates':'molecule.gro', 'coordinate_format':'gro'})
    preparation={'source_inputs':inputs, 'coordinate_conversion':None}
    if inputs['topology'] != 'molecule.itp':
        if (molecule/'molecule.itp').exists(): raise ValueError('Topology dependency conflicts with prepared molecule.itp')
        (molecule/'molecule.itp').write_text('#include "'+inputs['topology']+'"\n')
    if inputs['coordinates'] != 'molecule.gro':
        if (molecule/'molecule.gro').exists(): raise ValueError('Input dependency conflicts with prepared molecule.gro')
        original=molecule/inputs['coordinates']
        if inputs['coordinate_format']=='pdb':
            (molecule/'molecule.gro').write_text(aa_molecules.pdb_gro(original.read_text()))
            preparation['coordinate_conversion']={'method':'aa_molecules.pdb_gro', 'version':1,
                                                  'source':inputs['coordinates'], 'output':'molecule.gro',
                                                  'units':'angstrom to nm; original atom order'}
        else:
            shutil.copy2(original,molecule/'molecule.gro')
    preparation['prepared_gro_sha256']=files.sha256(molecule/'molecule.gro')
    if any(p.is_symlink() for p in FORCE_FIELD.rglob('*')):raise ValueError('Force-field symlinks are unsupported')
    shutil.copytree(FORCE_FIELD,common/FORCE_FIELD.name)
    for name,module in RUN_HELPERS:
        shutil.copy2(Path(module.__file__), common/name)
    context={'protocol_version':VERSION,'settings':settings,'molecule_snapshot':molecule_snapshot,
             'input_preparation':preparation, 'force_field_sha256':files.hashes(common/FORCE_FIELD.name),'scientifically_validated':False}
    files.atomic_json(common/'context.json',context)
    n=molecule_snapshot['atom_count'];charge=round(molecule_snapshot['metadata']['net_charge'])
    from ...analysis.runs.references import index_group
    (common/'solute.ndx').write_text(index_group('Solute',1,n+1))
    top='#include "../common/charmm36-jul2022.ff/forcefield.itp"\n#include "../common/molecule/molecule.itp"\n#include "../common/charmm36-jul2022.ff/tip3p.itp"\n#include "../common/charmm36-jul2022.ff/ions.itp"\n\n[ system ]\nSingle solute in water\n[ molecules ]\n'+molecule_snapshot['metadata']['molecule_type']+' 1\n'
    scripts=[f'''gmx editconf -f ../common/molecule/molecule.gro -d {settings['box_padding_nm']:g} -c -bt dodecahedron -o boxed.gro
gmx grompp -f run.mdp -c boxed.gro -p system.top -o input-check.tpr
gmx solvate -cp boxed.gro -cs spc216.gro -p system.top -o system.gro
''',f'''cp ../01_solvation/system.top system.top
cp ../01_solvation/system.gro system.gro
gmx grompp -f run.mdp -c system.gro -p system.top -o ions.tpr
''']
    if charge:
        scripts[1]+=f'''python ../common/aa_references.py solvent-index system.gro {n}
printf 'SOL\\n' | gmx genion -s ions.tpr -o neutral.gro -p system.top -n solvent.ndx -pname SOD -nname CLA -neutral -seed {settings['aa_seed']}
mv neutral.gro system.gro
'''
    scripts[1]+='python ../common/aa_references.py counts system.top ../common/context.json\n'
    for i,kind in enumerate(('em','nvt','npt','production'),2):
        prev=Path(STAGES[i-1][1]).parent.as_posix(); coord='system.gro' if i==2 else 'run.gro'
        checkpoint=f' -t ../{prev}/run.cpt' if i>=4 else ''
        gpu_flags = MDRUN_GPU_NONBONDED_FLAGS if kind == 'em' else MDRUN_GPU_PME_FLAGS
        scripts.append(f'cp ../{prev}/system.top system.top\ngmx grompp -f run.mdp -c ../{prev}/{coord}{checkpoint} -p system.top -o run.tpr\ngmx mdrun -deffnm run -ntmpi 1 -ntomp 8 {gpu_flags} -v\n')
    scripts.append('''printf 'Solute\\nSolute\\n' | gmx trjconv -f ../06_production/run.xtc -s ../06_production/run.tpr -n ../common/solute.ndx -pbc mol -center -o lig.xtc
printf 'Solute\\n' | gmx trjconv -f ../06_production/run.xtc -s ../06_production/run.tpr -n ../common/solute.ndx -dump 0 -o lig.gro
printf 'Solute\\n' | gmx convert-tpr -s ../06_production/run.tpr -n ../common/solute.ndx -o lig.tpr
printf 'Temperature\\nPressure\\nDensity\\nPotential\\nTotal-Energy\\n0\\n' | gmx energy -f ../06_production/run.edr -o diagnostics.xvg
python ../common/aa_references.py publish ..
''')
    for i,((_,relative),script) in enumerate(zip(STAGES,scripts)):
        target=stages/relative;target.parent.mkdir();target.write_text('#!/bin/bash\nset -euxo pipefail\n'+script)
        if i<6:(target.parent/'run.mdp').write_text(mdp(settings,('ions','ions','em','nvt','npt','production')[i]))
    (stages/'01_solvation/system.top').write_text(top)
    shutil.copytree(stages,run_dir/'inputs')
    files.atomic_json(run_dir/'manifest.json',dict(context,run_type='aa_only',workflow_version=VERSION,layout_version=2,
        stage_plan=[name for name,_ in STAGES],stages=[],input_snapshot_sha256=files.hashes(run_dir/'inputs'),
        tools=tool_metadata(),prepared_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        environment={k:environment()[k] for k in ('PATH','MPLBACKEND','OMP_NUM_THREADS')}))


def _protocol_stage_contract(metadata):
    """AA stages carry no run-specific placeholders, so metadata is unused."""
    return STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS


def _protocol_stages(metadata):
    """AA stages name no molecule-specific script, so metadata is unused."""
    return tuple(STAGE_DEFS)


def _protocol_readiness(metadata):
    molecule_id = metadata.get('molecule_id')
    if not molecule_id:
        return protocol.blocked('molecule_id is required to check an AA-only run')
    return readiness(metadata.get('molecule_root'), molecule_id)


def _protocol_prepare(run_dir, metadata):
    prepare_run(run_dir, metadata['molecule_root'], metadata['molecule_snapshot'],
                metadata.get('settings'))


PROTOCOL = protocol.Protocol(
    name='aa_only',
    stage_contract=_protocol_stage_contract,
    stages=_protocol_stages,
    settings_specs=lambda: SETTING_SPECS,
    stage_defaults=stage_defaults,
    normalize_settings=lambda settings=None, profile='standard': normalize_settings(settings),
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
)
