"""Technical AA reference publication and immutable shared-source resolution."""
import hashlib
import json
import math
import re
import sys
from pathlib import Path

try:
    from ... import files
    from ...models.molecules import aa as aa_molecules
except ImportError:
    import aa_molecules
    import files


def identity(snapshot):
    """The identity of a molecule *selection*, from its per-file digests and its chemistry.

    Two spellings are read because two exist: `reference_sha256` is what `molecules/aa.py` writes into a selection, and
    `sha256` is the older name for the same map. What is *not* accepted is the scalar of the same name that a reference
    block carries (`bonded/fitting.py`): that is a digest of one published `reference.json`, and feeding it here was an
    `AttributeError` on `.items()`. The eager default that used to sit here was worse -- `snapshot.get('reference_sha256',
    snapshot['sha256'])` raised `KeyError('sha256')` for a snapshot that had the one key it was looking for.
    """
    metadata=snapshot['metadata']
    digests=(snapshot.get('reference_files_sha256') or snapshot.get('reference_sha256')
             or snapshot.get('sha256') or {})
    if not isinstance(digests, dict):
        raise ValueError('A molecule selection states per-file digests; this is a single digest')
    return hashlib.sha256(json.dumps({'files':{k:v for k,v in digests.items() if k!='metadata.json'},
        'chemistry':{k:metadata[k] for k in ('force_field','water_model','molecule_type','net_charge')}},sort_keys=True).encode()).hexdigest()


def index_group(name,start,stop):
    return f'[ {name} ]\n'+'\n'.join(' '.join(str(i) for i in range(first,min(first+15,stop))) for first in range(start,stop,15))+'\n'


def counts(topology,context):
    section=''; result={}
    for raw in Path(topology).read_text().splitlines():
        line=raw.split(';',1)[0].strip()
        if line.startswith('['):section=line.strip('[] ').strip()
        elif section=='molecules' and line:
            name,count=line.split();result[name]=result.get(name,0)+int(count)
    metadata=json.loads(Path(context).read_text())['molecule_snapshot']['metadata']
    if result.get(metadata['molecule_type'])!=1:raise ValueError('Expected exactly one solute')
    charge=metadata['net_charge']+result.get('SOD',0)-result.get('CLA',0)
    if abs(charge)>1e-4:raise ValueError('Counterion placement did not neutralize the system')
    payload={'molecule_counts':result,'net_charge_e':charge,'added_salt_molar':0}
    files.atomic_json(Path(topology).with_name('composition.json'),payload)
    return payload


def _locator(path):
    """Where a shared source lives, in a spelling that still resolves in another checkout.

    A published reference travels: the run directory is copied to another workspace, a colleague's checkout or a
    machine whose repository lives at a different absolute path. An absolute `path` published here would then name
    a directory that only this machine has. A source under the checkout is recorded as `repo`/`workspace` plus a
    relative path, which `_source_path` resolves against whichever checkout reads the record. A source outside the
    checkout (a force field installed under `/opt`, a molecule in `/data`) keeps its absolute path: there is no
    portable spelling for it, and `_verify_referenced` treats its absence as provenance it cannot re-check rather
    than as corruption.
    """
    resolved=Path(path).resolve()
    try:
        from ... import paths as path_config
    except ImportError:
        return {'root':'absolute','path':str(resolved)}
    selected=path_config.current()
    for root,base in (('repo',selected.project_root),('workspace',selected.workspace)):
        try: relative=resolved.relative_to(Path(base).resolve())
        except ValueError: continue
        return {'root':root,'path':relative.as_posix()}
    return {'root':'absolute','path':str(resolved)}


def _source_path(entry):
    """The filesystem path a recorded source names, resolved through this checkout when it was recorded relative."""
    path=Path(entry.get('path') or '')
    root=entry.get('root') or None
    if root is None or root=='absolute' or path.is_absolute():
        return path
    try:
        from ... import paths as path_config
        selected=path_config.current()
    except ImportError:raise ValueError('AA reference source is relative but this reader has no project root') from None
    base={'repo':selected.project_root,'workspace':selected.workspace}.get(root)
    if base is None:raise ValueError(f'AA reference source has an unknown root: {root!r}')
    return Path(base)/path


def referenced_sources(context):
    """The files this run read rather than wrote: where prepare found them, and the digest it recorded.

    A run no longer carries the force-field tree or the molecule's own files, so a publication hashes them at the
    paths prepare resolved. Each source is recorded with a locator (`_locator`) rather than only an absolute path,
    so the record still verifies after the run directory travels to another checkout. The record is also what
    `verify` re-hashes: a shared input changed after prepare is refused rather than silently published under a
    digest it no longer has.
    """
    sources=[]
    tree=context.get('force_field_path')
    if tree:
        tree=Path(tree);measured=files.hashes(tree)
        if measured!=context.get('force_field_sha256'):raise ValueError('Force-field tree changed since this run was prepared: '+str(tree))
        sources.append({'role':'force_field','label':tree.name,'kind':'directory',**_locator(tree),
                        'sha256':files.json_sha256(measured),'files':len(measured)})
    folder=context.get('molecule_directory');snapshot=context.get('molecule_snapshot') or {}
    if folder:
        folder=Path(folder)
        for relative,digest in sorted((snapshot.get('sha256') or {}).items()):
            path=folder/relative
            if path.is_symlink() or not path.is_file():raise ValueError('Molecule file is missing: '+str(path))
            measured=files.sha256(path)
            if measured!=digest:raise ValueError('Molecule file changed since this run was prepared: '+relative)
            sources.append({'role':'molecule','label':relative,'kind':'file',**_locator(path),
                            'sha256':measured,'bytes':path.stat().st_size})
    return sources


def _verify_referenced(entry):
    """Re-hash one source `referenced_sources` recorded, refusing a changed one by name.

    A source that is not on this machine is a warning, not a refusal: the run directory carries its own artifacts
    and hashes them in `verify`'s run-relative map, so a foreign checkout cannot corrupt the trajectory. What this
    re-hash proves is provenance -- that the force field and molecule files this reference was built from are still
    the ones the record names. That claim cannot be checked where those files do not exist, and pretending
    otherwise would drop an otherwise intact run from every picker.
    """
    path=_source_path(entry)
    if not path.exists():
        return {'role':entry.get('role'),'label':entry.get('label'),'path':str(path),
                'reason':'this source is not present on this host; its provenance was not re-checked'}
    if path.is_symlink():raise ValueError('AA reference source symlinks are not allowed: '+str(path))
    if entry.get('kind')=='directory':
        if not path.is_dir():raise ValueError('AA reference source is not a directory: '+str(path))
        measured=files.json_sha256(files.hashes(path))
    else:
        if not path.is_file():raise ValueError('AA reference source is not a file: '+str(path))
        measured=files.sha256(path)
    if measured!=entry.get('sha256'):raise ValueError(f'AA reference {entry.get("role")} source changed since publication: {path}')
    return None


def publish(stages):
    import MDAnalysis as mda
    import numpy as np
    stages=Path(stages).resolve();output=stages/'07_reference'
    context=json.loads((stages/'common/context.json').read_text());snapshot=context['molecule_snapshot']
    original=aa_molecules._gro((stages/'common/molecule/molecule.gro').read_text())
    coordinates=aa_molecules._gro((output/'lig.gro').read_text())
    if [(r,n) for r,n,_ in original]!=[(r,n) for r,n,_ in coordinates]:raise ValueError('Published solute atom order differs from source')
    universe=mda.Universe(str(output/'lig.gro'),str(output/'lig.xtc'));times=[]
    try:
        if len(universe.atoms)!=len(original):raise ValueError('Reference atom count mismatch')
        for frame in universe.trajectory:
            if not np.isfinite(frame.positions).all() or not math.isfinite(frame.time):raise ValueError('Nonfinite reference coordinates/time')
            times.append(float(frame.time))
    finally:universe.trajectory.close()
    if len(times)<2 or not np.all(np.diff(times)>0):raise ValueError('Reference needs at least two increasing frames')
    duration=context['settings']['aa_production_ps'];interval=context['settings']['output_interval_ps']
    if abs(times[0])>.01 or abs(times[-1]-duration)>interval+.01:raise ValueError('Reference trajectory does not cover the recorded production duration')
    diagnostic=output/'diagnostics.xvg';values=[];labels={}
    for line in diagnostic.read_text().splitlines():
        match=re.match(r'@\s+s(\d+)\s+legend\s+"([^"]+)"',line)
        if match:labels[int(match[1])]=match[2]
        elif line and line[0] not in '#@':values.append([float(x) for x in line.split()])
    array=np.asarray(values)
    if array.ndim!=2 or not len(array) or not np.isfinite(array).all():raise ValueError('Unreadable/nonfinite energy diagnostics')
    units={'Temperature':'K','Pressure':'bar','Density':'kg/m^3','Potential':'kJ/mol','Total Energy':'kJ/mol','Total-Energy':'kJ/mol'}
    diagnostics={name:{'mean':float(array[:,i+1].mean()),'std':float(array[:,i+1].std()),'unit':units.get(name,'GROMACS units')} for i,name in labels.items() if i+1<array.shape[1]}
    artifacts={name:'stages/07_reference/'+name for name in ('lig.gro','lig.xtc','lig.tpr')}
    hashed={str(p.relative_to(stages.parent)):files.sha256(p) for p in files.safe_files(output) if p.name!='reference.json'}
    # What the run referenced is named by the store it lives in rather than hashed as a copy inside the run; what it
    # synthesized is hashed here. A run prepared before the input model still holds the copies, so its publication
    # hashes them exactly as it always did.
    referenced=referenced_sources(context)
    if referenced:
        for relative in ('common/molecule/molecule.gro','common/molecule/molecule.itp'):
            hashed['stages/'+relative]=files.sha256(stages/relative)
    else:
        directory=context.get('force_field_directory') or 'charmm36-jul2022.ff'
        for relative in ('common/molecule','common/'+directory):
            hashed.update({f'stages/{relative}/{key}':value for key,value in files.hashes(stages/relative).items()})
    for relative in ('common/context.json','common/solute.ndx','02_ions/composition.json','06_production/run.gro','06_production/run.tpr','06_production/run.xtc','06_production/run.cpt','06_production/run.edr','06_production/run.log','06_production/system.top','06_production/run.mdp'):
        hashed['stages/'+relative]=files.sha256(stages/relative)
    #: Schema 2 records each referenced source with a portable locator (`root` + relative `path`); schema 1 records
    #: predate that and carry an absolute path, which `_source_path` still resolves when it exists on this host.
    result={'schema_version':2,'reference_eligible':True,'scientifically_validated':False,
            'molecule_identity':identity(snapshot),'molecule_snapshot':snapshot,'protocol_version':context['protocol_version'],
            'settings':context['settings'],'force_field_sha256':context['force_field_sha256'],
            'artifacts':artifacts,'sha256':hashed,'referenced_sources':referenced,'frames':{'count':len(times),'atoms':len(original),'times_ps':times,'start_ps':times[0],'end_ps':times[-1]},
            'composition':json.loads((stages/'02_ions/composition.json').read_text()),'diagnostics':diagnostics,
            'diagnostics_source':'stages/07_reference/diagnostics.xvg',
            'limitations':['Technical eligibility only; convergence and force-field accuracy have not been established',f'Single-solute AA production: {duration:g} ps; no added salt']}
    files.atomic_json(output/'reference.json',result)
    return result


def verify(run_dir,expected=None,molecule_snapshot=None,settings=None):
    run_dir=Path(run_dir)
    if run_dir.is_symlink():raise ValueError('Reference run symlinks are not allowed')
    manifest=json.loads((run_dir/'manifest.json').read_text())
    if manifest.get('run_type')!='aa_only' or manifest.get('status')!='completed':raise ValueError('Reference must be a completed AA-only run')
    path=run_dir/'stages/07_reference/reference.json'
    data=json.loads(path.read_text())
    if data.get('reference_eligible') is not True:raise ValueError('AA reference failed technical checks')
    hashes=dict(data['sha256']);hashes['stages/07_reference/reference.json']=files.sha256(path)
    if expected is not None and hashes!=expected:raise ValueError('AA reference hashes changed since attachment')
    for relative in hashes:
        target=run_dir/relative
        if any(p.is_symlink() for p in (target,*target.parents) if p==run_dir or p.is_relative_to(run_dir)):
            raise ValueError('Reference artifact symlinks are not allowed')
    files.verify(run_dir,hashes)
    warnings=[]
    for entry in data.get('referenced_sources') or []:
        warning=_verify_referenced(entry)
        if warning:warnings.append(warning)
    if molecule_snapshot is not None and identity(molecule_snapshot)!=data['molecule_identity']:raise ValueError('AA reference molecule/topology does not match')
    if settings:
        for key,value in data['settings'].items():
            if key not in settings:continue
            # Scheme choices travel as strings ('auto', 'gpu', 'cpu'), so a shared reference matches them by
            # equality; the numeric settings keep their tolerance.
            try:same=abs(float(settings[key])-float(value))<=1e-6
            except (TypeError,ValueError):same=str(settings[key])==str(value)
            if not same:raise ValueError('AA protocol settings must match the shared reference: '+key)
    return dict(data,sha256=hashes,warnings=warnings)


def resolve(runs_root,source_id,expected=None,molecule_snapshot=None,settings=None):
    if not isinstance(source_id,str) or not re.fullmatch(r'[a-f0-9]{12}',source_id):raise ValueError('Invalid AA source run ID')
    root=Path(runs_root)/source_id
    data=verify(root,expected,molecule_snapshot,settings)
    return root/'stages/07_reference',data


if __name__=='__main__':
    if sys.argv[1]=='publish':publish(sys.argv[2])
    elif sys.argv[1]=='counts':counts(sys.argv[2],sys.argv[3])
    elif sys.argv[1]=='solvent-index':
        count=int(Path(sys.argv[2]).read_text().splitlines()[1]);solute=int(sys.argv[3])
        if count<=solute:raise ValueError('No solvent available for neutralization')
        Path('solvent.ndx').write_text(index_group('SOL',solute+1,count+1))
