"""Versioned single-solute CHARMM AA protocol, independent of CG tooling."""
import subprocess
from pathlib import Path

from ... import files
from ...models.molecules import aa as aa_molecules
from .. import devices, forcefields, protocol, run_inputs, tools
from ..environment import environment, probe_tool, recorded_environment
from ..mdp import write_mdp
from ..settings import normalize
from ..stages import Stage, stage_tables
from . import aa_box

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
def gpu_flags(settings):
    """The device choice and the nonbonded offload, from the setting.

    One index, not a list: `-gpu_id 0,1` would spread ranks across devices and is a follow-up, so today the
    run names one device and the panel says when several ranks share it. `0` is the default rather than
    `auto`, and deliberately: `auto` would let GROMACS pick a different device than every existing run used,
    and the point of the setting is to make the device visible and choosable, not to move the work silently.

    A host that reports no device produces no flag at all: there is no index to name and nothing to offload, so
    every generated command keeps GROMACS' own CPU default instead of asking for a GPU that is not there.
    """
    if not devices.present():
        return ''
    choice = settings.get('mdrun_gpu')
    index = 0 if choice in (None, '') else int(choice)
    if index < 0:
        raise ValueError('mdrun_gpu must be a device index of 0 or more')
    return f'-gpu_id {index} -nb gpu -pin on'


def gromacs_flavour(binary=None, *, report=None):
    """Which mdrun this build is: 'mpi', 'thread-mpi' or 'unknown'.

    GROMACS prints its own configuration, so this asks the binary rather than assuming from the host: an MPI
    build takes ranks as separate processes under mpirun, a thread-MPI build takes them inside one process with
    -ntmpi -- and passing -ntmpi to an MPI build aborts mdrun before the first step. Costs one subprocess; stage
    preparation calls it per stage, which is cheap beside grompp.
    """
    import shutil

    if report is None:
        resolved = binary or shutil.which('gmx') or '/usr/local/gromacs/2026.3/bin/gmx'
        try:
            report = subprocess.run([resolved, '--version'], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return 'unknown'
        text = report.stdout + report.stderr
    else:
        text = str(report)
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
    pmefft = str(settings.get('mdrun_pmefft') or 'auto')
    if pmefft not in CHOICE_SPECS['mdrun_pmefft'][1]:
        raise ValueError(f'mdrun_pmefft must be one of {", ".join(CHOICE_SPECS["mdrun_pmefft"][1])}')
    if pmefft == 'gpu' and not devices.present():
        raise ValueError('mdrun_pmefft gpu needs a GPU on this host')
    scheme = ''
    for key, flag in (('mdrun_nb', '-nb'), ('mdrun_pme', '-pme')):
        choice = str(settings.get(key) or 'auto')
        if choice not in CHOICE_SPECS[key][1]:
            raise ValueError(f'{key} must be one of {", ".join(CHOICE_SPECS[key][1])}')
        # A scheme that asks for a device is refused on a host that reports none, before a command is written:
        # the route no longer offers the option, but an old job retried here would still carry it in its settings.
        if choice == 'gpu' and not devices.present():
            raise ValueError(f'{key} gpu needs a GPU on this host')
        if key == 'mdrun_pme' and choice == 'gpu' and str(settings.get('mdrun_nb') or 'auto') != 'gpu':
            raise ValueError('mdrun_pme gpu needs mdrun_nb gpu: GROMACS runs PME on the GPU only when the '
                             'nonbonded scheme is on the GPU too')
        if key == 'mdrun_pme' and choice == 'cpu' and pmefft == 'gpu':
            raise ValueError('mdrun_pmefft gpu needs the PME scheme on the GPU')
        if choice != 'auto':
            scheme += f' {flag} {choice}'
    # The FFT scheme is named once, after the PME scheme it belongs to: a named one is the run's choice, and `auto`
    # keeps the scheme the GPU-PME bracket has always asked for.
    if pmefft != 'auto':
        scheme += f' -pmefft {pmefft}'
    elif str(settings.get('mdrun_pme') or 'auto') == 'gpu':
        scheme += ' -pmefft gpu'
    return prefix, f'{rank_flags}-ntomp {threads}{scheme}'


def _without_flag(tokens, flag):
    """`tokens` with `flag` and the value after it removed: a scheme replaces a flag, never appends a second."""
    kept, skip = [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token == flag:
            skip = True
            continue
        kept.append(token)
    return kept


def mdrun_command_flags(settings, stage, flavour=None):
    """The launcher and the whole flag set for one mdrun command.

    One place decides the budget and the schemes, so a generated command and a stage script cannot disagree.
    A minimisation keeps PME on the CPU and every other stage may put it on the GPU, which is the bracket the AA
    stages have always used.

    A stage setting *replaces* the bracket flag it names rather than being appended after it: emitting both would
    leave GROMACS to use whichever came last, which would not be what the setting says. With every scheme on 'auto'
    the result is byte-for-byte the command these stages produced before the settings existed.

    `mdrun_update`, `mdrun_pmefft` and `mdrun_tunepme` are the execution additions the New run form offers. 'auto'
    for each emits nothing -- GROMACS' own default -- so an untouched run's command does not move; `tunepme` writes
    `-tunepme` or `-notunepme` only when the run names one.
    """
    launcher, thread_flags = mdrun_launch(settings, flavour)
    # The device is read here, from the setting, and nowhere else: the constants above are the default the
    # scripts' own fallbacks state, not a second opinion about which device this run uses. A host with no GPU
    # gets no device and no offload flag -- not even the PME pair the dynamics bracket has always added.
    device_flags = gpu_flags(settings)
    bracket = device_flags if stage == 'em' or not device_flags else f'{device_flags} -pme gpu -pmefft gpu'
    tokens = bracket.split()
    for key, flag in (('mdrun_nb', '-nb'), ('mdrun_pme', '-pme')):
        if str(settings.get(key) or 'auto') != 'auto':
            tokens = _without_flag(tokens, flag)
    pmefft = str(settings.get('mdrun_pmefft') or 'auto')
    if pmefft != 'auto' or str(settings.get('mdrun_pme') or 'auto') != 'auto':
        # A named PME scheme owns both of its flags: the FFT flag belongs to a GPU PME and goes with it, and a named
        # FFT scheme is emitted by `mdrun_launch`. Leaving the bracket's copy would emit two values for one option.
        tokens = _without_flag(tokens, '-pmefft')
    # The checkpoint cadence is a run setting with no default: a run that names none emits nothing, so GROMACS'
    # own 15 minutes stands and the command is the one every earlier run produced, byte for byte.
    flags = f'{thread_flags} {" ".join(tokens)}'.strip()
    update = str(settings.get('mdrun_update') or 'auto')
    if update not in CHOICE_SPECS['mdrun_update'][1]:
        raise ValueError(f'mdrun_update must be one of {", ".join(CHOICE_SPECS["mdrun_update"][1])}')
    if update == 'gpu' and not devices.present():
        raise ValueError('mdrun_update gpu needs a GPU on this host')
    if update != 'auto':
        flags += f' -update {update}'
    tunepme = str(settings.get('mdrun_tunepme') or 'auto')
    if tunepme not in CHOICE_SPECS['mdrun_tunepme'][1]:
        raise ValueError(f'mdrun_tunepme must be one of {", ".join(CHOICE_SPECS["mdrun_tunepme"][1])}')
    if tunepme == 'on':
        flags += ' -tunepme'
    elif tunepme == 'off':
        flags += ' -notunepme'
    cpt = settings.get('mdrun_cpt')
    if cpt is not None:
        minutes = float(cpt)
        if minutes != int(minutes) or not 1 <= minutes <= 100000:
            raise ValueError('mdrun_cpt must be a whole number of minutes between 1 and 100000')
        flags += f' -cpt {int(minutes)}'
    return launcher, flags


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
          ('run.gro', 'run.tpr', 'run.edr', 'run.log', 'run.cpt', 'run.xtc'),
          checkpoint='run.cpt'),
    Stage('AA NPT equilibration', '05_npt/run.sh',
          ('../04_nvt/run.gro', '../04_nvt/system.top', 'run.mdp', '../04_nvt/run.cpt'),
          ('run.gro', 'run.tpr', 'run.edr', 'run.log', 'run.cpt', 'run.xtc'),
          checkpoint='run.cpt'),
    Stage('AA NPT production', '06_production/run.sh',
          ('../05_npt/run.gro', '../05_npt/system.top', 'run.mdp', '../05_npt/run.cpt'),
          ('run.gro', 'run.tpr', 'run.edr', 'run.log', 'run.cpt', 'run.xtc'),
          checkpoint='run.cpt'),
    Stage('AA reference publication', '07_reference/run.sh',
          ('../06_production/run.xtc', '../06_production/run.tpr', '../06_production/run.gro'),
          ('lig.gro', 'lig.xtc', 'lig.tpr', 'reference.json')),
)

STAGES, REQUIRED_INPUTS, REQUIRED_OUTPUTS = stage_tables(STAGE_DEFS)


DEFAULTS=dict(aa_nvt_ps=100,aa_npt_ps=1000,aa_production_ps=10000,
              temperature_k=forcefields.entry().temperature_k,
              pressure_bar=1,output_interval_ps=10,box_nm=aa_box.DEFAULT_EDGE_NM,aa_seed=20260917,
              mdrun_ntomp=8,mdrun_ranks=1,mdrun_nb='auto',mdrun_pme='auto',mdrun_gpu=0,
              # The execution additions: 'auto' emits no flag for each, so every run prepared before these settings
              # existed keeps its exact command. `tunepme` is GROMACS' own default on; 'auto' leaves it there.
              mdrun_pmefft='auto',mdrun_update='auto',mdrun_tunepme='auto',
              # A checkpoint every ten minutes of wall time: the user's cadence for this project, recorded by every
              # run so a failed leg loses at most that much sampling to Restart.
              mdrun_cpt=10,
              box_shape=aa_box.DEFAULT_SHAPE,
              force_field=forcefields.DEFAULT)
# Choices are a separate shape rather than a third element of the numeric tuple, which unpacks as (label, lo,
# hi). 'auto' means the execution profile decides, which is what every run did before these settings existed.
# The force field is a choice as well, and its options are the registry's entries: a name the registry does not
# offer cannot reach a run.
CHOICE_SPECS={'mdrun_nb':('Nonbonded scheme',('auto','cpu','gpu')),
              'mdrun_pme':('PME scheme',('auto','cpu','gpu')),
              # The PME FFT scheme and the update/constraints scheme: 'auto' keeps the profile's bracket, and a named
              # one replaces that bracket's flag. `tunepme` is a three-way choice rather than a boolean so the form
              # can post a string and 'auto' can mean GROMACS' own default, which is on.
              'mdrun_pmefft':('PME FFT scheme',('auto','cpu','gpu')),
              'mdrun_update':('Update and constraints',('auto','cpu','gpu')),
              'mdrun_tunepme':('PME load tuning',('auto','on','off')),
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
               # An index, not a list: one device per run, chosen from the ones the host reports. The upper bound
               # is a form bound rather than a statement about any machine -- the check that matters is against
               # the devices that exist, at prepare.
               'mdrun_gpu':('mdrun GPU device',0,64),
               # Minutes between checkpoint saves, a count rather than a duration; there is deliberately no default,
               # so a run that names none leaves GROMACS' own cadence in force and writes no flag.
               'mdrun_cpt':('Checkpoint interval (minutes)',1,100000),
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
    supplied=settings or {}
    result=normalize(
        settings, stage_defaults(profile)['values'], specs=SETTING_SPECS, choices=CHOICE_SPECS,
        object_message='AA settings must be an object', unknown_prefix='Unknown AA setting: ',
        bool_message='AA settings must be numeric',
        integrals={'mdrun_gpu':'mdrun_gpu must be an integer', 'mdrun_cpt':'mdrun_cpt must be an integer',
                   'aa_seed':'AA seed must be an integer'})
    if result['output_interval_ps']>result['aa_production_ps']:raise ValueError('Output interval exceeds AA production duration')
    # The temperature a run starts from belongs to the force field: each parameterisation assumes one, and the
    # reference protocol this project reproduces runs each force field at its own. A caller who names a
    # temperature still wins, because they may be testing the assumption.
    if 'temperature_k' not in supplied:
        result['temperature_k']=forcefields.entry(result['force_field']).temperature_k
    return result


def tool_metadata():
    return tools.record_versions('gmx', env=environment(),
                                 missing=lambda name: ValueError('GROMACS executable is unavailable'))


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




#: The reviewed profile each of the first six stages writes, in `STAGES` order: solvation prepares a tpr for genion
#: with the ions file, the ions stage writes it again after neutralising, and the four dynamics stages follow.
MDP_PROFILES = ('aa-ions-v1', 'aa-ions-v1', 'aa-em-v1', 'aa-nvt-v1', 'aa-npt-v1', 'aa-production-v1')
_DURATION_SETTING = {'aa-nvt-v1': 'aa_nvt_ps', 'aa-npt-v1': 'aa_npt_ps', 'aa-production-v1': 'aa_production_ps'}


def mdp_values(settings, profile):
    """The numbers one profile leaves to the run, computed exactly as `mdp()` computes them."""
    values = {'force_field': settings['force_field']}
    if profile in ('aa-ions-v1', 'aa-em-v1'):
        return values
    interval = max(1, round(settings['output_interval_ps'] / 0.002))
    values.update({'nsteps': round(settings[_DURATION_SETTING[profile]] / 0.002),
                   'ref-t': settings['temperature_k'], 'gen-temp': settings['temperature_k'],
                   'gen-seed': settings['aa_seed'], 'ld-seed': settings['aa_seed'],
                   'nstxout-compressed': interval, 'nstenergy': min(interval, 500), 'nstlog': min(interval, 500)})
    if profile != 'aa-nvt-v1':
        values['ref-p'] = settings['pressure_bar']
    return values


def prepare_run(run_dir,molecule_root,molecule_snapshot,settings=None):
    run_dir=Path(run_dir); settings=normalize_settings(settings)
    # The device is checked against the ones this host reports, before anything is written: a run that named a
    # device that is not there would otherwise be refused by mdrun three stages in. A host that reports none is
    # not a refusal -- see `devices.require`.
    devices.require(settings['mdrun_gpu'])
    aa_molecules.verify_selection(molecule_root,molecule_snapshot)
    stages=run_dir/'stages'; stages.mkdir()
    common=stages/'common'; common.mkdir(); molecule=common/'molecule'; molecule.mkdir()
    # The store is the molecule's own directory: the run names its bytes and reads them where they live instead of
    # carrying a second copy. Both checks the copy used to make still run, against the store.
    molecule_root=Path(molecule_root).resolve(); source=molecule_root/molecule_snapshot['id']
    files.verify(source,molecule_snapshot['sha256'])
    # Preserve original filenames/includes; normalize only the run-local entry points.
    inputs=molecule_snapshot.get('inputs', {'topology':'molecule.itp', 'coordinates':'molecule.gro', 'coordinate_format':'gro'})
    preparation={'source_inputs':inputs, 'coordinate_conversion':None}
    # `molecule.itp` is a generated shim: one include, spelled absolute because the stored topology is referenced in
    # place. Its own relative includes resolve against the store, which is where those files are.
    stored_topology=(source/inputs['topology']).resolve()
    (molecule/'molecule.itp').write_text('#include "'+str(stored_topology)+'"\n')
    preparation['topology_include']=str(stored_topology)
    if inputs['coordinate_format']=='pdb':
        (molecule/'molecule.gro').write_text(aa_molecules.pdb_gro((source/inputs['coordinates']).read_text()))
        preparation['coordinate_conversion']={'method':'aa_molecules.pdb_gro', 'version':1,
                                              'source':inputs['coordinates'], 'output':'molecule.gro',
                                              'units':'angstrom to nm; original atom order'}
    else:
        (molecule/'molecule.gro').write_bytes((source/inputs['coordinates']).read_bytes())
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
    # What already existed when prepare ran is named, by path and digest, rather than copied: the force-field tree and
    # each molecule file. The molecule's repo root is the folder the store folder sits in, so a run prepared from
    # `molecules/<id>/` records `molecules/<id>/<file>` against the repository.
    force_field_entry=run_inputs.published_tree('force_field', tree, label=ff.label)
    force_field_path=run_inputs.resolve(force_field_entry)
    references=[force_field_entry, *[
        run_inputs.published('molecule', source/relative, label=f'{molecule_snapshot["id"]}/{relative}',
                             repo_root=molecule_root.parent)
        for relative in sorted(molecule_snapshot['sha256'])]]
    caveats=[str(caveat) for caveat in (molecule_snapshot['metadata'].get('caveats') or [])]
    context={'protocol_version':VERSION,'settings':settings,'molecule_snapshot':molecule_snapshot,
             'input_preparation':preparation,'force_field':ff.name,'force_field_directory':tree.name,
             'caveats':caveats,
             # Where the referenced sources are, so the publication can hash them without a copy in the run. Absolute
             # because the module that reads them runs with a stage directory as its working directory, so the record
             # must not depend on the working directory it is read from.
             'force_field_path':str(force_field_path),
             'molecule_directory':str(source),
             'force_field_sha256':files.hashes(tree),'scientifically_validated':False}
    files.atomic_json(common/'context.json',context)
    n=molecule_snapshot['atom_count'];charge=round(molecule_snapshot['metadata']['net_charge'])
    from ...analysis.runs.references import index_group
    (common/'solute.ndx').write_text(index_group('Solute',1,n+1))
    # The force field is referenced, never copied, and every later stage copies this topology forward into its own
    # directory -- so its includes are absolute. They keep resolving from any stage directory and from the mirrored
    # copy in `inputs/`. The molecule shim is run-local and stays relative; it is generated data like the rest.
    top=(f'#include "{force_field_path / "forcefield.itp"}"\n#include "../common/molecule/molecule.itp"\n'
         f'#include "{force_field_path / ff.water_file}"\n#include "{force_field_path / "ions.itp"}"\n\n'
         f'[ system ]\nSingle solute in water\n[ molecules ]\n{molecule_snapshot["metadata"]["molecule_type"]} 1\n')
    scripts=[f'''gmx editconf -f ../common/molecule/molecule.gro {aa_box.editconf_arguments(settings['box_nm'], settings.get('box_shape', aa_box.DEFAULT_SHAPE))} -o boxed.gro
gmx grompp -f run.mdp -c boxed.gro -p system.top -o input-check.tpr
gmx solvate -cp boxed.gro -cs spc216.gro -p system.top -o system.gro
''','''cp ../01_solvation/system.top system.top
cp ../01_solvation/system.gro system.gro
gmx grompp -f run.mdp -c system.gro -p system.top -o ions.tpr
''']
    if charge:
        scripts[1]+=f'''"$PYTHON" -m dashboard.analysis.runs.references solvent-index system.gro {n}
printf '{ff.water_molecule}\\n' | gmx genion -s ions.tpr -o neutral.gro -p system.top -n solvent.ndx -pname {ff.cation} -nname {ff.anion} -neutral -seed {settings['aa_seed']}
mv neutral.gro system.gro
'''
    scripts[1]+='"$PYTHON" -m dashboard.analysis.runs.references counts system.top ../common/context.json\n'
    # Asked once for the whole run rather than once per stage: the build flavour is a property of the binary,
    # and on this host `gmx --version` costs 1.3 s, so four per-stage probes were 5.3 s of prepare_run's 5.4 s.
    flavour = gromacs_flavour()
    for i,kind in enumerate(('em','nvt','npt','production'),2):
        prev=Path(STAGES[i-1][1]).parent.as_posix(); coord='system.gro' if i==2 else 'run.gro'
        checkpoint=f' -t ../{prev}/run.cpt' if i>=4 else ''
        launcher, mdrun_flags = mdrun_command_flags(settings, kind, flavour)
        # No -ntmpi here. This host's GROMACS is an MPI build only -- /usr/local/gromacs/2026.3/bin/gmx is
        # a symlink to gmx_mpi -- and -ntmpi is a thread-MPI option, so mdrun aborts with "Setting the
        # number of thread-MPI ranks is only supported with thread-MPI and GROMACS was compiled without
        # thread-MPI". That killed every run on this machine before the first minimization step, which is
        # why runs/ was empty. The CPU budget is mdrun_ranks x mdrun_ntomp instead, checked against the
        # machine by mdrun_launch; a capability-aware probe that offers -ntmpi on a thread-MPI build is the
        # remaining piece.
        # A continue re-enters one stage with MDRUN_CONTINUE naming that stage's final checkpoint (`run.cpt`); the
        # leg then skips `grompp` and appends to the trajectory it already wrote. Without that variable the script
        # takes the same branch it always did, so an ordinary run's commands do not move.
        grompp = f'gmx grompp -f run.mdp -c ../{prev}/{coord}{checkpoint} -p system.top -o run.tpr'
        mdrun = f'{launcher}gmx mdrun -deffnm run {mdrun_flags} -v'
        continuation = ('if [ -n "${MDRUN_CONTINUE:-}" ] && [ "$MDRUN_CONTINUE" -ef "$(pwd -P)/run.cpt" ]; then\n'
                        f'  {launcher}gmx mdrun -deffnm run -cpi "$MDRUN_CONTINUE" -append {mdrun_flags} -v\n'
                        'else\n'
                        f'  {grompp}\n  {mdrun}\n'
                        'fi\n')
        scripts.append(f'cp ../{prev}/system.top system.top\n'
                       + (f'{grompp}\n{mdrun}\n' if kind == 'em' else continuation))
    scripts.append('''printf 'Solute\\nSolute\\n' | gmx trjconv -f ../06_production/run.xtc -s ../06_production/run.tpr -n ../common/solute.ndx -pbc mol -center -o lig.xtc
printf 'Solute\\n' | gmx trjconv -f ../06_production/run.xtc -s ../06_production/run.tpr -n ../common/solute.ndx -dump 0 -o lig.gro
printf 'Solute\\n' | gmx convert-tpr -s ../06_production/run.tpr -n ../common/solute.ndx -o lig.tpr
printf 'Temperature\\nPressure\\nDensity\\nPotential\\nTotal-Energy\\n0\\n' | gmx energy -f ../06_production/run.edr -o diagnostics.xvg
"$PYTHON" -m dashboard.analysis.runs.references publish ..
''')
    mdp_profiles={}
    for i,((_,relative),script) in enumerate(zip(STAGES,scripts)):
        target=stages/relative;target.parent.mkdir();target.write_text('#!/bin/bash\nset -euxo pipefail\n'+script)
        if i<len(MDP_PROFILES):
            profile=MDP_PROFILES[i]
            write_mdp(profile,target.parent/'run.mdp',mdp_values(settings,profile))
            mdp_profiles[f'{target.parent.relative_to(stages).as_posix()}/run.mdp']=profile
    (stages/'01_solvation/system.top').write_text(top)
    # `finish_prepared_run` mirrors the generated data into `inputs/` and writes the manifest naming the referenced
    # sources. What is copied is only what prepare synthesized: the tree and the molecule files stay where they live.
    # The helper modules are executed from the repository as package modules through `"$PYTHON" -m`, so the run records
    # their paths and digests instead of carrying a copy that could drift from the tree that supports it.
    protocol.finish_prepared_run(
        run_dir, stages, metadata=dict(context, run_type='aa_only', workflow_version=VERSION,
                                       mdp_profiles=mdp_profiles),
        tools=tool_metadata(), plan=[name for name,_ in STAGES],
        environment=recorded_environment(), references=references,
        modules={'aa_references': 'dashboard/analysis/runs/references.py',
                 'aa_molecules': 'dashboard/models/molecules/aa.py',
                 'files': 'dashboard/files.py'})


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
    settings_specs=lambda: devices.published_settings(SETTING_SPECS),
    stage_defaults=stage_defaults,
    normalize_settings=lambda settings=None, profile='standard': normalize_settings(settings, profile),
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
    choice_specs=lambda: devices.published_choices(CHOICE_SPECS),
)
