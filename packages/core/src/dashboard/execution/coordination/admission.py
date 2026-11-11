"""Run-type admission rules shared by the queue and clone routes.

Raises ValueError for rejected payloads; the application-level error handler
converts that to HTTP 400 with a JSON body. Kept free of Flask imports so the
admission rules can be unit-tested and reused outside the web layer.
"""

AA_ONLY_FORBIDDEN = (
    'mapping_candidate',
    'mapping_snapshot',
    'reference_run_id',
    'cg_equil_ps',
    'cg_production_ps',
    'cg_seed',
    'sasa_probe_nm',
)

# The CG parameterizers a payload may name. Only the run types that *map* an atomistic structure choose one; a run whose
# topology comes from a mapping -- a protein-detergent build, a composition, an osmotic series -- has no choice to make.
# Asking every run for one is how a pdc job was refused with "Unsupported method" while its own adapter was ready.
CG_METHODS = ('fast_forward', 'bartender')


def _cg_payload(data):
    """The payload contract of a CG run: one parameterization of the selected molecule, and nothing from the kinds it
    is not.

    The model is one of three shapes, and each needs exactly one name: a saved mapping and its revision, a published
    sugar entry, or a composition. The server checks the shape here, before a job record exists; whether the named
    thing exists and belongs to the molecule is the run type's readiness, which reads the stores.
    """
    parameterization = data.get('parameterization')
    if not isinstance(parameterization, dict):
        raise ValueError('CG runs require parameterization: the model the run consumes')
    model_kind = parameterization.get('kind') or 'revision'
    if model_kind not in ('revision', 'reference', 'composition'):
        raise ValueError('CG parameterization.kind must be revision, reference or composition')
    if model_kind == 'revision':
        mapping = parameterization.get('mapping_candidate') or parameterization.get('mapping') \
            or data.get('mapping_candidate')
        if not mapping:
            raise ValueError('A revision CG run requires parameterization.mapping_candidate')
        starting = parameterization.get('starting_coordinates')
        if starting not in (None, 'stored', 'remap'):
            raise ValueError('starting_coordinates must be stored or remap')
        revision = parameterization.get('revision')
        if revision is not None and (not isinstance(revision, int) or isinstance(revision, bool) or revision < 1):
            raise ValueError('parameterization.revision must be a positive integer')
        return
    if model_kind == 'reference':
        entry = parameterization.get('sugar_entry') or data.get('sugar_entry')
        if not entry:
            raise ValueError('A reference CG run requires parameterization.sugar_entry')
        for key in ('mapping_candidate', 'mapping_snapshot', 'reference_run_id'):
            if data.get(key) not in (None, ''):
                raise ValueError(f'A reference CG run cannot include {key}')
        return
    composition_id = parameterization.get('composition_id') or data.get('composition_id')
    if not composition_id:
        raise ValueError('A composition CG run requires parameterization.composition_id')
    revision = parameterization.get('composition_revision')
    if revision is None:
        revision = data.get('composition_revision')
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int) or revision < 0):
        raise ValueError('parameterization.composition_revision must be a non-negative integer')
    for key in ('mapping_candidate', 'mapping_snapshot', 'reference_run_id'):
        if data.get(key) not in (None, ''):
            raise ValueError(f'A composition CG run cannot include {key}')


def validate_run_type(data):
    """Reject payloads whose run_type and fields are inconsistent."""
    if not hasattr(data, 'get'):
        raise ValueError('Expected an object')
    from ... import features
    from .. import protocol
    features.ensure()
    kind = data.get('run_type')
    # The published run types, not a second list: a feature's type is admitted when its distribution is installed, and
    # a name no adapter answers is refused here before it reaches the coordinator. A retired name is refused with its
    # own sentence rather than as a typo, because the record is real and only the migration can move it.
    if kind is not None and kind not in protocol.RUN_TYPES:
        if kind in protocol.RETIRED_RUN_TYPES:
            raise ValueError(protocol.RETIRED_RUN_TYPE_MESSAGE.format(name=kind))
        raise ValueError('Unknown run type')
    if kind is None:
        # There is no default run type any more: the historical combined job is retired, and guessing which of the
        # four a payload meant is how a CG run would be queued with no parameterization.
        raise ValueError('run_type is required')
    rule = features.admission_for(kind)
    if rule is not None:
        rule(data)
        return
    if kind == 'cg':
        _cg_payload(data)
        return
    if kind != 'aa_only':
        return
    if any(data.get(key) not in (None, '') for key in AA_ONLY_FORBIDDEN):
        raise ValueError('AA-only cannot include CG inputs or a reference source')
    if data.get('method') not in (None, '', 'gromacs'):
        raise ValueError('AA-only uses GROMACS without a CG parameterizer')
