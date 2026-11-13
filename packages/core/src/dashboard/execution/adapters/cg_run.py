"""The `cg` run type: one user-facing CG run over three parameterization kinds.

A CG run never builds its own model. It consumes one of three things, and the kind names which:

* ``revision``    -- a saved mapping's chosen parameterization revision (the main case);
* ``reference``   -- a published Martini 3 sugar entry (the feature's `sugar_cg` adapter);
* ``composition`` -- a composed CG molecule's derived parameterization (`composition.py`).

Each kind already had a proven stage plan. This module does not restate any of them: each hook reads the kind the
payload names and forwards the call to that implementation. ``revision`` is the default and the only kind the engine
itself implements; the other two are delegated, and the feature one is imported lazily because the engine may not
import a feature at module scope. A build without the validation distribution refuses that kind by name rather than
failing on an import.
"""
from __future__ import annotations

import json
from pathlib import Path

from ... import files
from ...models import compositions
from .. import devices, protocol
from . import cg, composition

KINDS: tuple[str, ...] = ('revision', 'reference', 'composition')
DEFAULT_KIND = 'revision'
#: The per-run starting-coordinate choice of the revision kind. A `reference` or `composition` run carries its own
#: coordinates, so the choice is offered for the `revision` kind only.
STARTING_COORDINATES: tuple[str, ...] = cg.STARTING_COORDINATES
DEFAULT_STARTING_COORDINATES = cg.DEFAULT_STARTING_COORDINATES
NO_FEATURE = ('The reference CG parameterization needs the detergent-validation feature installed; '
              'install that distribution to run a published sugar entry')


def kind_of(metadata) -> str:
    """The kind a payload or a record names: the payload's own, then the migration's field, then `revision`."""
    payload = metadata.get('parameterization') if isinstance(metadata, dict) else None
    if isinstance(payload, dict) and payload.get('kind'):
        return payload['kind']
    return (metadata.get('cg_model_kind') if isinstance(metadata, dict) else None) or DEFAULT_KIND


def _payload(metadata) -> dict:
    payload = metadata.get('parameterization') if isinstance(metadata, dict) else None
    return payload if isinstance(payload, dict) else {}


def _sugar():
    """The feature adapter, or `None` when that distribution is absent. Imported when asked, never at module scope."""
    try:
        from detergent_validation.execution.adapters import sugar_cg
    except ImportError:
        return None
    return sugar_cg


def _require(kind: str):
    """The adapter one kind delegates to, refusing a kind this build cannot run."""
    if kind == 'revision':
        return cg.PROTOCOL
    if kind == 'composition':
        return composition.PROTOCOL
    if kind == 'reference':
        sugar = _sugar()
        if sugar is None:
            raise ValueError(NO_FEATURE)
        return sugar.PROTOCOL
    raise ValueError(f'Unknown CG parameterization kind: {kind}')


def _mapping(metadata) -> dict:
    """The saved model a revision-kind payload names, as a mapping snapshot."""
    return metadata.get('mapping_candidate') if isinstance(metadata.get('mapping_candidate'), dict) else {}


def _bound_molecule(mapping, molecule_id):
    """Refuse a model bound to another molecule; a model with no recorded binding is the caller's own choice."""
    bound = mapping.get('molecule_id') if isinstance(mapping, dict) else None
    if bound and molecule_id and bound != molecule_id:
        raise ValueError(f'This parameterization belongs to {bound}, not {molecule_id}')


def _check_composition_molecule(composition_id, molecule_id):
    """Refuse a composition record bound to another molecule; a record that names none is the caller's own choice.

    A composition is a CG molecule built from fragments, not from one AA molecule, so most records name no
    molecule. When one does, the binding is enforced here the same way a mapping's is.
    """
    if not composition_id or not molecule_id:
        return
    try:
        record = compositions.get(composition_id)
    except (OSError, ValueError, KeyError, FileNotFoundError):
        return
    bound = compositions.molecule_id(record) if isinstance(record, dict) else None
    if bound and bound != molecule_id:
        raise ValueError(f'This composition belongs to {bound}, not {molecule_id}')


def _revision_metadata(metadata) -> dict:
    """The revision kind's metadata: the payload's mapping, revision and coordinates, in cg's own spelling."""
    payload = _payload(metadata)
    mapping = _mapping(metadata)
    prepared = dict(metadata)
    if payload:
        prepared['parameterization'] = {
            'kind': 'revision',
            'mapping': payload.get('mapping') or payload.get('mapping_candidate') or mapping.get('file'),
            'revision': payload.get('revision'),
            'starting_coordinates': payload.get('starting_coordinates') or DEFAULT_STARTING_COORDINATES,
        }
    return prepared


def _consumes(metadata) -> bool:
    """Whether a revision-kind run recorded that it consumes a revision rather than fitting one.

    A new payload names a revision, so it consumes. A prepared record says so in `bonded`; a record written before
    the split named its shape in `bonded.consumes_parameterization` too. A record with neither is the fit path a
    direct caller can still take, and its stage plan has to say so.
    """
    return bool(metadata.get('parameterization')) or cg.consumes_parameterization(metadata)


def _sugar_metadata(metadata) -> dict:
    payload = _payload(metadata)
    entry = payload.get('sugar_entry') or metadata.get('sugar_entry') or (metadata.get('settings') or {}).get(
        'sugar_entry') or 'SUCR'
    return {**metadata, 'sugar_entry': entry,
            'settings': {**(metadata.get('settings') or {}), 'sugar_entry': entry}}


def _composition_metadata(metadata) -> dict:
    payload = _payload(metadata)
    return {**metadata, 'composition_id': payload.get('composition_id') or metadata.get('composition_id')}


def stage_contract(metadata):
    """The stage contract of the chosen kind, in that implementation's own terms."""
    kind = kind_of(metadata)
    if kind == 'revision':
        prepared = _revision_metadata(metadata)
        return cg.stage_contract_for(prepared, parameterized=_consumes(prepared))
    if kind == 'reference':
        return _require(kind).stage_contract(_sugar_metadata(metadata))
    return _require(kind).stage_contract(_composition_metadata(metadata))


def stages(metadata):
    """The resolved stage declarations of the chosen kind."""
    kind = kind_of(metadata)
    if kind == 'revision':
        prepared = _revision_metadata(metadata)
        return cg.stages_for(prepared, parameterized=_consumes(prepared))
    if kind == 'reference':
        return _require(kind).stages(_sugar_metadata(metadata))
    return _require(kind).stages(_composition_metadata(metadata))


def settings_specs():
    """Every kind's settings, advertised together because a form asks the run type once.

    The revision kind keeps the AA and CG dialects it has always accepted; a reference run adds the sugar entry's
    own bounds and durations. Where two kinds bound the same key the same value, the tighter one wins -- the
    published table is what a form shows, and a value it accepts is one the normalizer then accepts for that kind.
    """
    published = dict(cg.protocol_settings_specs())
    sugar = _sugar()
    if sugar is not None:
        published.update(sugar.PROTOCOL.settings_specs())
    published.update(composition.PROTOCOL.settings_specs())
    return published


def stage_defaults():
    """The defaults a form starts from: the revision kind's, the default kind."""
    return cg.stage_defaults()


def defaults_for(kind=None, profile=None):
    """The defaults a form starts from for one kind. Called by `/api/defaults` before a payload exists.

    A composition run has no AA half to derive durations from, so its form starts on the CG-only defaults at the
    profile the queue will stamp the run with (`protocol.profile_for_run_type('cg')`), not on `standard`'s.
    """
    kind = kind or DEFAULT_KIND
    if kind == 'revision':
        return cg.stage_defaults()
    if kind == 'reference':
        sugar = _sugar()
        if sugar is None:
            raise ValueError(NO_FEATURE)
        return sugar.stage_defaults()
    if kind == 'composition':
        # A composition run writes its own CG MDPs at the run's numbers; these are the defaults those numbers start
        # from.
        return composition.stage_defaults(profile or protocol.profile_for_run_type('cg'))
    raise ValueError(f'Unknown CG parameterization kind: {kind}')


def choice_specs():
    """The choice-typed vocabulary: the revision kind's own choices, `starting_coordinates`, and a sugar entry."""
    choices = dict(cg.PROTOCOL.choice_specs()) if callable(getattr(cg.PROTOCOL, 'choice_specs', None)) else {}
    choices['starting_coordinates'] = ('Starting coordinates', STARTING_COORDINATES)
    sugar = _sugar()
    if sugar is not None:
        choices.update(sugar.PROTOCOL.choice_specs())
    choices.update(composition.PROTOCOL.choice_specs())
    return devices.published_choices(choices)


def normalize_settings(settings=None, profile='standard', parameterization=None):
    """Normalize the payload's settings in the chosen kind's dialect, dropping the other kinds' keys.

    A form posts one vocabulary; the route keeps only advertised keys, so a revision run can be handed a sugar key
    the union advertises. Filtering here rather than refusing it is what lets one form serve all three kinds, and
    the settings a kind does not own never reach its run.
    """
    kind = (parameterization or {}).get('kind') if isinstance(parameterization, dict) else DEFAULT_KIND
    kind = kind or DEFAULT_KIND
    supplied = dict(settings or {})
    adapter = _require(kind)
    # Each kind owns its own vocabulary, and its normalizer is what refuses a key it does not know. Filtering here
    # would silently drop a setting a retired form still posts (a recorded `mdrun_gpu` on a host that now reports no
    # device), which is the failure the advertised-specs rule exists to prevent.
    return adapter.normalize_settings(supplied, profile)


def readiness(metadata):
    """Can this CG run start? The chosen kind answers, after the molecule/kind binding is checked here."""
    kind = kind_of(metadata)
    if kind not in KINDS:
        return protocol.blocked(f'Unknown CG parameterization kind: {kind}')
    if kind in ('revision', 'reference') and not metadata.get('molecule_id'):
        return protocol.blocked('molecule_id is required to check a CG run')
    if kind == 'revision':
        prepared = _revision_metadata(metadata)
        mapping = _mapping(prepared)
        try:
            _bound_molecule(mapping, metadata.get('molecule_id'))
        except ValueError as exc:
            return protocol.blocked(str(exc))
        # `cg`'s readiness asks for the runs root to resolve the revision's AA reference; the web route passes it.
        prepared.setdefault('runs_root', metadata.get('runs_root'))
        return cg.parameterization_readiness(prepared)
    try:
        adapter = _require(kind)
    except ValueError as exc:
        return protocol.blocked(str(exc))
    if kind == 'reference':
        return adapter.readiness(_sugar_metadata(metadata))
    payload = _payload(metadata)
    try:
        _check_composition_molecule(payload.get('composition_id') or metadata.get('composition_id'),
                                    metadata.get('molecule_id'))
    except ValueError as exc:
        return protocol.blocked(str(exc))
    return adapter.readiness(_composition_metadata(metadata))


def prepare(run_dir, metadata):
    """Prepare the run in the chosen kind's own shape, and record the kind on the run.

    The two delegated kinds declare their manifests themselves; this adds the one field the user-facing run type
    owns -- which parameterization it consumed -- and makes the record name `cg` rather than the kind's old type.
    The revision kind records it itself, in `cg.prepare`.
    """
    kind = kind_of(metadata)
    if kind == 'revision':
        prepared = _revision_metadata(metadata)
        return cg.PROTOCOL.prepare(run_dir, prepared)
    if kind == 'reference':
        sugar = _sugar()
        if sugar is None:
            raise ValueError(NO_FEATURE)
        record = sugar.PROTOCOL.prepare(run_dir, _sugar_metadata(metadata))
        parameterization = {'kind': 'reference', 'sugar_entry': _sugar_metadata(metadata)['sugar_entry']}
    elif kind == 'composition':
        prepared_metadata = _composition_metadata(metadata)
        record = composition.PROTOCOL.prepare(run_dir, prepared_metadata)
        # The composition's own manifest already carries the revision it consumed and the digests that prove it
        # (`composition.prepare`); this keeps that block rather than restating a shorter one, so a reader cannot see
        # a run that names revision 1 while the record said only "composition".
        parameterization = dict(record.get('parameterization') or {})
        parameterization['kind'] = 'composition'
        parameterization.setdefault('composition_id', prepared_metadata.get('composition_id'))
    else:
        raise ValueError(f'Unknown CG parameterization kind: {kind}')
    manifest = Path(run_dir) / 'manifest.json'
    document = json.loads(manifest.read_text())
    document.update(run_type='cg', parameterization=parameterization)
    files.atomic_json(manifest, document)
    return record


PROTOCOL = protocol.Protocol(
    name='cg',
    stage_contract=stage_contract,
    stages=stages,
    settings_specs=settings_specs,
    stage_defaults=stage_defaults,
    normalize_settings=normalize_settings,
    readiness=readiness,
    prepare=prepare,
    choice_specs=choice_specs,
)
