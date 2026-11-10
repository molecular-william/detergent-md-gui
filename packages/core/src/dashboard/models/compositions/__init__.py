"""Immutable fragment compositions and attachment-map validation.

A saved composition is a **named CG model**: it carries its own stable ``molecule_id`` (the record id), the
``molecule_name`` it was saved under, and an optional ``head_molecule_id`` linking it to the atomistic molecule its
head fragment came from. The record is one identity: the duplicate rule still compares ``identity`` alone, so a
second save with the same fragments, tail and linkage but a different display text is the same composition and is
refused; the name and the head link are provenance, not identity.

Its parameterization is **derived**, never fitted: the terms come from the published Martini 3 sugar reference the
head fragment was transcribed from plus the tail recipe's own linkage, and :func:`derived_parameterization` states
that in the CG-model catalog. ``source`` is ``recipe+reference`` when the record links a head molecule (the
molecule whose published reference the head terms came from) and ``recipe-only`` when it does not.
"""
import json
import re
import uuid
from pathlib import Path

from ... import files, itp, paths
from ..molecules import aa as aa_molecules
from ..molecules import registry as model_registry
from ..repository import JsonRepository
from . import topology as composition_topology

#: The name a saved model may carry, and the term sections counted from its topology.
MAX_MOLECULE_NAME = 160
TERM_SECTIONS = ('atoms', 'bonds', 'constraints', 'angles', 'dihedrals', 'virtual_sitesn', 'exclusions')
#: The immutable files every saved composition carries, in the order the catalog and a run read them.
ARTIFACTS = ('composition.gro', 'composition.itp', 'mapping.json', 'bonded-state.json')


def storage_root():
    return paths.current().compositions


def _id(): return uuid.uuid4().hex[:16]


def _path(cid):
    return _repository().path(cid)


def _validate_id(cid):
    if not isinstance(cid, str) or not re.fullmatch(r'[a-f0-9]{16}', cid):
        raise ValueError('Invalid composition ID')
    return cid


def _repository():
    return JsonRepository(storage_root(), '{id}.json', _validate_id)


def all_compositions():
    return _repository().list(skip_invalid=True)


def get(cid): return _repository().get(cid)


def catalog(project_root=None):
    """Return the immutable choices exposed by Molecule Combination."""
    sugars = composition_topology.load_sugar_catalog(composition_topology._sugar_source(project_root))
    return {
        'sugars': [{'id': key, 'name': key, 'source_sha256': value['source_sha256'],
                    'beads': value['bead_names'],
                    'endpoints': [atom['name'] for atom in value['atoms'] if not atom['virtual']]}
                   for key, value in sugars.items()],
        'tail_recipes': composition_topology.tail_recipe_catalog(),
        'linkage_profiles': composition_topology.linkage_profile_catalog(),
    }


def preview(payload, project_root=None):
    result = composition_topology.build_preview(payload, project_root)
    composition_topology.validate_preview(result)
    result['geometry'] = composition_topology.preview_geometry(result)
    # The panel hands this straight to the NGL viewer, so the browser needs no second request and no route of
    # its own. It is derived, like `geometry`: composition_identity hashes mapping/topology/tail/profile, so a
    # rendering convenience cannot change a composition's identity.
    result['pdb'] = composition_topology.render_pdb(result)
    return result


def _molecule_name(payload, default):
    """The model's display name: the payload's, else the composition's existing name; 1-160 characters."""
    value = payload.get('molecule_name')
    if value is None or (isinstance(value, str) and not value.strip()):
        value = default
    if not isinstance(value, str):
        raise ValueError('molecule_name must be a string')
    value = value.strip()
    if not value:
        raise ValueError('molecule_name must not be empty')
    if len(value) > MAX_MOLECULE_NAME:
        raise ValueError(f'molecule_name must be at most {MAX_MOLECULE_NAME} characters')
    return value


def _head_molecule(head_molecule_id):
    """The linked atomistic molecule, read through the catalogue; a missing one is refused by name.

    The catalogue is the application's `molecules/` tree, which is what a New run offers. Metadata is not generated
    here: saving a composition is not the act that prepares a molecule, so a folder the catalogue cannot read as it
    stands is refused rather than written to.
    """
    if head_molecule_id in (None, ''):
        return None
    if not isinstance(head_molecule_id, str):
        raise ValueError('head_molecule_id must be a molecule id')
    try:
        aa_molecules.validate_id(head_molecule_id)
        record = aa_molecules.inspect(paths.current().project_root / 'molecules', head_molecule_id,
                                      generate_metadata=False)
    except (OSError, ValueError) as exc:
        raise ValueError(f'Head molecule {head_molecule_id!r} is not in the molecule catalogue: {exc}') from exc
    if not record.get('valid'):
        raise ValueError(f'Head molecule {head_molecule_id!r} is not a valid molecule: '
                         + '; '.join(record.get('issues') or ['it has no readable inputs']))
    return head_molecule_id


def create_composition(payload, project_root=None):
    result = preview(payload, project_root)
    identity = result['identity']
    for record in all_compositions():
        if record.get('identity') == identity:
            raise ValueError(f'Composition already exists: {record["id"]}')
    molecule_name = _molecule_name(payload, result['mapping']['name'])
    head_molecule_id = _head_molecule(payload.get('head_molecule_id'))
    cid = _id()
    root = storage_root() / cid
    root.mkdir(parents=True, exist_ok=False)
    try:
        artifacts = {'composition.itp': result['itp'], 'composition.gro': result['gro'],
                     'mapping.json': json.dumps(result['mapping'], indent=2),
                     'bonded-state.json': json.dumps({'mapping': result['mapping'],
                         'topology': result['topology'], 'status': 'complete',
                         'origin': 'composition-generated'}, indent=2)}
        for name, content in artifacts.items():
            (root / name).write_text(content)
        snapshot = {'payload': dict(payload), 'identity': identity,
                    'mapping': result['mapping'], 'topology': result['topology'],
                    'tail': result['tail'], 'profile': result['profile'],
                    'artifacts': {name: files.sha256(root / name) for name in artifacts}}
        # `molecule_id` is the composition's own stable id -- the record id, which the molecule catalogue's own
        # pattern already accepts. It is not the head's: `head_molecule_id` names that, and the two are what let a
        # CG run tell "the model I selected" from "the AA molecule its head came from".
        record = {'id': cid, 'kind': 'composition', 'name': molecule_name,
                  'molecule_id': cid, 'molecule_name': molecule_name,
                  'head_molecule_id': head_molecule_id,
                  'created_at': files.now_iso(), 'identity': identity,
                  'snapshot_hash': files.json_sha256(snapshot),
                  'status': 'candidate-unvalidated', 'scientifically_validated': False,
                  'artifact_root': str(root),
                  'snapshot': snapshot}
        _repository().write(cid, record, replace=False)
        return record
    except Exception:
        for path in sorted(root.rglob('*'), reverse=True):
            if path.is_file(): path.unlink()
        root.rmdir()
        raise


def molecule_id(record):
    """The composition's own stable id, defaulting to the record id for records saved before the field existed."""
    return record.get('molecule_id') or record['id']


def molecule_name(record):
    """The model's display name, defaulting to the record's name for records saved before the field existed."""
    return record.get('molecule_name') or record.get('name') or record['id']


def names(record):
    """The CG naming context a real simulation needs: the residue its topology and coordinates both state.

    `cg_simulation.sh` is handed these through the run's `cg_names` record, so the one spelling here is what the
    topology include, the coarse-grained file and the trajectory's own group selection all use. GROMACS keeps a
    residue name in five characters and `trjconv` selects the trajectory's group by it, so a longer name would write
    a topology whose molecule the group selection cannot find; it is refused here instead.
    """
    mapping = (record.get('snapshot') or {}).get('mapping') or {}
    residue = str(mapping.get('residue_name') or '')
    if not re.fullmatch(r'[A-Za-z0-9_+-]{1,5}', residue):
        raise ValueError('The composition records no usable residue name for a CG simulation '
                         '(1-5 letters, digits, _ + -)')
    return {'residue_name': residue, 'initial_itp': f'{residue}.itp', 'final_itp': f'{residue}.itp'}


def artifact_root(record):
    """Where the immutable artifacts live, refusing a symlinked directory."""
    root = Path(record.get('artifact_root') or '')
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Composition artifact directory is unavailable')
    return root


def _artifact(root, name):
    """One immutable artifact, refusing a symlink, a non-regular file and a changed byte."""
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Missing composition artifact: {name}')
    return path


def artifacts(record):
    """The immutable artifacts by name, refusing a symlink, a non-regular file or a changed byte.

    The recorded digest is the immutability check: a store file edited after the composition was saved refuses here,
    where the run and the catalog both read it, rather than being discovered as a simulation using bytes nobody
    recorded.
    """
    root = artifact_root(record)
    recorded = (record.get('snapshot') or {}).get('artifacts') or {}
    paths_found = {}
    for name in ARTIFACTS:
        path = _artifact(root, name)
        if name in recorded and files.sha256(path) != recorded[name]:
            raise ValueError(f'Composition artifact {name} changed since it was saved; '
                             'a composition is immutable, so save the altered choices as a new one')
        paths_found[name] = path
    return paths_found


def _itp_terms(path):
    """The bead and term counts of a composition topology, read with the shared ITP section reader."""
    counts = {name: len(rows) for name, rows in itp.sections(Path(path).read_text())
              if name in TERM_SECTIONS and rows}
    beads = counts.pop('atoms', 0)
    return beads, counts


def derived_parameterization(cid):
    """The composition's derived parameterization, in the shape every CG model is listed in.

    It is **derived**, never fitted: the engine is `composition-derivation`, the revision is the composition's own
    0, and `source` says whether a linked head molecule supplied the published reference terms
    (`recipe+reference`) or the record names only the recipe (`recipe-only`). The topology and coordinate
    descriptors carry the artifact path and digest, and the topology also carries the bead count and the term
    counts read from `composition.itp` itself, so a reader need not parse the file.
    """
    record = get(cid)
    found = artifacts(record)
    beads, terms = _itp_terms(found['composition.itp'])
    head = record.get('head_molecule_id')
    return {'kind': 'composition', 'revision': 0, 'engine': 'composition-derivation',
            'source': 'recipe+reference' if head else 'recipe-only',
            'head_molecule_id': head,
            'topology': {'path': str(found['composition.itp']), 'sha256': files.sha256(found['composition.itp']),
                         'beads': beads, 'terms': terms},
            'coordinates': {'path': str(found['composition.gro']),
                            'sha256': files.sha256(found['composition.gro'])}}


def composition_detail(cid, project_root=None):
    record = get(cid)
    detail = {**record, **record.get('snapshot', {}), 'composition_id': cid}
    detail['molecule_id'] = molecule_id(record)
    detail['molecule_name'] = molecule_name(record)
    detail['head_molecule_id'] = record.get('head_molecule_id')
    detail['status'] = record.get('status', 'candidate-unvalidated')
    detail['parameterization'] = derived_parameterization(cid)
    return detail


def validate(payload):
    if not isinstance(payload, dict): raise ValueError('Composition must be an object')
    fragments = payload.get('fragments')
    if not isinstance(fragments, list) or not fragments: raise ValueError('Composition needs fragments')
    ids = [f.get('id') if isinstance(f, dict) else f for f in fragments]
    if len(set(ids)) != len(ids): raise ValueError('Composition cannot repeat a fragment')
    records = {f['id']: f for f in model_registry.fragments()}
    if any(i not in records for i in ids): raise ValueError('Composition references an unknown fragment')
    attachments = payload.get('attachments', [])
    if not isinstance(attachments, list): raise ValueError('attachments must be a list')
    seen = set()
    for item in attachments:
        if not isinstance(item, dict): raise ValueError('Each attachment must be an object')
        required = ('left_fragment','right_fragment','left_atom','right_atom')
        if any(k not in item for k in required): raise ValueError('Attachment is missing fragment or atom ownership')
        if item['left_fragment'] not in ids or item['right_fragment'] not in ids: raise ValueError('Attachment references an unselected fragment')
        key = tuple(item[k] for k in required)
        if key in seen: raise ValueError('Duplicate attachment')
        seen.add(key)
        if item['left_fragment'] == item['right_fragment']: raise ValueError('Attachment must connect distinct fragments')
    return {'ok': True, 'fragment_ids': ids, 'attachment_count': len(attachments)}


def create(payload):
    """Write a composition record without artifacts; the root-free validation entry point.

    Tests that exercise fragment and attachment validation use this, because they need no
    molecule workspace. It writes a record with no composition.itp, composition.gro,
    mapping.json or bonded-state.json, so nothing that resolves a composition's artifacts can
    consume it: `create_composition` is the one the API and the catalog use, and the route
    that called this was unreachable code until Task 6.6 deleted it.
    """
    validate(payload)
    body = json.loads(json.dumps(payload, sort_keys=True))
    record = {'id': _id(), 'kind': 'composition', 'created_at': files.now_iso(), 'snapshot_hash': files.json_sha256(body), 'validation': validate(body), 'snapshot': body}
    _repository().write(record['id'], record)
    return record
