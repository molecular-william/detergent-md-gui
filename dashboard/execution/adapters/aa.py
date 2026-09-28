"""Versioned single-solute CHARMM AA protocol, independent of CG tooling."""
import math
import shutil
import subprocess
from pathlib import Path

from ... import files
from ...analysis.runs import references as aa_references
from ...models.molecules import aa as aa_molecules
from .. import forcefields, protocol, tools
from ..environment import environment, probe_tool, recorded_environment
from ..stages import Stage, stage_tables
from . import aa_box

# Modules copied into every run's common/ directory. The names are part of the
# run contract, not a detail: the generated stage scripts invoke
# ../common/aa_references.py, and the copied publication helper imports
# aa_molecules by module name. Copying each module under its own __file__ name
# silently breaks both whenever a module moves.
RUN_HELPERS = (('aa_references.py', aa_references),
               ('aa_molecules.py', aa_molecules),
               ('files.py', files))

# The ruleset, not the force field: which force field a run used is recorded beside it, because two runs at one
# ruleset with different force fields are exactly the comparison this version keeps straight.
VERSION='aa-single-solute-v2'
# One vocabulary of execution profiles, owned here because it decides AA durations.
# 'draft-smoke-reference' is the exception: it keeps a full-length AA reference and
# shortens only the CG half, for a run whose reference is meant to be reused.
PROFILES=('standard','draft-smoke','draft-smoke-reference','aa-200ns')
DRAFT_DURATIONS={'draft-smoke':{'aa_nvt_ps':5.0,'aa_npt_ps':5.0,'aa_production_ps':50.0}}
# A full-length reference for ensemble work. The paper sampled at least 200 ns of atomistic data for the
# geometry and volume comparisons behind its ring scaling, so an AA run that is to feed ring-target
# averaging has to reach that scale. This is a sampling scale, not a validation claim.
LONG_DURATIONS={'aa-200ns':{'aa_nvt_ps':100.0,'aa_npt_ps':1000.0,'aa_production_ps':200000.0}}


def validate_profile(profile):
    if profile not in PROFILES:raise ValueError('Unsupported execution profile')
    return profile
MDRUN_GPU_NONBONDED_FLAGS='-gpu_id 0 -nb gpu -pin on'
MDRUN_GPU_PME_FLAGS=f'{MDRUN_GPU_NONBONDED_FLAGS} -pme gpu -pmefft gpu'


def gromacs_flavour(binary=None):
    """Which mdrun this build is: 'mpi', 'thread-mpi' or 'unknown'.

    GROMACS prints its own configuration, so this asks the binary rather than assuming from the host: an MPI
    build takes ranks as separate processes under mpirun, a thread-MPI build takes them inside one process with
    -ntmpi -- and passing -ntmpi to an MPI build aborts mdrun before the first step. Costs one subprocess; stage
    preparation calls it per stage, which is cheap beside grompp.
    """
    import shutil
    import subprocess

    resolved = binary or shutil.which('gmx') or '/usr/local/gromacs/2026.3/bin/gmx'
    try:
        report = subprocess.run([resolved, '--version'], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return 'unknown'
    text = report.stdout + report.stderr
    # An MPI build links an MPI library and may still mention thread-MPI (as being off), so the library is the
    # discriminator and the mention only breaks a tie the library left open.
    if 'MPI library' in text: return 'mpi'
    return 'thread-mpi' if 'thread MPI' in text else 'unknown'


def mdrun_launch(settings, flavour=None):
    """The mdrun launcher and its thread flags, from the stage settings.

    Two levers, and on this host only one of them is the second one people expect. `-ntomp` sets OpenMP
    threads per rank and is valid for every build. `-ntmpi` sets thread-MPI ranks and is invalid here:
    /usr/local/gromacs/2026.3/bin/gmx is a symlink to gmx_mpi, so mdrun aborts with "Setting the number of
    thread-MPI ranks is only supported with thread-MPI". The equivalent lever for an MPI build is the
    number of ranks under mpirun, which is what `mdrun_ranks` sets; ranks and threads multiply, so the two
    together are the CPU budget and are checked against the machine rather than left to mdrun to discover.

    Sizes are honest about scale: a small solute box saturates well before a machine of this size, so more
    ranks is not automatically faster. The settings exist so the number can be measured rather than assumed.
    """
    import os
    cores = os.cpu_count() or 1
    ranks = int(settings.get('mdrun_ranks') or 1)
    threads = int(settings.get('mdrun_ntomp') or 8)
    if ranks < 1 or threads < 1:
        raise ValueError('mdrun ranks and threads must be positive')
    if ranks * threads > cores:
        raise ValueError(f'mdrun would use {ranks * threads} CPU slots for {cores} cores; '
                         'lower mdrun_ranks or mdrun_ntomp')
    build = flavour or gromacs_flavour()
    if ranks > 1:
        if build == 'thread-mpi':
            # Ranks live inside one process here, so -ntmpi is the flag and mpirun does not exist to use.
            prefix, rank_flags = '', f'-ntmpi {ranks} '
        else:
            # An MPI build (and an unprobed one, which is what this adapter always assumed) takes the ranks as
            # separate processes. 'unknown' keeps that behaviour and shows up in the manifest.
            prefix, rank_flags = f'mpirun -np {ranks} ', ''
    else:
        prefix, rank_flags = '', ''
    # 'auto' emits nothing, so a run that does not touch these settings produces exactly the command it
    # produced before they existed, and a GPU execution profile keeps its own flags.
    scheme = ''
    for key, flag in (('mdrun_nb', '-nb'), ('mdrun_pme', '-pme')):
        choice = str(settings.get(key) or 'auto')
        if choice not in CHOICE_SPECS[key][1]:
            raise ValueError(f'{key} must be one of {", ".join(CHOICE_SPECS[key][1])}')
        if key == 'mdrun_pme' and choice == 'gpu' and str(settings.get('mdrun_nb') or 'auto') != 'gpu':
            raise ValueError('mdrun_pme gpu needs mdrun_nb gpu: GROMACS runs PME on the GPU only when the '
                             'nonbonded scheme is on the GPU too')
        if choice != 'auto':
            scheme += f' {flag} {choice}' + (' -pmefft gpu' if key == 'mdrun_pme' and choice == 'gpu' else '')
    return prefix, f'{rank_flags}-ntomp {threads}{scheme}'


def mdrun_command_flags(settings, stage, flavour=None):
    """The launcher and the whole flag set for one mdrun command.

    One place decides the budget and the schemes, so a generated command and a stage script cannot disagree.
    A minimisation keeps PME on the CPU and every other stage may put it on the GPU, which is the bracket the AA
    stages have always used.

    A stage setting *replaces* the bracket flag it names rather than being appended after it: emitting both would
    leave GROMACS to use whichever came last, which would not be what the setting says. With both on 'auto' the
    result is byte-for-byte the command these stages produced before the settings existed.
    """
    launcher, thread_flags = mdrun_launch(settings, flavour)
    bracket = MDRUN_GPU_NONBONDED_FLAGS if stage == 'em' else MDRUN_GPU_PME_FLAGS
    for key, flag in (('mdrun_nb', '-nb'), ('mdrun_pme', '-pme')):
        if str(settings.get(key) or 'auto') == 'auto': continue
        bracket = ' '.join(part for part in bracket.split()
                           if part != flag and not part.startswith(flag + 'fft'))
    return launcher, f'{thread_flags} {bracket}'.strip()


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


DEFAULTS=dict(aa_nvt_ps=100,aa_npt_ps=1000,aa_production_ps=10000,
              temperature_k=forcefields.entry().temperature_k,
              pressure_bar=1,output_interval_ps=10,box_nm=aa_box.DEFAULT_EDGE_NM,aa_seed=20260917,
              mdrun_ntomp=8,mdrun_ranks=1,mdrun_nb='auto',mdrun_pme='auto',
              box_shape=aa_box.DEFAULT_SHAPE,
              force_field=forcefields.DEFAULT)
# Choices are a separate shape rather than a third element of the numeric tuple, which unpacks as (label, lo,
# hi). 'auto' means the execution profile decides, which is what every run did before these settings existed.
# The force field is a choice as well, and its options are the registry's entries: a name the registry does not
# offer cannot reach a run.
CHOICE_SPECS={'mdrun_nb':('Nonbonded scheme',('auto','cpu','gpu')),
              'mdrun_pme':('PME scheme',('auto','cpu','gpu')),
              # The cube is the protocol's own shape and stays the default. The dodecahedron was added on the
              # manual's recommendation for a spherical solute and measured: it holds this cut-off in more water,
              # not less, and runs 12% slower here. Available because it was worth testing; not the faster option.
              'box_shape':('Box shape',aa_box.SHAPES),
              'force_field':('Force field',forcefields.names())}
# One shape across every run type: (label, lo, hi). The label is what a caller renders.
SETTING_SPECS={'aa_nvt_ps':('AA NVT duration',1,1000000),'aa_npt_ps':('AA NPT duration',1,1000000),
               'aa_production_ps':('AA production duration',1,1000000),
               'mdrun_ntomp':('mdrun OpenMP threads per rank',1,72),
               'mdrun_ranks':('mdrun MPI ranks',1,72),
               'temperature_k':('Temperature',200,500),'pressure_bar':('Pressure',.1,100),
               'output_interval_ps':('Trajectory output interval',.002,100000),
               'box_nm':('Box edge',1.0,20),'aa_seed':('AA random seed',1,2147483646)}


def stage_defaults(profile='standard'):
    """The settings an AA run starts from, at one execution profile.

    A draft profile shortens the work: it is a diagnostic execution check, short enough
    to run interactively, and it says nothing about the physics. The CG composition
    derives its AA durations from these, so a profile that is not applied here reaches
    an AA-to-CG run as a full-length AA reference (see cg.mirror_aa_settings).
    """
    validate_profile(profile)
    values = dict(DEFAULTS)
    values.update(DRAFT_DURATIONS.get(profile, {}))
    values.update(LONG_DURATIONS.get(profile, {}))
    default = forcefields.entry(values['force_field'])
    return {'values': values, 'sources': {'AA': f'{VERSION} · {default.name} / {default.water_molecule}'},
            'profile': VERSION}


def normalize_settings(settings=None, profile='standard'):
    if settings is not None and not isinstance(settings,dict):raise ValueError('AA settings must be an object')
    supplied=settings or {}
    result=dict(stage_defaults(profile)['values'])
    for key,value in supplied.items():
        if key in CHOICE_SPECS:
            label,options=CHOICE_SPECS[key]
            if not isinstance(value,str) or value not in options:
                raise ValueError(f'{key} must be one of {", ".join(options)}')
            result[key]=value
            continue
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
    # The temperature a run starts from belongs to the force field: each parameterisation assumes one, and the
    # reference protocol this project reproduces runs each force field at its own. A caller who names a
    # temperature still wins, because they may be testing the assumption.
    if 'temperature_k' not in supplied:
        result['temperature_k']=forcefields.entry(result['force_field']).temperature_k
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
        selected_metadata=selected['metadata']
        caveats=[str(caveat) for caveat in (selected_metadata.get('caveats') or [])] if isinstance(selected_metadata,dict) else []
        detail='Input consistency checked; GROMACS verifies parameter resolution before MD.'
        # A caveat is stated where the run is configured rather than buried in a comment: it does not block the
        # run, and a reader deciding whether to trust the result needs to see it beside the readiness verdict.
        if caveats:detail+=' Caveat: '+' '.join(caveats)
        checks.append({'label':'AA molecule','path':selected['path'],'ready':True,'detail':detail})
    except (ValueError,OSError) as exc:blockers.append(str(exc))
    executable=tools.tool_path('gmx')
    ok,detail=probe_tool(executable) if executable else (False,'Executable not found')
    checks.append({'label':'GROMACS','path':executable or 'gmx','ready':ok,'detail':detail})
    if not ok:blockers.append('GROMACS: '+detail)
    available=[forcefields.entry(name) for name in forcefields.names()]
    missing=[ff.name for ff in available if not (ff.tree()/'forcefield.itp').is_file()]
    checks.append({'label':'Force fields','path':str(available[0].tree().parent),'ready':not missing,
                   'detail':('Available: '+', '.join(ff.name for ff in available)) if not missing
                             else 'Missing a force-field tree: '+', '.join(missing)})
    if missing:blockers.append('Force-field tree missing: '+', '.join(missing))

    declared_checks,declared_blockers=tools.declared_tool_checks()
    checks.extend(declared_checks);blockers.extend(declared_blockers)
    return {'ready':not blockers,'checks':checks,'blockers':blockers,'scientifically_validated':False}


def mdp(settings,kind,ff=None):
    """One stage's mdp, with the force field's settings read rather than restated.

    The registry holds the block GROMACS prescribes for the force field, so a change follows the reference
    instead of a duplicated literal, and the constraints choice is the entry's. What is not the force field's
    business -- the neighbour-list update, the integrator, the durations, the coupling -- stays here.
    """
    ff=ff or forcefields.entry(settings.get('force_field'))
    # The protocol's box is small -- 2.5 nm, as close to the paper's stated 2.4 as its own 1.2 nm cut-off allows --
    # and GROMACS's automatic Verlet buffer does not fit inside it. The buffer is *added* to rlist, and the result
    # has to stay strictly inside half the box; with half a box of 1.25 nm and a cut-off of 1.2 nm there is no room
    # for even a small one, so the buffer is disabled and rlist used exactly as written. GROMACS's own note about
    # this configuration is worth keeping in view: the cluster pair list still buffers a little, rlist raises no
    # accuracy problem, and the cost is that a larger rlist might be wanted for energy conservation -- which the
    # box does not allow, so that caveat is accepted knowingly rather than overlooked.
    #
    # nstlist is left at 20 because GROMACS says it is a performance knob and not an accuracy one ("with the
    # Verlet scheme, nstlist has no effect on the accuracy"), and that with GPUs the optimal value is at least 20.
    # The manual's other recommendation for this configuration -- `mts = yes`, the PME mesh every second step,
    # for GPUs with the integration on the CPU -- is accepted by grompp here and is being measured before it is
    # offered as a setting: it is a numerical approximation, and the protocol this project reproduces did not use
    # it, so it should come with numbers rather than with an assumption.
    common={'nstlist':20,'pbc':'xyz','constraint-algorithm':'lincs','verlet-buffer-tolerance':-1,
            **ff.mdp,'constraints':ff.constraints}

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
    # A box that cannot hold the solute is refused here, before any stage is written, rather than discovered as a
    # solute interacting with its own periodic image three stages later.
    aa_box.check_fit(molecule_snapshot['metadata']['name'], aa_box.read_coordinates(molecule/'molecule.gro'),
                     settings['box_nm'])
    # The box also has to be big enough for the force field's own neighbour-list cut-off, which is a different
    # requirement from holding the solute: the two failures look nothing alike and only one of them is obvious.
    aa_box.check_cutoffs(settings['box_nm'], float(forcefields.entry(settings['force_field']).mdp['rlist']))
    ff=forcefields.entry(settings['force_field']); tree=ff.tree()
    if any(p.is_symlink() for p in tree.rglob('*')):raise ValueError('Force-field symlinks are unsupported')
    shutil.copytree(tree,common/tree.name)
    for name,module in RUN_HELPERS:
        shutil.copy2(Path(module.__file__), common/name)
    caveats=[str(caveat) for caveat in (molecule_snapshot['metadata'].get('caveats') or [])]
    context={'protocol_version':VERSION,'settings':settings,'molecule_snapshot':molecule_snapshot,
             'input_preparation':preparation,'force_field':ff.name,'force_field_directory':tree.name,
             'caveats':caveats,
             'force_field_sha256':files.hashes(common/tree.name),'scientifically_validated':False}
    files.atomic_json(common/'context.json',context)
    n=molecule_snapshot['atom_count'];charge=round(molecule_snapshot['metadata']['net_charge'])
    from ...analysis.runs.references import index_group
    (common/'solute.ndx').write_text(index_group('Solute',1,n+1))
    top=(f'#include "../common/{tree.name}/forcefield.itp"\n#include "../common/molecule/molecule.itp"\n'
         f'#include "../common/{tree.name}/{ff.water_file}"\n#include "../common/{tree.name}/ions.itp"\n\n'
         f'[ system ]\nSingle solute in water\n[ molecules ]\n{molecule_snapshot["metadata"]["molecule_type"]} 1\n')
    scripts=[f'''gmx editconf -f ../common/molecule/molecule.gro {aa_box.editconf_arguments(settings['box_nm'], settings.get('box_shape', aa_box.DEFAULT_SHAPE))} -o boxed.gro
gmx grompp -f run.mdp -c boxed.gro -p system.top -o input-check.tpr
gmx solvate -cp boxed.gro -cs spc216.gro -p system.top -o system.gro
''','''cp ../01_solvation/system.top system.top
cp ../01_solvation/system.gro system.gro
gmx grompp -f run.mdp -c system.gro -p system.top -o ions.tpr
''']
    if charge:
        scripts[1]+=f'''python ../common/aa_references.py solvent-index system.gro {n}
printf '{ff.water_molecule}\\n' | gmx genion -s ions.tpr -o neutral.gro -p system.top -n solvent.ndx -pname {ff.cation} -nname {ff.anion} -neutral -seed {settings['aa_seed']}
mv neutral.gro system.gro
'''
    scripts[1]+='python ../common/aa_references.py counts system.top ../common/context.json\n'
    for i,kind in enumerate(('em','nvt','npt','production'),2):
        prev=Path(STAGES[i-1][1]).parent.as_posix(); coord='system.gro' if i==2 else 'run.gro'
        checkpoint=f' -t ../{prev}/run.cpt' if i>=4 else ''
        launcher, mdrun_flags = mdrun_command_flags(settings, kind)
        # No -ntmpi here. This host's GROMACS is an MPI build only -- /usr/local/gromacs/2026.3/bin/gmx is
        # a symlink to gmx_mpi -- and -ntmpi is a thread-MPI option, so mdrun aborts with "Setting the
        # number of thread-MPI ranks is only supported with thread-MPI and GROMACS was compiled without
        # thread-MPI". That killed every run on this machine before the first minimization step, which is
        # why runs/ was empty. The CPU budget is mdrun_ranks x mdrun_ntomp instead, checked against the
        # machine by mdrun_launch; a capability-aware probe that offers -ntmpi on a thread-MPI build is the
        # remaining piece.
        scripts.append(f'cp ../{prev}/system.top system.top\ngmx grompp -f run.mdp -c ../{prev}/{coord}{checkpoint} -p system.top -o run.tpr\n{launcher}gmx mdrun -deffnm run {mdrun_flags} -v\n')
    scripts.append('''printf 'Solute\\nSolute\\n' | gmx trjconv -f ../06_production/run.xtc -s ../06_production/run.tpr -n ../common/solute.ndx -pbc mol -center -o lig.xtc
printf 'Solute\\n' | gmx trjconv -f ../06_production/run.xtc -s ../06_production/run.tpr -n ../common/solute.ndx -dump 0 -o lig.gro
printf 'Solute\\n' | gmx convert-tpr -s ../06_production/run.tpr -n ../common/solute.ndx -o lig.tpr
printf 'Temperature\\nPressure\\nDensity\\nPotential\\nTotal-Energy\\n0\\n' | gmx energy -f ../06_production/run.edr -o diagnostics.xvg
python ../common/aa_references.py publish ..
''')
    for i,((_,relative),script) in enumerate(zip(STAGES,scripts)):
        target=stages/relative;target.parent.mkdir();target.write_text('#!/bin/bash\nset -euxo pipefail\n'+script)
        if i<6:(target.parent/'run.mdp').write_text(mdp(settings,('ions','ions','em','nvt','npt','production')[i],ff))
    (stages/'01_solvation/system.top').write_text(top)
    shutil.copytree(stages,run_dir/'inputs')
    protocol.write_prepared_manifest(
        run_dir, dict(context, run_type='aa_only', workflow_version=VERSION), tools=tool_metadata(),
        plan=[name for name,_ in STAGES],
        environment=recorded_environment())


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
    normalize_settings=lambda settings=None, profile='standard': normalize_settings(settings, profile),
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
)
