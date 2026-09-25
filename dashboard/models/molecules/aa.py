"""AA input discovery and metadata catalogue, separate from scientific model/evidence registries.

Directory checks establish input consistency, not force-field validity. Every
valid molecule is a candidate for the generic CG workflow; the run path
verifies inputs, mapping and reference checksums independently.
"""
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

try:
    from ... import files, paths
    _PROJECT_ROOT = paths.PROJECT_ROOT
except ImportError:  # imported as a run-local copy: no package, and no paths module beside it
    import files
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The packaged DDM results are read through the project root when the package is
# importable. A run-local copy never reads them, so its fallback only has to
# resolve to something; it must not require a module the run directory lacks.
PACKAGED = _PROJECT_ROOT / 'molecules/DDM/results/MMFF'


def validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value):
        raise ValueError('Molecule ID must be a folder name, not a path')
    return value


def cg_residue_name(record_or_snapshot):
    """Coarse-grained residue name for a molecule record or snapshot.

    metadata.cg_molecule_type overrides the folder id when the AA topology and
    the CG topology use different names (DDM's AA name is LIG1, its CG name is
    DDM). Defaults to the molecule id.
    """
    metadata = record_or_snapshot.get('metadata') or {}
    residue = metadata.get('cg_molecule_type') or record_or_snapshot['id']
    if len(residue) > 5 and isinstance(metadata.get('molecule_type'), str):
        residue = metadata['molecule_type']
    return residue


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'{path.name}: missing regular file (symlinks are not allowed)')
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f'{path.name}: exceeds 8 MiB input limit')
    return path.read_bytes()


def pdb_gro(text):
    """Import one unambiguous PDB structure, preserving atom order, Å to nm."""
    if sum(line.startswith("MODEL ") for line in text.splitlines()) > 1:
        raise ValueError("PDB must contain a single model")
    atoms = [line for line in text.splitlines() if line.startswith(('ATOM  ', 'HETATM'))]
    if not 1 <= len(atoms) <= 99999:
        raise ValueError('PDB atom count must be between 1 and 99999')
    rows = ['Imported AA molecule', str(len(atoms))]
    for i, line in enumerate(atoms, 1):
        xyz = [float(line[a:b]) / 10 for a, b in ((30,38),(38,46),(46,54))]
        if line[16:17].strip() or line[26:27].strip():
            raise ValueError('PDB alternate locations and insertion codes must be resolved first')
        if not all(math.isfinite(v) and len(f'{v:8.3f}') == 8 for v in xyz):
            raise ValueError('PDB coordinates are nonfinite or exceed GRO field limits')
        if not line[12:16].strip() or not line[17:21].strip():
            raise ValueError('PDB atom and residue names are required')
        rows.append(f'{int(line[22:26]):5d}{line[17:21].strip():<5}{line[12:16].strip():>5}{i:5d}' + ''.join(f'{v:8.3f}' for v in xyz))
    return '\n'.join([*rows, '   0.00000   0.00000   0.00000', ''])


def _gro(text):
    lines = text.splitlines()
    count = int(lines[1])
    if count < 1 or len(lines) != count + 3:
        raise ValueError('molecule.gro: invalid atom count or missing box')
    box = [float(x) for x in lines[-1].split()]
    if len(box) not in (3, 9) or not all(math.isfinite(x) for x in box):
        raise ValueError('molecule.gro: invalid box')
    atoms = []
    for i, line in enumerate(lines[2:-1], 1):
        xyz = [float(line[a:b]) for a,b in ((20,28),(28,36),(36,44))]
        if not all(math.isfinite(v) for v in xyz) or int(line[15:20]) != i:
            raise ValueError('molecule.gro: invalid coordinates or atom numbering')
        atoms.append((line[5:10].strip(), line[10:15].strip(), xyz))
    return atoms


def _itp(text):
    section = ''; atoms = []; molecule_types = []; charge = 0
    for raw in text.splitlines():
        line = raw.split(';',1)[0].strip()
        if not line or line.startswith('#'): continue
        if line.startswith('['):
            section = line.strip('[] ').strip(); continue
        parts = line.split()
        if section == 'moleculetype': molecule_types.append(parts[0])
        if section == 'atoms':
            if len(parts) < 7 or int(parts[0]) != len(atoms)+1:
                raise ValueError('molecule.itp: invalid atom numbering or incomplete atom definition')
            q = float(parts[6])
            if not math.isfinite(q): raise ValueError('molecule.itp: nonfinite charge')
            charge += q; atoms.append((parts[3], parts[4]))
    if len(molecule_types) != 1 or not atoms:
        raise ValueError('molecule.itp: expected one moleculetype and a nonempty atoms section')
    return molecule_types[0], atoms, charge


def topology_tree(folder, entry="molecule.itp"):
    """Resolve local quoted includes; only inactive position-restraint guards."""
    folder=Path(folder); contents={}; active=set()
    def read(relative):
        path=folder/relative
        if path.is_absolute() and not path.is_relative_to(folder): raise ValueError('Invalid topology include')
        if '..' in relative.parts or relative.is_absolute(): raise ValueError('Topology include traversal is not allowed')
        if any(p.is_symlink() for p in [path,*path.parents] if p==folder or p.is_relative_to(folder)):
            raise ValueError('Topology include symlinks are not allowed')
        key=relative.as_posix()
        if key in active: raise ValueError('Cyclic topology include: '+key)
        active.add(key); raw=_read(path); contents[key]=raw; expanded=[]; guards=[]
        for line in raw.decode().splitlines():
            stripped=line.split(';',1)[0].strip()
            if stripped.startswith('#'):
                include=re.fullmatch(r'#include\s+"([^"\\]+)"\s*',stripped)
                guard=re.fullmatch(r'#ifdef\s+(POSRES[A-Za-z0-9_]*)',stripped)
                if include:
                    child=read(relative.parent/Path(include[1]))
                    if not guards: expanded.append(child)
                elif guard: guards.append(guard[1])
                elif stripped=='#endif' and guards: guards.pop()
                else: raise ValueError('Unsupported topology directive: '+stripped)
            elif not guards: expanded.append(line)
        if guards: raise ValueError('Unclosed topology position-restraint guard')
        active.remove(key)
        return '\n'.join(expanded)
    return read(Path(entry)),contents


def discover(folder):
    """Choose a unique local topology/coordinate pair without following symlinks."""
    paths = list(files.safe_files(folder))
    topologies = [p for p in paths if p.suffix.lower() == '.itp']
    pairs = []
    for topology in topologies:
        nearby = [p for p in paths if p.parent == topology.parent and p.suffix.lower() in ('.gro', '.pdb')]
        matching = [p for p in nearby if p.stem == topology.stem]
        if not matching and sum(p.parent == topology.parent for p in topologies) == 1:
            matching = nearby
        gro = [p for p in matching if p.suffix.lower() == '.gro']
        coordinates = gro or matching
        pairs.extend((topology, coordinate) for coordinate in coordinates)
    if not pairs:
        raise ValueError('No matching ITP and coordinates found: provide molecule.itp + molecule.gro or a matching .itp + .gro/.pdb pair')
    if len(pairs) != 1:
        raise ValueError('Multiple topology/coordinate pairs found; keep one molecule input pair per folder')
    topology, coordinate = pairs[0]
    relative = lambda p: p.relative_to(folder).as_posix()
    for path in (topology, coordinate):
        if any(not re.fullmatch(r'[A-Za-z0-9_. -]+', part) for part in path.relative_to(folder).parts):
            raise ValueError('Unsupported characters in molecule input path')
    return {'topology': relative(topology), 'coordinates': relative(coordinate),
            'coordinate_format': coordinate.suffix.lower()[1:]}


def ensure_metadata(folder, molecule_id, expanded, topology_type, charge):
    """Publish missing metadata atomically without replacing an existing user file."""
    target = folder/'metadata.json'
    if target.exists() or target.is_symlink():
        return
    swissparam = bool(re.search(r'by user SwissParam', expanded, re.I))
    metadata = {'name': molecule_id, 'molecule_type': topology_type, 'net_charge': round(charge) if abs(charge-round(charge)) < 1e-4 else round(charge, 8),
                'force_field': 'charmm36-jul2022.ff' if swissparam else 'unknown',
                'water_model': 'tip3p' if swissparam else 'unknown',
                'generated': True,
                'parameterization': 'SwissParam' if swissparam else 'Unknown; set force_field and water_model before launch',
                'provenance': 'Identity and charge read from ITP. ' + (
                    'SwissParam detected; CHARMM36 July 2022 / TIP3P selected for the supported adapter. '
                    'GROMACS preprocessing must resolve parameters; scientific validation is not established.'
                    if swissparam else 'Force-field compatibility could not be inferred.')}
    fd, temporary = tempfile.mkstemp(prefix='.metadata-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(metadata, stream, indent=2, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)


def inspect(root, molecule_id, *, generate_metadata=True):
    validate_id(molecule_id)
    root = Path(root); folder = root / molecule_id
    if root.is_symlink() or folder.is_symlink() or not folder.is_dir():
        raise ValueError('Molecule directory is unavailable or is a symlink')
    result = {'id': molecule_id, 'name': molecule_id, 'path': f'molecules/{molecule_id}',
              'valid': False, 'executable': False, 'issues': [], 'blockers': [], 'sha256': {}}
    try:
        inputs = discover(folder)
        result['inputs'] = inputs
        expanded, dependencies = topology_tree(folder, inputs['topology'])
        topology_type, topology_atoms, charge = _itp(expanded)
        coordinate_bytes = _read(folder/inputs['coordinates'])
        coordinate_text = coordinate_bytes.decode()
        coords = _gro(pdb_gro(coordinate_text) if inputs['coordinate_format'] == 'pdb' else coordinate_text)
        if topology_atoms != [(residue, name) for residue, name, _ in coords]:
            raise ValueError('Coordinates and ITP atom counts, residue names, or atom order do not match')
        metadata_path = folder / 'metadata.json'
        if generate_metadata:
            ensure_metadata(folder, molecule_id, expanded, topology_type, charge)
        elif not metadata_path.is_file():
            raise ValueError('metadata.json is missing; select this molecule for a run to generate it')
        content = dict(dependencies)
        content[inputs['coordinates']] = coordinate_bytes
        content['metadata.json'] = _read(metadata_path)
        result['sha256'] = {name: hashlib.sha256(value).hexdigest() for name, value in content.items()}
        topology_parent = Path(inputs['topology']).parent
        reference_files = {('molecule.itp' if name == inputs['topology'] else Path(name).relative_to(topology_parent).as_posix()):
                           hashlib.sha256(value).hexdigest() for name, value in dependencies.items()}
        gro_bytes = pdb_gro(coordinate_text).encode() if inputs['coordinate_format'] == 'pdb' else coordinate_bytes
        reference_files['molecule.gro'] = hashlib.sha256(gro_bytes).hexdigest()
        result['reference_sha256'] = reference_files
        metadata = json.loads(content['metadata.json'])
        if not isinstance(metadata, dict): raise ValueError('metadata.json: expected an object')
        for key in ('name', 'force_field', 'water_model', 'molecule_type'):
            if not isinstance(metadata.get(key), str) or not metadata[key].strip() or len(metadata[key]) > 160:
                raise ValueError(f'metadata.json: {key} must be a nonempty string, at most 160 characters')
        if isinstance(metadata.get('net_charge'), bool) or not isinstance(metadata.get('net_charge'), (int,float)) or not math.isfinite(metadata['net_charge']):
            raise ValueError('metadata.json: finite numeric net_charge is required')
        if metadata['molecule_type'] != topology_type or abs(charge - metadata['net_charge']) > 1e-4:
            raise ValueError('Metadata molecule_type or net_charge does not match the ITP')
        result.update(name=metadata['name'], metadata=metadata, atom_count=len(coords), valid=True)
    except (OSError, ValueError, IndexError, TypeError, UnicodeError) as exc:
        result['issues'].append(str(exc))
    result['blockers'] = list(result['issues'])
    if result['valid']:
        # Every valid molecule is a candidate for the generic CG workflow.
        # A packaged-shape source supplies provenance hashes without gating.
        try:
            pdb = _read(PACKAGED/'lig1.pdb'); itp = _read(PACKAGED/'lig1.itp')
            if (content[inputs['topology']] == itp and coords == _gro(pdb_gro(pdb.decode()))
                    and metadata['force_field'] == 'charmm36-jul2022.ff'
                    and metadata['water_model'] == 'tip3p'):
                result['adapter_sources'] = {
                    'molecule.pdb': hashlib.sha256(pdb).hexdigest(),
                    'MMFF_lig1.itp': hashlib.sha256(itp).hexdigest(),
                }
        except (OSError, ValueError, IndexError, UnicodeError):
            pass
        result['executable'] = True
        result['adapter'] = 'cg-fast-forward'
        result['cg_residue_name'] = cg_residue_name(result)
    aa_blockers=list(result['issues'])
    if result['valid']:
        if metadata['force_field']!='charmm36-jul2022.ff' or metadata['water_model']!='tip3p':
            aa_blockers.append('AA-only supports CHARMM36 July 2022 with CHARMM TIP3P only')
        if abs(metadata['net_charge']-round(metadata['net_charge']))>1e-4:
            aa_blockers.append('Net charge must be integral for monovalent counterion neutralization')
        if not re.fullmatch(r'[A-Za-z0-9_+-]{1,80}',metadata['molecule_type']):
            aa_blockers.append('Unsupported topology molecule name')
    result['capabilities']={'aa_only':{'executable':not aa_blockers,'blockers':aa_blockers},
                            'aa_cg':{'executable':result['executable'],'blockers':result['blockers']}}
    return result


def catalogue(root, *, generate_metadata=False):
    root = Path(root)
    if not root.is_dir() or root.is_symlink(): return []
    return [inspect(root, path.name, generate_metadata=generate_metadata) for path in sorted(root.iterdir())
            if path.is_dir() and not path.is_symlink() and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', path.name)]


def selection(root, molecule_id, run_type='aa_cg'):
    record = inspect(root, molecule_id, generate_metadata=True)
    if run_type=='aa_only':
        capability=record['capabilities']['aa_only']
        if not capability['executable']: raise ValueError('; '.join(capability['blockers']))
        return {key:record[key] for key in ('id','name','path','metadata','sha256','atom_count','inputs','reference_sha256')} | {'adapter':'aa-charmm36'}
    if run_type!='aa_cg':raise ValueError('Unknown run type')
    if not record['executable']: raise ValueError('; '.join(record['blockers']))
    fields = ('id','name','path','metadata','sha256','adapter','inputs','reference_sha256','cg_residue_name')
    snapshot = {key: record[key] for key in fields}
    if 'adapter_sources' in record:
        snapshot['adapter_sources'] = record['adapter_sources']
    return snapshot


def verify_selection(root, snapshot):
    if selection(root, snapshot['id'], 'aa_only' if snapshot.get('adapter')=='aa-charmm36' else 'aa_cg') != snapshot:
        raise ValueError('Molecule files changed since this run was queued; select the molecule again')


def verify_prepared(aa_directory, snapshot):
    if 'adapter_sources' not in snapshot:
        raise ValueError('No packaged adapter sources recorded; prepared input verification is unavailable for this molecule')
    files.verify(aa_directory, snapshot['adapter_sources'])
