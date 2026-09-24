"""Run-type admission rules shared by the queue and clone routes.

Raises ValueError for rejected payloads; the application-level error handler
converts that to HTTP 400 with a JSON body. Kept free of Flask imports so the
admission rules can be unit-tested and reused outside the web layer.
"""

AA_ONLY_FORBIDDEN = (
    'mapping_candidate',
    'bonded_state_id',
    'bonded_intent',
    'reference_run_id',
    'cg_equil_ps',
    'cg_production_ps',
    'cg_seed',
    'sasa_probe_nm',
)


def validate_run_type(data):
    """Reject payloads whose run_type and fields are inconsistent."""
    if not hasattr(data, 'get'):
        raise ValueError('Expected an object')
    kind = data.get('run_type')
    if kind not in (None, 'aa_only', 'aa_cg', 'cg_composition'):
        raise ValueError('Unknown run type')
    if kind == 'cg_composition':
        if not data.get('composition_id'):
            raise ValueError('CG composition runs require composition_id')
        for key in ('molecule_id', 'reference_run_id', 'mapping_candidate', 'bonded_state_id'):
            if data.get(key) not in (None, ''):
                raise ValueError('CG composition runs cannot include AA or ordinary mapping inputs')
        return
    if kind != 'aa_only':
        return
    if any(data.get(key) not in (None, '') for key in AA_ONLY_FORBIDDEN):
        raise ValueError('AA-only cannot include CG inputs or a reference source')
    if data.get('method') not in (None, '', 'gromacs'):
        raise ValueError('AA-only uses GROMACS without a CG parameterizer')
