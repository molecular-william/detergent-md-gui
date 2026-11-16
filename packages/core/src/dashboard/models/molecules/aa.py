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
PACKAGED = _PROJECT_ROOT / 'molecules/DDM/v1/results/MMFF'


def validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value):
        raise ValueError('Molecule ID must be a folder name, not a path')
    return value


#: A version directory's name: a folder name, never a path, and never a dotted temporary one.
VERSION_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')


def validate_version(value):
    if not isinstance(value, str) or not VERSION_NAME.fullmatch(value):
        raise ValueError('Molecule version must be a folder name, not a path')
    return value


def _version_key(version):
    """Order versions as versions, not as strings: v2 is older than v10."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', str(version)) if part)


def _version_folders(folder):
    """The children of a molecule folder that state a version, as (path, version).

    A child without a readable metadata, or without a version string in it, is not a version directory: the legacy
    shape keeps its own subdirectories (a SwissParam results/ tree, for one), and none of them is a version of the
    molecule. The stated version is returned rather than the directory name so a folder can be named one thing and
    state another.
    """
    folder = Path(folder)
    found = []
    if folder.is_symlink() or not folder.is_dir():
        return found
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            declared = _declared_metadata(path)
        except (OSError, ValueError, IndexError, TypeError, UnicodeError):
            continue
        version = declared.get('version')
        if isinstance(version, str) and VERSION_NAME.fullmatch(version):
            found.append((path, version))
    return found


def _version_names(folder):
    return {path.name for path, _version in _version_folders(folder)}


def local_files(folder):
    """The files a molecule folder itself holds, with a version directory's own tree left out.

    A legacy folder may gain version directories beside its files (an import never replaces one), and discovery
    reads one topology/coordinate pair from the folder's own files; a version's pair belongs to that version.
    """
    folder = Path(folder)
    excluded = _version_names(folder)
    return [path for path in (files.safe_files(folder) or [])
            if not excluded or path.relative_to(folder).parts[0] not in excluded]


def versions(root, molecule_id):
    """The versions one molecule folder states, oldest first; empty when it states none."""
    validate_id(molecule_id)
    found = _version_folders(Path(root) / molecule_id)
    return [version for _path, version in sorted(found, key=lambda item: (_version_key(item[1]), item[0].name))]


def resolve(root, molecule_id, version=None):
    """The folder a molecule id names, and the version it read.

    A molecule folder is molecules/<id>/<version>/ when it states metadata.version. No version named resolves the
    newest one stated (metadata version, then the directory name); a named version that is not installed is refused
    rather than answered by another, because a run that named one must not simulate different files. A folder with
    no version directory is the retired legacy shape, and is refused rather than read as its own version.
    """
    validate_id(molecule_id)
    root = Path(root)
    id_folder = root / molecule_id
    if root.is_symlink() or id_folder.is_symlink() or not id_folder.is_dir():
        raise ValueError('Molecule directory is unavailable or is a symlink')
    installed = _version_folders(id_folder)
    if version is not None:
        validate_version(version)
        for path, stated in installed:
            if stated == version:
                return path, stated
        folder = id_folder / version
        if folder.is_dir() and not folder.is_symlink():
            # An import validates its folder before the metadata that names the version is written.
            return folder, version
        raise ValueError(f'molecules/{molecule_id}/{version} is not an installed version')
    if installed:
        path, stated = max(installed, key=lambda item: (_version_key(item[1]), item[0].name))
        return path, stated
    raise ValueError(f'molecules/{molecule_id} has no version directory; '
                     'migrate it with cli/migrate_molecule_versions.py')


def selected_folder(molecule_root, snapshot):
    """The directory a selection names, under the molecule root it was selected from."""
    root = Path(molecule_root)
    recorded = snapshot.get('path')
    if isinstance(recorded, str):
        try:
            return root / Path(recorded).relative_to('molecules')
        except ValueError:
            pass
    return resolve(root, snapshot['id'], snapshot.get('version'))[0]


def next_version(folder):
    """The next free version directory of one molecule folder: v1, v2, ... -- never an existing name."""
    folder = Path(folder)
    names = {path.name for path in folder.iterdir() if path.is_dir() and not path.is_symlink()} \
        if folder.is_dir() and not folder.is_symlink() else set()
    numbers = [int(match.group(1)) for name in names if (match := re.fullmatch(r'v(\d+)', name))]
    candidate = max(numbers, default=0) + 1
    while f'v{candidate}' in names:
        candidate += 1
    return f'v{candidate}'


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
    """The .gro atoms as `(residue, name, position)`, with this reader's count, box and numbering checks."""
    # Deferred: a run-local copy may lack the package this module belongs to, and the module import must not fail.
    from ...analysis.runs import structures
    return [(atom['residue'], atom['name'], atom['position'])
            for atom in structures.read_gro_text(text, source='molecule.gro',
                                                 check_numbering=True, finite_box=True)]


def _itp(text):
    """One moleculetype's name, its atoms as `(residue, name, type)` in file order, and its charge sum.

    The atom numbering is read as the contiguity rule it is: a row must be the next number, so a gap or a reordered
    file is refused rather than silently accepted. A mass column after the charge is checked when the file states
    one -- a nonfinite mass is a topology `grompp` cannot integrate, and a coarse-grained bead has no other check.
    """
    # Deferred: a run-local copy may lack the package this module belongs to, and the module import must not fail.
    from ... import itp
    molecule_types = [fields[0] for _number, fields in itp.rows(text, 'moleculetype')
                      if not fields[0].startswith('#')]
    atoms = []; charge = 0
    for _number, parts in itp.rows(text, 'atoms'):
        if parts[0].startswith('#'): continue
        if len(parts) < 7 or int(parts[0]) != len(atoms)+1:
            raise ValueError('molecule.itp: invalid atom numbering or incomplete atom definition')
        q = float(parts[6])
        if not math.isfinite(q): raise ValueError('molecule.itp: nonfinite charge')
        if len(parts) > 7 and not math.isfinite(float(parts[7])):
            raise ValueError('molecule.itp: nonfinite mass')
        charge += q; atoms.append((parts[3], parts[4], parts[1]))
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
    paths = local_files(folder)
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


def ensure_metadata(folder, molecule_id, expanded, topology_type, charge, *, version=None):
    """Publish missing metadata atomically without replacing an existing user file."""
    target = folder/'metadata.json'
    if target.exists() or target.is_symlink():
        return
    swissparam = bool(re.search(r'by user SwissParam', expanded, re.I))
    metadata = {**({'version': version} if version is not None else {}),
                'name': molecule_id, 'molecule_type': topology_type, 'net_charge': round(charge) if abs(charge-round(charge)) < 1e-4 else round(charge, 8),
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


def cg_model(folder, *, discovered=None):
    """One coarse-grained molecule folder's own model, validated the way the catalogue validates a molecule.

    This is the reader a `cg` folder and a pdc build share. The folder states its inputs the way every molecule
    does (`discover`), its topology is one moleculetype (`topology_tree`/`_itp`, which also enforces contiguous
    numbering, finite charges and masses, and a charge sum), and its `.gro` must name the same beads in the same
    order with finite positions. Only two fields the catalogue does not need are added for the consumer: the beads
    with their positions, shifted so the molecule's centroid is the origin (a placement stamps the molecule's own
    body), and the residue the topology names, which is what the coordinates and `[ molecules ]` are written with.
    """
    from ...analysis.runs import structures
    folder = Path(folder)
    inputs = discovered or discover(folder)
    expanded, dependencies = topology_tree(folder, inputs['topology'])
    molecule_type, atoms, charge = _itp(expanded)
    # The catalogue's other moleculetype reader, for the bonded terms this one does not look at: a `[ bonds ]` or
    # `[ constraints ]` row nothing can read is a broken detergent definition, and its names and types must agree
    # with the charge-carrying rows above or one of the two readings is wrong.
    declared = structures.read_moleculetype_text(expanded, source=inputs['topology'])
    if (declared['atoms'] != [name for _, name, _ in atoms]
            or declared['types'] != [bead_type for _, _, bead_type in atoms]):
        raise ValueError('molecule.itp: its atoms cannot be read two ways')
    coordinate_bytes = _read(folder/inputs['coordinates'])
    coordinates = structures.read_gro(folder/inputs['coordinates'])
    if [(atom['residue'], atom['name']) for atom in coordinates] != [(residue, name) for residue, name, _ in atoms]:
        raise ValueError('Coordinates and ITP atom counts, residue names, or atom order do not match')
    if not all(math.isfinite(value) for atom in coordinates for value in atom['position']):
        raise ValueError('Coordinates are nonfinite')
    centroid = [sum(atom['position'][axis] for atom in coordinates) / len(coordinates) for axis in range(3)]
    beads = [{'name': name, 'residue': molecule_type[:5], 'type': bead_type,
              'position': [value - centre for value, centre in zip(atom['position'], centroid)]}
             for atom, (_, name, bead_type) in zip(coordinates, atoms)]
    return {'molecule_id': folder.name, 'molecule_type': molecule_type, 'residue': molecule_type[:5],
            'beads': beads, 'topology': expanded, 'charge': charge,
            'inputs': inputs, 'dependencies': dependencies, 'coordinate_bytes': coordinate_bytes}


def _declared_metadata(folder):
    """The `metadata.json` a folder states, as an object, before its inputs are validated; `{}` when absent.

    `kind` is read here first because it decides which validator runs, and `cg` is only ever explicit: a folder
    whose bead types look coarse-grained but whose metadata does not say so stays on the all-atom path, where the
    force-field gate reports what it cannot check rather than a guess being made from a type column.
    """
    path = folder/'metadata.json'
    if not path.exists() and not path.is_symlink():
        return {}
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError('metadata.json: expected an object')
    return value


def _cg_metadata(metadata, molecule_id, model):
    """A `cg` folder's metadata: the kind, and whatever else it states has to agree with the topology."""
    name = metadata.get('name')
    if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 160):
        raise ValueError('metadata.json: name must be a nonempty string, at most 160 characters')
    if metadata.get('molecule_type') is not None and metadata['molecule_type'] != model['molecule_type']:
        raise ValueError('Metadata molecule_type does not match the ITP')
    charge = metadata.get('net_charge')
    if charge is not None:
        if isinstance(charge, bool) or not isinstance(charge, (int, float)) or not math.isfinite(charge):
            raise ValueError('metadata.json: finite numeric net_charge is required when stated')
        if abs(charge - model['charge']) > 1e-4:
            raise ValueError('Metadata net_charge does not match the ITP')
    return str(name or molecule_id)


def _cg_result(result, folder, molecule_id, metadata):
    """Fill a `cg` record: its model, its digests, and the run types it is not an input for."""
    model = cg_model(folder)
    inputs = model['inputs']
    result['inputs'] = inputs
    content = dict(model['dependencies'])
    content[inputs['coordinates']] = model['coordinate_bytes']
    content['metadata.json'] = _read(folder/'metadata.json')
    result['sha256'] = {name: hashlib.sha256(value).hexdigest() for name, value in content.items()}
    topology_parent = Path(inputs['topology']).parent
    result['reference_sha256'] = {
        **{('molecule.itp' if name == inputs['topology'] else Path(name).relative_to(topology_parent).as_posix()):
           hashlib.sha256(value).hexdigest() for name, value in model['dependencies'].items()},
        'molecule.gro': hashlib.sha256(model['coordinate_bytes']).hexdigest()}
    name = _cg_metadata(metadata, molecule_id, model)
    # A CG-only molecule is a detergent model, not an all-atom source: the bead editor and both AA run types must
    # read a stated refusal rather than a force field it does not have. The reason is the same sentence in both
    # capabilities because it is the same fact about the folder.
    blocker = ('a coarse-grained (cg) molecule is not an all-atom topology: it is a pdc detergent, not an '
               'aa_only or aa_cg source')
    result.update(name=name, metadata=metadata, atom_count=len(model['beads']), valid=True, executable=False,
                  kind='cg', cg_residue_name=metadata.get('cg_molecule_type') or model['residue'],
                  blockers=[blocker])
    result['capabilities'] = {'aa_only': {'executable': False, 'blockers': [blocker]},
                              'aa_cg': {'executable': False, 'blockers': [blocker]},
                              'cg': {'executable': True, 'blockers': []}}
    return result


def inspect(root, molecule_id, *, version=None, generate_metadata=True):
    """One molecule record: the newest version a folder states, or the version a selection names."""
    folder, resolved = resolve(root, molecule_id, version)
    return _inspect_folder(molecule_id, folder, resolved, generate_metadata)


def _inspect_folder(molecule_id, folder, version, generate_metadata):
    folder = Path(folder)
    result = {'id': molecule_id, 'name': molecule_id, 'version': version,
              'path': f'molecules/{molecule_id}/{folder.name}',
              'kind': 'aa', 'valid': False, 'executable': False, 'issues': [], 'blockers': [], 'sha256': {}}
    kind = 'aa'
    try:
        declared = _declared_metadata(folder)
        kind = declared.get('kind', 'aa')
        if kind not in ('aa', 'cg'):
            raise ValueError("metadata.json: kind must be 'aa' or 'cg'")
        result['kind'] = kind
        if kind == 'cg':
            return _cg_result(result, folder, molecule_id, declared)
        inputs = discover(folder)
        result['inputs'] = inputs
        expanded, dependencies = topology_tree(folder, inputs['topology'])
        topology_type, topology_atoms, charge = _itp(expanded)
        coordinate_bytes = _read(folder/inputs['coordinates'])
        coordinate_text = coordinate_bytes.decode()
        coords = _gro(pdb_gro(coordinate_text) if inputs['coordinate_format'] == 'pdb' else coordinate_text)
        if ([(residue, name) for residue, name, _ in topology_atoms]
                != [(residue, name) for residue, name, _ in coords]):
            raise ValueError('Coordinates and ITP atom counts, residue names, or atom order do not match')
        metadata_path = folder / 'metadata.json'
        if generate_metadata:
            ensure_metadata(folder, molecule_id, expanded, topology_type, charge, version=version)
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
    if kind == 'cg':
        # A CG folder that failed validation still reports the two AA run types as refused, with the actual issue
        # rather than the capability sentence: the reader is looking at a broken file, not at the wrong run type.
        result['blockers'] = list(result['issues'])
        result['capabilities'] = {name: {'executable': False, 'blockers': result['blockers']}
                                  for name in ('aa_only', 'aa_cg', 'cg')}
        return result
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
        # Which force fields a molecule may be run with is the registry's answer rather than a literal, and the
        # metadata names the tree the molecule's own topology was parameterised against. A run then selects one
        # of the entries; whether the pairing is sound is the entry's business (the CGenFF version rule), not
        # something this gate can judge from a directory name.
        from ...execution import forcefields
        trees={forcefields.entry(name).directory for name in forcefields.names()}
        waters={forcefields.entry(name).water_file for name in forcefields.names()}
        if metadata['force_field'] not in trees:
            aa_blockers.append('AA-only supports these force-field trees: '+', '.join(sorted(trees)))
        # The metadata names a water model rather than a file ('tip3p'), so it is compared with the file names
        # the entries use by adding the extension once, not by assuming which of the two forms it holds.
        water=str(metadata['water_model'])
        if not water.endswith('.itp'):
            water+='.itp'
        if water not in waters:
            aa_blockers.append('AA-only supports these water models: '
                               +', '.join(sorted(name[:-4] for name in waters)))
        if abs(metadata['net_charge']-round(metadata['net_charge']))>1e-4:
            aa_blockers.append('Net charge must be integral for monovalent counterion neutralization')
        if not re.fullmatch(r'[A-Za-z0-9_+-]{1,80}',metadata['molecule_type']):
            aa_blockers.append('Unsupported topology molecule name')
    result['capabilities']={'aa_only':{'executable':not aa_blockers,'blockers':aa_blockers},
                            'aa_cg':{'executable':result['executable'],'blockers':result['blockers']}}
    return result


def _refused(molecule_id, error):
    """The record a folder that states no version is listed as: invalid, with the migration it needs."""
    result = {'id': molecule_id, 'name': molecule_id, 'version': None, 'path': f'molecules/{molecule_id}',
              'kind': 'aa', 'valid': False, 'executable': False, 'issues': [str(error)],
              'blockers': [str(error)], 'sha256': {}}
    result['capabilities'] = {name: {'executable': False, 'blockers': result['blockers']}
                              for name in ('aa_only', 'aa_cg', 'cg')}
    return result


def catalogue(root, *, generate_metadata=False):
    root = Path(root)
    if not root.is_dir() or root.is_symlink(): return []
    records = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.is_symlink() or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', path.name):
            continue
        try:
            records.append(inspect(root, path.name, generate_metadata=generate_metadata))
        except ValueError as error:
            # A folder with no version directory is retired data, not an unreadable molecule: it stays listed so the
            # reader is told which migration it needs, rather than disappearing from the catalogue.
            records.append(_refused(path.name, error))
    return records


def selection(root, molecule_id, run_type='aa_cg', *, version=None):
    """One run's molecule selection: where it is, which version, and the metadata a run needs.

    The selection names the molecule and its version; it deliberately carries no per-file digest, because the
    version directory is the change detector.
    """
    return _selection(inspect(root, molecule_id, version=version, generate_metadata=True), run_type)


def _selection(record, run_type='aa_cg'):
    if run_type == 'cg':
        capability = record['capabilities']['cg']
        if not capability['executable']: raise ValueError('; '.join(capability['blockers']))
    elif run_type == 'aa_only':
        capability = record['capabilities']['aa_only']
        if not capability['executable']: raise ValueError('; '.join(capability['blockers']))
    elif run_type != 'aa_cg':
        raise ValueError('Unknown run type')
    elif not record['executable']:
        raise ValueError('; '.join(record['blockers']))
    snapshot = {key: record[key] for key in ('id', 'version', 'path', 'metadata', 'inputs')}
    snapshot['atom_count'] = record['atom_count']
    if 'adapter_sources' in record:
        snapshot['adapter_sources'] = record['adapter_sources']
    if run_type == 'cg':
        snapshot.update(kind=record['kind'], cg_residue_name=record['cg_residue_name'])
    elif run_type == 'aa_only':
        snapshot['adapter'] = 'aa-charmm36'
    else:
        snapshot.update(adapter=record['adapter'], cg_residue_name=record['cg_residue_name'])
    return snapshot


def verify_selection(root, snapshot):
    """Refuse a selection whose molecule or version no longer reads as it did when it was queued.

    A selection names a version; a folder with no version directory is refused by `resolve` with the migration it
    needs, because reading the legacy folder as its own version is the shape this contract deleted.
    """
    if not isinstance(snapshot, dict):
        raise ValueError('A molecule selection must be an object')
    validate_id(snapshot.get('id'))
    # The snapshot's own kind decides the run type it was selected as: a `cg` record carries no adapter, and asking
    # the AA branch about it would report a molecule whose files are fine as a changed molecule.
    run_type = 'cg' if snapshot.get('kind') == 'cg' else (
        'aa_only' if snapshot.get('adapter') == 'aa-charmm36' else 'aa_cg')
    expected = selection(root, snapshot['id'], run_type, version=snapshot.get('version'))
    if expected != snapshot:
        raise ValueError('Molecule files changed since this run was queued; select the molecule again')
